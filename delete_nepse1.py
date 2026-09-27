import sqlite3
conn = sqlite3.connect("indices/nepse_indices.sqlite")
deleted = conn.execute("delete from index_history where index_name='Nepse1'").rowcount
conn.commit()
print(f"Deleted {deleted} rows")