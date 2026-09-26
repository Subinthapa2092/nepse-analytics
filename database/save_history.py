# """
# Bulk insert for historical OHLCV data (backfill), separate from the
# daily save_rows() logic since historical inserts don't need the
# "already have today's data" duplicate guard.
# """

# from database.connection import get_connection


# def save_historical_rows(rows: list[dict]):
#     """
#     Each row must have: symbol, date, open, high, low, close (or ltp), qty
#     """
#     if not rows:
#         print("No historical rows to save.")
#         return

#     conn = get_connection()
#     cur = conn.cursor()
#     for r in rows:
#         cur.execute(
#             """
#             insert into daily_prices (symbol, ltp, pct_change, high, low, open, qty, fetched_at)
#             values (%s, %s, %s, %s, %s, %s, %s, %s::date)
#             """,
#             (
#                 r["symbol"],
#                 r.get("ltp"),
#                 r.get("pct_change"),
#                 r["high"],
#                 r["low"],
#                 r["open"],
#                 r.get("qty", 0),
#                 r["date"],
#             ),
#         )
#     conn.commit()
#     cur.close()
#     conn.close()
#     print(f"Inserted {len(rows)} historical rows.")
"""
Bulk insert for historical OHLCV data (backfill), separate from the
daily save_rows() logic since historical inserts don't need the
"already have today's data" duplicate guard.

FIXED: the original version used a plain `insert` with no conflict
handling. Since the daily live-price job already writes today's row
for every symbol, a historical backfill's date range almost always
overlaps at least one existing (symbol, fetched_at) pair -- and a
plain insert failing on ANY row aborts the whole transaction, silently
discarding every row already fetched for that symbol (sometimes
thousands of rows of real, successfully-scraped history). This is why
backfilled symbols kept coming back with sparse/no history despite the
scraper genuinely finding it.

Fix: upsert with ON CONFLICT (symbol, fetched_at) DO UPDATE, matching
the same idempotent "safe to re-run" pattern already used elsewhere in
this project (e.g. archive/store.py's load_prices). A date that's
already there gets refreshed with the latest values instead of
blocking every other row in the batch.
"""

from database.connection import get_connection


def save_historical_rows(rows: list[dict]):
    """
    Each row must have: symbol, date, open, high, low, ltp (or close), qty
    """
    if not rows:
        print("No historical rows to save.")
        return

    conn = get_connection()
    cur = conn.cursor()
    inserted = 0
    failed = []
    try:
        for r in rows:
            try:
                cur.execute(
                    """
                    insert into daily_prices
                        (symbol, ltp, pct_change, high, low, open, qty, fetched_at)
                    values (%s, %s, %s, %s, %s, %s, %s, %s::date)
                    on conflict (symbol, fetched_at) do update set
                        ltp        = excluded.ltp,
                        pct_change = excluded.pct_change,
                        high       = excluded.high,
                        low        = excluded.low,
                        open       = excluded.open,
                        qty        = excluded.qty
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
                inserted += 1
            except Exception as e:
                # One bad row (e.g. malformed date) no longer kills the
                # whole batch -- log it and keep going with the rest.
                conn.rollback()
                failed.append((r.get("date"), str(e)))
                continue
        conn.commit()
    finally:
        cur.close()
        conn.close()

    print(f"Inserted/updated {inserted} of {len(rows)} historical rows.")
    if failed:
        print(f"  {len(failed)} row(s) failed and were skipped:")
        for d, err in failed[:10]:
            print(f"    {d}: {err}")