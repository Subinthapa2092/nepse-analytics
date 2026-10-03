"""
Diagnostic only -- not part of the real scraper.

Fetches ADBL's real page the same way scrape_fundamentals.py does, then
dumps the raw HTML around every occurrence of "bonus" to bonus_html_dump.txt
-- specifically looking for WHICH <a> tag containing "bonus" comes first in
the document, since that's the one _history_rows_near will match.

Run this from inside the fundamentals/ folder:
    python dump_bonus_html.py
"""

import re
from scrape_fundamentals import BASE_URL, HEADERS
import requests
from bs4 import BeautifulSoup

SYMBOL = "ADBL"

resp = requests.get(BASE_URL.format(SYMBOL), headers=HEADERS, timeout=20)
resp.raise_for_status()
html = resp.text
soup = BeautifulSoup(html, "html.parser")

print(f"Fetched {len(html)} characters for {SYMBOL}")

# Dump raw HTML around every "bonus" occurrence, same as the dividend dump.
out_lines = []
for m in re.finditer(r"bonus", html, re.IGNORECASE):
    start = max(0, m.start() - 300)
    end = min(len(html), m.end() + 300)
    out_lines.append(f"\n{'='*80}\nMATCH at character {m.start()}:\n{'='*80}\n")
    out_lines.append(html[start:end])

with open("bonus_html_dump.txt", "w", encoding="utf-8") as f:
    f.writelines(out_lines)

match_count = len(re.findall(r"bonus", html, re.IGNORECASE))
print(f"Found {match_count} occurrence(s) of 'bonus' in the page.")

# Also specifically show which <a> tag _history_rows_near would actually
# match first, using the exact same normalize+startswith logic.
def _normalize_label(s):
    return s.strip().lstrip("%").strip().lower()

target = _normalize_label("% bonus")
print(f"\nSearching for first <a> tag whose normalized text starts with: {target!r}")
for i, a in enumerate(soup.find_all("a")):
    normalized = _normalize_label(a.get_text(strip=True))
    if normalized.startswith(target):
        print(f"  MATCHED <a> #{i}: raw text={a.get_text(strip=True)!r} | normalized={normalized!r}")
        print(f"  href={a.get('href')!r} title={a.get('title')!r}")
        break
else:
    print("  No <a> tag matched at all.")

print("\nDumped surrounding HTML to: bonus_html_dump.txt")
print("Open that file and paste me its contents.")