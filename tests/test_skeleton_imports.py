"""Smoke tests for the initial project skeleton."""

from src.connectors.base import BaseAdsConnector
from src.connectors.meta_ads import MetaAdsConnector
from src.destinations.bigquery import BigQueryDestination


def test_skeleton_imports() -> None:
    """Core modules can be imported."""
    assert BaseAdsConnector is not None
    assert MetaAdsConnector.platform_name == "meta_ads"


def test_bigquery_destination_placeholder() -> None:
    """BigQuery destination placeholder stores constructor values."""
    destination = BigQueryDestination(project_id="oudseed", dataset_id="ads_pipeline")

    assert destination.project_id == "oudseed"
    assert destination.dataset_id == "ads_pipeline"
