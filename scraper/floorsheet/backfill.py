"""
Floorsheet backfill + daily job (same script, different arguments).

Which dates? Every date already in daily_prices (that's your list of real trading
days -- it correctly handles the Sun-Thu -> Mon-Fri schedule change in April 2026 and
all holidays) minus the dates already fully scraped. Newest first, so the most useful
data lands first and the run stops naturally when Merolagani runs out of old data.

Resumable: a day is logged only after ALL its pages were read, so if you close the
laptop / lose the connection / Ctrl+C, just run the same command again.

Examples (run from the project root):

  # smoke test, nothing written to the database (3 pages of one day)
  python -m scraper.floorsheet.backfill --dates 2026-09-18 --max-pages 3 --dry-run

  # one complete day, saved
  python -m scraper.floorsheet.backfill --dates 2026-09-18

  # newest 30 pending trading days (default)
  python -m scraper.floorsheet.backfill

  # everything pending, oldest data Merolagani will give us
  python -m scraper.floorsheet.backfill --all

  # daily job (used by GitHub Actions)
  python -m scraper.floorsheet.backfill --days 3 --no-raw
"""

from __future__ import annotations

import argparse
import csv
import gzip
import random
import time
from datetime import date, datetime
from pathlib import Path

from scraper.floorsheet.aggregate import aggregate_by_broker, total_amount
from scraper.floorsheet.fetch_floorsheet import DateMismatch, FloorsheetSession

RAW_DIR = Path("data/raw/floorsheet")  # already git-ignored by data/raw/ in .gitignore
RAW_FIELDS = ["transaction_no", "symbol", "buyer_broker", "seller_broker", "quantity", "rate", "amount"]


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape Merolagani floorsheets into broker_daily_summary")
    p.add_argument("--dates", nargs="+", type=_parse_date, help="specific dates, YYYY-MM-DD")
    p.add_argument("--days", type=int, default=30, help="newest N pending trading days (default 30)")
    p.add_argument("--all", action="store_true", help="every pending trading day")
    p.add_argument("--from", dest="date_from", type=_parse_date, help="earliest date to consider")
    p.add_argument("--to", dest="date_to", type=_parse_date, help="latest date to consider")
    p.add_argument("--max-pages", type=int, help="only read N pages per day (testing; day is NOT saved)")
    p.add_argument("--dry-run", action="store_true", help="scrape and print, but don't touch the database")
    p.add_argument("--no-raw", action="store_true", help="don't keep the raw trades as .csv.gz")
    p.add_argument("--delay", type=float, default=10.0, help="seconds to pause between days (default 10)")
    p.add_argument("--max-bad", type=int, default=8,
                   help="stop after this many empty/failed days in a row (default 8)")
    p.add_argument("--headed", action="store_true", help="show the browser window (debugging)")
    return p.parse_args()


def _select_dates(args: argparse.Namespace) -> list[date]:
    if args.dates:
        return sorted(set(args.dates), reverse=True)

    from database.save_floorsheet import get_done_dates, get_known_trading_dates

    known = get_known_trading_dates()
    done = get_done_dates()
    pending = [
        d for d in known
        if d not in done
        and (not args.date_from or d >= args.date_from)
        and (not args.date_to or d <= args.date_to)
    ]
    return pending if args.all else pending[: args.days]


def _write_raw(trade_date: date, trades: list[dict]) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{trade_date.isoformat()}.csv.gz"
    with gzip.open(path, "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RAW_FIELDS)
        w.writeheader()
        w.writerows(trades)
    return path


def main() -> None:
    args = _parse_args()

    if not args.dry_run:
        from database.save_floorsheet import ensure_tables
        ensure_tables()

    dates = _select_dates(args)
    if not dates:
        print("Nothing to do -- every known trading day is already scraped.")
        return
    print(f"{len(dates)} day(s) to scrape, newest first: {dates[0]} -> {dates[-1]}")

    saved = 0
    bad_streak = 0
    started = time.time()

    try:
        with FloorsheetSession(headless=not args.headed) as session:
            for i, d in enumerate(dates, start=1):
                print(f"\n[{i}/{len(dates)}] {d} ...")
                day_start = time.time()

                try:
                    result = session.fetch(d, max_pages=args.max_pages)
                except DateMismatch as e:
                    print(f"STOPPING: {e}")
                    return
                except Exception as e:
                    print(f"  failed: {e}")
                    result = None

                if result is None or not result.rows:
                    reason = "error" if result is None else result.note
                    print(f"  no data for {d} ({reason})")
                    bad_streak += 1
                elif not result.complete:
                    print(f"  INCOMPLETE, not saved: {result.note} "
                          f"({len(result.rows):,} trades read)")
                    # a deliberate --max-pages test is not a failure
                    if not args.max_pages:
                        bad_streak += 1
                else:
                    bad_streak = 0
                    summary = aggregate_by_broker(result.rows)
                    amount = total_amount(result.rows)
                    print(f"  {len(result.rows):,} trades / {result.pages_read} pages -> "
                          f"{len(summary):,} broker-symbol rows, turnover Rs {amount:,.0f}")

                    if not args.dry_run:
                        if not args.no_raw:
                            _write_raw(d, result.rows)
                        from database.save_floorsheet import save_day
                        save_day(d, summary, len(result.rows), result.pages_read, amount)
                        saved += 1
                        print("  saved.")

                if bad_streak >= args.max_bad:
                    print(f"\nStopping: {bad_streak} days in a row returned nothing or failed.\n"
                          "Either Merolagani doesn't serve floorsheets this far back (normal for the "
                          "oldest dates), or you're being rate-limited/blocked -- wait a while, "
                          "switch network, then re-run; finished days are skipped automatically.")
                    break

                if i < len(dates):
                    elapsed = time.time() - started
                    eta_min = elapsed / i * (len(dates) - i) / 60
                    print(f"  took {time.time() - day_start:.0f}s; ~{eta_min:.0f} min left")
                    time.sleep(args.delay + random.uniform(0, 3))
    except KeyboardInterrupt:
        print("\nInterrupted. Finished days are saved; re-run the same command to resume.")

    print(f"\nDone. Saved {saved} day(s).")


if __name__ == "__main__":
    main()
