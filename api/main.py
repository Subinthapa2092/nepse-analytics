from fastapi import FastAPI, HTTPException
from database.connection import get_connection

app = FastAPI(title="nepse-analytics API")


@app.get("/")
def health():
    return {"status": "alive"}


@app.get("/prices")
def get_all_prices():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        select symbol, ltp, pct_change, high, low, open, qty, trend, fetched_at
        from daily_prices
        order by symbol
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    columns = ["symbol", "ltp", "pct_change", "high", "low", "open", "qty", "trend", "fetched_at"]
    return [dict(zip(columns, row)) for row in rows]


# @app.get("/prices/{symbol}")
# def get_price(symbol: str):
#     conn = get_connection()
#     cur = conn.cursor()
#     cur.execute("""
#         select symbol, ltp, pct_change, high, low, open, qty, trend, fetched_at
#         from daily_prices
#         where symbol = %s
#     """, (symbol.upper(),))
#     row = cur.fetchone()
#     cur.close()
#     conn.close()

#     if row is None:
#         raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found")

#     columns = ["symbol", "ltp", "pct_change", "high", "low", "open", "qty", "trend", "fetched_at"]
#     return dict(zip(columns, row))
@app.get("/prices/{symbol}")
def get_price(symbol: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        select symbol, ltp, pct_change, high, low, open, qty, trend, fetched_at
        from daily_prices
        where symbol = %s
        order by fetched_at desc
        limit 1
    """, (symbol.upper(),))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found")

    columns = ["symbol", "ltp", "pct_change", "high", "low", "open", "qty", "trend", "fetched_at"]
    return dict(zip(columns, row))