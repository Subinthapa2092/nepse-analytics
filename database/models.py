"""
Table schema definitions for nepse-analytics.

Raw SQL DDL, not an ORM — matches the rest of the codebase (database/save.py,
save_history.py) which talks to Postgres directly via psycopg2.

Run this file directly to create/verify all tables:
    python -m database.models
"""

from database.connection import get_connection


DAILY_PRICES_DDL = """
CREATE TABLE IF NOT EXISTS daily_prices (
    id          SERIAL PRIMARY KEY,
    symbol      TEXT NOT NULL,
    ltp         NUMERIC,
    pct_change  NUMERIC,
    high        NUMERIC,
    low         NUMERIC,
    open        NUMERIC,
    qty         BIGINT,
    trend       TEXT,
    fetched_at  DATE NOT NULL DEFAULT CURRENT_DATE,
    UNIQUE (symbol, fetched_at)
);
"""

# Index used by every /prices/{symbol}* endpoint (symbol lookup + date ordering)
DAILY_PRICES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_daily_prices_symbol_fetched_at
    ON daily_prices (symbol, fetched_at DESC);
"""

COMPANIES_DDL = """
CREATE TABLE IF NOT EXISTS companies (
    symbol         TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    sector         TEXT,
    listed_shares  BIGINT,
    updated_at     TIMESTAMP DEFAULT NOW()
);
"""


def create_all():
    """Create every table if it doesn't already exist. Safe to re-run."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(DAILY_PRICES_DDL)
    cur.execute(DAILY_PRICES_INDEX)
    cur.execute(COMPANIES_DDL)
    conn.commit()
    cur.close()
    conn.close()
    print("All tables verified/created.")


if __name__ == "__main__":
    create_all()