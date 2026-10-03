"""
Diagnostic only -- not part of the real scraper.

Finds the same "% Bonus" <a> tag the real scraper finds, follows
find_next("table") from it exactly like _history_rows_near does, then
prints the table's actual HTML and shows row-by-row why each row is
accepted or rejected by the current parsing logic.

Run this from inside the fundamentals/ folder:
    python dump_bonus_table.py
"""

import re
from scrape_fundamentals import BASE_URL, HEADERS
import requests
from bs4 import BeautifulSoup

SYMBOL = "ADBL"

resp = requests.get(BASE_URL.format(SYMBOL), headers=HEADERS, timeout=20)
resp.raise_for_status()
soup = BeautifulSoup(resp.text, "html.parser")


def _normalize_label(s):
    return s.strip().lstrip("%").strip().lower()


target = _normalize_label("% bonus")
heading_el = None
for a in soup.find_all("a"):
    if _normalize_label(a.get_text(strip=True)).startswith(target):
        heading_el = a
        break

print(f"Matched <a>: {heading_el.get_text(strip=True)!r} href={heading_el.get('href')!r}")

table = heading_el.find_next("table")
if table is None:
    print("find_next('table') returned None -- no table found after this <a> at all.")
else:
    print(f"\n--- Full HTML of the table find_next('table') returned ---\n")
    print(table.prettify()[:3000])  # cap output length

    print(f"\n--- Row-by-row parsing check ---")
    for i, tr in enumerate(table.find_all("tr")):
        cells = [c.get_text(strip=True) for c in tr.find_all("td")]
        if len(cells) < 2:
            print(f"  row {i}: REJECTED (fewer than 2 <td> cells) -- cells={cells}")
            continue
        fy_cell = next((c for c in cells if re.search(r"\d{2,3}[-/]\d{2,3}", c)), None)
        if fy_cell is None:
            print(f"  row {i}: REJECTED (no fiscal-year-shaped cell found) -- cells={cells}")
            continue
        value_cell = next((c for c in cells if c is not fy_cell), None)
        print(f"  row {i}: ACCEPTED -- fiscal_year={fy_cell!r} value={value_cell!r}")

with open("bonus_table_dump.txt", "w", encoding="utf-8") as f:
    f.write(table.prettify() if table else "No table found.")
print("\nFull table HTML also saved to: bonus_table_dump.txt")