"""
Pushes the local quarterly_reports + quarterly_detail SQLite tables into
Supabase, so the live API (on Render) can serve this data -- same pattern
as push_adjustment_factors.py.

Re-runnable: uses ON CONFLICT ... DO UPDATE, so running this again after a
fresh scrape just updates existing rows / adds new ones.
"""

import os
import sqlite3
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)

CORP_DB = os.path.join(PROJECT_ROOT, "companies", "nepse_quarterly_reports.sqlite")

from database.connection import get_connection

pg_conn = get_connection()
pg_cursor = pg_conn.cursor()

pg_cursor.execute("""
    CREATE TABLE IF NOT EXISTS quarterly_reports (
        symbol           TEXT NOT NULL,
        fiscal_year      TEXT,
        date_text        TEXT,
        announcement_id  TEXT NOT NULL,
        description      TEXT,
        PRIMARY KEY (symbol, announcement_id)
    )
""")
pg_cursor.execute("""
    CREATE TABLE IF NOT EXISTS quarterly_detail (
        symbol            TEXT NOT NULL,
        announcement_id   TEXT NOT NULL,
        bookclose_date    TEXT,
        cash_dividend_pct TEXT,
        bonus_share_pct   TEXT,
        right_share_ratio TEXT,
        announcement_date TEXT,
        fiscal_year       TEXT,
        tags              TEXT,
        PRIMARY KEY (symbol, announcement_id)
    )
""")
pg_conn.commit()

corp_conn = sqlite3.connect(CORP_DB)

list_rows = corp_conn.execute(
    "select symbol, fiscal_year, date_text, announcement_id, description from quarterly_reports"
).fetchall()
detail_rows = corp_conn.execute(
    """select symbol, announcement_id, bookclose_date, cash_dividend_pct,
              bonus_share_pct, right_share_ratio, announcement_date, fiscal_year, tags
       from quarterly_detail"""
).fetchall()
corp_conn.close()

print(f"Pushing {len(list_rows)} quarterly_reports row(s) and {len(detail_rows)} quarterly_detail row(s) to Supabase...")

for row in list_rows:
    pg_cursor.execute(
        """INSERT INTO quarterly_reports (symbol, fiscal_year, date_text, announcement_id, description)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (symbol, announcement_id) DO UPDATE SET
               fiscal_year = EXCLUDED.fiscal_year,
               date_text = EXCLUDED.date_text,
               description = EXCLUDED.description""",
        row,
    )

for row in detail_rows:
    pg_cursor.execute(
        """INSERT INTO quarterly_detail
               (symbol, announcement_id, bookclose_date, cash_dividend_pct,
                bonus_share_pct, right_share_ratio, announcement_date, fiscal_year, tags)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (symbol, announcement_id) DO UPDATE SET
               bookclose_date = EXCLUDED.bookclose_date,
               cash_dividend_pct = EXCLUDED.cash_dividend_pct,
               bonus_share_pct = EXCLUDED.bonus_share_pct,
               right_share_ratio = EXCLUDED.right_share_ratio,
               announcement_date = EXCLUDED.announcement_date,
               fiscal_year = EXCLUDED.fiscal_year,
               tags = EXCLUDED.tags""",
        row,
    )

pg_conn.commit()
pg_cursor.close()
pg_conn.close()
print("Done.")