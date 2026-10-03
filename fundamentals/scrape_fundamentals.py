"""
Scrapes fundamentals (EPS, P/E, Book Value, PBV) and corporate action history
(bonus %, right share ratio, dividend %) for each symbol in company_list,
from https://merolagani.com/CompanyDetail.aspx?symbol=X

Reads its symbol list from ../companies/nepse_companies.sqlite (built by
scrape_company_list.py) -- run that first if this table is empty.

HONESTY NOTE, read before running against all 345 symbols:
This page was only inspected via a rendered-content fetch, not raw HTML
source -- unlike scrape_company_list.py, the exact markup here (class names,
element structure) has NOT been directly confirmed. This script matches by
LABEL TEXT ("EPS", "P/E Ratio", etc.) rather than guessing CSS selectors,
which is more robust to markup differences, but it still needs a real test
run to prove it actually works. TEST ON 2-3 SYMBOLS FIRST:

    python scrape_fundamentals.py --limit 3

Only run the full 345-symbol pass once that confirms real numbers are being
captured, not blanks.

Also known, stated honestly: the bonus/dividend/right-share history tables on
the live page may show only a FEW recent years by default, with a "Show All"
link needed for full history -- this script captures whatever is present on
page load. If the [debug] output after a test run shows fewer history rows
than you'd expect, that's the likely reason, and getting the rest would need
a browser (Playwright) click on "Show All", not yet built here.
"""

import argparse
import os
import re
import sqlite3
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://merolagani.com/CompanyDetail.aspx?symbol={}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
DELAY_SECONDS = 1.0  # politeness delay between requests -- 345 symbols, be gentle

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COMPANY_DB = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "companies", "nepse_companies.sqlite"))
OUT_DB = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "companies", "nepse_fundamentals.sqlite"))

# Label text to look for on the page -> the field name we save it as.
# Matched case-insensitively against the text of small label elements
# (spans/divs/th/td), then the VALUE is taken from that element's sibling
# or immediate next text -- see _label_value() below.
FUNDAMENTAL_LABELS = {
    "eps": "eps",
    "p/e ratio": "pe_ratio",
    "book value": "book_value",
    "pbv": "pbv",
    "market cap": "market_cap",
    "1 year yield": "one_year_yield",
}

# History table headings to look for -> what dataset they belong to.
HISTORY_TABLE_LABELS = {
    "% dividend": "dividend",
    "% bonus": "bonus",
    "right share": "right_share",
}


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fundamentals (
            symbol         TEXT PRIMARY KEY,
            eps            REAL,
            pe_ratio       REAL,
            book_value     REAL,
            pbv            REAL,
            market_cap     REAL,
            one_year_yield REAL,
            fetched_at     TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS corporate_actions (
            symbol       TEXT NOT NULL,
            action_type  TEXT NOT NULL,   -- 'dividend' | 'bonus' | 'right_share'
            fiscal_year  TEXT NOT NULL,   -- as shown on the site, e.g. '082-083' (Bikram Sambat)
            value        TEXT NOT NULL,   -- '22.00' or '1:0.70' -- kept as text, meaning differs by type
            PRIMARY KEY (symbol, action_type, fiscal_year)
        )
    """)
    conn.commit()


def _clean_number(text):
    """Extracts the leading numeric value from text, ignoring any trailing
    context (e.g. "16.11    (FY:082-083, Q:4)" -> 16.11)."""
    import re
    if not text:
        return None
    text = text.replace(",", "")
    match = re.search(r"-?\d+\.?\d*", text)
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _label_value(soup, label_text):
    """Finds a small element whose text matches label_text (case-insensitive,
    exact match after stripping), and returns the text of whatever looks like
    its paired value -- tries the next sibling first, then the parent's next
    sibling, since label/value pairs render differently across sites."""
    for el in soup.find_all(["span", "div", "td", "th", "label", "li", "p"]):
        text = el.get_text(strip=True)
        if text.lower() == label_text.lower():
            nxt = el.find_next_sibling()
            if nxt and nxt.get_text(strip=True):
                return nxt.get_text(strip=True)
            parent = el.parent
            if parent:
                parent_nxt = parent.find_next_sibling()
                if parent_nxt and parent_nxt.get_text(strip=True):
                    return parent_nxt.get_text(strip=True)
    return None
def _inline_snapshot_near(heading_el):
    """Fallback for labels like Bonus that show only a single inline snapshot
    value in the SAME table row as their own link/heading, rather than a real
    multi-row history table (confirmed on ADBL: the real bonus history table
    is just an empty header shell with no data rows -- the only bonus info on
    the page is "3.25    (FY:081-082)" sitting in the same row as the
    '% Bonus' link)."""
    row = heading_el.find_parent("tr")
    if row is None:
        return []
    text = row.get_text(" ", strip=True)
    m = re.search(r"(-?\d+\.?\d*)\s*\(\s*FY[:\s]*([\d]{2,3}[-/][\d]{2,3})\s*\)", text)
    if not m:
        return []
    value, fiscal_year = m.group(1), m.group(2)
    return [(fiscal_year, value)]

def _history_rows_near(soup, heading_text):
    """Finds the specific panel-link element matching heading_text, then the
    nearest following <table>, and returns [(fiscal_year, value), ...] from
    its rows. Returns [] if nothing matches.

    FIX: the previous version searched span/div/h1-4/th/td for ANY element
    whose text CONTAINED heading_text as a substring, then broke on the
    first hit. On this site, the whole summary block (Sector, Market Price,
    ..., % Dividend, % Bonus, Right Share, ...) sits inside one outer
    container, so that outer wrapper's combined text contains ALL THREE
    labels as substrings -- and since BeautifulSoup yields parents before
    children, that same outer wrapper matched first for every label,
    sending "Dividend", "Bonus" and "Right Share" all to the same
    .find_next("table") call. That's why all three counts always came out
    identical.

    This version searches only <a> tags (the actual panel links, e.g.
    '% Dividend', '% Bonus', 'Right Share') and requires the link's
    stripped text to START WITH heading_text rather than just contain it
    anywhere -- much less likely to accidentally match a large wrapping
    element instead of the specific link.
    """
    def _normalize_label(s):
        # Strip a leading '%' AND surrounding whitespace from BOTH sides of
        # the comparison -- the real site's panel links render as "% Dividend"
        # and "% Bonus" but "Right Share" (no %), so normalizing only the
        # scraped text and not heading_text (the previous bug) silently broke
        # matching for any label that itself included a '%'.
        return s.strip().lstrip("%").strip().lower()

    heading_el = None
    target = _normalize_label(heading_text)
    for a in soup.find_all("a"):
        normalized = _normalize_label(a.get_text(strip=True))
        if normalized.startswith(target):
            heading_el = a
            break

    if heading_el is None:
        return []

    table = heading_el.find_next("table")
    if table is None:
        return _inline_snapshot_near(heading_el)

    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all("td")]
        if len(cells) < 2:
            continue
        fy_cell = next((c for c in cells if re.search(r"\d{2,3}[-/]\d{2,3}", c)), None)
        if fy_cell is None:
            continue
        value_cell = next((c for c in cells if c is not fy_cell), None)
        if value_cell is None:
            continue
        rows.append((fy_cell, value_cell))
    if not rows:
        return _inline_snapshot_near(heading_el)
    return rows

def scrape_symbol(symbol):
    resp = requests.get(BASE_URL.format(symbol), headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    fundamentals = {}
    for label, field in FUNDAMENTAL_LABELS.items():
        raw = _label_value(soup, label)
        fundamentals[field] = _clean_number(raw) if raw else None

    history = {}
    for label, action_type in HISTORY_TABLE_LABELS.items():
        history[action_type] = _history_rows_near(soup, label)

    return fundamentals, history


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

    empty_count = 0
    for i, symbol in enumerate(symbols, start=1):
        try:
            fundamentals, history = scrape_symbol(symbol)
        except Exception as e:
            print(f"[{i}/{len(symbols)}] {symbol}: FAILED -- {e}")
            continue

        got_any_fundamental = any(v is not None for v in fundamentals.values())
        got_any_history = any(rows for rows in history.values())

        print(f"[{i}/{len(symbols)}] {symbol}: "
              f"EPS={fundamentals['eps']} PE={fundamentals['pe_ratio']} "
              f"BookValue={fundamentals['book_value']} | "
              f"history rows: dividend={len(history['dividend'])} "
              f"bonus={len(history['bonus'])} right={len(history['right_share'])}")

        if not got_any_fundamental and not got_any_history:
            empty_count += 1
            print(f"    [warn] nothing parsed for {symbol} -- label matching may not be "
                  f"finding the right elements on this page")

        out_conn.execute(
            """INSERT OR REPLACE INTO fundamentals
               (symbol, eps, pe_ratio, book_value, pbv, market_cap, one_year_yield)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (symbol, fundamentals["eps"], fundamentals["pe_ratio"], fundamentals["book_value"],
             fundamentals["pbv"], fundamentals["market_cap"], fundamentals["one_year_yield"]),
        )
        for action_type, rows in history.items():
            for fiscal_year, value in rows:
                out_conn.execute(
                    """INSERT OR REPLACE INTO corporate_actions
                       (symbol, action_type, fiscal_year, value) VALUES (?, ?, ?, ?)""",
                    (symbol, action_type, fiscal_year, value),
                )
        out_conn.commit()
        time.sleep(DELAY_SECONDS)

    print(f"\nDone. {len(symbols) - empty_count}/{len(symbols)} symbols had at least "
          f"some data parsed. {empty_count} came back completely empty.")
    if empty_count == len(symbols):
        print("\nEVERY symbol came back empty -- the label-matching almost certainly "
              "isn't finding the right page elements. Do not run this against all 345 "
              "symbols yet; send back this output so the matching logic can be fixed "
              "against the real page structure.")
    out_conn.close()


if __name__ == "__main__":
    main()