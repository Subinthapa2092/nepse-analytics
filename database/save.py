from datetime import date
from database.connection import get_connection


def save_rows(rows: list[dict]):
    if not rows:
        print("No rows to save.")
        return

    conn = get_connection()
    cur = conn.cursor()

    today = date.today()
    cur.execute(
        "select count(*) from daily_prices where fetched_at::date = %s",
        (today,)
    )
    existing = cur.fetchone()[0]
    if existing > 0:
        print(f"Already have {existing} rows for today. Skipping insert to avoid duplicates.")
        cur.close()
        conn.close()
        return

    for r in rows:
        cur.execute(
            """insert into daily_prices (symbol, ltp, pct_change, high, low, open, qty, trend)
               values (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (r["symbol"], r["ltp"], r["pct_change"], r["high"], r["low"], r["open"], r["qty"], r["trend"]),
        )
    conn.commit()
    cur.close()
    conn.close()
    print(f"Saved {len(rows)} rows.")