"""
Pushes the local company_fundamentals + fundamentals_history SQLite tables
into Supabase -- same pattern as push_quarterly_reports.py / push_adjustment_factors.py.

Re-runnable: uses ON CONFLICT ... DO UPDATE, so running this again after a
fresh scrape just updates existing rows / adds new ones.
"""

import os
import sqlite3
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)

CORP_DB = os.path.join(PROJECT_ROOT, "companies", "nepse_fundamentals.sqlite")

from database.connection import get_connection

pg_conn = get_connection()
pg_cursor = pg_conn.cursor()

pg_cursor.execute("""
    CREATE TABLE IF NOT EXISTS company_fundamentals (
        symbol        TEXT NOT NULL PRIMARY KEY,
        eps           TEXT,
        eps_fy        TEXT,
        pe_ratio      TEXT,
        book_value    TEXT,
        book_value_fy TEXT,
        pbv           TEXT,
        scraped_at    TEXT
    )
""")
pg_cursor.execute("""
    CREATE TABLE IF NOT EXISTS fundamentals_history (
        symbol       TEXT NOT NULL,
        event_type   TEXT NOT NULL,
        fiscal_year  TEXT NOT NULL,
        value_text   TEXT,
        PRIMARY KEY (symbol, event_type, fiscal_year)
    )
""")
pg_conn.commit()

corp_conn = sqlite3.connect(CORP_DB)

fund_rows = corp_conn.execute(
    """select symbol, eps, eps_fy, pe_ratio, book_value, book_value_fy, pbv, scraped_at
       from company_fundamentals"""
).fetchall()
history_rows = corp_conn.execute(
    "select symbol, event_type, fiscal_year, value_text from fundamentals_history"
).fetchall()
corp_conn.close()

print(f"Pushing {len(fund_rows)} company_fundamentals row(s) and "
      f"{len(history_rows)} fundamentals_history row(s) to Supabase...")

for row in fund_rows:
    pg_cursor.execute(
        """INSERT INTO company_fundamentals
               (symbol, eps, eps_fy, pe_ratio, book_value, book_value_fy, pbv, scraped_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (symbol) DO UPDATE SET
               eps = EXCLUDED.eps,
               eps_fy = EXCLUDED.eps_fy,
               pe_ratio = EXCLUDED.pe_ratio,
               book_value = EXCLUDED.book_value,
               book_value_fy = EXCLUDED.book_value_fy,
               pbv = EXCLUDED.pbv,
               scraped_at = EXCLUDED.scraped_at""",
        row,
    )

for row in history_rows:
    pg_cursor.execute(
        """INSERT INTO fundamentals_history (symbol, event_type, fiscal_year, value_text)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (symbol, event_type, fiscal_year) DO UPDATE SET
               value_text = EXCLUDED.value_text""",
        row,
    )

pg_conn.commit()
pg_cursor.close()
pg_conn.close()
print("Done.")