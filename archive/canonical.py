"""
Turns a list of dict rows into a fixed, sorted, exact-text form, and hashes that.

This is the integrity check the whole pipeline depends on: two representations of
"the same data" (a .csv.gz file vs. rows loaded into SQLite) must produce the
IDENTICAL checksum, or verification correctly fails. That only works if the
canonical form ignores anything that legitimately differs between formats:

  - column/key ORDER          -> we fix an explicit field order per dataset
  - row ORDER                 -> we sort rows by a stable key before hashing
  - type representation       -> everything is cast to str the same way (so
                                  100 and 100.0 and "100" all hash the same,
                                  which matters because CSV has no types and
                                  SQLite does)
  - trailing whitespace       -> stripped

Do NOT hash file bytes (gzip timestamps, compression level, and SQLite's file
format all differ from a CSV's bytes even when the DATA is identical) and do not
hash dataclass/dict repr() (field order in a dict is not guaranteed stable
across Python versions or code paths).
"""

from __future__ import annotations

import hashlib

PRICE_FIELDS = ["symbol", "ltp", "pct_change", "high", "low", "open", "qty", "trend"]
PRICE_KEY = ("symbol",)

FLOORSHEET_FIELDS = ["transaction_no", "symbol", "buyer_broker", "seller_broker",
                      "quantity", "rate", "amount"]
FLOORSHEET_KEY = ("transaction_no",)


def _cell(value) -> str:
    """Normalizes one cell so the SAME logical value hashes identically whether
    it arrived as a Python float (from SQLite) or as text (from a CSV, where
    everything is a string -- including "561.0", "12345", and "" for None)."""
    if value is None:
        return ""
    s = str(value).strip()
    if s == "":
        return ""
    try:
        f = float(s)
    except ValueError:
        return s  # not numeric at all (e.g. a symbol or trend label): leave as-is
    return str(int(f)) if f == int(f) else repr(f)


def canonical_rows(rows: list[dict], fields: list[str], key: tuple[str, ...]) -> list[tuple]:
    """Sorted list of fixed-order string tuples. Deterministic regardless of
    input row order or dict key order."""
    out = [tuple(_cell(r.get(f)) for f in fields) for r in rows]
    key_idx = [fields.index(k) for k in key]
    out.sort(key=lambda t: tuple(t[i] for i in key_idx))
    return out


def checksum(rows: list[dict], fields: list[str], key: tuple[str, ...]) -> str:
    canon = canonical_rows(rows, fields, key)
    h = hashlib.sha256()
    for row in canon:
        h.update("\x1f".join(row).encode("utf-8"))
        h.update(b"\x1e")  # row separator, distinct from any cell content
    return h.hexdigest()


def checksum_prices(rows: list[dict]) -> str:
    return checksum(rows, PRICE_FIELDS, PRICE_KEY)


def checksum_floorsheet(rows: list[dict]) -> str:
    return checksum(rows, FLOORSHEET_FIELDS, FLOORSHEET_KEY)
