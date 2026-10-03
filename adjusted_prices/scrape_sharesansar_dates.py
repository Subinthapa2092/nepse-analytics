"""
Scrapes ShareSansar's per-company AJAX endpoints (company-dividend,
company-rightshare) for every symbol in ../companies/nepse_companies.sqlite.

Unlike merolagani's fiscal-year-only corporate_actions table, this captures
the exact Gregorian book-close date for each bonus/dividend/right-share
event -- the piece actually needed to adjust historical daily prices
correctly (you can't back-adjust a price series without knowing the exact
date each event took effect).

Each symbol costs 1 GET (the company page, for its CSRF token + internal
company id) + 2 POST (dividend history, right-share history) = 3 requests.
"""

import argparse
import os
import sqlite3
import time

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
DELAY_SECONDS = 1.0

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COMPANY_DB = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "companies", "nepse_companies.sqlite"))
OUT_DB = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "companies", "nepse_corporate_dates.sqlite"))

DIVIDEND_COLUMNS = ["DT_Row_Index", "bonus_share", "cash_dividend", "total_dividend",
                     "announcement_date", "bookclose_date"]
RIGHT_COLUMNS = ["DT_Row_Index", "ratio_value", "total_units", "issue_price",
                  "opening_date", "closing_date", "final_date", "listing_date",
                  "issue_manager", "status", "view"]


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dividend_history (
            symbol         TEXT NOT NULL,
            fiscal_year    TEXT,
            bonus_share    REAL,
            cash_dividend  REAL,
            total_dividend REAL,
            announcement_date TEXT,
            bookclose_date TEXT,       -- exact Gregorian date, e.g. '2025-11-30'
            bonus_listing_date TEXT,
            PRIMARY KEY (symbol, fiscal_year)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS right_share_history (
            symbol        TEXT NOT NULL,
            ratio_value   TEXT,        -- e.g. '2:1'
            total_units   REAL,
            issue_price   REAL,
            opening_date  TEXT,
            closing_date  TEXT,
            bookclose_date TEXT,       -- exact Gregorian date (from 'final_date')
            listing_date  TEXT,
            PRIMARY KEY (symbol, bookclose_date)
        )
    """)
    conn.commit()


def _datatable_payload(columns, company_id):
    data = {
        "draw": "1", "start": "0", "length": "50",
        "search[value]": "", "search[regex]": "false",
        "company": company_id,
    }
    for i, col in enumerate(columns):
        data[f"columns[{i}][data]"] = col
        data[f"columns[{i}][name]"] = ""
        data[f"columns[{i}][searchable]"] = "false"
        data[f"columns[{i}][orderable]"] = "false"
        data[f"columns[{i}][search][value]"] = ""
        data[f"columns[{i}][search][regex]"] = "false"
    return data


def _clean_num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _strip_closed(v):
    # bookclose_date / final_date come back like "2025-11-30 [Closed]"
    if not v:
        return None
    return v.split(" ")[0].strip() or None


def scrape_symbol(session, symbol):
    page = session.get(f"https://www.sharesansar.com/company/{symbol.lower()}",
                        headers=HEADERS, timeout=20)
    page.raise_for_status()
    soup = BeautifulSoup(page.text, "html.parser")

    token_el = soup.find("meta", attrs={"name": "_token"})
    id_el = soup.find(id="companyid")
    if token_el is None or id_el is None:
        raise ValueError("no CSRF token or company id found on page -- symbol may not exist here")

    token = token_el["content"]
    company_id = id_el.get_text(strip=True)
    post_headers = dict(HEADERS)
    post_headers["X-CSRF-Token"] = token
    post_headers["X-Requested-With"] = "XMLHttpRequest"

    div_resp = session.post("https://www.sharesansar.com/company-dividend",
                             headers=post_headers,
                             data=_datatable_payload(DIVIDEND_COLUMNS, company_id),
                             timeout=20)
    div_resp.raise_for_status()
    dividends = div_resp.json().get("data", [])

    time.sleep(0.3)

    right_resp = session.post("https://www.sharesansar.com/company-rightshare",
                               headers=post_headers,
                               data=_datatable_payload(RIGHT_COLUMNS, company_id),
                               timeout=20)
    right_resp.raise_for_status()
    rights = right_resp.json().get("data", [])

    return dividends, rights


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="only process the first N symbols -- use this for a first test run")
    args = parser.parse_args()

    if not os.path.exists(COMPANY_DB):
        print(f"ERROR: {COMPANY_DB} not found -- run scrape_company_list.py first.")
        return

    company_conn = sqlite3.connect(COMPANY_DB)
    symbols = [r[0] for r in company_conn.execute("select symbol from company_list order by symbol").fetchall()]
    company_conn.close()

    if args.limit:
        symbols = symbols[:args.limit]
    print(f"Processing {len(symbols)} symbol(s). Writing to: {OUT_DB}\n")

    out_conn = sqlite3.connect(OUT_DB)
    init_db(out_conn)

    session = requests.Session()
    empty_count = 0

    for i, symbol in enumerate(symbols, start=1):
        try:
            dividends, rights = scrape_symbol(session, symbol)
        except Exception as e:
            print(f"[{i}/{len(symbols)}] {symbol}: FAILED -- {e}")
            continue

        for d in dividends:
            out_conn.execute(
                """INSERT OR REPLACE INTO dividend_history
                   (symbol, fiscal_year, bonus_share, cash_dividend, total_dividend,
                    announcement_date, bookclose_date, bonus_listing_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, d.get("year"), _clean_num(d.get("bonus_share")),
                 _clean_num(d.get("cash_dividend")), _clean_num(d.get("total_dividend")),
                 d.get("announcement_date"), _strip_closed(d.get("bookclose_date")),
                 d.get("bonus_listing_date")),
            )
        for r in rights:
            out_conn.execute(
                """INSERT OR REPLACE INTO right_share_history
                   (symbol, ratio_value, total_units, issue_price, opening_date,
                    closing_date, bookclose_date, listing_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, r.get("ratio_value"), _clean_num(r.get("total_units")),
                 _clean_num(r.get("issue_price")), r.get("opening_date"),
                 r.get("closing_date"), _strip_closed(r.get("final_date")),
                 r.get("listing_date")),
            )
        out_conn.commit()

        if not dividends and not rights:
            empty_count += 1
        print(f"[{i}/{len(symbols)}] {symbol}: dividend_rows={len(dividends)} right_rows={len(rights)}")
        time.sleep(DELAY_SECONDS)

    print(f"\nDone. {len(symbols) - empty_count}/{len(symbols)} symbols had at least some data. "
          f"{empty_count} came back completely empty.")
    out_conn.close()


if __name__ == "__main__":
    main()