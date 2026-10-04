"""
Diagnostic only. Dumps exactly what a plain GET on CompanyDetail.aspx
returns for the div#divQuaterly tab pane, so we can see whether it's
truly empty (needs a postback) or just has a different structure than
expected.

Run from quarterly/:
    python debug_quarterly.py
"""

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
SYMBOL = "ADBL"

url = f"https://merolagani.com/CompanyDetail.aspx?symbol={SYMBOL}"
resp = requests.get(url, headers=HEADERS, timeout=20)
resp.raise_for_status()
print(f"Status: {resp.status_code}, page length: {len(resp.text)} chars")

soup = BeautifulSoup(resp.text, "html.parser")

container = soup.find(id="divQuaterly")
if container is None:
    print("div#divQuaterly NOT FOUND on the page at all.")
else:
    print("div#divQuaterly FOUND. Its content:")
    print(container.prettify()[:3000])

# also check: does "Fiscal Year" / "divQuarterlyData" appear ANYWHERE in the raw page?
print(f"\n'divQuarterlyData' appears in raw HTML: {'divQuarterlyData' in resp.text}")
print(f"'AnnouncementDetail.aspx' appears in raw HTML: {'AnnouncementDetail.aspx' in resp.text}")

with open("quarterly_page_dump.html", "w", encoding="utf-8") as f:
    f.write(resp.text)
print("\nFull page saved to: quarterly_page_dump.html")