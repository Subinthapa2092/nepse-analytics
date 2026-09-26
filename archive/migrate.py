"""
One-time migration: archive the raw floorsheet files your scraper ALREADY wrote
to data/raw/floorsheet/*.csv.gz (via the old backfill.py's _write_raw, before
the archive/ package existed) into the verified local SQLite archive.

This does NOT re-scrape anything and does NOT write a second copy of each raw
file -- it loads the EXISTING file, verifies it, and records it in the manifest
at its existing path. Only after a date is verified here is it safe to delete
that date's rows from Supabase (see cleanup_run.py).

Deliberately separate from archive.pipeline.archive_and_verify(), which is for
NEW days going forward and always writes a fresh raw file -- migrating old days
should never duplicate storage for files that already exist.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from archive.canonical import checksum_floorsheet
from archive.raw_store import read_raw_csv_gz
from archive.store import ArchiveDB


def migrate_existing_floorsheet_day(db: ArchiveDB, raw_path: Path, d: date) -> dict:
    """Loads an EXISTING raw floorsheet file into the archive, verifies it, and
    writes the manifest row pointing at that existing path. Returns the same
    shape as archive.pipeline.archive_and_verify()'s result dict."""
    if not raw_path.exists():
        result = {"verified": False, "row_count": 0, "checksum": "", "path": str(raw_path),
                   "error": f"raw file not found: {raw_path}"}
        db.write_manifest("floorsheet", d, 0, "", False, str(raw_path))
        return result

    try:
        raw_rows = read_raw_csv_gz(raw_path)
    except Exception as e:
        result = {"verified": False, "row_count": 0, "checksum": "", "path": str(raw_path),
                   "error": f"couldn't read existing raw file: {e}"}
        db.write_manifest("floorsheet", d, 0, "", False, str(raw_path))
        return result

    if not raw_rows:
        result = {"verified": False, "row_count": 0, "checksum": "", "path": str(raw_path),
                   "error": "raw file is empty"}
        db.write_manifest("floorsheet", d, 0, "", False, str(raw_path))
        return result

    db.load_floorsheet(d, raw_rows)
    db_rows = db.read_floorsheet(d)

    db_sum = checksum_floorsheet(db_rows)
    raw_sum = checksum_floorsheet(raw_rows)
    ok = db_sum == raw_sum and len(db_rows) == len(raw_rows)

    db.write_manifest("floorsheet", d, len(db_rows), db_sum, ok, str(raw_path))

    error = None if ok else (
        f"checksum/row-count mismatch: raw file has {len(raw_rows)} rows, "
        f"loaded database has {len(db_rows)} rows -- NOT marked verified"
    )
    return {"verified": ok, "row_count": len(db_rows), "checksum": db_sum,
            "path": str(raw_path), "error": error}
