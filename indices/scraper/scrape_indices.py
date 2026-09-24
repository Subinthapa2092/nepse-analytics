"""
Scrapes all NEPSE index history tables from https://merolagani.com/Indices.aspx
into a local SQLite database.

The site is old-school ASP.NET WebForms: the dropdown and pagination links
are javascript:__doPostBack(...) calls, not plain URLs. Rather than replaying
the __VIEWSTATE/__EVENTVALIDATION tokens by hand, this drives a real headless
browser with Playwright, so it just clicks things the same way you would.

Setup (run once):
    pip install playwright
    playwright install chromium

Run:
    python scrape_indices.py
"""

import os
import re
import sqlite3
import time

from playwright.sync_api import sync_playwright

URL = "https://merolagani.com/Indices.aspx"

# Resolves to <project>/indices/nepse_indices.sqlite no matter which folder
# you run "python scrape_indices.py" from, as long as this file stays at
# indices/scraper/scrape_indices.py.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "..", "nepse_indices.sqlite")
DB_PATH = os.path.normpath(DB_PATH)

DELAY_SECONDS = 1.0  # politeness delay between page loads

INDEX_NAMES = [
    "Nepse1", "NEPSE", "Sensitive", "Float", "Sen. Float", "Banking",
    "Trading", "Hotels And Tourism", "Development Bank", "Hydropower",
    "Finance", "Microfinance", "Non-Life Insurance", "Life Insurance",
    "Manu.and Pro.", "Others", "Mutual Fund", "Investment",
]


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS index_history (
            index_name  TEXT NOT NULL,
            date        TEXT NOT NULL,   -- 'YYYY-MM-DD'
            index_value REAL NOT NULL,
            abs_change  REAL,
            pct_change  REAL,
            PRIMARY KEY (index_name, date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_date ON index_history(date)")
    conn.commit()


def parse_number(text):
    """'2,618.03' -> 2618.03, '-1.36%' -> -1.36, '' -> None"""
    text = text.strip().replace(",", "").replace("%", "")
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def wait_for_table_data(page, timeout=15000):
    """
    Waits until a table row containing a real 'YYYY/MM/DD' date actually
    appears in the DOM. This site renders its grid via an ASP.NET
    UpdatePanel (AJAX partial postback), so wait_for_load_state("networkidle")
    can resolve before the new rows are actually patched in — this waits for
    the real condition we need instead of guessing a timeout.
    """
    page.wait_for_function(
        """() => {
            const rows = document.querySelectorAll('table tr');
            for (const r of rows) {
                const tds = r.querySelectorAll('td');
                if (tds.length >= 2 && /\\d{4}\\/\\d{2}\\/\\d{2}/.test(tds[1].innerText)) {
                    return true;
                }
            }
            return false;
        }""",
        timeout=timeout,
    )
    rows = page.query_selector_all("table tr")
    inserted = 0
    for row in rows:
        cells = row.query_selector_all("td")
        if len(cells) < 5:
            continue
        date_text = cells[1].inner_text().strip()
        if not re.match(r"\d{4}/\d{2}/\d{2}", date_text):
            continue
        date_iso = date_text.replace("/", "-")
        value = parse_number(cells[2].inner_text())
        abs_chg = parse_number(cells[3].inner_text())
        pct_chg = parse_number(cells[4].inner_text())
        if value is None:
            continue
        conn.execute(
            """INSERT OR REPLACE INTO index_history
               (index_name, date, index_value, abs_change, pct_change)
               VALUES (?, ?, ?, ?, ?)""",
            (index_name, date_iso, value, abs_chg, pct_chg),
        )
        inserted += 1
    conn.commit()
    return inserted


def scrape_index(page, index_name, conn, stop_at_first_existing_date=False):
    print(f"\n=== {index_name} ===")

    # Select the index from the dropdown (adjust the selector below if the
    # site's actual <select> id differs — inspect with browser devtools if
    # this fails: right-click the dropdown -> Inspect).
    page.select_option("select", label=index_name)
    try:
        wait_for_table_data(page)
    except Exception:
        print(f"  [warn] table never appeared after selecting {index_name} (timed out)")
    time.sleep(DELAY_SECONDS)

    # --- DIAGNOSTIC: confirm what's actually on the page now ---
    heading = page.query_selector("h1, h2, h3, h4")
    heading_text = heading.inner_text().strip() if heading else "(no heading found)"
    select_el = page.query_selector("select")
    current_value = select_el.evaluate("el => el.value") if select_el else "(no select found)"
    all_selects = page.query_selector_all("select")
    print(f"  [debug] page heading: {heading_text!r} | select.value: {current_value!r} | #select elements on page: {len(all_selects)}")
    # --- end diagnostic ---

    page_num = 1
    while True:
        got = scrape_current_page(page, index_name, conn)
        print(f"  page {page_num}: {got} rows")

        if got == 0:
            # --- DIAGNOSTIC: show what the table actually contains ---
            rows = page.query_selector_all("table tr")
            print(f"  [debug] {len(rows)} <tr> found on page, first 3 raw:")
            for r in rows[:3]:
                print(f"    {r.inner_text()[:120]!r}")
            # --- end diagnostic ---

        # Try to click "Next"; if it's not there or disabled, we're done.
        next_link = page.query_selector("a:has-text('Next')")
        if not next_link:
            break
        before_first_date = _first_row_date(page)
        next_link.click()
        try:
            wait_for_table_data(page)
        except Exception:
            print(f"  [warn] table never reappeared after clicking Next (page {page_num + 1})")
            break
        time.sleep(DELAY_SECONDS)
        after_first_date = _first_row_date(page)
        if before_first_date == after_first_date:
            # Next click didn't actually move to a new page — stop.
            break
        page_num += 1


def main():
    print(f"Writing to: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL)
        page.wait_for_load_state("networkidle")

        for name in INDEX_NAMES:
            try:
                scrape_index(page, name, conn)
            except Exception as e:
                print(f"  !! failed on {name}: {e}")

        browser.close()

    total = conn.execute("SELECT COUNT(*) FROM index_history").fetchone()[0]
    print(f"\nDone. {total} total rows in {DB_PATH}")
    conn.close()


if __name__ == "__main__":
    main()