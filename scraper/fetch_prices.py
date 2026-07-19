"""
Day 1 starter: fetch today's live share prices from Merolagani's
LatestMarket page and print the parsed rows.

This is intentionally minimal — the goal right now is to confirm the
fetch -> parse pipeline works before wiring it into the database or
a scheduled job.

NOTE: the table `id` below is a placeholder. Inspect the actual page
in your browser (right-click the price table -> Inspect) and replace
it with the real id you find.
"""

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

URL = "https://merolagani.com/LatestMarket.aspx"


def fetch_today_prices():
    resp = requests.get(URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    # TODO: replace with the real table id found via browser DevTools
    table = soup.find("table", {"id": "PUT_REAL_ID_HERE"})

    if table is None:
        print("Table not found — the page structure may differ from expected.")
        print("Open the page in a browser and re-check the table id.")
        return []

    rows = []
    for tr in table.find_all("tr"):
        cols = [td.get_text(strip=True) for td in tr.find_all("td")]
        if cols:
            rows.append(cols)
    return rows


if __name__ == "__main__":
    data = fetch_today_prices()
    for row in data[:5]:
        print(row)
