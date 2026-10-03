"""
Diagnostic only -- checks whether ShareSansar's per-company page
(sharesansar.com/company/<symbol>) renders the Dividend History and
Right Share History tables directly in the static HTML (requests +
BeautifulSoup can see them) or only loads them via a separate AJAX
call (would need Playwright, like merolagani's bonus panel did).
"""

import requests
from bs4 import BeautifulSoup

SYMBOL = "adbl"
URL = f"https://www.sharesansar.com/company/{SYMBOL}"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

resp = requests.get(URL, headers=HEADERS, timeout=20)
resp.raise_for_status()
print(f"Fetched {len(resp.text)} characters for {SYMBOL}")

with open("sharesansar_full_dump.html", "w", encoding="utf-8") as f:
    f.write(resp.text)
print("Saved full raw HTML to: sharesansar_full_dump.html")

soup = BeautifulSoup(resp.text, "html.parser")

for target_id in ["cdividend", "crightshare", "cagm"]:
    el = soup.find(id=target_id)
    if el is None:
        print(f"\nid='{target_id}': NOT FOUND in raw HTML")
        continue
    rows = el.find_all("tr")
    print(f"\nid='{target_id}': FOUND -- {len(rows)} <tr> rows")
    for i, tr in enumerate(rows[:5]):
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        print(f"  row {i}: {cells}")