"""
Historical price scraper using Playwright.
Selectors confirmed against real Merolagani Price History tab HTML.
"""

import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

TABLE_CONTAINER_ID = "ctl00_ContentPlaceHolder1_CompanyDetail1_divDataPrice"
HISTORY_TAB_LINK_ID = "ctl00_ContentPlaceHolder1_CompanyDetail1_lnkHistoryTab"
RECORDS_LABEL_ID = "ctl00_ContentPlaceHolder1_CompanyDetail1_PagerControlTransactionHistory1_litRecords"
HIDDEN_PAGE_FIELD_ID = "ctl00_ContentPlaceHolder1_CompanyDetail1_PagerControlTransactionHistory1_hdnCurrentPage"
HIDDEN_BUTTON_ID = "ctl00_ContentPlaceHolder1_CompanyDetail1_PagerControlTransactionHistory1_btnPaging"


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
            continue  # skip header row
        texts = [c.get_text(strip=True) for c in cells]
        rows.append({
            "date": texts[1].replace("/", "-"),   # 2026/07/22 -> 2026-07-22
            "ltp": _to_number(texts[2]),
            "pct_change": _to_number(texts[3]),
            "high": _to_number(texts[4]),
            "low": _to_number(texts[5]),
            "open": _to_number(texts[6]),
            "qty": int(_to_number(texts[7]) or 0),
        })
    return rows


def fetch_symbol_history(symbol: str, headless: bool = True, max_pages: int | None = None) -> list[dict]:
    url = f"https://merolagani.com/CompanyDetail.aspx?symbol={symbol}"
    all_rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(url, timeout=30000)

        # click the Price History tab
        page.click(f"#{HISTORY_TAB_LINK_ID}")
        page.wait_for_timeout(1500)

        # read total pages from the records label, e.g. "[Total pages: 60]"
        records_text = page.inner_text(f"#{RECORDS_LABEL_ID}")
        match = re.search(r"Total pages:\s*(\d+)", records_text)
        total_pages = int(match.group(1)) if match else 1

        if max_pages:
            total_pages = min(total_pages, max_pages)

        print(f"{symbol}: {records_text.strip()} -> fetching {total_pages} page(s)")

        for page_num in range(1, total_pages + 1):
            if page_num > 1:
                page.evaluate(
                    f"changePageIndex('{page_num}', '{HIDDEN_PAGE_FIELD_ID}', '{HIDDEN_BUTTON_ID}')"
                )
                page.wait_for_timeout(1200)  # let postback complete

            html = page.content()
            rows = _parse_history_table(html)
            all_rows.extend(rows)

        browser.close()

    return all_rows