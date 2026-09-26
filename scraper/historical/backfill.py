"""
Orchestrates historical backfill across multiple symbols.
Run manually, not on the daily cron -- this is slow by design
(deliberate delays to avoid hammering Merolagani's server).

Resumable at TWO levels:
  1. Symbol level: only backfills symbols that don't already have solid
     history (thin row count, or history not going back far enough).
  2. Page level: if a symbol's page-scrape stalls partway, progress is
     saved to data/backfill_progress.json so a re-run resumes from the
     last successful page instead of starting over.

Permanently-completed symbols (data/backfill_completed.json) are always
excluded, no matter what -- this is what lets you manually mark a symbol
"good enough" (e.g. SIFC, which reproducibly stalls on the same page no
matter how it's approached, most likely a genuine server-side slowdown on
deep pagination, not something retries can fix) without it being dragged
back in by leftover progress-file state.

FIXED (this version): the __main__ block used to unconditionally re-add
every symbol still listed in backfill_progress.json, even ones that had
since been added to backfill_completed.json -- so marking a symbol
"completed" by hand didn't actually stick; its stale progress entry kept
forcing it back into the next run. Completed status now always wins, and
marking a symbol done also clears its progress entry so the two files
can't disagree with each other again.
"""

import json
import time
from datetime import date, timedelta
from pathlib import Path

from scraper.historical.fetch_history import fetch_symbol_history
from database.save_history import save_historical_rows
from database.connection import get_connection

DELAY_BETWEEN_SYMBOLS_SECONDS = 8
MIN_HISTORY_DAYS = 365 * 12  # ~12 years -- a fallback heuristic only
PROGRESS_FILE = Path("data/backfill_progress.json")
COMPLETED_FILE = Path("data/backfill_completed.json")


def _load_progress() -> dict:
    if not PROGRESS_FILE.exists():
        return {}
    try:
        return json.loads(PROGRESS_FILE.read_text())
    except Exception:
        return {}


def _save_progress(progress: dict) -> None:
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2))


def _load_completed() -> set:
    if not COMPLETED_FILE.exists():
        return set()
    try:
        return set(json.loads(COMPLETED_FILE.read_text()))
    except Exception:
        return set()


def _save_completed(completed: set) -> None:
    COMPLETED_FILE.parent.mkdir(parents=True, exist_ok=True)
    COMPLETED_FILE.write_text(json.dumps(sorted(completed), indent=2))


def mark_symbol_done(symbol: str) -> None:
    """Permanently mark a symbol as done (e.g. one that reproducibly stalls
    on the same page and isn't worth further retries), and clear any stale
    progress entry for it so the two files can't disagree."""
    completed = _load_completed()
    completed.add(symbol)
    _save_completed(completed)

    progress = _load_progress()
    if symbol in progress:
        progress.pop(symbol)
        _save_progress(progress)
    print(f"{symbol}: marked permanently complete (progress entry cleared).")


def get_symbols_needing_backfill(min_rows: int = 50,
                                  min_history_days: int = MIN_HISTORY_DAYS) -> list[str]:
    """
    Returns symbols that either:
      (a) have fewer than `min_rows` rows at all (thin/new symbols), OR
      (b) have plenty of rows, but their EARLIEST row isn't old enough,
    excluding anything already marked permanently complete.
    """
    cutoff = date.today() - timedelta(days=min_history_days)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        select symbol,
               count(*)               as row_count,
               min(fetched_at::date)  as earliest_date
        from daily_prices
        group by symbol
        having count(*) < %s
            or min(fetched_at::date) > %s
        order by symbol
    """, (min_rows, cutoff))
    symbols = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()

    completed = _load_completed()
    return [s for s in symbols if s not in completed]


def run_backfill(symbols: list[str] = None, max_pages: int | None = None):
    symbols = symbols or get_symbols_needing_backfill()
    progress = _load_progress()
    completed = _load_completed()
    print(f"Backfilling {len(symbols)} symbols...")

    for i, symbol in enumerate(symbols, start=1):
        entry = progress.get(symbol, {})
        start_page = entry.get("last_page_reached", 0) + 1
        if start_page > 1:
            print(f"\n[{i}/{len(symbols)}] Resuming {symbol} from page {start_page} "
                  f"(previously reached page {entry['last_page_reached']} "
                  f"of {entry.get('total_pages', '?')})...")
        else:
            print(f"\n[{i}/{len(symbols)}] Fetching history for {symbol}...")

        try:
            rows, last_page_reached, total_pages = fetch_symbol_history(
                symbol, max_pages=max_pages, start_page=start_page
            )
            for r in rows:
                r["symbol"] = symbol
            save_historical_rows(rows)

            if last_page_reached >= total_pages:
                progress.pop(symbol, None)
                completed.add(symbol)
                _save_completed(completed)
                print(f"  {symbol}: complete ({total_pages}/{total_pages} pages).")
            else:
                progress[symbol] = {
                    "last_page_reached": last_page_reached,
                    "total_pages": total_pages,
                }
                print(f"  {symbol}: partial -- reached page {last_page_reached} of "
                      f"{total_pages}. Will resume from page {last_page_reached + 1} "
                      f"next run.")
            _save_progress(progress)

        except Exception as e:
            print(f"FAILED for {symbol}: {e}")

        if i < len(symbols):
            time.sleep(DELAY_BETWEEN_SYMBOLS_SECONDS)

    print("\nBackfill run complete.")

    # FIXED: only report/resume symbols still in progress AND not manually
    # marked complete in the meantime -- this is the actual bug fix.
    completed = _load_completed()
    still_partial = {s: p for s, p in progress.items() if s not in completed}
    if still_partial != progress:
        _save_progress(still_partial)  # drop stale entries for completed symbols
    if still_partial:
        print(f"\n{len(still_partial)} symbol(s) still have partial history and "
              f"will resume automatically on the next run: "
              f"{', '.join(still_partial.keys())}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--mark-done":
        for sym in sys.argv[2:]:
            mark_symbol_done(sym)
        sys.exit(0)

    symbols = get_symbols_needing_backfill()
    completed = _load_completed()
    progress = _load_progress()
    for sym in progress:
        if sym not in symbols and sym not in completed:
            symbols.append(sym)
    print(f"{len(symbols)} symbols still need backfilling "
          f"(thin history, history not going back {MIN_HISTORY_DAYS} days, "
          f"or resuming partial progress)")
    run_backfill(symbols=symbols)