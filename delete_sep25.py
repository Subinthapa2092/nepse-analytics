import sqlite3
conn = sqlite3.connect("data/nepse_archive.db")
conn.execute("delete from prices where trade_date = '2026-09-25'")
conn.execute("delete from archive_manifest where dataset='daily_prices' and trade_date = '2026-09-25'")
conn.commit()
print("removed 2026-09-25 from local archive")