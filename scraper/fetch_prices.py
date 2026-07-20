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


def to_number(value: str):
    value = value.replace(",", "").strip()
    if value in ("", "-"):
        return None
    return float(value)


def fetch_today_prices():
    resp = requests.get(URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", {"data-live": "live-trading"})
    if table is None:
        print("Table not found — page structure may have changed.")
        return []

    rows = []
    for tr in table.find("tbody").find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 7:
            continue

        texts = [c.get_text(strip=True) for c in cells]

        rows.append({
            "symbol": texts[0],
            "ltp": to_number(texts[1]),
            "pct_change": to_number(texts[2]),
            "high": to_number(texts[3]),
            "low": to_number(texts[4]),
            "open": to_number(texts[5]),
            "qty": int(to_number(texts[6]) or 0),
            "trend": tr.get("class", [""])[0],
        })

    return rows


if __name__ == "__main__":
    data = fetch_today_prices()
    print(f"Parsed {len(data)} rows")
    for row in data[:5]:
        print(row)