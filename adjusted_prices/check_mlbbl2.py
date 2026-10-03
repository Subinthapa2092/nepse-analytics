import sqlite3
conn = sqlite3.connect(r"..\companies\nepse_corporate_dates.sqlite")
for row in conn.execute("select * from right_share_history where symbol='MLBBL' order by bookclose_date"):
    print(row)