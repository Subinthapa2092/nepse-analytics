"""
Daily live price fetch from Merolagani's LatestMarket page.

Two things added on top of the original script, both explained below. The
actual fetch/parse logic and the call to database.save.save_rows() are
UNCHANGED -- save.py itself is not modified by this.

1. HOLIDAY DETECTION
   Merolagani's LatestMarket.aspx doesn't say anywhere on the page when the
   market is closed -- it just keeps showing the LAST TRADING DAY's closing
   prices, unchanged, with nothing in the HTML marking it as stale. That's
   exactly what caused the fake rows found on 2026-08-28, 09-04, 09-08, 09-21,
   and 09-25: a holiday's fetch returned yesterday's numbers, and the old
   script saved them as if they were today's. save_rows()'s own "already have
   rows for today" check does NOT catch this -- it only prevents running
   twice on the SAME day, it has no idea whether today's content is actually
   new.

   The fix: this compares today's checksum of ALL rows against the most
   recently ARCHIVED day's checksum (see archive/canonical.py). Hundreds of
   symbols having byte-for-byte identical prices, highs, lows, and volumes to
   the prior day is not something that happens on a real trading day -- it's
   the site serving a stale page. When that happens, the fetch is skipped
   entirely: not archived, not passed to save_rows() at all.

   Limitation, stated honestly: this can only compare against a day that was
   already archived. The very first run (empty archive) can't detect a
   holiday and will save whatever it gets -- a one-time gap when this script
   is first deployed, not an ongoing risk. Your archive already has 2,716
   verified days as of the last migration, so this is not a concern going
   forward.

2. ARCHIVE (steps 3-6 of the agreed pipeline, from archive/pipeline.py)
   Before calling save_rows(), today's rows are written to a permanent local
   .csv.gz file, loaded into the local SQLite archive, and verified.

   If archiving fails for some reason, this script logs a clear warning but
   still calls save_rows() -- a local-archive problem should never be the
   reason your live product's prices stop updating.

DATE HANDLING, on purpose: this uses plain date.today() (machine-local date),
the SAME thing save_rows() already uses internally for its own "already
saved today" check. That keeps the archive's date and daily_prices'
fetched_at::date always in agreement, since both come from the exact same
call -- they can never disagree by construction. The tradeoff, inherited
from the ORIGINAL script (not introduced here): if a run is badly delayed
across midnight (a known issue -- see the ~5hr GitHub Actions scheduling
delay discussed separately), date.today() may not match NEPSE's true trading
date. That's a pre-existing limitation, not something this fix changes.
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

# A real trading day returns 300+ symbols. If the page structure changed, or
# the request half-failed, we'd get far fewer (or zero) -- this stops a
# broken/partial fetch from ever reaching save_rows() at all.
MIN_EXPECTED_SYMBOLS = 50


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


def _most_recent_verified(db: ArchiveDB) -> tuple[date | None, str | None]:
    """(date, checksum) of the most recently archived+verified daily_prices
    day, or (None, None) if nothing's archived yet."""
    row = db.conn.execute(
        "select trade_date, checksum from archive_manifest "
        "where dataset = 'daily_prices' and verified = 1 "
        "order by trade_date desc limit 1"
    ).fetchone()
    if row is None:
        return None, None
    return date.fromisoformat(row["trade_date"]), row["checksum"]


def run(today: date | None = None) -> str:
    """Returns what happened, as a short string, for logging/testing:
    'saved' | 'skipped_too_few_rows' | 'skipped_holiday_duplicate'."""
    today = today or date.today()  # see module docstring: matches save_rows()'s own date logic on purpose
    data = fetch_today_prices()
    print(f"Parsed {len(data)} rows")

    if len(data) < MIN_EXPECTED_SYMBOLS:
        print(f"Only {len(data)} rows parsed (expected {MIN_EXPECTED_SYMBOLS}+) -- "
              f"the page may not have loaded correctly. NOT saving, to avoid "
              f"storing a broken or partial day.")
        return "skipped_too_few_rows"

    with ArchiveDB(ARCHIVE_DB_PATH) as db:
        prev_date, prev_checksum = _most_recent_verified(db)
        today_checksum = checksum_prices(data)

        if prev_checksum is not None and today_checksum == prev_checksum:
            print(f"Today's {len(data)} rows are byte-for-byte identical to "
                  f"{prev_date}'s archived data. This looks like a market "
                  f"holiday (Merolagani shows the last trading day's closing "
                  f"prices with nothing indicating it's stale). Skipping -- "
                  f"nothing archived, nothing saved to Supabase.")
            return "skipped_holiday_duplicate"

        result = archive_and_verify(db, RAW_ROOT, "daily_prices", today, data)
        if result["verified"]:
            print(f"Archived and verified {result['row_count']} rows for {today}.")
        else:
            print(f"WARNING: archive verification failed for {today}: "
                  f"{result['error']}\nSaving to Supabase anyway -- an archive "
                  f"problem shouldn't block the live product, but this needs "
                  f"a look.")

    # Unchanged from the original script -- save.py itself is not modified.
    # save_rows() does its own "already have rows for today" check internally.
    from database.save import save_rows
    save_rows(data)
    return "saved"


if __name__ == "__main__":
    outcome = run()
    # A holiday or a broken page is not an error worth failing the GitHub
    # Actions job over -- only exit non-zero for the broken-page case, so a
    # true failure still shows up as a red run.
    if outcome == "skipped_too_few_rows":
        sys.exit(1)
