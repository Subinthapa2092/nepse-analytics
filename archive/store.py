"""
The local historical database: one file (nepse_archive.db), holding every day of
prices and floorsheet data ever archived, plus the manifest that records what's
been verified. Uses SQLite (Python's stdlib `sqlite3`, no install needed).

Loading a day is idempotent: loading the same date twice replaces that date's
rows rather than duplicating them, so re-running the pipeline after a crash, or
retrying a failed day, is always safe.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from archive.canonical import (
    FLOORSHEET_FIELDS, PRICE_FIELDS, checksum_floorsheet, checksum_prices,
)

SCHEMA = """
create table if not exists prices (
    trade_date   text not null,
    symbol       text not null,
    ltp          real, pct_change real, high real, low real, open real,
    qty          integer, trend text,
    primary key (trade_date, symbol)
);
create index if not exists idx_prices_date on prices(trade_date);

create table if not exists floorsheet (
    trade_date       text not null,
    transaction_no   text not null,
    symbol           text, buyer_broker text, seller_broker text,
    quantity         integer, rate real, amount real,
    primary key (trade_date, transaction_no)
);
create index if not exists idx_floorsheet_date on floorsheet(trade_date);

create table if not exists archive_manifest (
    dataset          text not null,   -- 'daily_prices' | 'floorsheet'
    trade_date       text not null,
    row_count        integer not null,
    checksum         text not null,
    archive_path     text,
    archived_at      text not null,
    verified         integer not null default 0,
    supabase_deleted integer not null default 0,
    primary key (dataset, trade_date)
);
"""


class ArchiveDB:
    def __init__(self, path: Path | str):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- loading (idempotent: replace-by-date) --------------------------

    def load_prices(self, d: date, rows: list[dict]) -> None:
        with self.conn:
            self.conn.execute("delete from prices where trade_date = ?", (d.isoformat(),))
            self.conn.executemany(
                """insert into prices
                   (trade_date, symbol, ltp, pct_change, high, low, open, qty, trend)
                   values (?,?,?,?,?,?,?,?,?)""",
                [(d.isoformat(), r.get("symbol"), r.get("ltp"), r.get("pct_change"),
                  r.get("high"), r.get("low"), r.get("open"), r.get("qty"), r.get("trend"))
                 for r in rows],
            )

    def load_floorsheet(self, d: date, rows: list[dict]) -> None:
        with self.conn:
            self.conn.execute("delete from floorsheet where trade_date = ?", (d.isoformat(),))
            self.conn.executemany(
                """insert into floorsheet
                   (trade_date, transaction_no, symbol, buyer_broker, seller_broker,
                    quantity, rate, amount)
                   values (?,?,?,?,?,?,?,?)""",
                [(d.isoformat(), r.get("transaction_no"), r.get("symbol"),
                  r.get("buyer_broker"), r.get("seller_broker"),
                  r.get("quantity"), r.get("rate"), r.get("amount"))
                 for r in rows],
            )

    # ---- reading back (for verification) ---------------------------------

    def read_prices(self, d: date) -> list[dict]:
        rows = self.conn.execute(
            "select symbol, ltp, pct_change, high, low, open, qty, trend "
            "from prices where trade_date = ?", (d.isoformat(),)
        ).fetchall()
        return [dict(r) for r in rows]

    def read_floorsheet(self, d: date) -> list[dict]:
        rows = self.conn.execute(
            "select transaction_no, symbol, buyer_broker, seller_broker, "
            "quantity, rate, amount from floorsheet where trade_date = ?", (d.isoformat(),)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- manifest ----------------------------------------------------------

    def write_manifest(self, dataset: str, d: date, row_count: int, checksum: str,
                        verified: bool, archive_path: str | None) -> None:
        with self.conn:
            self.conn.execute(
                """insert into archive_manifest
                       (dataset, trade_date, row_count, checksum, archive_path,
                        archived_at, verified, supabase_deleted)
                   values (?,?,?,?,?,?,?,0)
                   on conflict(dataset, trade_date) do update set
                       row_count = excluded.row_count,
                       checksum = excluded.checksum,
                       archive_path = excluded.archive_path,
                       archived_at = excluded.archived_at,
                       verified = excluded.verified
                       -- supabase_deleted is deliberately NOT reset here: re-archiving
                       -- a date (e.g. a later correction) must not un-delete history
                       -- that a human should decide about explicitly.
                """,
                (dataset, d.isoformat(), row_count, checksum, archive_path,
                 datetime.now(timezone.utc).isoformat(), int(verified)),
            )

    def get_manifest(self, dataset: str, d: date) -> dict | None:
        row = self.conn.execute(
            "select * from archive_manifest where dataset = ? and trade_date = ?",
            (dataset, d.isoformat()),
        ).fetchone()
        return dict(row) if row else None

    def verified_dates_not_yet_deleted(self, dataset: str, before: date) -> list[date]:
        rows = self.conn.execute(
            """select trade_date from archive_manifest
               where dataset = ? and verified = 1 and supabase_deleted = 0
                 and trade_date < ?
               order by trade_date""",
            (dataset, before.isoformat()),
        ).fetchall()
        return [date.fromisoformat(r["trade_date"]) for r in rows]

    def mark_supabase_deleted(self, dataset: str, d: date) -> None:
        with self.conn:
            self.conn.execute(
                "update archive_manifest set supabase_deleted = 1 "
                "where dataset = ? and trade_date = ?",
                (dataset, d.isoformat()),
            )


def verify_against_raw(db: ArchiveDB, dataset: str, d: date, raw_rows: list[dict]) -> tuple[bool, str, int]:
    """Compares what's in the DB for this date against the raw rows just written
    to disk. Returns (verified, checksum, row_count). checksum is of the DB's
    content -- if it doesn't match the raw file's own checksum, callers should
    treat the day as unverified regardless of what this function returns."""
    if dataset == "daily_prices":
        db_rows = db.read_prices(d)
        db_sum, raw_sum = checksum_prices(db_rows), checksum_prices(raw_rows)
    elif dataset == "floorsheet":
        db_rows = db.read_floorsheet(d)
        db_sum, raw_sum = checksum_floorsheet(db_rows), checksum_floorsheet(raw_rows)
    else:
        raise ValueError(f"unknown dataset {dataset!r}")

    ok = db_sum == raw_sum and len(db_rows) == len(raw_rows)
    return ok, db_sum, len(db_rows)
