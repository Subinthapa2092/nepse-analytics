import os
import sqlite3

DB_PATH = "data/nepse_archive.db"

conn = sqlite3.connect(DB_PATH)

size_mb = os.path.getsize(DB_PATH) / 1024 / 1024
print(f"File size (MB): {size_mb:.2f}")

floorsheet = conn.execute(
    "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) "
    "FROM archive_manifest WHERE dataset='floorsheet' AND verified=1"
).fetchone()
print("Floorsheet days:", floorsheet)

prices = conn.execute(
    "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) "
    "FROM archive_manifest WHERE dataset='daily_prices' AND verified=1"
).fetchone()
print("Price days:", prices)

conn.close()