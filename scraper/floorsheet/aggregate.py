"""
Turn raw floorsheet trades into one row per (symbol, broker) for the day.

Each trade counts once as a BUY for the buyer broker and once as a SELL for the
seller broker. Net buying = buy_qty - sell_qty is what accumulation/distribution
is built from later.
"""

from __future__ import annotations

import re


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


def total_quantity(trades: list[dict]) -> int:
    return sum(t["quantity"] for t in trades)


def find_missing_contracts(trades: list[dict]) -> list[str]:
    """
    Contract numbers look like YYYYMMDD + 2-digit group + 6-digit sequence, and each
    group counts up from 000001 (seen on the official NEPSE floorsheet). So any hole in
    a group's sequence is a trade we failed to collect. This can only see holes BELOW a
    group's highest number -- missing trades at the very end of a group are invisible.
    Returns [] if the numbers don't follow that pattern.
    """
    groups: dict[str, set[int]] = {}
    prefix = None
    for t in trades:
        m = re.fullmatch(r"(\d{8})(\d{2})(\d{6})", t["transaction_no"])
        if not m:
            return []  # unknown numbering scheme; don't guess
        prefix = m.group(1)
        groups.setdefault(m.group(2), set()).add(int(m.group(3)))

    missing = []
    for group in sorted(groups):
        present = groups[group]
        for seq in range(1, max(present) + 1):
            if seq not in present:
                missing.append(f"{prefix}{group}{seq:06d}")
    return missing
