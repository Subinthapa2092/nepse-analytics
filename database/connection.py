"""
Basic Postgres (Supabase) connection helper.
Run this file directly to sanity-check that DATABASE_URL in your .env works.
"""

import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "DATABASE_URL not set. Copy .env.example to .env and fill it in."
        )
    return psycopg2.connect(db_url)


if __name__ == "__main__":
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT version();")
    print(cur.fetchone())
    cur.close()
    conn.close()
#Subin@612427