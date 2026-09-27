import sqlite3
conn = sqlite3.connect("indices/nepse_indices.sqlite")
count = conn.execute(
    "select count(*) from index_history where index_name='Nepse1'"
).fetchone()[0]
print("Nepse1 rows:", count)