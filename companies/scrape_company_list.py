"""
Scrapes the full NEPSE listed-company directory from
https://merolagani.com/CompanyList.aspx into a local SQLite database.

Unlike the floorsheet/indices pages, this page is PLAIN SERVER-RENDERED HTML
-- confirmed by fetching it directly with no browser needed. No Playwright,
no postback clicks, no Search button -- just requests + BeautifulSoup.

This is the FIRST scraper in the fundamentals/corporate-actions pipeline: the
symbol list here feeds the next scraper, which will visit
CompanyDetail.aspx?symbol=X for each one to pull EPS, P/E, book value, and
bonus/rights/dividend history.

Run:
    python scrape_company_list.py

NOTE: the exact HTML structure below (the "[id^='collapse_']" selector) is
inferred from the page's rendered content, not confirmed against raw HTML
source -- the [debug]/[warn] prints exist specifically to catch a wrong guess
on the FIRST real run, the same way they did for the floorsheet/indices
scrapers.
"""

import os
import sqlite3

import requests
from bs4 import BeautifulSoup

URL = "https://merolagani.com/CompanyList.aspx"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "nepse_companies.sqlite"))

# Sectors to skip -- not ordinary equity shares, so EPS/PE/bonus history
# doesn't meaningfully apply (bonds pay coupons not dividends; promoter
# shares/preferred stock are a different share class from the ordinary
# shares your prices and floorsheet data already track).
SKIP_SECTORS = {"Corporate Debenture", "Government Bond", "Preferred Stock", "Promotor Share"}


def parse_number(text):
    text = text.replace(",", "").strip()
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS company_list (
            symbol         TEXT PRIMARY KEY,
            company_name   TEXT NOT NULL,
            sector         TEXT NOT NULL,
            listed_shares  REAL,
            paidup_value   REAL,
            total_paidup   REAL
        )
    """)
    conn.commit()


def scrape():
    resp = requests.get(URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    rows = []
    panels = soup.select("[id^='collapse_']")
    print(f"[debug] found {len(panels)} sector panel(s) matching [id^='collapse_']")
    if not panels:
        print("[debug] trying fallback: every <table> on the page, sector name from "
              "the nearest preceding heading")
        panels = soup.find_all("table")

    for panel in panels:
        heading = panel.find_previous(["h2", "h3", "h4"])
        sector = heading.get_text(strip=True) if heading else "(unknown sector)"
        if sector in SKIP_SECTORS:
            print(f"  skipping sector: {sector}")
            continue

        table = panel if panel.name == "table" else panel.find("table")
        if table is None:
            print(f"  [warn] no <table> found for sector: {sector!r}")
            continue

        tbody = table.find("tbody") or table
        count = 0
        for tr in tbody.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 5:
                continue
            symbol_link = cells[0].find("a")
            symbol = (symbol_link.get_text(strip=True) if symbol_link
                      else cells[0].get_text(strip=True))
            if not symbol:
                continue
            rows.append({
                "symbol": symbol,
                "company_name": cells[1].get_text(strip=True),
                "sector": sector,
                "listed_shares": parse_number(cells[2].get_text()),
                "paidup_value": parse_number(cells[3].get_text()),
                "total_paidup": parse_number(cells[4].get_text()),
            })
            count += 1
        print(f"  {sector}: {count} companies")

    return rows


def main():
    print(f"Writing to: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    rows = scrape()
    if not rows:
        print("\n[warn] zero rows parsed -- the page structure likely differs from what "
              "this script assumes. Check the [debug]/[warn] lines above and send them "
              "back so the selectors can be corrected against the real page.")

    for r in rows:
        conn.execute(
            """INSERT OR REPLACE INTO company_list
               (symbol, company_name, sector, listed_shares, paidup_value, total_paidup)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (r["symbol"], r["company_name"], r["sector"],
             r["listed_shares"], r["paidup_value"], r["total_paidup"]),
        )
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM company_list").fetchone()[0]
    print(f"\nDone. {total} companies saved to {DB_PATH}")
    conn.close()


if __name__ == "__main__":
    main()