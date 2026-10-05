import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)

import psycopg2
from psycopg2.extras import execute_values
from database.connection import get_connection  # nepse-analytics' own DB

FLOORSHEET_DB_URL = os.environ["FLOORSHEET_DATABASE_URL"]

src_conn = get_connection()
src_cur = src_conn.cursor()
src_cur.execute("""
    SELECT symbol, ex_date, event_type, raw_detail, cum_price, event_factor, cum_factor
    FROM adjustment_factors
""")
rows = src_cur.fetchall()
src_cur.close()
src_conn.close()

dst_conn = psycopg2.connect(FLOORSHEET_DB_URL)
dst_cur = dst_conn.cursor()
dst_cur.execute("""
    CREATE TABLE IF NOT EXISTS adjustment_factors (
        symbol TEXT, ex_date DATE, event_type TEXT, raw_detail TEXT,
        cum_price REAL, event_factor REAL, cum_factor REAL,
        PRIMARY KEY (symbol, ex_date, event_type)
    )
""")
dst_conn.commit()

execute_values(
    dst_cur,
    """INSERT INTO adjustment_factors (symbol, ex_date, event_type, raw_detail, cum_price, event_factor, cum_factor)
       VALUES %s
       ON CONFLICT (symbol, ex_date, event_type) DO UPDATE SET
           raw_detail = EXCLUDED.raw_detail,
           cum_price = EXCLUDED.cum_price,
           event_factor = EXCLUDED.event_factor,
           cum_factor = EXCLUDED.cum_factor""",
    rows,
)
dst_conn.commit()
dst_cur.close()
dst_conn.close()
print(f"Synced {len(rows)} adjustment_factors row(s) to nepse_floorsheet.")