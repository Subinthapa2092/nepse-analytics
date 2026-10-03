"""
One-time patch: adds a GET /prices/{symbol}/adjustments endpoint to api/main.py
that returns the bonus/right-share ex-dates for a symbol, so the frontend can
draw markers on the chart.

Run this from the project root (E:\\nepse-analytics):
    python add_adjustments_endpoint.py

Makes api/main.py.bak as a backup first.
"""

path = "api/main.py"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

anchor = '@app.get("/screener/vcp")'
if anchor not in src:
    raise SystemExit(
        "Could not find the expected anchor in api/main.py -- the file has "
        "changed since this script was written. Paste me the current "
        "api/main.py and I'll adjust the script."
    )

if "/prices/{symbol}/adjustments" in src:
    print("Endpoint already present in api/main.py -- nothing to do.")
else:
    with open(path + ".bak", "w", encoding="utf-8") as f:
        f.write(src)

    new_endpoint = '''@app.get("/prices/{symbol}/adjustments")
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


'''

    src = src.replace(anchor, new_endpoint + anchor, 1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(src)

    print("Done. Added GET /prices/{symbol}/adjustments to api/main.py")
    print("Backup saved to api/main.py.bak")