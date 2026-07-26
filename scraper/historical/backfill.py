"""
Orchestrates historical backfill across multiple symbols.
Run manually, not on the daily cron — this is slow by design
(deliberate delays to avoid hammering Merolagani's server).

Resumable: only backfills symbols that don't already have solid
history, so if the script stops partway through (laptop sleep,
closed terminal, error), you can just re-run it and it picks up
where it left off instead of starting over.
"""

import time
from scraper.historical.fetch_history import fetch_symbol_history
from database.save_history import save_historical_rows
from database.connection import get_connection

DELAY_BETWEEN_SYMBOLS_SECONDS = 8


def get_symbols_needing_backfill(min_rows: int = 50) -> list[str]:
    """Only return symbols that don't already have solid history."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        select symbol, count(*) as row_count
        from daily_prices
        group by symbol
        having count(*) < %s
        order by symbol
    """, (min_rows,))
    symbols = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return symbols


def run_backfill(symbols: list[str] = None, max_pages: int | None = None):
    symbols = symbols or get_symbols_needing_backfill()
    print(f"Backfilling {len(symbols)} symbols...")

    for i, symbol in enumerate(symbols, start=1):
        print(f"\n[{i}/{len(symbols)}] Fetching history for {symbol}...")
        for attempt in range(1, 3):
            try:
                rows = fetch_symbol_history(symbol, max_pages=max_pages)
                for r in rows:
                    r["symbol"] = symbol
                save_historical_rows(rows)
                break
            except Exception as e:
                print(f"FAILED for {symbol} (attempt {attempt}/2): {e}")
                if attempt < 2:
                    print("  waiting 30s before retry (possible connectivity issue)...")
                    time.sleep(30)

        if i < len(symbols):
            time.sleep(DELAY_BETWEEN_SYMBOLS_SECONDS)

    print("\nBackfill run complete.")


if __name__ == "__main__":
    symbols = get_symbols_needing_backfill(min_rows=50)
    print(f"{len(symbols)} symbols still need backfilling")
    run_backfill(symbols=symbols)