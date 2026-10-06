"""
Diagnostic: dumps the raw HTML of the dividend/bonus/right panels for a
given symbol, so we can see why scrape_fundamentals.py found 0 history
rows for some symbols (e.g. ACLBSL, AHL) but 14 for ADBL.

Usage:
    python check_panels.py ACLBSL
"""
import sys
import requests
from bs4 import BeautifulSoup

symbol = sys.argv[1] if len(sys.argv) > 1 else "ACLBSL"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

url = f"https://merolagani.com/CompanyDetail.aspx?symbol={symbol}"
resp = requests.get(url, headers=HEADERS, timeout=20)
soup = BeautifulSoup(resp.text, "html.parser")

for panel_id in ["dividend-panel", "bonus-panel", "right-panel"]:
    panel = soup.find(id=panel_id)
    print(f"\n===== {panel_id} =====")
    if panel is None:
        print("NOT FOUND on page at all")
        continue
    table = panel.find("table")
    if table is None:
        print("panel found, but NO <table> inside it")
        print(panel.prettify()[:1000])
        continue
    rows = table.find_all("tr")
    print(f"panel found, table found, {len(rows)} <tr> row(s)")
    print(table.prettify()[:2000])

with open(f"{symbol.lower()}_dump.html", "w", encoding="utf-8") as f:
    f.write(resp.text)
print(f"\nFull page saved to {symbol.lower()}_dump.html")