from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from database.connection import get_connection

app = FastAPI(title="nepse-analytics API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

COLUMNS = ["symbol", "ltp", "pct_change", "high", "low", "open", "qty", "trend", "fetched_at"]


@app.get("/")
def health():
    return {"status": "alive"}


@app.get("/prices")
def get_all_prices():
    """Latest snapshot for every symbol."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        select distinct on (symbol)
            symbol, ltp, pct_change, high, low, open, qty, trend, fetched_at
        from daily_prices
        order by symbol, fetched_at desc
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [dict(zip(COLUMNS, row)) for row in rows]


@app.get("/prices/{symbol}")
def get_price(symbol: str):
    """Latest snapshot for one symbol."""
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

    return dict(zip(COLUMNS, row))


# @app.get("/prices/{symbol}/history")
# def get_price_history(symbol: str):
#     """Full OHLC history for one symbol, formatted for lightweight-charts."""
#     conn = get_connection()
#     cur = conn.cursor()
#     cur.execute("""
#         select fetched_at, open, high, low, ltp
#         from daily_prices
#         where symbol = %s
#         order by fetched_at asc
#     """, (symbol.upper(),))
#     rows = cur.fetchall()
#     cur.close()
#     conn.close()

#     if not rows:
#         raise HTTPException(status_code=404, detail=f"No history found for '{symbol}'")

#     return [
#         {
#             "time": r[0].strftime("%Y-%m-%d"),
#             "open": float(r[1]),
#             "high": float(r[2]),
#             "low": float(r[3]),
#             "close": float(r[4]),
#         }
#         for r in rows
#     ]
@app.get("/prices/{symbol}/history")
def get_price_history(symbol: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        select fetched_at, open, high, low, ltp, qty
        from daily_prices
        where symbol = %s
        order by fetched_at asc
    """, (symbol.upper(),))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No history found for '{symbol}'")

    return [
        {
            "time": r[0].strftime("%Y-%m-%d"),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "qty": int(r[5]) if r[5] is not None else 0,
        }
        for r in rows
    ]