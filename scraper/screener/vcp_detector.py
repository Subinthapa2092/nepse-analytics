"""
VCP (Volatility Contraction Pattern) detector.

Idea: a stock's daily trading range (as % of price) tends to shrink
over several weeks before a breakout. This script checks the most
recent ~10 trading days' average range against the ~10 days before
that, and flags a contraction if the recent range is meaningfully
tighter.

Run manually for now:
    python -m scraper.screener.vcp_detector
"""

from database.connection import get_connection

# how many recent days count as the "recent" window vs the "prior" window
WINDOW_SIZE = 10

# how much tighter the recent window must be to count as a contraction
# e.g. 0.7 means recent range must be <= 70% of the prior window's range
CONTRACTION_THRESHOLD = 0.7


def get_symbol_history(symbol: str, limit_days: int = 60):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        select fetched_at, high, low, open, ltp
        from daily_prices
        where symbol = %s
        order by fetched_at desc
        limit %s
    """, (symbol, limit_days))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    # rows come back newest-first; flip to oldest-first for easier windowing
    rows.reverse()
    return rows


def get_all_symbols():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("select distinct symbol from daily_prices order by symbol")
    symbols = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return symbols


def daily_range_pct(high, low, close):
    """Daily range as a percentage of closing price."""
    if close is None or close == 0:
        return None
    if high is None or low is None:
        return None
    return (float(high) - float(low)) / float(close) * 100


def check_vcp(symbol: str):
    """
    Returns a dict with contraction info if this symbol shows a VCP
    pattern, or None if there's not enough data or no contraction.
    """
    rows = get_symbol_history(symbol, limit_days=WINDOW_SIZE * 2 + 5)

    if len(rows) < WINDOW_SIZE * 2:
        return None  # not enough history yet

    ranges = []
    for date, high, low, open_, ltp in rows:
        r = daily_range_pct(high, low, ltp)
        if r is not None:
            ranges.append(r)

    if len(ranges) < WINDOW_SIZE * 2:
        return None

    prior_window = ranges[-(WINDOW_SIZE * 2):-WINDOW_SIZE]
    recent_window = ranges[-WINDOW_SIZE:]

    prior_avg = sum(prior_window) / len(prior_window)
    recent_avg = sum(recent_window) / len(recent_window)

    if prior_avg == 0:
        return None

    contraction_ratio = recent_avg / prior_avg

    if contraction_ratio <= CONTRACTION_THRESHOLD:
        return {
            "symbol": symbol,
            "prior_avg_range_pct": round(prior_avg, 2),
            "recent_avg_range_pct": round(recent_avg, 2),
            "contraction_ratio": round(contraction_ratio, 2),
        }

    return None


def run_screener(symbols: list[str] = None, debug: bool = False):
    symbols = symbols or get_all_symbols()
    print(f"Checking {len(symbols)} symbols for VCP contraction...")

    hits = []
    for symbol in symbols:
        try:
            result = check_vcp(symbol)
            if result:
                hits.append(result)
            elif debug:
                # show why it didn't hit, even without a full contraction
                rows = get_symbol_history(symbol, limit_days=WINDOW_SIZE * 2 + 5)
                if len(rows) < WINDOW_SIZE * 2:
                    print(f"  {symbol}: not enough history ({len(rows)} rows)")
                else:
                    ranges = [daily_range_pct(h, l, c) for _, h, l, o, c in rows if daily_range_pct(h, l, c) is not None]
                    if len(ranges) >= WINDOW_SIZE * 2:
                        prior = ranges[-(WINDOW_SIZE*2):-WINDOW_SIZE]
                        recent = ranges[-WINDOW_SIZE:]
                        prior_avg = sum(prior)/len(prior)
                        recent_avg = sum(recent)/len(recent)
                        ratio = recent_avg/prior_avg if prior_avg else None
                        print(f"  {symbol}: prior={prior_avg:.2f}% recent={recent_avg:.2f}% ratio={ratio:.2f}" if ratio else f"  {symbol}: n/a")
        except Exception as e:
            print(f"  skipped {symbol}: {e}")

    print(f"\nFound {len(hits)} symbols showing contraction:\n")
    for hit in sorted(hits, key=lambda h: h["contraction_ratio"]):
        print(
            f"  {hit['symbol']:12s} "
            f"prior: {hit['prior_avg_range_pct']:5.2f}%  "
            f"recent: {hit['recent_avg_range_pct']:5.2f}%  "
            f"ratio: {hit['contraction_ratio']:.2f}"
        )

    return hits


if __name__ == "__main__":
    test_symbols = ["NABIL", "AHPC", "ACLBSL", "ADBL", "HDL", "NICA", "AKPL"]
    run_screener(symbols=test_symbols, debug=True)