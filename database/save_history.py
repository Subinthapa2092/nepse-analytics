"""
Bulk insert for historical OHLCV data (backfill), separate from the
daily save_rows() logic since historical inserts don't need the
"already have today's data" duplicate guard.

Uses ON CONFLICT DO NOTHING so re-running backfill (e.g. after a
restart or connectivity drop) is always safe — a row that already
exists for that (symbol, date) is silently skipped instead of
inserted again. Requires a unique constraint on (symbol, fetched_at).
"""

from database.connection import get_connection


def save_historical_rows(rows: list[dict]):
    """
    Each row must have: symbol, date, open, high, low, close (or ltp), qty
    """
    if not rows:
        print("No historical rows to save.")
        return

    conn = get_connection()
    cur = conn.cursor()
    saved = 0
    try:
        for r in rows:
            cur.execute(
                """
                insert into daily_prices (symbol, ltp, pct_change, high, low, open, qty, fetched_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s::date)
                on conflict (symbol, fetched_at) do nothing
                """,
                (
                    r["symbol"],
                    r.get("ltp"),
                    r.get("pct_change"),
                    r["high"],
                    r["low"],
                    r["open"],
                    r.get("qty", 0),
                    r["date"],
                ),
            )
            saved += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Database error after saving {saved}/{len(rows)} rows: {e}")
    finally:
        cur.close()
        conn.close()
    print(f"Inserted {saved} historical rows.")