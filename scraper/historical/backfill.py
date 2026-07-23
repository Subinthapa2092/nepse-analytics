import time
from scraper.historical.fetch_history import fetch_symbol_history
from database.save_history import save_historical_rows
from database.connection import get_connection

DELAY_BETWEEN_SYMBOLS_SECONDS = 5


def get_all_tracked_symbols() -> list[str]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("select distinct symbol from daily_prices order by symbol")
    symbols = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return symbols


def run_backfill(symbols: list[str] = None, max_pages: int | None = None):
    symbols = symbols or get_all_tracked_symbols()
    print(f"Backfilling {len(symbols)} symbols...")

    for i, symbol in enumerate(symbols, start=1):
        print(f"\n[{i}/{len(symbols)}] Fetching history for {symbol}...")
        try:
            rows = fetch_symbol_history(symbol, max_pages=max_pages)
            for r in rows:
                r["symbol"] = symbol
            save_historical_rows(rows)
        except Exception as e:
            print(f"FAILED for {symbol}: {e}")

        if i < len(symbols):
            time.sleep(DELAY_BETWEEN_SYMBOLS_SECONDS)

    print("\nBackfill run complete.")


if __name__ == "__main__":
    run_backfill(symbols=["NABIL", "ADBL", "NICA", "HDL", "AKPL"], max_pages=3)