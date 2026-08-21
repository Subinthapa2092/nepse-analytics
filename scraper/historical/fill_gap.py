"""
One-off script to backfill a small number of recently-missed days
(e.g. Aug 19, when the daily cron was broken) for every symbol we
already track — not a full multi-year backfill like backfill.py.

Pulls the symbol list straight from daily_prices (whatever symbols
already have history), fetches only page 1 of each symbol's price
history (fast — page 1 has the most recent dates), and inserts via
save_historical_rows(), which uses ON CONFLICT DO NOTHING — so this
is always safe to (re-)run and will never duplicate or overwrite
days you already have.

Run manually:
    python -m scraper.historical.fill_gap
"""

import time
from scraper.historical.fetch_history import fetch_symbol_history
from database.save_history import save_historical_rows
from database.connection import get_connection

DELAY_BETWEEN_SYMBOLS_SECONDS = 8


def get_all_tracked_symbols() -> list[str]:
    """Every symbol already present in daily_prices, alphabetically."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT symbol FROM daily_prices ORDER BY symbol;")
    symbols = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return symbols


def run_fill_gap(symbols: list[str] = None):
    symbols = symbols or get_all_tracked_symbols()
    print(f"Filling recent gaps for {len(symbols)} symbols...")

    for i, symbol in enumerate(symbols, start=1):
        print(f"\n[{i}/{len(symbols)}] Fetching recent history for {symbol}...")
        for attempt in range(1, 3):
            try:
                # max_pages=1 -> just the newest page, which covers the
                # last few trading days. Plenty for a 1-2 day gap.
                rows = fetch_symbol_history(symbol, max_pages=1)
                for r in rows:
                    r["symbol"] = symbol
                save_historical_rows(rows)
                break
            except Exception as e:
                print(f"FAILED for {symbol} (attempt {attempt}/2): {e}")
                if attempt < 2:
                    print("  waiting 30s before retry...")
                    time.sleep(30)

        if i < len(symbols):
            time.sleep(DELAY_BETWEEN_SYMBOLS_SECONDS)

    print("\nGap-fill run complete.")


if __name__ == "__main__":
    run_fill_gap()