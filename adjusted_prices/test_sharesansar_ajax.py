"""
Tests calling ShareSansar's AJAX endpoint directly with requests, using the
CSRF token + company id pulled from the page itself (same session/cookies
the real page would use).
"""

import requests
from bs4 import BeautifulSoup

SYMBOL = "adbl"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

session = requests.Session()
page = session.get(f"https://www.sharesansar.com/company/{SYMBOL}", headers=HEADERS, timeout=20)
page.raise_for_status()
soup = BeautifulSoup(page.text, "html.parser")

token = soup.find("meta", attrs={"name": "_token"})["content"]
company_id = soup.find(id="companyid").get_text(strip=True)
print(f"token={token}")
print(f"company_id={company_id}")

post_headers = dict(HEADERS)
post_headers["X-CSRF-Token"] = token
post_headers["X-Requested-With"] = "XMLHttpRequest"

columns = ["DT_Row_Index", "bonus_share", "cash_dividend", "total_dividend",
           "announcement_date", "bookclose_date"]

post_data = {
    "draw": "1",
    "start": "0",
    "length": "50",
    "search[value]": "",
    "search[regex]": "false",
    "company": company_id,
}
for i, col in enumerate(columns):
    post_data[f"columns[{i}][data]"] = col
    post_data[f"columns[{i}][name]"] = ""
    post_data[f"columns[{i}][searchable]"] = "false"
    post_data[f"columns[{i}][orderable]"] = "false"
    post_data[f"columns[{i}][search][value]"] = ""
    post_data[f"columns[{i}][search][regex]"] = "false"

resp = session.post(
    "https://www.sharesansar.com/company-dividend",
    headers=post_headers,
    data=post_data,
    timeout=20,
)
print(f"\nStatus: {resp.status_code}")
print(f"Response (first 2000 chars):\n{resp.text[:2000]}")
right_columns = ["DT_Row_Index", "ratio_value", "total_units", "issue_price",
                  "opening_date", "closing_date", "final_date", "listing_date",
                  "issue_manager", "status", "view"]

right_data = {
    "draw": "1",
    "start": "0",
    "length": "50",
    "search[value]": "",
    "search[regex]": "false",
    "company": company_id,
}
for i, col in enumerate(right_columns):
    right_data[f"columns[{i}][data]"] = col
    right_data[f"columns[{i}][name]"] = ""
    right_data[f"columns[{i}][searchable]"] = "false"
    right_data[f"columns[{i}][orderable]"] = "false"
    right_data[f"columns[{i}][search][value]"] = ""
    right_data[f"columns[{i}][search][regex]"] = "false"

resp2 = session.post(
    "https://www.sharesansar.com/company-rightshare",
    headers=post_headers,
    data=right_data,
    timeout=20,
)
print(f"\nRight-share Status: {resp2.status_code}")
print(f"Response (first 2000 chars):\n{resp2.text[:2000]}")