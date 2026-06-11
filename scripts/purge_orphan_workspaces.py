"""Reconcile BigQuery against the app DB: purge rows for dead workspaces.

Earlier local/test runs wrote into the *shared* BigQuery tables under
``workspace_id``s that only ever existed in a local SQLite database. After moving
to the cloud (Cloud SQL / Neon) the app uses a *new* workspace id, so those old
rows are **orphans**: they belong to no live workspace, and because the wide
Looker views are not workspace-scoped they double-count and inflate metrics
(spend, ROAS, …) — which makes validation against another tool fail.

This script treats the **app database as the source of truth**: any BigQuery row
whose ``workspace_id`` is not a live workspace in the app DB is an orphan and gets
removed from the raw + unified tables, after which the reporting marts/views are
refreshed so they recompute cleanly.

Safety:
  * DRY-RUN by default — only prints how many rows *would* be deleted. Pass
    ``--apply`` to actually delete.
  * Refuses to run if the app DB reports **zero** live workspaces (that would mean
    "delete everything" — almost certainly a misconfiguration).
  * Prints counts only — never workspace/account ids.

Usage:
  .venv/bin/python scripts/purge_orphan_workspaces.py            # dry-run
  .venv/bin/python scripts/purge_orphan_workspaces.py --apply    # delete + refresh
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow running as a plain script (python scripts/purge_orphan_workspaces.py):
# put the repo root on sys.path so `import src...` works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

TABLES = ("raw_meta_ads_daily", "raw_google_ads_daily", "unified_ads_daily")


def _live_workspace_ids() -> list[str]:
    """Return the workspace ids that currently exist in the app database."""
    from sqlalchemy import text

    from src.storage.db import create_db_engine

    engine = create_db_engine()
    with engine.connect() as conn:
        return [row[0] for row in conn.execute(text("SELECT id FROM workspaces"))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="actually delete (default is dry-run)"
    )
    args = parser.parse_args()

    load_dotenv()
    project_id = os.getenv("GCP_PROJECT_ID")
    dataset_id = os.getenv("BIGQUERY_DATASET")
    if not project_id or not dataset_id:
        print("Missing GCP_PROJECT_ID / BIGQUERY_DATASET.", file=sys.stderr)
        return 2

    live_ids = _live_workspace_ids()
    if not live_ids:
        print(
            "Refusing to run: the app database has 0 workspaces, so every BigQuery "
            "row would look orphaned. Check DATABASE_URL points at the right DB.",
            file=sys.stderr,
        )
        return 2
    print(f"Live workspaces in app DB: {len(live_ids)}")

    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    param = bigquery.ArrayQueryParameter("live", "STRING", live_ids)
    job_config = bigquery.QueryJobConfig(query_parameters=[param])

    total_orphans = 0
    for table in TABLES:
        fq = f"{project_id}.{dataset_id}.{table}"
        count_sql = (
            f"SELECT COUNT(*) AS n FROM `{fq}` "
            "WHERE workspace_id NOT IN UNNEST(@live)"
        )
        orphans = list(client.query(count_sql, job_config=job_config).result())[0].n
        total_orphans += orphans
        print(f"  {table}: {orphans} orphan row(s)")
        if args.apply and orphans:
            del_sql = f"DELETE FROM `{fq}` WHERE workspace_id NOT IN UNNEST(@live)"
            client.query(del_sql, job_config=job_config).result()
            print(f"    deleted {orphans} row(s) from {table}")

    if not args.apply:
        print(f"\nDRY-RUN: {total_orphans} row(s) would be deleted. Re-run with --apply.")
        return 0

    print(f"\nDeleted {total_orphans} orphan row(s). Refreshing reporting marts/views…")
    from src.destinations.bigquery import BigQueryDestination
    from src.main import refresh_reporting_marts

    refresh_reporting_marts(
        destination=BigQueryDestination(project_id=project_id, dataset_id=dataset_id)
    )
    print("Done. Wide views are now scoped to your live workspace(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
