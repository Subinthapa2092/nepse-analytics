import sqlite3
conn = sqlite3.connect("data/nepse_archive.db")
result = conn.execute(
    "select count(*), min(trade_date), max(trade_date) "
    "from archive_manifest where dataset='floorsheet' and verified=1"
).fetchone()
print("verified floorsheet days:", result)