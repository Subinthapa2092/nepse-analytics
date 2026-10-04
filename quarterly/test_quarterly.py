"""
Test-only script: proves out scraping merolagani's per-symbol Quarterly Report
list and the announcement detail page, on ONE symbol (ADBL) before building
the real 345-symbol scraper.

Run from the quarterly/ folder:
    python test_quarterly.py

What this checks:
  1. Can we get the Quarterly Report list (fiscal year, date, announcement id)
     from a plain GET on CompanyDetail.aspx -- no JS, no postback needed?
  2. Can we get the structured fields (Bookclose Date, % Cash Dividend, etc.)
     from the Announcement Detail page?
  3. THE BIG UNKNOWN: is the embedded financial statement (Total Assets, Net
     Profit) real text in that same page's HTML, or not? This script searches
     for "Total Assets" in the raw page text and tells you honestly either
     way -- no guessing.
"""

import re

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
SYMBOL = "ADBL"


def get_quarterly_list(symbol):
    url = f"https://merolagani.com/CompanyDetail.aspx?symbol={symbol}"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    container = soup.find(id="divQuaterly")
    if container is None:
        print("[FAIL] Could not find div#divQuaterly on the page at all.")
        return []

    table = container.find("table")
    if table is None:
        print("[FAIL] Found div#divQuaterly but no <table> inside it.")
        return []

    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue  # header row or malformed
        link = cells[3].find("a", href=True)
        if link is None:
            continue
        m = re.search(r"id=(\d+)", link["href"])
        announcement_id = m.group(1) if m else None
        rows.append({
            "fiscal_year": cells[1].get_text(strip=True),
            "date": cells[2].get_text(" ", strip=True),
            "announcement_id": announcement_id,
            "description": link.get_text(strip=True),
        })
    return rows


def get_announcement_detail(announcement_id):
    url = f"https://merolagani.com/AnnouncementDetail.aspx?id={announcement_id}"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    full_text = soup.get_text(" ", strip=True)

    # structured key/value rows -- label in one cell, value in the next
    fields = {}
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) == 2:
            label = cells[0].get_text(strip=True)
            value = cells[1].get_text(strip=True)
            if label:
                fields[label] = value

    # the big unknown: is "Total Assets" (or similar) present as real text?
    has_total_assets = "Total Assets" in full_text or "Total assets" in full_text.lower()

    return fields, has_total_assets, full_text


def main():
    print(f"=== Step 1: Quarterly Report list for {SYMBOL} ===")
    rows = get_quarterly_list(SYMBOL)
    if not rows:
        print("Got zero rows -- stopping here, something is wrong with Step 1.")
        return

    print(f"Found {len(rows)} row(s) on first page. First 3:")
    for r in rows[:3]:
        print(f"  FY {r['fiscal_year']} | {r['date']} | id={r['announcement_id']} | {r['description'][:70]}")

    latest = rows[0]
    if not latest["announcement_id"]:
        print("\n[FAIL] Latest row has no announcement_id -- can't continue to Step 2.")
        return

    print(f"\n=== Step 2: Announcement detail for id={latest['announcement_id']} ===")
    fields, has_total_assets, full_text = get_announcement_detail(latest["announcement_id"])

    print("Structured fields found:")
    for k, v in fields.items():
        print(f"  {k!r}: {v!r}")

    print(f"\n=== Step 3: THE BIG QUESTION ===")
    if has_total_assets:
        print("[GOOD NEWS] Found the text 'Total Assets' in the raw page HTML.")
        print("This means the embedded financial statement IS real, parseable text.")
        idx = full_text.lower().find("total assets")
        print(f"Context around it: ...{full_text[max(0,idx-50):idx+150]}...")
    else:
        print("[BAD NEWS] Did NOT find 'Total Assets' anywhere in the raw page text.")
        print("This means the embedded statement is rendered as an image/canvas,")
        print("not real text -- a plain requests+BeautifulSoup scraper can't read it.")
        print("(The structured fields above -- dividend/bonus/bookclose -- still work fine.)")


if __name__ == "__main__":
    main()