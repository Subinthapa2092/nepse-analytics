"""
Daily live price fetch from Merolagani's LatestMarket page.

HOLIDAY DETECTION -- checked against SUPABASE, not the local archive.
Merolagani's LatestMarket.aspx doesn't say when the market is closed -- it
just keeps showing the last trading day's closing prices, unchanged. This
compares today's checksum of ALL rows against the most recent PRIOR day's
checksum, read straight from Supabase's daily_prices -- this works whether
run locally or on GitHub Actions, since Supabase always has yesterday's data.

If the Supabase check itself fails, this logs a warning and proceeds WITHOUT
the holiday check rather than crashing the whole run.

ARCHIVE: before calling save_rows(), today's rows are written to a local
.csv.gz file, loaded into the local SQLite archive, and verified. If that
fails, this logs a warning but still saves to Supabase -- an archive problem
should never block the live product.
"""

import sys
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from archive.canonical import checksum_prices
from archive.pipeline import archive_and_verify
from archive.store import ArchiveDB

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

URL = "https://merolagani.com/LatestMarket.aspx"

RAW_ROOT = Path("data/raw")
ARCHIVE_DB_PATH = Path("data/nepse_archive.db")

MIN_EXPECTED_SYMBOLS = 50

PRICE_COLUMNS = ["symbol", "ltp", "pct_change", "high", "low", "open", "qty", "trend"]


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


def _most_recent_supabase_checksum(today: date) -> tuple[date | None, str | None]:
    try:
        from database.connection import get_connection
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "select max(fetched_at::date) from daily_prices "
                    "where fetched_at::date < %s",
                    (today,),
                )
                prev_date = cur.fetchone()[0]
                if prev_date is None:
                    return None, None

                cur.execute(
                    "select symbol, ltp, pct_change, high, low, \"open\", qty, trend "
                    "from daily_prices where fetched_at::date = %s",
                    (prev_date,),
                )
                rows = [dict(zip(PRICE_COLUMNS, r)) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        print(f"  [warn] couldn't read Supabase for holiday check: {e} "
              f"-- proceeding WITHOUT holiday detection this run")
        return None, None

    if not rows:
        return None, None
    return prev_date, checksum_prices(rows)


def run(today: date | None = None) -> str:
    today = today or date.today()
    data = fetch_today_prices()
    print(f"Parsed {len(data)} rows")

    if len(data) < MIN_EXPECTED_SYMBOLS:
        print(f"Only {len(data)} rows parsed (expected {MIN_EXPECTED_SYMBOLS}+) -- "
              f"the page may not have loaded correctly. NOT saving, to avoid "
              f"storing a broken or partial day.")
        return "skipped_too_few_rows"

    prev_date, prev_checksum = _most_recent_supabase_checksum(today)
    today_checksum = checksum_prices(data)

    if prev_checksum is not None and today_checksum == prev_checksum:
        print(f"Today's {len(data)} rows are byte-for-byte identical to "
              f"{prev_date}'s data already in Supabase. This looks like a "
              f"market holiday (Merolagani shows the last trading day's "
              f"closing prices with nothing indicating it's stale). "
              f"Skipping -- nothing archived, nothing saved to Supabase.")
        return "skipped_holiday_duplicate"

    try:
        with ArchiveDB(ARCHIVE_DB_PATH) as db:
            result = archive_and_verify(db, RAW_ROOT, "daily_prices", today, data)
        if result["verified"]:
            print(f"Archived and verified {result['row_count']} rows for {today}.")
        else:
            print(f"WARNING: archive verification failed for {today}: {result['error']}")
    except Exception as e:
        print(f"  [warn] local archive step failed: {e} -- continuing to save to Supabase anyway")

    from database.save import save_rows
    save_rows(data)
    return "saved"


if __name__ == "__main__":
    outcome = run()
    if outcome == "skipped_too_few_rows":
        sys.exit(1)