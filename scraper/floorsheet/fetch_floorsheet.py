"""
Floorsheet scraper for Merolagani (https://merolagani.com/Floorsheet.aspx).

One trading day is roughly 60-110k trades = a couple of hundred pages, so this
module is built around three rules:

  1. A day is only "complete" if EVERY page was read. Partial days are never saved
     (a partial broker summary would silently give wrong buy/sell totals).
  2. Every page change is verified (the first transaction number on screen must
     change) -- no blind sleeps that can re-read the same page twice.
  3. Trades are de-duplicated by transaction number, so a stale/repeated page can
     never double count.

Selectors below were confirmed against the real page (date input, search button,
pager control, table class).
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from datetime import date

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

URL = "https://merolagani.com/Floorsheet.aspx"
DATE_FORMAT = "%m/%d/%Y"  # matches the site's date placeholder (MM/DD/YYYY)

DATE_INPUT_ID = "ctl00_ContentPlaceHolder1_txtFloorsheetDateFilter"
SEARCH_BUTTON_ID = "ctl00_ContentPlaceHolder1_lbtnSearchFloorsheet"
HIDDEN_PAGE_FIELD_ID = "ctl00_ContentPlaceHolder1_PagerControl2_hdnCurrentPage"
HIDDEN_BUTTON_ID = "ctl00_ContentPlaceHolder1_PagerControl2_btnPaging"
RECORDS_LABEL_SUFFIX = "PagerControl2_litRecords"

# Floorsheet transaction numbers normally start with the trade date (YYYYMMDD).
# We use that as a safety net: if we asked for one date but the site shows another
# (e.g. wrong date format), we stop instead of saving data under the wrong day.
# If the very first test run raises DateMismatch on a date you KNOW is right, the
# numbering isn't date-based -- set this to False.
CHECK_TXN_DATE = True

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

FIRST_TXN_JS = """() => {
    const c = document.querySelector('table.sortable tbody tr td:nth-child(2)');
    return c ? c.textContent.trim() : null;
}"""

TOTAL_PAGES_JS = """(suffix) => {
    const el = document.querySelector("[id$='" + suffix + "']");
    return el ? el.innerText : document.body.innerText;
}"""


class DateMismatch(Exception):
    """The site showed a different date than the one we asked for."""


@dataclass
class FloorsheetResult:
    trade_date: date
    rows: list[dict]
    pages_read: int
    total_pages: int | None
    complete: bool
    note: str = ""


# --------------------------------------------------------------------------- parsing

def _to_number(value: str):
    value = value.replace(",", "").strip()
    if value in ("", "-"):
        return None
    return float(value)


def _cell_text(cell) -> str:
    link = cell.find("a")
    return (link or cell).get_text(strip=True)


def _parse_floorsheet_table(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"class": "sortable"})
    if table is None:
        return []

    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 8:
            continue  # header row or spacer

        rows.append({
            "transaction_no": cells[1].get_text(strip=True),
            "symbol": _cell_text(cells[2]),
            "buyer_broker": _cell_text(cells[3]),
            "seller_broker": _cell_text(cells[4]),
            "quantity": int(_to_number(cells[5].get_text(strip=True)) or 0),
            "rate": _to_number(cells[6].get_text(strip=True)),
            "amount": _to_number(cells[7].get_text(strip=True)),
        })
    return rows


def _check_txn_date(rows: list[dict], trade_date: date) -> None:
    if not CHECK_TXN_DATE or not rows:
        return
    expected = trade_date.strftime("%Y%m%d")
    for r in rows[:25]:
        m = re.match(r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])", r["transaction_no"])
        if m and "".join(m.groups()) != expected:
            raise DateMismatch(
                f"Asked for {trade_date} but transaction {r['transaction_no']} looks like "
                f"{'-'.join(m.groups())}. Check DATE_FORMAT in fetch_floorsheet.py "
                f"(or set CHECK_TXN_DATE = False if transaction numbers aren't date-based)."
            )


# --------------------------------------------------------------------------- browser helpers

def _first_txn(page):
    try:
        return page.evaluate(FIRST_TXN_JS)
    except Exception:
        return None  # page is mid-postback


def _wait_for_rows(page, changed_from: str | None = None, timeout_s: float = 25.0) -> bool:
    """Wait until the table shows rows (and, if given, a different first row than before)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        current = _first_txn(page)
        if current and current != changed_from:
            return True
        time.sleep(0.3)
    return False


def _read_total_pages(page) -> int | None:
    try:
        text = page.evaluate(TOTAL_PAGES_JS, RECORDS_LABEL_SUFFIX)
    except Exception:
        return None
    m = re.search(r"Total\s*pages\s*:\s*(\d+)", text or "", re.I)
    return int(m.group(1)) if m else None


def _go_to_page(page, page_num: int, prev_first_txn: str | None, retries: int = 3) -> bool:
    for attempt in range(1, retries + 1):
        try:
            page.wait_for_selector(f"#{HIDDEN_PAGE_FIELD_ID}", state="attached", timeout=10000)
            page.evaluate(
                "([n, field, btn]) => changePageIndex(String(n), field, btn)",
                [page_num, HIDDEN_PAGE_FIELD_ID, HIDDEN_BUTTON_ID],
            )
            if _wait_for_rows(page, changed_from=prev_first_txn):
                return True
            print(f"    page {page_num}: table didn't change (attempt {attempt}/{retries})")
        except Exception as e:
            print(f"    page {page_num}: attempt {attempt}/{retries} failed: {e}")
        time.sleep(2 * attempt)
    return False


# --------------------------------------------------------------------------- session

class FloorsheetSession:
    """
    One browser reused across many dates (much faster than relaunching per date).
    Each date gets a fresh browser context, so no state leaks between days.

        with FloorsheetSession() as s:
            result = s.fetch(date(2026, 9, 17))
    """

    def __init__(self, headless: bool = True, page_delay: tuple[float, float] = (0.8, 1.6)):
        self.headless = headless
        self.page_delay = page_delay
        self._pw = None
        self._browser = None

    def __enter__(self):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        return self

    def __exit__(self, *exc):
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def fetch(self, trade_date: date, max_pages: int | None = None) -> FloorsheetResult:
        context = self._browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        page.set_default_timeout(30000)
        try:
            page.goto(URL, timeout=30000)
            page.fill(f"#{DATE_INPUT_ID}", trade_date.strftime(DATE_FORMAT))
            page.click(f"#{SEARCH_BUTTON_ID}")

            if not _wait_for_rows(page):
                return FloorsheetResult(trade_date, [], 0, None, False, "no rows returned")

            total_pages = _read_total_pages(page)
            rows = _parse_floorsheet_table(page.content())
            _check_txn_date(rows, trade_date)

            seen = {r["transaction_no"] for r in rows}
            all_rows = list(rows)
            pages_read = 1

            if total_pages is None:
                return FloorsheetResult(
                    trade_date, all_rows, pages_read, None, False,
                    "couldn't read 'Total pages' from the pager -- can't prove the day is complete",
                )

            limit = min(total_pages, max_pages) if max_pages else total_pages
            for page_num in range(2, limit + 1):
                prev_first = _first_txn(page)
                if not _go_to_page(page, page_num, prev_first):
                    return FloorsheetResult(
                        trade_date, all_rows, pages_read, total_pages, False,
                        f"stuck on page {page_num}/{total_pages}",
                    )
                page_rows = _parse_floorsheet_table(page.content())
                fresh = [r for r in page_rows if r["transaction_no"] not in seen]
                if not fresh:
                    return FloorsheetResult(
                        trade_date, all_rows, pages_read, total_pages, False,
                        f"page {page_num}/{total_pages} had no new trades",
                    )
                seen.update(r["transaction_no"] for r in fresh)
                all_rows.extend(fresh)
                pages_read += 1

                if page_num % 20 == 0:
                    print(f"    ...page {page_num}/{total_pages}, {len(all_rows):,} trades")
                time.sleep(random.uniform(*self.page_delay))

            complete = pages_read == total_pages
            note = "" if complete else f"stopped early at {pages_read}/{total_pages} pages (max_pages)"
            return FloorsheetResult(trade_date, all_rows, pages_read, total_pages, complete, note)
        finally:
            context.close()


def fetch_floorsheet_for_date(trade_date: date, headless: bool = True,
                              max_pages: int | None = None) -> FloorsheetResult:
    """Convenience wrapper for one-off use. For many dates, use FloorsheetSession."""
    with FloorsheetSession(headless=headless) as s:
        return s.fetch(trade_date, max_pages=max_pages)


if __name__ == "__main__":
    # Quick smoke test: first 3 pages of a known trading day, nothing saved.
    result = fetch_floorsheet_for_date(date(2026, 9, 18), max_pages=3)
    print(f"{result.trade_date}: {len(result.rows):,} trades, "
          f"{result.pages_read}/{result.total_pages} pages, complete={result.complete} {result.note}")
    for r in result.rows[:5]:
        print(r)
