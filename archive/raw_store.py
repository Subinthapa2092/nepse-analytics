"""
The raw .csv.gz files are the source of truth: dumb, simple, openable by any tool
in 20 years even if SQLite/DuckDB/this codebase no longer exists. Everything else
(the SQL database, R2) is a convenience layer built FROM these files, never the
other way round.
"""

from __future__ import annotations

import csv
import gzip
from datetime import date
from pathlib import Path


def raw_path(root: Path, dataset: str, d: date) -> Path:
    # data/raw/<dataset>/<year>/<dataset>-<date>.csv.gz -- year folders keep any
    # one directory from holding 10 years * ~250 files without becoming unwieldy.
    return root / dataset / str(d.year) / f"{dataset}-{d.isoformat()}.csv.gz"


def write_raw_csv_gz(path: Path, fields: list[str], rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)  # atomic on the same filesystem: never leaves a half-written file at `path`
    return path


def read_raw_csv_gz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
