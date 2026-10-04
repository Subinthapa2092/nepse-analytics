"""
Scrapes, for every symbol in companies/nepse_companies.sqlite:
  1. The full Quarterly Report list from merolagani's CompanyDetail.aspx
     (fiscal year, date, announcement id) -- up to the first 50 records.
  2. For the LATEST announcement only, the structured detail fields
     (Bookclose Date, % Cash Dividend, % Bonus Share, Right Share Ratio,
     Announcement Date, Tags) from AnnouncementDetail.aspx.

Deliberately does NOT attempt to read the embedded financial-statement
image on the detail page (Total Assets / Net Profit) -- confirmed via
direct testing to be a flattened image, not text, so OCR would be needed
and that's not reliable enough for financial figures.

Uses Playwright (real headless browser) because this site's Quarterly
Report tab only populates via an ASP.NET AJAX postback that a plain
requests.get() can't trigger -- confirmed by direct testing. Same reason
your floorsheet scraper also uses Playwright.

TEST ON A FEW SYMBOLS FIRST:
    python scrape_quarterly_reports.py --limit 3

Then run the full pass:
    python scrape_quarterly_reports.py
"""

import argparse
import os
import re
import sqlite3
import time

from playwright.sync_api import sync_playwright

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COMPANY_DB = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "companies", "nepse_companies.sqlite"))
OUT_DB = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "companies", "nepse_quarterly_reports.sqlite"))

DELAY_SECONDS = 0.5  # politeness delay between symbols (on top of real page-load time)

DETAIL_LABELS = {
    "Bookclose Date": "bookclose_date",
    "% Cash Dividend": "cash_dividend_pct",
    "% Bonus Share": "bonus_share_pct",
    "Right Share Ratio": "right_share_ratio",
    "Announcement Date": "announcement_date",
    "Fiscal Year": "fiscal_year",
    "Tags": "tags",
}


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quarterly_reports (
            symbol           TEXT NOT NULL,
            fiscal_year      TEXT,
            date_text        TEXT,
            announcement_id  TEXT,
            description      TEXT,
            PRIMARY KEY (symbol, announcement_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quarterly_detail (
            symbol            TEXT NOT NULL,
            announcement_id   TEXT NOT NULL,
            bookclose_date    TEXT,
            cash_dividend_pct TEXT,
            bonus_share_pct   TEXT,
            right_share_ratio TEXT,
            announcement_date TEXT,
            fiscal_year       TEXT,
            tags              TEXT,
            PRIMARY KEY (symbol, announcement_id)
        )
    """)
    conn.commit()


def scrape_quarterly_list(page, symbol):
    url = f"https://merolagani.com/CompanyDetail.aspx?symbol={symbol}"
    page.goto(url, timeout=30000)
    try:
        page.click("#ctl00_ContentPlaceHolder1_CompanyDetail1_lnkQuaterlyTab", timeout=10000)
        page.wait_for_selector(
            "#divQuaterly table tr td a[href*='AnnouncementDetail']",
            timeout=10000,
        )
    except Exception:
        return []  # no quarterly reports for this symbol (or tab didn't load) -- not fatal

    rows = []
    trs = page.query_selector_all("#divQuaterly table tr")
    for tr in trs:
        tds = tr.query_selector_all("td")
        if len(tds) < 4:
            continue
        link = tds[3].query_selector("a[href*='AnnouncementDetail']")
        if link is None:
            continue
        href = link.get_attribute("href") or ""
        m = re.search(r"id=(\d+)", href)
        rows.append({
            "fiscal_year": tds[1].inner_text().strip(),
            "date_text": tds[2].inner_text().strip().replace("\n", " "),
            "announcement_id": m.group(1) if m else None,
            "description": link.inner_text().strip(),
        })
    return rows


def scrape_announcement_detail(page, announcement_id):
    url = f"https://merolagani.com/AnnouncementDetail.aspx?id={announcement_id}"
    page.goto(url, timeout=30000)
    page.wait_for_timeout(500)

    fields = {}
    trs = page.query_selector_all("table tr")
    for tr in trs:
        tds = tr.query_selector_all("td")
        if len(tds) == 2:
            label = tds[0].inner_text().strip()
            value = tds[1].inner_text().strip()
            if label in DETAIL_LABELS:
                fields[DETAIL_LABELS[label]] = value
    return fields


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="only process the first N symbols -- use this for a test run")
    args = parser.parse_args()

    if not os.path.exists(COMPANY_DB):
        print(f"ERROR: {COMPANY_DB} not found -- run scrape_company_list.py first.")
        return

    company_conn = sqlite3.connect(COMPANY_DB)
    symbols = [r[0] for r in company_conn.execute(
        "select symbol from company_list order by symbol"
    ).fetchall()]
    company_conn.close()

    if args.limit:
        symbols = symbols[:args.limit]
    print(f"Processing {len(symbols)} symbol(s). Writing to: {OUT_DB}\n")

    out_conn = sqlite3.connect(OUT_DB)
    init_db(out_conn)

    done, no_reports, failed = 0, 0, 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for symbol in symbols:
            try:
                rows = scrape_quarterly_list(page, symbol)
                if not rows:
                    print(f"  {symbol}: no quarterly reports found")
                    no_reports += 1
                    time.sleep(DELAY_SECONDS)
                    continue

                for r in rows:
                    out_conn.execute(
                        """INSERT OR REPLACE INTO quarterly_reports
                           (symbol, fiscal_year, date_text, announcement_id, description)
                           VALUES (?, ?, ?, ?, ?)""",
                        (symbol, r["fiscal_year"], r["date_text"], r["announcement_id"], r["description"]),
                    )

                latest = rows[0]
                if latest["announcement_id"]:
                    detail = scrape_announcement_detail(page, latest["announcement_id"])
                    out_conn.execute(
                        """INSERT OR REPLACE INTO quarterly_detail
                           (symbol, announcement_id, bookclose_date, cash_dividend_pct,
                            bonus_share_pct, right_share_ratio, announcement_date,
                            fiscal_year, tags)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (symbol, latest["announcement_id"],
                         detail.get("bookclose_date"), detail.get("cash_dividend_pct"),
                         detail.get("bonus_share_pct"), detail.get("right_share_ratio"),
                         detail.get("announcement_date"), detail.get("fiscal_year"),
                         detail.get("tags")),
                    )

                out_conn.commit()
                print(f"  {symbol}: {len(rows)} report(s), latest FY {latest['fiscal_year']} ({latest['date_text']})")
                done += 1
            except Exception as e:
                print(f"  {symbol}: FAILED -- {e}")
                failed += 1

            time.sleep(DELAY_SECONDS)

        browser.close()

    out_conn.close()
    print(f"\nDone. {done} symbol(s) with data, {no_reports} with no reports, {failed} failed.")


if __name__ == "__main__":
    main()