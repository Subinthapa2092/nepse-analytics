"""
Step 8, done the safe way agreed on:

    archive verified?
        -> yes: check archived row_count matches what's actually in Supabase
            -> matches: DELETE
                -> verify Supabase now has 0 rows for that date
                    -> yes: mark_supabase_deleted, log success
                    -> no:  do NOT mark_supabase_deleted, log failure (delete
                            may have partially failed -- next run retries it,
                            since it's still "verified but not yet deleted")
            -> row_count mismatch: log failure, do NOT delete (the archive may
               be verified-but-stale, e.g. Supabase got a late correction
               after archiving -- a human should look, not the script)
        -> no (unverified or no manifest row at all): skip silently -- this
           date just isn't eligible for deletion yet; the daily job's next
           successful archive run will make it eligible

Nothing here ever deletes a date that isn't BOTH verified in the manifest AND
count-matched against Supabase immediately before deleting.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from archive.store import ArchiveDB

# One entry per Supabase table this cleanup knows how to handle. date_column is
# the column to filter/group on; count_query and delete_query take one %s param
# (the date, as 'YYYY-MM-DD' text) via psycopg2's parameter substitution.
DATASETS = {
    "daily_prices": dict(
        table="daily_prices",
        count_sql="select count(*) from daily_prices where fetched_at::date = %s",
        delete_sql="delete from daily_prices where fetched_at::date = %s",
    ),
    "floorsheet": dict(
        table="broker_daily_summary",
        count_sql="select count(*) from broker_daily_summary where trade_date = %s",
        delete_sql="delete from broker_daily_summary where trade_date = %s",
    ),
}


@dataclass
class CleanupResult:
    date: date
    action: str      # "deleted" | "skipped_unverified" | "skipped_count_mismatch" | "delete_incomplete"
    detail: str = ""


def cleanup_old_data(db: ArchiveDB, conn, dataset: str, keep_days: int = 365,
                      dry_run: bool = False) -> list[CleanupResult]:
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}")
    cfg = DATASETS[dataset]
    cutoff = date.today() - timedelta(days=keep_days)

    results: list[CleanupResult] = []
    candidates = db.verified_dates_not_yet_deleted(dataset, before=cutoff)

    for d in candidates:
        manifest = db.get_manifest(dataset, d)
        archived_count = manifest["row_count"]

        with conn.cursor() as cur:
            cur.execute(cfg["count_sql"], (d.isoformat(),))
            supabase_count = cur.fetchone()[0]

        if supabase_count == 0:
            # Already gone (e.g. a previous run's delete succeeded but the mark
            # failed) -- safe to just mark it, nothing to delete.
            if not dry_run:
                db.mark_supabase_deleted(dataset, d)
            results.append(CleanupResult(d, "deleted", "already absent from Supabase"))
            continue

        if supabase_count != archived_count:
            results.append(CleanupResult(
                d, "skipped_count_mismatch",
                f"archive has {archived_count} rows, Supabase currently has "
                f"{supabase_count} -- not deleting; needs a human look"))
            continue

        if dry_run:
            results.append(CleanupResult(d, "deleted", f"[dry run] would delete {supabase_count} rows"))
            continue

        with conn:
            with conn.cursor() as cur:
                cur.execute(cfg["delete_sql"], (d.isoformat(),))
            with conn.cursor() as verify_cur:
                verify_cur.execute(cfg["count_sql"], (d.isoformat(),))
                remaining = verify_cur.fetchone()[0]

        if remaining == 0:
            db.mark_supabase_deleted(dataset, d)
            results.append(CleanupResult(d, "deleted", f"removed {supabase_count} rows, verified 0 remain"))
        else:
            results.append(CleanupResult(
                d, "delete_incomplete",
                f"deleted but {remaining} rows still present -- NOT marked deleted, will retry next run"))

    return results
