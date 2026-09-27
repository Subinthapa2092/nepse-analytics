import sqlite3
conn = sqlite3.connect("data/nepse_archive.db")
rows = conn.execute(
    "select trade_date, symbol, ltp, qty from prices "
    "where trade_date in ('2026-09-24','2026-09-25') "
    "order by symbol, trade_date"
).fetchall()

by_date = {}
for d, sym, ltp, qty in rows:
    by_date.setdefault(d, {})[sym] = (ltp, qty)

d1, d2 = "2026-09-24", "2026-09-25"
if d1 in by_date and d2 in by_date:
    identical = sum(1 for s in by_date[d1] if by_date[d1].get(s) == by_date[d2].get(s))
    print(f"{identical} of {len(by_date[d2])} symbols on {d2} match {d1} exactly")
else:
    print("one of the dates has no data")