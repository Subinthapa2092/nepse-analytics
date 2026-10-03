import sqlite3
conn = sqlite3.connect(r"..\companies\nepse_corporate_dates.sqlite")
for row in conn.execute("select * from adjustment_factors where symbol='MLBBL' order by ex_date"):
    print(row)