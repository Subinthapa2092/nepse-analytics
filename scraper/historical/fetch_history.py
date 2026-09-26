"""
Historical price scraper using Playwright.
Selectors confirmed against real Merolagani Price History tab HTML.

FIXED: two changes to handle slow/heavy pages (symbols with thousands of
records, e.g. ADBL's 37 pages) without losing progress:
  1. Longer timeout (25s, up from 10s) and more retries (5, up from 3) per
     page -- a single 10s timeout was too aggressive for a page this size
     under real network conditions.
  2. fetch_symbol_history now accepts start_page, and returns how far it
     actually got (last_page_reached) alongside the rows -- so a caller can
     resume from that page next time instead of re-fetching from page 1
     and potentially hitting the same wall forever.
"""

import re
import time
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

TABLE_CONTAINER_ID = "ctl00_ContentPlaceHolder1_CompanyDetail1_divDataPrice"
HISTORY_TAB_LINK_ID = "ctl00_ContentPlaceHolder1_CompanyDetail1_lnkHistoryTab"
RECORDS_LABEL_ID = "ctl00_ContentPlaceHolder1_CompanyDetail1_PagerControlTransactionHistory1_litRecords"
HIDDEN_PAGE_FIELD_ID = "ctl00_ContentPlaceHolder1_CompanyDetail1_PagerControlTransactionHistory1_hdnCurrentPage"
HIDDEN_BUTTON_ID = "ctl00_ContentPlaceHolder1_CompanyDetail1_PagerControlTransactionHistory1_btnPaging"

PAGE_TIMEOUT_MS = 25000  # was 10000 -- too short for heavy pages under load
PAGE_RETRIES = 5         # was 3
RETRY_BACKOFF_SECONDS = 3  # was a flat 2s; small ramp helps transient slowness


def _to_number(value: str):
    value = value.replace(",", "").strip()
    if value in ("", "-"):
        return None
    return float(value)


def _parse_history_table(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("div", {"id": TABLE_CONTAINER_ID})
    if container is None:
        return []
    table = container.find("table")
    if table is None:
        return []

    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 8:
            continue
        texts = [c.get_text(strip=True) for c in cells]
        rows.append({
            "date": texts[1].replace("/", "-"),
            "ltp": _to_number(texts[2]),
            "pct_change": _to_number(texts[3]),
            "high": _to_number(texts[4]),
            "low": _to_number(texts[5]),
            "open": _to_number(texts[6]),
            "qty": int(_to_number(texts[7]) or 0),
        })
    return rows


def _go_to_page(page, page_num: int, retries: int = PAGE_RETRIES) -> bool:
    """Attempts to navigate to a given page number. Returns True on success."""
    for attempt in range(1, retries + 1):
        try:
            page.wait_for_selector(f"#{HIDDEN_PAGE_FIELD_ID}", state="attached",
                                    timeout=PAGE_TIMEOUT_MS)
            page.evaluate(
                f"changePageIndex('{page_num}', '{HIDDEN_PAGE_FIELD_ID}', '{HIDDEN_BUTTON_ID}')"
            )
            page.wait_for_timeout(1500)
            return True
        except Exception as e:
            print(f"  page {page_num} attempt {attempt}/{retries} failed: {e}")
            time.sleep(RETRY_BACKOFF_SECONDS * attempt)  # small ramp: 3s, 6s, 9s...
    return False


def fetch_symbol_history(symbol: str, headless: bool = True, max_pages: int | None = None,
                          start_page: int = 1) -> tuple[list[dict], int, int]:
    """
    Returns (rows, last_page_reached, total_pages).

    start_page: resume from this page instead of page 1 (page 1 is still
    loaded first regardless, to read total_pages and grab its rows, since
    that's unavoidable with how the site's postback pagination works --
    but pages before start_page are then skipped rather than re-fetched).
    """
    url = f"https://merolagani.com/CompanyDetail.aspx?symbol={symbol}"
    all_rows = []
    last_page_reached = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(url, timeout=30000)

        page.click(f"#{HISTORY_TAB_LINK_ID}")
        page.wait_for_timeout(1500)

        records_text = page.inner_text(f"#{RECORDS_LABEL_ID}")
        match = re.search(r"Total pages:\s*(\d+)", records_text)
        total_pages = int(match.group(1)) if match else 1

        if max_pages:
            total_pages = min(total_pages, max_pages)

        print(f"{symbol}: {records_text.strip()} -> fetching {total_pages} page(s) "
              f"(starting from page {start_page})")

        # page 1 is already loaded regardless of where we're resuming from
        if start_page <= 1:
            html = page.content()
            all_rows.extend(_parse_history_table(html))
        last_page_reached = 1

        # FIXED: resuming used to jump straight to start_page via
        # changePageIndex(start_page, ...) without ever requesting the pages
        # in between. That's not how any successful run actually worked --
        # every symbol that completed got there by walking 2, 3, 4... in
        # order, and the site's own postback/pager state seems to depend on
        # that sequence. Jumping straight to e.g. page 24 silently breaks it
        # (matches exactly what we saw: SIFC always failing one page past
        # wherever it resumed from). So we still walk every page in order --
        # we just don't bother re-parsing/keeping rows for pages we already
        # have (< start_page), which is cheap; only pages >= start_page are
        # actually kept.
        for page_num in range(2, total_pages + 1):
            success = _go_to_page(page, page_num)
            if not success:
                print(f"  giving up on page {page_num} for {symbol} -- "
                      f"keeping {len(all_rows)} new row(s) collected this run "
                      f"(reached page {last_page_reached} of {total_pages})")
                break

            last_page_reached = page_num
            if page_num < start_page:
                continue  # already have this page's rows from a prior run
            html = page.content()
            all_rows.extend(_parse_history_table(html))

        browser.close()

    return all_rows, last_page_reached, total_pages