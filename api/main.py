from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from database.connection import get_connection
from scraper.screener.vcp_detector import run_screener

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

@app.get("/prices/{symbol}/history")
def get_price_history(symbol: str, adjusted: bool = True):
    """Full OHLC + volume history for one symbol, formatted for lightweight-charts.

    By default, prices are back-adjusted for bonus/right-share dilution (the
    same idea as Yahoo Finance's "adjusted close") using the adjustment_factors
    table -- so a bonus issue doesn't show up as a fake price crash on the
    chart. Pass ?adjusted=false to get the raw, as-traded prices instead.
    """
    symbol = symbol.upper()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        select fetched_at, open, high, low, ltp, qty
        from daily_prices
        where symbol = %s
        order by fetched_at asc
    """, (symbol,))
    rows = cur.fetchall()

    events = []
    if adjusted:
        cur.execute("""
            select ex_date, event_factor, cum_factor
            from adjustment_factors
            where symbol = %s
            order by ex_date asc
        """, (symbol,))
        events = cur.fetchall()  # ascending by ex_date

    cur.close()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No history found for '{symbol}'")

    def factor_for(d):
        """Most recent event with ex_date <= d; if d is before every event,
        use the full product (that event's cum_factor * its own event_factor)."""
        if not events:
            return 1.0
        applicable = None
        for ex_date, event_factor, cum_factor in events:
            if ex_date <= d:
                applicable = (ex_date, event_factor, cum_factor)
            else:
                break
        if applicable is None:
            _, event_factor, cum_factor = events[0]
            return cum_factor * event_factor
        return applicable[2]

    result = []
    for r in rows:
        f = factor_for(r[0])
        result.append({
            "time": r[0].strftime("%Y-%m-%d"),
            "open": float(r[1]) * f,
            "high": float(r[2]) * f,
            "low": float(r[3]) * f,
            "close": float(r[4]) * f,
            "qty": int(r[5]) if r[5] is not None else 0,
        })
    return result


@app.get("/prices/{symbol}/adjustments")
def get_adjustments(symbol: str):
    """List of bonus/right-share ex-dates for one symbol, for chart markers."""
    symbol = symbol.upper()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        select ex_date, event_type, event_factor
        from adjustment_factors
        where symbol = %s
        order by ex_date asc
    """, (symbol,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = []
    for ex_date, event_type, event_factor in rows:
        event_factor = float(event_factor)
        if event_type == "bonus" and event_factor > 0:
            pct = round((100.0 / event_factor) - 100.0, 1)
            label = f"Bonus {pct}%"
        else:
            label = "Right Share"
        result.append({
            "date": ex_date.strftime("%Y-%m-%d"),
            "event_type": event_type,
            "factor": event_factor,
            "label": label,
        })
    return result


@app.get("/screener/vcp")
def screener_vcp():
    """Returns the most recently computed VCP screener results (cached, not live)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        select symbol, prior_avg_range_pct, recent_avg_range_pct, contraction_ratio
        from screener_results
        order by contraction_ratio asc
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    cols = ["symbol", "prior_avg_range_pct", "recent_avg_range_pct", "contraction_ratio"]
    return [dict(zip(cols, row)) for row in rows]


@app.get("/fundamentals/{symbol}")
def get_fundamentals(symbol: str):
    """EPS, P/E, Book Value, PBV + full dividend/bonus/right-share history
    (scraped from merolagani's accordion summary table), plus the raw
    quarterly-report filing list for reference."""
    symbol = symbol.upper()
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        select eps, eps_fy, pe_ratio, book_value, book_value_fy, pbv, scraped_at
        from company_fundamentals
        where symbol = %s
    """, (symbol,))
    fund_row = cur.fetchone()

    cur.execute("""
        select event_type, fiscal_year, value_text
        from fundamentals_history
        where symbol = %s
        order by fiscal_year
    """, (symbol,))
    history_rows = cur.fetchall()

    cur.execute("""
        select fiscal_year, date_text, announcement_id, description
        from quarterly_reports
        where symbol = %s
        order by announcement_id::bigint desc
    """, (symbol,))
    quarterly_rows = cur.fetchall()

    cur.close()
    conn.close()

    fundamentals = None
    if fund_row:
        eps, eps_fy, pe_ratio, book_value, book_value_fy, pbv, scraped_at = fund_row
        fundamentals = {
            "eps": eps,
            "eps_fy": eps_fy,
            "pe_ratio": pe_ratio,
            "book_value": book_value,
            "book_value_fy": book_value_fy,
            "pbv": pbv,
            "scraped_at": scraped_at,
        }

    dividend_history, bonus_history, right_share_history = [], [], []
    for event_type, fiscal_year, value_text in history_rows:
        entry = {"fiscal_year": fiscal_year, "value": value_text}
        if event_type == "dividend":
            dividend_history.append(entry)
        elif event_type == "bonus":
            bonus_history.append(entry)
        elif event_type == "right":
            right_share_history.append(entry)

    quarterly_reports = [
        {
            "fiscal_year": fy,
            "date_text": dt,
            "announcement_id": aid,
            "description": desc,
        }
        for fy, dt, aid, desc in quarterly_rows
    ]

    return {
        "symbol": symbol,
        "fundamentals": fundamentals,
        "dividend_history": dividend_history,
        "bonus_history": bonus_history,
        "right_share_history": right_share_history,
        "quarterly_reports": quarterly_reports,
    }