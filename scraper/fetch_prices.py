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

# COLUMNS = ["symbol", "ltp", "pct_change", "open", "high", "low", "qty", "pclose", "diff"]
COLUMNS = ["symbol", "ltp", "pct_change", "open", "high", "low", "qty"]

# def fetch_today_prices():
#     resp = requests.get(URL, headers=HEADERS, timeout=15)
#     resp.raise_for_status()

#     soup = BeautifulSoup(resp.text, "lxml")
#     table = soup.find("table", {"data-live": "live-trading"})

#     if table is None:
#         print("Table not found — page structure may have changed.")
#         return []

#     rows = []
#     for tr in table.find("tbody").find_all("tr"):
#         cells = tr.find_all("td")
#         if len(cells) < 9:
#             continue
#         symbol = cells[0].get_text(strip=True)
#         values = [c.get_text(strip=True) for c in cells[1:9]]
#         row = dict(zip(COLUMNS, [symbol] + values))
#         row["trend"] = tr.get("class", [""])[0]   # increase-row / decrease-row / nochange-row
#         rows.append(row)

#     return rows
def fetch_today_prices():
    resp = requests.get(URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"data-live": "live-trading"})

    if table is None:
        print("Table not found — page structure may have changed.")
        return []

    # print header labels in order
    headers = [th.get_text(strip=True) for th in table.find("thead").find_all("th")]
    print("HEADERS:", headers)

    # print first row's cells in order, right below the headers
    first_row = table.find("tbody").find("tr")
    cells = [td.get_text(strip=True) for td in first_row.find_all("td")]
    print("ROW:   ", cells)

    return []


if __name__ == "__main__":
    data = fetch_today_prices()
    print(f"Parsed {len(data)} rows")
    for row in data[:5]:
        print(row)
