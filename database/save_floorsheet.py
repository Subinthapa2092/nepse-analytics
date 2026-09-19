"""
Database helpers for floorsheet data.

save_day() replaces a day's summary inside ONE transaction, so re-running a date is
always safe (no duplicates, no half-written days).
"""

from datetime import date
from pathlib import Path

from psycopg2.extras import execute_values

from database.connection import get_connection

SCHEMA_PATH = Path(__file__).with_name("floorsheet_schema.sql")


def ensure_tables() -> None:
    """Create the floorsheet tables if they don't exist yet (safe to call every run)."""
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    finally:
        conn.close()


def get_known_trading_dates() -> list[date]:
    """Every date we already have prices for, newest first. These are our trading days."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                select distinct fetched_at::date as d
                from daily_prices
                where fetched_at is not null
                order by d desc
                """
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def get_done_dates() -> set[date]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("select trade_date from floorsheet_ingest_log")
            return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


def save_day(trade_date: date, summary_rows: list[dict], trade_rows: int,
             pages: int, total_amount: float,
             expected_rows: int | None = None, missing_rows: int = 0) -> None:
    """Replace this day's broker summary and mark the day complete, atomically."""
    values = [
        (
            trade_date, r["symbol"], r["broker"],
            r["buy_qty"], r["buy_amount"], r["buy_trades"],
            r["sell_qty"], r["sell_amount"], r["sell_trades"],
        )
        for r in summary_rows
    ]

    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("delete from broker_daily_summary where trade_date = %s", (trade_date,))
            execute_values(
                cur,
                """
                insert into broker_daily_summary
                    (trade_date, symbol, broker,
                     buy_qty, buy_amount, buy_trades,
                     sell_qty, sell_amount, sell_trades)
                values %s
                """,
                values,
                page_size=1000,
            )
            cur.execute(
                """
                insert into floorsheet_ingest_log
                    (trade_date, trade_rows, pages, total_amount, expected_rows, missing_rows)
                values (%s, %s, %s, %s, %s, %s)
                on conflict (trade_date) do update
                    set trade_rows = excluded.trade_rows,
                        pages = excluded.pages,
                        total_amount = excluded.total_amount,
                        expected_rows = excluded.expected_rows,
                        missing_rows = excluded.missing_rows,
                        completed_at = now()
                """,
                (trade_date, trade_rows, pages, total_amount, expected_rows, missing_rows),
            )
    finally:
        conn.close()
