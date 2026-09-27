import sqlite3
conn = sqlite3.connect("data/nepse_archive.db")
rows = conn.execute(
    "select trade_date, row_count from archive_manifest "
    "where dataset='daily_prices' and trade_date like '%-09-%' "
    "order by trade_date desc limit 20"
).fetchall()
for r in rows:
    print(r)