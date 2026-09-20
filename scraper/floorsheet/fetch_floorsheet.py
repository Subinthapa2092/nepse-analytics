"""
Floorsheet scraper for Merolagani (https://merolagani.com/Floorsheet.aspx).

One trading day is roughly 60-110k trades = a couple of hundred pages, so this
module is built around three rules:

  1. A day is only "complete" if the number of unique trades we collected equals the
     record count the site itself advertises ("Showing 1 - 500 of N records"). Reading
     every page is NOT enough -- overlapping/skipped pages silently lose trades. If
     we come up short we re-read only the pages that look wrong before giving up.
     Incomplete days are never saved (they would give wrong buy/sell totals).
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
MAX_RECOVERY_PASSES = 2

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

ROW_COUNT_JS = "() => document.querySelectorAll('table.sortable tbody tr').length"

# Rows-per-page choices the pager could be using; we pick the one that reproduces the
# advertised "N records / M pages" so we know how many rows a full page must contain.
PAGE_SIZE_CANDIDATES = (10, 20, 25, 50, 100, 200, 250, 500, 1000)

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
    expected_rows: int | None = None   # record count the site advertises for this day
    dupes: int = 0                     # duplicate rows dropped while paging
    shortfall: int | None = None       # expected - collected, when every page was read cleanly
    recovery_passes: int = 0           # extra re-read passes that were needed
    short_pages: tuple = ()            # (page, rows_seen, rows_wanted) for pages that stayed short


# --------------------------------------------------------------------------- parsing

def _to_number(value: str):
    value = value.replace(",", "").strip()
    if value in ("", "-"):
        return None
    return float(value)


def _cell_text(cell) -> str:
    link = cell.find("a")
    return (link or cell).get_text(strip=True)


def _parse_with_stats(html: str) -> tuple[list[dict], int]:
    """Returns (rows, skipped) where skipped = data-looking rows we couldn't parse."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", {"class": "sortable"})
    if table is None:
        return [], 0

    rows = []
    skipped = 0
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue  # header row
        if len(cells) < 8:
            skipped += 1
            continue

        rows.append({
            "transaction_no": cells[1].get_text(strip=True),
            "symbol": _cell_text(cells[2]),
            "buyer_broker": _cell_text(cells[3]),
            "seller_broker": _cell_text(cells[4]),
            "quantity": int(_to_number(cells[5].get_text(strip=True)) or 0),
            "rate": _to_number(cells[6].get_text(strip=True)),
            "amount": _to_number(cells[7].get_text(strip=True)),
        })
    return rows, skipped


def _parse_floorsheet_table(html: str) -> list[dict]:
    return _parse_with_stats(html)[0]


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


def _row_count(page) -> int:
    try:
        return int(page.evaluate(ROW_COUNT_JS))
    except Exception:
        return 0  # page is mid-postback


def _wait_for_full_page(page, want: int | None, timeout_s: float = 10.0) -> int:
    """
    The first row appearing does NOT mean the whole page has rendered. Wait until the
    table holds `want` rows. If the page stays short for ~2s it is genuinely short (we
    report it); if `want` is unknown, wait for the row count to stop changing.
    """
    deadline = time.time() + timeout_s
    last, stable = -1, 0
    while time.time() < deadline:
        n = _row_count(page)
        if want is not None and n >= want:
            return n
        stable = stable + 1 if (n == last and n > 0) else 0
        last = n
        if want is None and stable >= 3:
            return n
        if want is not None and stable >= 8:
            return n
        time.sleep(0.25)
    return max(last, 0)


def _guess_page_size(total_pages: int | None, expected: int | None) -> int | None:
    if not total_pages or not expected:
        return None
    for size in PAGE_SIZE_CANDIDATES:
        if -(-expected // size) == total_pages:  # ceil division
            return size
    return None


def _rows_wanted(page_num: int, total_pages: int, page_size: int | None,
                 expected: int | None) -> int | None:
    if page_size is None:
        return None
    if page_num < total_pages:
        return page_size
    if expected is not None:
        return expected - page_size * (total_pages - 1)
    return None


def _read_pager_info(page) -> tuple[int | None, int | None]:
    """Returns (total_pages, total_records) from text like
    'Showing 1 - 500 of 64,072 records. [Total pages: 129]'."""
    try:
        text = page.evaluate(TOTAL_PAGES_JS, RECORDS_LABEL_SUFFIX) or ""
    except Exception:
        return None, None
    pages = re.search(r"Total\s*pages\s*:\s*(\d+)", text, re.I)
    records = re.search(r"of\s+([\d,]+)\s+records", text, re.I)
    return (
        int(pages.group(1)) if pages else None,
        int(records.group(1).replace(",", "")) if records else None,
    )


def _wait_for_requested_date(page, trade_date: date, timeout_s: float = 15.0) -> bool:
    """
    Rows on screen aren't necessarily OURS: right after clicking Search the page can still
    show a previous view (e.g. the latest day). Only continue once the first trade's number
    carries the date we asked for. On a market holiday this never happens, which is how we
    tell "holiday" from "slow page".
    """
    if not CHECK_TXN_DATE:
        return True
    want = trade_date.strftime("%Y%m%d")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        txn = _first_txn(page)
        if txn:
            m = re.match(r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])", txn)
            if not m:
                return True  # numbering isn't date-like; the check can't apply
            if "".join(m.groups()) == want:
                return True
        time.sleep(0.3)
    return False


def _wait_for_pager_info(page, timeout_s: float = 20.0) -> tuple[int | None, int | None]:
    """The pager text renders a moment AFTER the first table row, so poll for it."""
    deadline = time.time() + timeout_s
    pages = records = None
    while time.time() < deadline:
        pages, records = _read_pager_info(page)
        if pages is not None and records is not None:
            return pages, records
        if pages is not None:           # have the page count; give the record count a moment
            deadline = min(deadline, time.time() + 3)
        time.sleep(0.3)
    return pages, records


def _absorb(rows: list[dict], seen: set, all_rows: list[dict]) -> int:
    """Add unseen trades (by transaction number). Returns how many were new."""
    fresh = 0
    for r in rows:
        if r["transaction_no"] in seen:
            continue
        seen.add(r["transaction_no"])
        all_rows.append(r)
        fresh += 1
    return fresh


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

    def _read_pages(self, page, page_numbers, seen, all_rows, total_pages, stats,
                    stop_at: int | None = None, track_dupes: bool = True,
                    page_size: int | None = None, expected: int | None = None,
                    refetch: bool = False) -> tuple[int, str | None]:
        """Visit pages, absorb unseen trades. Returns (pages_loaded, error_note_or_None)."""
        loaded = 0
        for page_num in page_numbers:
            if stop_at is not None and len(all_rows) >= stop_at:
                break
            if page_num == stats["cur"] and refetch:
                # Re-reading the page we're on would just re-parse the same DOM: hop away first.
                hop = page_num - 1 if page_num > 1 else page_num + 1
                if not _go_to_page(page, hop, _first_txn(page)):
                    return loaded, f"stuck on page {hop}/{total_pages}"
                stats["cur"] = hop
            if page_num != stats["cur"]:
                prev_first = _first_txn(page)
                if not _go_to_page(page, page_num, prev_first):
                    return loaded, f"stuck on page {page_num}/{total_pages}"
                stats["cur"] = page_num
            want = _rows_wanted(page_num, total_pages, page_size, expected)
            _wait_for_full_page(page, want)
            rows, skipped = _parse_with_stats(page.content())
            fresh = _absorb(rows, seen, all_rows)
            loaded += 1
            stats["skipped"] += skipped
            if track_dupes:  # re-read passes intentionally revisit pages; not "dupes"
                stats["dupes"] += len(rows) - fresh
                if fresh == 0:
                    stats["empty_pages"] += 1
                if want is not None and len(rows) < want:
                    stats["short_pages"].append((page_num, len(rows), want))
            if page_num % 20 == 0:
                print(f"    ...page {page_num}/{total_pages}, {len(all_rows):,} trades")
            time.sleep(random.uniform(*self.page_delay))
        return loaded, None

    def fetch(self, trade_date: date, max_pages: int | None = None) -> FloorsheetResult:
        """One attempt, plus one retry if the page never showed usable data (a slow or
        half-loaded page looks the same as a holiday, so give it a second chance)."""
        result = self._attempt(trade_date, max_pages)
        if not result.rows or result.total_pages is None:
            print(f"    ({result.note or 'no data'}) -- retrying once")
            time.sleep(3)
            retry = self._attempt(trade_date, max_pages)
            if retry.rows or not result.rows:
                result = retry
        return result

    def _attempt(self, trade_date: date, max_pages: int | None = None) -> FloorsheetResult:
        try:
            return self._fetch_once(trade_date, max_pages)
        except DateMismatch:
            raise
        except Exception as e:
            reason = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
            return FloorsheetResult(trade_date, [], 0, None, False, f"error: {reason}")

    def _fetch_once(self, trade_date: date, max_pages: int | None = None) -> FloorsheetResult:
        context = self._browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        page.set_default_timeout(30000)
        try:
            # 'load' also waits for every third-party script on the page (ads, analytics), which
            # can hang for minutes. We only need the form, so wait for that instead.
            page.goto(URL, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_selector(f"#{DATE_INPUT_ID}", timeout=45000)
            page.fill(f"#{DATE_INPUT_ID}", trade_date.strftime(DATE_FORMAT))
            page.click(f"#{SEARCH_BUTTON_ID}")

            if not _wait_for_rows(page):
                return FloorsheetResult(trade_date, [], 0, None, False, "no rows returned")
            if not _wait_for_requested_date(page, trade_date):
                shown = (_first_txn(page) or "")[:8]
                return FloorsheetResult(trade_date, [], 0, None, False,
                                        f"page still shows {shown}, not {trade_date:%Y%m%d} "
                                        f"(market holiday, or wrong date format)")

            total_pages, expected = _wait_for_pager_info(page)
            page_size = _guess_page_size(total_pages, expected)
            want1 = _rows_wanted(1, total_pages, page_size, expected) if total_pages else None
            _wait_for_full_page(page, want1)
            rows, skipped = _parse_with_stats(page.content())
            _check_txn_date(rows, trade_date)

            seen: set[str] = set()
            all_rows: list[dict] = []
            fresh = _absorb(rows, seen, all_rows)
            stats = {"skipped": skipped, "dupes": len(rows) - fresh, "empty_pages": 0,
                     "short_pages": [], "cur": 1}
            if want1 is not None and len(rows) < want1:
                stats["short_pages"].append((1, len(rows), want1))
            pages_read = 1
            passes = 0

            def result(complete: bool, note: str = "", shortfall: int | None = None) -> FloorsheetResult:
                return FloorsheetResult(trade_date, all_rows, pages_read, total_pages,
                                        complete, note, expected, stats["dupes"],
                                        shortfall, passes, tuple(stats["short_pages"]))

            if total_pages is None:
                return result(False, "couldn't read 'Total pages' from the pager -- "
                                     "can't prove the day is complete")

            limit = min(total_pages, max_pages) if max_pages else total_pages
            loaded, err = self._read_pages(page, range(2, limit + 1), seen, all_rows,
                                           total_pages, stats,
                                           page_size=page_size, expected=expected)
            pages_read += loaded
            if err:
                return result(False, err)
            if limit < total_pages:
                return result(False, f"stopped early at {pages_read}/{total_pages} pages (max_pages)")

            # Site says N trades but we hold fewer. Two cheap, targeted remedies -- we do NOT
            # blindly re-read all pages, because a shortfall that comes back identical on every
            # read (the site simply not showing some trades) would just triple the run time.
            #  1) pages that came back short: re-read only those, once.
            #  2) duplicates seen while paging mean pages overlapped and may be hiding trades
            #     elsewhere: only then do full re-read passes (reverse, then forward).
            if expected is not None and len(all_rows) < expected:
                short_list = sorted({n for n, _, _ in stats["short_pages"]})
                if short_list:
                    passes += 1
                    print(f"    have {len(all_rows):,} of {expected:,} trades -- re-reading the "
                          f"{len(short_list)} page(s) that came back short")
                    _, err = self._read_pages(page, short_list, seen, all_rows, total_pages, stats,
                                              stop_at=expected, track_dupes=False,
                                              page_size=page_size, expected=expected,
                                              refetch=True)
                    if err:
                        return result(False, f"{err} during recovery pass")
                    print(f"    now {len(all_rows):,} trades")

                full = 0
                while len(all_rows) < expected and stats["dupes"] > 0 and full < MAX_RECOVERY_PASSES:
                    full += 1
                    passes += 1
                    forward = full % 2 == 0
                    print(f"    have {len(all_rows):,} of {expected:,} trades and pages overlapped -- "
                          f"full re-read ({'forward' if forward else 'reverse'}, {full}/{MAX_RECOVERY_PASSES})")
                    order = range(1, total_pages + 1) if forward else range(total_pages, 0, -1)
                    _, err = self._read_pages(page, order, seen, all_rows, total_pages, stats,
                                              stop_at=expected, track_dupes=False,
                                              page_size=page_size, expected=expected,
                                              refetch=True)
                    if err:
                        return result(False, f"{err} during recovery pass")
                    print(f"    now {len(all_rows):,} trades")

            if expected is None:
                if stats["empty_pages"]:
                    return result(False, f"{stats['empty_pages']} page(s) returned no new trades and the "
                                         "site's record count couldn't be read to verify")
                return result(True, "site record count not found -- total NOT verified")

            if len(all_rows) == expected:
                return result(True, shortfall=0)
            short = expected - len(all_rows)
            shown = ", ".join(f"p{n}:{got}/{want}" for n, got, want in stats["short_pages"][:8])
            return result(False, (
                f"collected {len(all_rows):,} unique trades but the site lists {expected:,} "
                f"(short by {short}; {stats['dupes']} duplicate rows dropped, "
                f"{stats['skipped']} unparsed rows; short pages: {shown or 'none'})"
            ), shortfall=short)
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
          f"{result.pages_read}/{result.total_pages} pages, site says {result.expected_rows}, "
          f"complete={result.complete} {result.note}")
    for r in result.rows[:5]:
        print(r)
