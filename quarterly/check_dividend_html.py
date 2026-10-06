import requests
from bs4 import BeautifulSoup
import re

url = "https://merolagani.com/CompanyDetail.aspx?symbol=ADBL"
headers = {"User-Agent": "Mozilla/5.0"}
resp = requests.get(url, headers=headers, timeout=30)
soup = BeautifulSoup(resp.text, "html.parser")

table = soup.find("table", id="accordion")
print(table.prettify())

matches = soup.find_all(string=re.compile(r"%\s*Dividend"))
print(f"Found {len(matches)} match(es) for '% Dividend' text\n")
for m in matches[:3]:
    parent = m.parent
    for _ in range(4):
        if parent.parent:
            parent = parent.parent
    print("=" * 60)
    print(parent.prettify()[:3000])

with open("adbl_dividend_dump.html", "w", encoding="utf-8") as f:
    f.write(resp.text)
print("\nFull page saved to adbl_dividend_dump.html")