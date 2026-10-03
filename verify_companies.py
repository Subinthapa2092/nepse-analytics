import sqlite3
conn = sqlite3.connect("E:/nepse_companies.sqlite")
print("Total:", conn.execute("select count(*) from company_list").fetchone()[0])
print("\nSample rows:")
for row in conn.execute("select symbol, company_name, sector from company_list limit 5"):
    print(row)
print("\nSectors:")
for row in conn.execute("select sector, count(*) from company_list group by sector"):
    print(row)