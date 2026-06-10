"""Refresh BigQuery reporting marts + Looker Studio views — without re-syncing.

The reporting views (e.g. ``vw_looker_meta_ads_wide`` /
``vw_looker_google_ads_wide``) and summary tables are normally (re)created as a
best-effort step after a sync. When a NEW view is added to ``SUMMARY_SQL_PATHS``
it does not exist in BigQuery until the SQL runs once. This entrypoint runs that
SQL on demand — no ad-platform API calls, no new data fetched — so newly added
views appear immediately:

    GCP_PROJECT_ID=oudseed BIGQUERY_DATASET=ads_pipeline \
        .venv/bin/python -m src.refresh_marts

It is idempotent (every statement is CREATE OR REPLACE / rebuild-from-unified),
so it is safe to re-run.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from src.destinations.bigquery import BigQueryDestination
from src.main import SUMMARY_SQL_PATHS, _log, refresh_reporting_marts


def main() -> None:
    """Refresh all reporting marts/views using BigQuery settings from the env."""
    load_dotenv()
    project_id = os.getenv("GCP_PROJECT_ID")
    dataset_id = os.getenv("BIGQUERY_DATASET")
    if not project_id:
        raise ValueError("GCP project id is required via GCP_PROJECT_ID.")
    if not dataset_id:
        raise ValueError("BigQuery dataset is required via BIGQUERY_DATASET.")

    destination = BigQueryDestination(project_id=project_id, dataset_id=dataset_id)
    _log(
        "refresh_marts_started",
        project_id=project_id,
        dataset_id=dataset_id,
        sql_files=len(SUMMARY_SQL_PATHS),
    )
    refresh_reporting_marts(destination=destination)
    _log("refresh_marts_finished")


if __name__ == "__main__":
    main()
