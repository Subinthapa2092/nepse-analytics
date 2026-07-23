"""
Bulk insert for historical OHLCV data (backfill), separate from the
daily save_rows() logic since historical inserts don't need the
"already have today's data" duplicate guard.
"""

from database.connection import get_connection


def save_historical_rows(rows: list[dict]):
    if not rows:
        print("No historical rows to save.")
        return

    conn = get_connection()
    cur = conn.cursor()
    for r in rows:
        cur.execute(
            """
            insert into daily_prices (symbol, ltp, pct_change, high, low, open, qty, fetched_at)
            values (%s, %s, %s, %s, %s, %s, %s, %s::date)
            """,
            (r["symbol"], r["ltp"], r["pct_change"], r["high"], r["low"], r["open"], r["qty"], r["date"]),
        )
    conn.commit()
    cur.close()
    conn.close()
    print(f"Inserted {len(rows)} historical rows.")