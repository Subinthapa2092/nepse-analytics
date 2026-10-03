"""
One-time patch: makes the chart draw a dashed vertical line + label at every
bonus/right-share ex-date, using the VerticalLine plugin that's already in
the file. Markers are cleared and re-fetched every time you load a symbol.

Run this from the project root (E:\\nepse-analytics):
    python add_adjustment_markers.py

Makes frontend/index.html.bak2 as a backup first (kept separate from the
.bak that fix_frontend.py already made, so neither gets overwritten).
"""

path = "frontend/index.html"

with open(path, "r", encoding="utf-8") as f:
    src = f.read()

if "adjustmentMarkers" in src:
    print("Markers already wired in -- nothing to do.")
    raise SystemExit

anchor1 = "let currentPriceLine = null;"
anchor2 = "candleSeries.setData(data);"

missing = [a for a in (anchor1, anchor2) if a not in src]
if missing:
    raise SystemExit(
        "Could not find expected anchor(s) in frontend/index.html: "
        f"{missing}. The file has changed since this script was written -- "
        "paste me the current frontend/index.html and I'll adjust it."
    )

with open(path + ".bak2", "w", encoding="utf-8") as f:
    f.write(src)

# 1. declare the marker list + a helper to clear old markers, right after
#    currentPriceLine is declared.
src = src.replace(
    anchor1,
    anchor1 + "\n  let adjustmentMarkers = [];\n"
    "  function clearAdjustmentMarkers() {\n"
    "    adjustmentMarkers.forEach(m => candleSeries.detachPrimitive(m));\n"
    "    adjustmentMarkers = [];\n"
    "  }",
    1,
)

# 2. right after the candles are set on the chart, clear any old markers and
#    fetch+draw this symbol's adjustment events (bonus/right-share ex-dates).
src = src.replace(
    anchor2,
    anchor2 + "\n"
    "      clearAdjustmentMarkers();\n"
    "      try {\n"
    "        const evRes = await fetch(`${API_BASE}/prices/${symbol}/adjustments`);\n"
    "        if (evRes.ok) {\n"
    "          const events = await evRes.json();\n"
    "          events.forEach(ev => {\n"
    "            const vline = new VerticalLine(ev.date, ev.label, { color: '#F0B90B', width: 1 });\n"
    "            candleSeries.attachPrimitive(vline);\n"
    "            adjustmentMarkers.push(vline);\n"
    "          });\n"
    "        }\n"
    "      } catch (e) { /* non-fatal: markers are a nice-to-have */ }",
    1,
)

with open(path, "w", encoding="utf-8") as f:
    f.write(src)

print("Done. Bonus/right-share ex-dates will now show as dashed gold lines on the chart.")
print("Backup saved to frontend/index.html.bak2")