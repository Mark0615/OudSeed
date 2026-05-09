"""Tests for Meta Ads normalization."""

import json
from pathlib import Path

import pytest

from src.transforms.normalize_meta import normalize_meta_ads_rows


def load_fixture() -> list[dict]:
    """Load sample Meta raw rows."""
    fixture_path = Path("tests/fixtures/meta_ads_raw_sample.json")
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def default_context() -> dict:
    """Return normalization context for tests."""
    return {
        "workspace_id": "mark_internal",
        "client_id": "demo_client_001",
        "account_id": "act_000000000000000",
        "account_name": "Fallback Account",
        "conversion_action_type": "purchase",
    }


def test_normalize_meta_ads_rows_maps_unified_schema() -> None:
    """Meta fields map into unified_ads_daily shape."""
    rows = normalize_meta_ads_rows(load_fixture(), default_context())

    assert len(rows) == 1
    row = rows[0]
    assert row["date"] == "2026-05-03"
    assert row["workspace_id"] == "mark_internal"
    assert row["client_id"] == "demo_client_001"
    assert row["platform"] == "meta_ads"
    assert row["account_id"] == "act_000000000000000"
    assert row["account_name"] == "Demo Meta Ads Account"
    assert row["campaign_id"] == "campaign_001"
    assert row["ad_group_id"] == "adset_001"
    assert row["ad_group_name"] == "Prospecting"
    assert row["ad_id"] == "ad_001"
    assert row["impressions"] == 1000
    assert row["clicks"] == 40
    assert row["spend"] == 250.5
    assert row["conversions"] == 5.0
    assert row["conversion_value"] == 1500.0
    assert row["add_to_cart"] == 12.0
    assert row["purchase"] == 5.0
    assert row["purchase_value"] == 1500.0
    assert row["cost_per_add_to_cart"] == 20.875
    assert row["cost_per_purchase"] == 50.1
    assert row["outbound_clicks"] == 35
    assert row["page_engagement"] == 90.0
    assert row["post_engagement"] == 80.0
    assert row["post_reactions"] == 20.0
    assert row["post_comments"] == 3.0
    assert row["post_saves"] == 4.0
    assert row["post_shares"] == 2.0
    assert row["currency"] == "TWD"
    assert row["source_updated_at"] is None
    assert row["created_at"]
    assert row["updated_at"]


def test_normalize_meta_ads_rows_calculates_metrics() -> None:
    """Derived metrics are calculated from numeric fields."""
    row = normalize_meta_ads_rows(load_fixture(), default_context())[0]

    assert row["ctr"] == 0.04
    assert row["cpc"] == 250.5 / 40
    assert row["cpm"] == 250.5
    assert row["cpa"] == 50.1
    assert row["roas"] == 1500.0 / 250.5


def test_normalize_meta_ads_rows_handles_zero_denominators() -> None:
    """Division by zero returns None for derived metrics."""
    raw_rows = [
        {
            "date_start": "2026-05-03",
            "impressions": "0",
            "clicks": "0",
            "spend": "0",
            "actions": [{"action_type": "purchase", "value": "0"}],
            "action_values": [{"action_type": "purchase", "value": "0"}],
        }
    ]

    row = normalize_meta_ads_rows(raw_rows, default_context())[0]

    assert row["ctr"] is None
    assert row["cpc"] is None
    assert row["cpm"] is None
    assert row["cpa"] is None
    assert row["roas"] is None


def test_normalize_meta_ads_rows_supports_configurable_conversion_action() -> None:
    """Conversion action type is selected from context."""
    raw_rows = [
        {
            "date_start": "2026-05-03",
            "impressions": "10",
            "clicks": "2",
            "spend": "20",
            "actions": [{"action_type": "lead", "value": "3"}],
            "action_values": [{"action_type": "lead", "value": "90"}],
        }
    ]
    context = {**default_context(), "conversion_action_type": "lead"}

    row = normalize_meta_ads_rows(raw_rows, context)[0]

    assert row["conversions"] == 3.0
    assert row["conversion_value"] == 90.0


def test_normalize_meta_ads_rows_uses_action_aliases_and_cost_fallbacks() -> None:
    """Common Meta action aliases are expanded for reporting."""
    raw_rows = [
        {
            "date_start": "2026-05-03",
            "impressions": "10",
            "inline_link_clicks": "2",
            "spend": "30",
            "actions": [
                {"action_type": "omni_add_to_cart", "value": "3"},
                {"action_type": "omni_purchase", "value": "2"},
            ],
            "action_values": [{"action_type": "omni_purchase", "value": "120"}],
        }
    ]

    row = normalize_meta_ads_rows(raw_rows, default_context())[0]

    assert row["add_to_cart"] == 3.0
    assert row["purchase"] == 2.0
    assert row["purchase_value"] == 120.0
    assert row["cost_per_add_to_cart"] == 10.0
    assert row["cost_per_purchase"] == 15.0


def test_normalize_meta_ads_rows_requires_context_fields() -> None:
    """Required context fields fail loudly."""
    with pytest.raises(ValueError, match="workspace_id"):
        normalize_meta_ads_rows([], {"client_id": "demo", "account_id": "act_123"})
