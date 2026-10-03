"""
Diagnostic only -- not part of the real scraper.

Fetches ADBL's real page the exact same way scrape_fundamentals.py does
(same BASE_URL, same HEADERS), then dumps the raw HTML around wherever
"Dividend" appears to dividend_html_dump.txt, so we can see the ACTUAL
structure instead of guessing from an unreliable fetch.

Run this from inside the fundamentals/ folder:
    python dump_dividend_html.py
"""

import re
from scrape_fundamentals import BASE_URL, HEADERS
import requests

SYMBOL = "ADBL"

resp = requests.get(BASE_URL.format(SYMBOL), headers=HEADERS, timeout=20)
resp.raise_for_status()
html = resp.text

print(f"Fetched {len(html)} characters for {SYMBOL}")

# Find every spot where "dividend" appears (case-insensitive) and dump a
# window of raw HTML around each one, so we can see what's actually there.
out_lines = []
for m in re.finditer(r"dividend", html, re.IGNORECASE):
    start = max(0, m.start() - 300)
    end = min(len(html), m.end() + 500)
    out_lines.append(f"\n{'='*80}\nMATCH at character {m.start()}:\n{'='*80}\n")
    out_lines.append(html[start:end])

with open("dividend_html_dump.txt", "w", encoding="utf-8") as f:
    f.writelines(out_lines)

match_count = len(re.findall(r"dividend", html, re.IGNORECASE))
print(f"Found {match_count} occurrence(s) of 'dividend' in the page.")
print("Dumped surrounding HTML to: dividend_html_dump.txt")
print("Open that file and paste me its contents.")