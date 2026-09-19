"""
Turn raw floorsheet trades into one row per (symbol, broker) for the day.

Each trade counts once as a BUY for the buyer broker and once as a SELL for the
seller broker. Net buying = buy_qty - sell_qty is what accumulation/distribution
is built from later.
"""

from __future__ import annotations


def aggregate_by_broker(trades: list[dict]) -> list[dict]:
    acc: dict[tuple[str, str], dict] = {}

    def slot(symbol: str, broker: str) -> dict:
        key = (symbol, broker)
        if key not in acc:
            acc[key] = {
                "symbol": symbol, "broker": broker,
                "buy_qty": 0, "buy_amount": 0.0, "buy_trades": 0,
                "sell_qty": 0, "sell_amount": 0.0, "sell_trades": 0,
            }
        return acc[key]

    for t in trades:
        qty = t["quantity"]
        amount = t["amount"] or 0.0

        b = slot(t["symbol"], t["buyer_broker"])
        b["buy_qty"] += qty
        b["buy_amount"] += amount
        b["buy_trades"] += 1

        s = slot(t["symbol"], t["seller_broker"])
        s["sell_qty"] += qty
        s["sell_amount"] += amount
        s["sell_trades"] += 1

    out = list(acc.values())
    for row in out:
        row["buy_amount"] = round(row["buy_amount"], 2)
        row["sell_amount"] = round(row["sell_amount"], 2)
    out.sort(key=lambda r: (r["symbol"], r["broker"]))
    return out


def total_amount(trades: list[dict]) -> float:
    return round(sum(t["amount"] or 0.0 for t in trades), 2)
