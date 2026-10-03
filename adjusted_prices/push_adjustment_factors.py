"""
One-time (and re-runnable) push of the local adjustment_factors table into
Supabase, so the live API (on Render) can serve adjusted prices -- the
local SQLite file never leaves this machine otherwise.

Small table (~1,100 rows for all 243 symbols with corporate actions), so
this costs essentially nothing against the free tier.
"""

import os
import sqlite3
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)

CORP_DB = os.path.join(PROJECT_ROOT, "companies", "nepse_corporate_dates.sqlite")

from database.connection import get_connection

pg_conn = get_connection()
pg_cursor = pg_conn.cursor()

pg_cursor.execute("""
    CREATE TABLE IF NOT EXISTS adjustment_factors (
        symbol        TEXT NOT NULL,
        ex_date       DATE NOT NULL,
        event_type    TEXT NOT NULL,
        raw_detail    TEXT,
        cum_price     REAL,
        event_factor  REAL NOT NULL,
        cum_factor    REAL NOT NULL,
        PRIMARY KEY (symbol, ex_date, event_type)
    )
""")
pg_conn.commit()

corp_conn = sqlite3.connect(CORP_DB)
rows = corp_conn.execute(
    "select symbol, ex_date, event_type, raw_detail, cum_price, event_factor, cum_factor "
    "from adjustment_factors"
).fetchall()
corp_conn.close()

print(f"Pushing {len(rows)} rows to Supabase...")

for row in rows:
    pg_cursor.execute(
        """INSERT INTO adjustment_factors
           (symbol, ex_date, event_type, raw_detail, cum_price, event_factor, cum_factor)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (symbol, ex_date, event_type) DO UPDATE SET
               raw_detail = EXCLUDED.raw_detail,
               cum_price = EXCLUDED.cum_price,
               event_factor = EXCLUDED.event_factor,
               cum_factor = EXCLUDED.cum_factor""",
        row,
    )
pg_conn.commit()

pg_cursor.execute("select count(*) from adjustment_factors")
print(f"Done. Supabase adjustment_factors now has {pg_cursor.fetchone()[0]} rows.")

pg_conn.close()