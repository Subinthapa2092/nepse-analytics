"""
Steps 2-6 of the agreed sequence, for one (dataset, date):

    2. validate           (caller's job -- e.g. the floorsheet scraper's own
                            date-match / completeness checks -- this module
                            assumes it's being handed already-validated rows)
    3. save raw .csv.gz    (local; R2 upload is a separate, pluggable step --
                            see r2_store.py)
    4. load into SQLite
    5. verify: checksum(raw file re-read from disk) == checksum(SQLite content)
    6. write manifest row (verified True or False -- always written, so a
                            failure is recorded, not silently dropped)

Re-reading the raw file from disk in step 5 (not just checksumming the `rows`
still in memory) is deliberate: it also catches a corrupted/truncated write,
not just a mismatch between what we intended to save and what got loaded.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from archive.canonical import FLOORSHEET_FIELDS, PRICE_FIELDS
from archive.raw_store import raw_path, read_raw_csv_gz, write_raw_csv_gz
from archive.store import ArchiveDB, verify_against_raw

FIELDS = {"daily_prices": PRICE_FIELDS, "floorsheet": FLOORSHEET_FIELDS}


def archive_and_verify(db: ArchiveDB, raw_root: Path, dataset: str, d: date,
                        rows: list[dict]) -> dict:
    """Returns a result dict: {verified, row_count, checksum, path, error}."""
    if dataset not in FIELDS:
        raise ValueError(f"unknown dataset {dataset!r}")
    fields = FIELDS[dataset]

    if not rows:
        result = {"verified": False, "row_count": 0, "checksum": "", "path": None,
                   "error": "no rows given -- refusing to archive an empty day "
                            "(a real empty day is a holiday, which shouldn't reach this "
                            "function at all -- the caller should skip it upstream)"}
        db.write_manifest(dataset, d, 0, "", False, None)
        return result

    path = raw_path(raw_root, dataset, d)
    try:
        write_raw_csv_gz(path, fields, rows)
        raw_rows = read_raw_csv_gz(path)  # re-read from disk on purpose, see docstring
    except Exception as e:
        result = {"verified": False, "row_count": 0, "checksum": "", "path": str(path),
                   "error": f"raw write/read failed: {e}"}
        db.write_manifest(dataset, d, 0, "", False, str(path))
        return result

    if dataset == "daily_prices":
        db.load_prices(d, raw_rows)
    else:
        db.load_floorsheet(d, raw_rows)

    ok, checksum, row_count = verify_against_raw(db, dataset, d, raw_rows)
    db.write_manifest(dataset, d, row_count, checksum, ok, str(path))

    error = None if ok else (
        f"checksum/row-count mismatch between raw file ({len(raw_rows)} rows) "
        f"and database ({row_count} rows) for {dataset} {d} -- NOT marked verified"
    )
    return {"verified": ok, "row_count": row_count, "checksum": checksum,
            "path": str(path), "error": error}
