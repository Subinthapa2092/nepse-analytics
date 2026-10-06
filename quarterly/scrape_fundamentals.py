"""
Scrapes, for every symbol in companies/nepse_companies.sqlite, the static
"accordion" summary table on merolagani's CompanyDetail.aspx:

  - EPS, P/E Ratio, Book Value, PBV (latest, with fiscal year if shown)
  - Full historical % Cash Dividend, % Bonus Share, Right Share rows
    (from the #dividend-panel / #bonus-panel / #right-panel collapsible
    tables on the same page)

Unlike the Quarterly Report tab, this data is in the plain server-rendered
HTML -- confirmed by direct testing -- so this uses plain requests +
BeautifulSoup. No Playwright, no browser, much faster than the quarterly
scraper.

A symbol having zero rows in a panel (e.g. no bonus history) is a valid,
correctly-scraped result, not a failure -- some companies genuinely never
issued bonus shares or right shares.

TEST ON A FEW SYMBOLS FIRST:
    python scrape_fundamentals.py --limit 5

Then run the full pass:
    python scrape_fundamentals.py
"""

import argparse
import os
import re
import sqlite3
import time

import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COMPANY_DB = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "companies", "nepse_companies.sqlite"))
OUT_DB = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "companies", "nepse_fundamentals.sqlite"))

DELAY_SECONDS = 0.3  # politeness delay between symbols -- no browser launch cost here, can be short

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

# panel id -> event_type label we store
PANELS = {
    "dividend-panel": "dividend",
    "bonus-panel": "bonus",
    "right-panel": "right",
}

# summary row label (as it appears in table#accordion) -> column name
SUMMARY_LABELS = {
    "EPS": "eps",
    "P/E Ratio": "pe_ratio",
    "Book Value": "book_value",
    "PBV": "pbv",
}

FY_RE = re.compile(r"FY[:\s]*([\d]{3}[/\-][\d]{3}|[\d]{2,4}[/\-][\d]{2,4})", re.IGNORECASE)
NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS company_fundamentals (
            symbol       TEXT NOT NULL PRIMARY KEY,
            eps          TEXT,
            eps_fy       TEXT,
            pe_ratio     TEXT,
            book_value   TEXT,
            book_value_fy TEXT,
            pbv          TEXT,
            scraped_at   TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fundamentals_history (
            symbol       TEXT NOT NULL,
            event_type   TEXT NOT NULL,   -- 'dividend' | 'bonus' | 'right'
            fiscal_year  TEXT NOT NULL,
            value_text   TEXT,            -- raw text, e.g. "9.75%" or "1:10" or "" if blank
            PRIMARY KEY (symbol, event_type, fiscal_year)
        )
    """)
    conn.commit()


def extract_fy(text):
    m = FY_RE.search(text)
    return m.group(1) if m else None


def extract_num(text):
    m = NUM_RE.search(text)
    return m.group(0) if m else None


def parse_summary_row(tr, found):
    """table#accordion top-level rows: label cell (th or first td) + value cell."""
    cells = tr.find_all(["th", "td"], recursive=False)
    if len(cells) < 2:
        return
    label = cells[0].get_text(strip=True)
    # label may be wrapped in an <a> (the % Dividend / % Bonus / Right Share rows) --
    # those are handled separately via PANELS, skip them here.
    label = re.sub(r"^%\s*", "", label)
    value_text = cells[1].get_text(" ", strip=True)
    for key, col in SUMMARY_LABELS.items():
        if label.lower() == key.lower():
            found[col] = extract_num(value_text)
            fy = extract_fy(value_text)
            if fy:
                found[col + "_fy"] = fy


def parse_panel_history(soup, panel_id, event_type, symbol, rows_out):
    panel = soup.find(id=panel_id)
    if panel is None:
        return
    table = panel.find("table")
    if table is None:
        return
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        texts = [c.get_text(" ", strip=True) for c in cells]
        joined = " ".join(texts)
        fy = extract_fy(joined)
        if not fy:
            continue  # header row or junk row -- skip
        # value is whichever cell holds a %, a ratio (a:b), or a plain number --
        # excluding the cell(s) that are just a sequence number like "12."
        value_text = ""
        for t in texts:
            if FY_RE.search(t):
                continue
            if re.fullmatch(r"\d+\.?", t):  # bare sequence number, e.g. "12."
                continue
            if t:
                value_text = t
                break
        rows_out.append((symbol, event_type, fy, value_text))


def scrape_symbol(session, symbol):
    url = f"https://merolagani.com/CompanyDetail.aspx?symbol={symbol}"
    resp = session.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    accordion = soup.find("table", id="accordion")
    found = {}
    if accordion is not None:
        for tr in accordion.find_all("tr", recursive=False):
            parse_summary_row(tr, found)
        # some pages nest the rows inside a tbody
        for tbody in accordion.find_all("tbody"):
            for tr in tbody.find_all("tr", recursive=False):
                parse_summary_row(tr, found)

    history_rows = []
    for panel_id, event_type in PANELS.items():
        parse_panel_history(soup, panel_id, event_type, symbol, history_rows)

    return found, history_rows


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

    session = requests.Session()
    done, empty, failed = 0, 0, 0

    for symbol in symbols:
        try:
            found, history_rows = scrape_symbol(session, symbol)

            if not found and not history_rows:
                print(f"  {symbol}: no fundamentals data found")
                empty += 1
                time.sleep(DELAY_SECONDS)
                continue

            out_conn.execute(
                """INSERT INTO company_fundamentals
                       (symbol, eps, eps_fy, pe_ratio, book_value, book_value_fy, pbv, scraped_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(symbol) DO UPDATE SET
                       eps=excluded.eps, eps_fy=excluded.eps_fy,
                       pe_ratio=excluded.pe_ratio,
                       book_value=excluded.book_value, book_value_fy=excluded.book_value_fy,
                       pbv=excluded.pbv, scraped_at=excluded.scraped_at""",
                (symbol, found.get("eps"), found.get("eps_fy"), found.get("pe_ratio"),
                 found.get("book_value"), found.get("book_value_fy"), found.get("pbv")),
            )

            for row in history_rows:
                out_conn.execute(
                    """INSERT OR REPLACE INTO fundamentals_history
                           (symbol, event_type, fiscal_year, value_text)
                       VALUES (?, ?, ?, ?)""",
                    row,
                )

            out_conn.commit()
            print(f"  {symbol}: EPS={found.get('eps')} PE={found.get('pe_ratio')} "
                  f"BV={found.get('book_value')} PBV={found.get('pbv')} "
                  f"| {len(history_rows)} history row(s)")
            done += 1
        except Exception as e:
            print(f"  {symbol}: FAILED -- {e}")
            failed += 1

        time.sleep(DELAY_SECONDS)

    out_conn.close()
    print(f"\nDone. {done} symbol(s) with data, {empty} empty, {failed} failed.")


if __name__ == "__main__":
    main()