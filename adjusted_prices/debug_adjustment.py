from database.connection import get_connection

conn = get_connection()
cur = conn.cursor()

cur.execute("""
    select ex_date, event_factor, cum_factor
    from adjustment_factors
    where symbol = 'ADBL'
    order by ex_date asc
""")
events = cur.fetchall()
print("Events (ascending by ex_date):")
for e in events:
    print(f"  ex_date={e[0]!r} (type={type(e[0]).__name__})  event_factor={e[1]}  cum_factor={e[2]}")

cur.execute("""
    select fetched_at from daily_prices where symbol = 'ADBL'
    order by fetched_at desc limit 1
""")
row = cur.fetchone()
print(f"\nMost recent fetched_at: {row[0]!r} (type={type(row[0]).__name__})")

cur.close()
conn.close()