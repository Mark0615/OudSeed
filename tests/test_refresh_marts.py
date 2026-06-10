"""Tests for the standalone reporting-marts refresh entrypoint (offline)."""

from __future__ import annotations

import pytest

import src.refresh_marts as refresh_marts
from src.main import SUMMARY_SQL_PATHS


class FakeDestination:
    def __init__(self):
        self.statements: list[str] = []

    def execute_sql(self, sql: str) -> None:
        self.statements.append(sql)


def test_main_refreshes_every_summary_sql(monkeypatch):
    """Running the CLI executes one statement per configured SQL file."""
    dest = FakeDestination()
    captured = {}

    def fake_destination(*, project_id, dataset_id):
        captured["project_id"] = project_id
        captured["dataset_id"] = dataset_id
        return dest

    monkeypatch.setenv("GCP_PROJECT_ID", "proj")
    monkeypatch.setenv("BIGQUERY_DATASET", "ds")
    monkeypatch.setattr(refresh_marts, "BigQueryDestination", fake_destination)
    monkeypatch.setattr(refresh_marts, "load_dotenv", lambda: None)

    refresh_marts.main()

    assert captured == {"project_id": "proj", "dataset_id": "ds"}
    # One executed statement per reporting SQL file, incl. both wide views.
    assert len(dest.statements) == len(SUMMARY_SQL_PATHS)
    joined = "\n".join(dest.statements)
    assert "vw_looker_meta_ads_wide" in joined
    assert "vw_looker_google_ads_wide" in joined


def test_main_requires_bigquery_env(monkeypatch):
    """Missing BigQuery settings fail loudly instead of silently no-op'ing."""
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("BIGQUERY_DATASET", raising=False)
    monkeypatch.setattr(refresh_marts, "load_dotenv", lambda: None)

    with pytest.raises(ValueError, match="GCP project id is required"):
        refresh_marts.main()
