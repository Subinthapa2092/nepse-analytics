"""
Computes back-adjustment factors for bonus-share and right-share events,
per symbol -- NOT a second copy of daily_prices. Produces one row per
corporate-action event; the adjusted price for any date is just
raw_price * cumulative_factor_active_on(date), applied at query time.

Methodology (same idea as Yahoo Finance's "adjusted close"):
  - Bonus share (e.g. 3.25%): price mechanically drops because share count
    rises. factor = 100 / (100 + bonus_pct), applied to every price BEFORE
    the bookclose date.
  - Right share (e.g. ratio "2:1" at issue price Rs 100): need the actual
    cum-rights closing price (last trading day before the bookclose date)
    to compute the theoretical ex-rights price (TERP).
        TERP = (N * cum_price + M * issue_price) / (N + M)
        factor = TERP / cum_price
    where ratio "N:M" means "for every N existing shares, M new shares".
  - Cash dividend: NOT adjusted -- that price drop is real value leaving
    the company (not a dilution artifact), so this matches standard
    "split-adjusted" (not "total-return-adjusted") charts.

Reads corporate actions from nepse_corporate_dates.sqlite (this folder's
own output from scrape_sharesansar_dates.py). Reads cum-rights prices from
Supabase's daily_prices table (needs database/connection.py's get_connection,
so this script's sys.path includes the project root).
"""

import os
import sqlite3
import sys
from datetime import date, datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)

CORP_DB = os.path.join(PROJECT_ROOT, "companies", "nepse_corporate_dates.sqlite")

def init_factor_table(conn):
    conn.execute("DROP TABLE IF EXISTS adjustment_factors")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS adjustment_factors (
            symbol        TEXT NOT NULL,
            ex_date       TEXT NOT NULL,   -- bookclose date, 'YYYY-MM-DD'
            event_type    TEXT NOT NULL,   -- 'bonus' | 'right'
            raw_detail    TEXT,            -- e.g. '3.25%' or '2:1 @ 100'
            cum_price     REAL,            -- only set for 'right' events
            event_factor  REAL NOT NULL,   -- this single event's multiplier
            cum_factor    REAL NOT NULL,   -- cumulative factor for all dates BEFORE ex_date
            PRIMARY KEY (symbol, ex_date, event_type)
        )
    """)
    conn.commit()


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _cum_price_before(pg_cursor, symbol, ex_date):
    """Last trading day's LTP strictly before ex_date, from Supabase."""
    pg_cursor.execute(
        "select ltp from daily_prices where symbol = %s and fetched_at::date < %s "
        "order by fetched_at::date desc limit 1",
        (symbol, ex_date),
    )
    row = pg_cursor.fetchone()
    return float(row[0]) if row and row[0] is not None else None


def main():
    if not os.path.exists(CORP_DB):
        print(f"ERROR: {CORP_DB} not found -- run scrape_sharesansar_dates.py first.")
        return

    from database.connection import get_connection
    pg_conn = get_connection()
    pg_cursor = pg_conn.cursor()

    corp_conn = sqlite3.connect(CORP_DB)
    init_factor_table(corp_conn)

    symbols = [r[0] for r in corp_conn.execute(
        "select distinct symbol from dividend_history "
        "union select distinct symbol from right_share_history"
    ).fetchall()]
    print(f"Processing {len(symbols)} symbol(s) with at least one corporate action.\n")

    total_events = 0
    skipped_right = 0

    for symbol in symbols:
        events = []  # list of (ex_date: date, event_type, raw_detail, cum_price, event_factor)

        for bonus_pct, bookclose in corp_conn.execute(
            "select bonus_share, bookclose_date from dividend_history "
            "where symbol = ? and bonus_share is not null and bonus_share > 0",
            (symbol,),
        ):
            ex_date = _parse_date(bookclose)
            if ex_date is None:
                continue
            factor = 100.0 / (100.0 + bonus_pct)
            events.append((ex_date, "bonus", f"{bonus_pct}%", None, factor))

        for ratio, issue_price, bookclose in corp_conn.execute(
            "select ratio_value, issue_price, bookclose_date from right_share_history "
            "where symbol = ? and ratio_value is not null",
            (symbol,),
        ):
            ex_date = _parse_date(bookclose)
            if ex_date is None or ":" not in ratio or issue_price is None:
                continue
            try:
                n_str, m_str = ratio.split(":")
                n, m = float(n_str), float(m_str)
            except ValueError:
                continue
            if n <= 0 or m <= 0:
                continue

            cum_price = _cum_price_before(pg_cursor, symbol, ex_date)
            if cum_price is None or cum_price <= 0:
                skipped_right += 1
                continue
            if issue_price > cum_price:
                print(f"  [skip] {symbol} {ex_date}: issue_price {issue_price} > "
                      f"cum_price {cum_price} -- looks like bad source data, skipping this event")
                skipped_right += 1
                continue
            terp = (n * cum_price + m * issue_price) / (n + m)
            factor = terp / cum_price
            events.append((ex_date, "right", f"{ratio} @ {issue_price}", cum_price, factor))

        if not events:
            continue

        events.sort(key=lambda e: e[0], reverse=True)  # most recent first
        cum_factor = 1.0
        rows = []
        for ex_date, event_type, raw_detail, cum_price, event_factor in events:
            rows.append((symbol, ex_date.isoformat(), event_type, raw_detail,
                         cum_price, event_factor, cum_factor))
            cum_factor *= event_factor  # applies to all dates BEFORE this ex_date

        for row in rows:
            corp_conn.execute(
                """INSERT OR REPLACE INTO adjustment_factors
                   (symbol, ex_date, event_type, raw_detail, cum_price, event_factor, cum_factor)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                row,
            )
        corp_conn.commit()
        total_events += len(rows)
        print(f"{symbol}: {len(rows)} event(s), earliest cumulative factor = {rows[-1][6]:.4f}")

    pg_conn.close()
    corp_conn.close()
    print(f"\nDone. {total_events} total adjustment events computed across {len(symbols)} symbols.")
    if skipped_right:
        print(f"({skipped_right} right-share events skipped -- no cum-rights price found in Supabase)")


if __name__ == "__main__":
    main()