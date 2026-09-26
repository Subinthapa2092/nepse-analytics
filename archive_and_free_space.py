"""
Run this from your project root (E:\\nepse-analytics) once the `archive/` folder
is in place:

    python archive_and_free_space.py --migrate
    python archive_and_free_space.py --cleanup --keep-days 150 --dry-run
    python archive_and_free_space.py --cleanup --keep-days 150

Step 1 (--migrate): reads floorsheet_ingest_log for every date you've already
saved, finds that date's existing raw file at data/raw/floorsheet/<date>.csv.gz
(the OLD path your scraper already writes to -- nothing new is scraped), loads
it into the local archive (data/nepse_archive.db), verifies it against the raw
file, and records it in the manifest. Safe to re-run -- already-migrated dates
are skipped.

Step 2 (--cleanup): for any date older than --keep-days that is BOTH verified
in the manifest AND whose row count still matches what's actually in Supabase
right now, deletes that date from broker_daily_summary -- freeing space. Always
run with --dry-run first to see exactly what it WOULD do before it does it.

This only ever touches broker_daily_summary (the floorsheet aggregate table).
daily_prices is untouched by this script.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # so `archive` and `database` import

from archive.migrate import migrate_existing_floorsheet_day
from archive.store import ArchiveDB
from archive.supabase_cleanup import cleanup_old_data

ARCHIVE_DB_PATH = Path("data/nepse_archive.db")
OLD_RAW_DIR = Path("data/raw/floorsheet")  # where your EXISTING scraper already writes
PRICE_RAW_ROOT = Path("data/raw")  # new-style path: data/raw/daily_prices/<year>/...


def run_migrate() -> None:
    from database.connection import get_connection

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("select trade_date from floorsheet_ingest_log order by trade_date")
            dates = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()

    print(f"{len(dates)} date(s) recorded as saved in floorsheet_ingest_log.\n")

    with ArchiveDB(ARCHIVE_DB_PATH) as db:
        already = 0
        migrated = 0
        failed = []
        for d in dates:
            existing = db.get_manifest("floorsheet", d)
            if existing and existing["verified"]:
                already += 1
                continue

            raw_path = OLD_RAW_DIR / f"{d.isoformat()}.csv.gz"
            result = migrate_existing_floorsheet_day(db, raw_path, d)
            if result["verified"]:
                migrated += 1
                print(f"  {d}: verified, {result['row_count']:,} trades")
            else:
                failed.append((d, result["error"]))
                print(f"  {d}: NOT verified -- {result['error']}")

        print(f"\nDone. {migrated} newly archived+verified, "
              f"{already} already done, {len(failed)} failed.")
        if failed:
            print("\nDates that could not be archived (their Supabase data will NOT "
                  "be eligible for cleanup until this is resolved):")
            for d, err in failed:
                print(f"  {d}: {err}")


def run_migrate_prices() -> None:
    """
    Prices have no existing local backup (unlike floorsheet, whose raw files
    were already being written to disk). This pulls every day directly out of
    Supabase's daily_prices ONE TIME, archives it locally, and verifies it --
    using the SAME tested archive_and_verify() that new days will go through
    going forward once the new fetch_prices.py is wired in. This does NOT
    delete anything from Supabase; daily_prices is small (well under the free
    limit) so there's no urgency to trim it -- this is purely "stop having a
    single copy of 12 years of price history."
    """
    from archive.pipeline import archive_and_verify
    from database.connection import get_connection

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # One query for everything, grouped in Python -- 12 years as ~2,700
            # individual round trips would be needlessly slow.
            cur.execute(
                "select symbol, ltp, pct_change, high, low, \"open\", qty, trend, "
                "fetched_at::date as d from daily_prices order by d"
            )
            rows = cur.fetchall()
            colnames = [c.name for c in cur.description]
    finally:
        conn.close()

    by_date: dict = {}
    date_idx = colnames.index("d")
    for row in rows:
        r = dict(zip(colnames, row))
        d = r.pop("d")
        by_date.setdefault(d, []).append(r)

    print(f"{len(by_date)} distinct date(s) found in daily_prices.\n")

    with ArchiveDB(ARCHIVE_DB_PATH) as db:
        already = 0
        migrated = 0
        failed = []
        for i, (d, day_rows) in enumerate(sorted(by_date.items()), start=1):
            existing = db.get_manifest("daily_prices", d)
            if existing and existing["verified"]:
                already += 1
                continue

            result = archive_and_verify(db, PRICE_RAW_ROOT, "daily_prices", d, day_rows)
            if result["verified"]:
                migrated += 1
                if i % 100 == 0 or migrated <= 5:
                    print(f"  {d}: verified, {result['row_count']} symbols "
                          f"({migrated} migrated so far)")
            else:
                failed.append((d, result["error"]))
                print(f"  {d}: NOT verified -- {result['error']}")

        print(f"\nDone. {migrated} newly archived+verified, "
              f"{already} already done, {len(failed)} failed.")
        if failed:
            print("\nDates that could not be archived:")
            for d, err in failed:
                print(f"  {d}: {err}")




def run_cleanup(keep_days: int, dry_run: bool) -> None:
    from database.connection import get_connection

    with ArchiveDB(ARCHIVE_DB_PATH) as db:
        conn = get_connection()
        try:
            results = cleanup_old_data(db, conn, "floorsheet", keep_days=keep_days, dry_run=dry_run)
        finally:
            conn.close()

    if not results:
        print(f"Nothing to do -- no verified, archived dates older than "
              f"{date.today() - timedelta(days=keep_days)} were found as cleanup candidates.")
        return

    by_action: dict[str, int] = {}
    for r in results:
        by_action[r.action] = by_action.get(r.action, 0) + 1
        print(f"  {r.date}: {r.action} -- {r.detail}")

    print(f"\n{'[DRY RUN] ' if dry_run else ''}Summary: " +
          ", ".join(f"{n} {action}" for action, n in by_action.items()))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--migrate", action="store_true", help="archive existing floorsheet raw files")
    p.add_argument("--migrate-prices", action="store_true", help="archive daily_prices from Supabase")
    p.add_argument("--cleanup", action="store_true")
    p.add_argument("--keep-days", type=int, default=150,
                    help="dates older than this many days become cleanup candidates (default 150)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not args.migrate and not args.migrate_prices and not args.cleanup:
        p.error("pass --migrate, --migrate-prices, --cleanup, or a combination")

    if args.migrate:
        run_migrate()
        print()
    if args.migrate_prices:
        run_migrate_prices()
        print()
    if args.cleanup:
        run_cleanup(args.keep_days, args.dry_run)
