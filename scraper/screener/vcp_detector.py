"""
VCP (Volatility Contraction Pattern) detector.

Uses ONE shared database connection for the whole run, instead of
opening a new connection per symbol — opening hundreds of rapid
connections in a loop triggers DNS/connection-pool failures partway
through (same category of issue as the original backfill script).
"""

from database.connection import get_connection

WINDOW_SIZE = 10
CONTRACTION_THRESHOLD = 0.9


def get_all_symbols(cur):
    cur.execute("select distinct symbol from daily_prices order by symbol")
    return [row[0] for row in cur.fetchall()]


def get_symbol_history(cur, symbol: str, limit_days: int = 60):
    cur.execute("""
        select fetched_at, high, low, open, ltp
        from daily_prices
        where symbol = %s
        order by fetched_at desc
        limit %s
    """, (symbol, limit_days))
    rows = cur.fetchall()
    rows.reverse()
    return rows


def daily_range_pct(high, low, close):
    if close is None or close == 0 or high is None or low is None:
        return None
    return (float(high) - float(low)) / float(close) * 100


def check_vcp(cur, symbol: str):
    rows = get_symbol_history(cur, symbol, limit_days=WINDOW_SIZE * 2 + 5)
    if len(rows) < WINDOW_SIZE * 2:
        return None

    ranges = [daily_range_pct(h, l, c) for _, h, l, o, c in rows]
    ranges = [r for r in ranges if r is not None]
    if len(ranges) < WINDOW_SIZE * 2:
        return None

    prior_window = ranges[-(WINDOW_SIZE * 2):-WINDOW_SIZE]
    recent_window = ranges[-WINDOW_SIZE:]
    prior_avg = sum(prior_window) / len(prior_window)
    recent_avg = sum(recent_window) / len(recent_window)

    if prior_avg == 0:
        return None

    ratio = recent_avg / prior_avg
    if ratio <= CONTRACTION_THRESHOLD:
        return {
            "symbol": symbol,
            "prior_avg_range_pct": round(prior_avg, 2),
            "recent_avg_range_pct": round(recent_avg, 2),
            "contraction_ratio": round(ratio, 2),
        }
    return None


def run_screener(symbols: list[str] = None):
    conn = get_connection()
    cur = conn.cursor()

    try:
        symbols = symbols or get_all_symbols(cur)
        print(f"Checking {len(symbols)} symbols for VCP contraction...")

        hits = []
        for symbol in symbols:
            try:
                result = check_vcp(cur, symbol)
                if result:
                    hits.append(result)
            except Exception as e:
                print(f"  skipped {symbol}: {e}")
    finally:
        cur.close()
        conn.close()

    print(f"\nFound {len(hits)} symbols showing contraction:\n")
    for hit in sorted(hits, key=lambda h: h["contraction_ratio"]):
        print(
            f"  {hit['symbol']:12s} "
            f"prior: {hit['prior_avg_range_pct']:5.2f}%  "
            f"recent: {hit['recent_avg_range_pct']:5.2f}%  "
            f"ratio: {hit['contraction_ratio']:.2f}"
        )
    return hits



def save_screener_results(hits: list[dict]):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("delete from screener_results")  # clear old results each run
    for hit in hits:
        cur.execute("""
            insert into screener_results (symbol, prior_avg_range_pct, recent_avg_range_pct, contraction_ratio)
            values (%s, %s, %s, %s)
        """, (hit["symbol"], hit["prior_avg_range_pct"], hit["recent_avg_range_pct"], hit["contraction_ratio"]))
    conn.commit()
    cur.close()
    conn.close()
    print(f"Saved {len(hits)} screener results.")

if __name__ == "__main__":
    hits = run_screener()
    save_screener_results(hits)