"""Tests for Google Ads normalization."""

from src.transforms.normalize_google import normalize_google_ads_rows


def test_normalize_google_ads_rows_writes_ad_rows_only() -> None:
    """Google Ads keyword rows stay out of unified totals."""
    rows = [
        {
            "date": "2026-04-01",
            "report_level": "ad",
            "account_name": "Demo Google",
            "campaign_id": "campaign_1",
            "campaign_name": "Search",
            "ad_group_id": "ad_group_1",
            "ad_group_name": "Brand",
            "ad_id": "ad_1",
            "ad_name": "Brand Ad",
            "impressions": 100,
            "clicks": 10,
            "spend": 50.0,
            "conversions": 2.0,
            "conversion_value": 500.0,
            "currency": "TWD",
        },
        {
            "date": "2026-04-01",
            "report_level": "keyword",
            "keyword_text": "brand keyword",
            "impressions": 100,
            "clicks": 10,
            "spend": 50.0,
        },
    ]

    normalized = normalize_google_ads_rows(
        rows,
        context={
            "workspace_id": "mark_internal",
            "client_id": "demo_client_001",
            "account_id": "1234567890",
            "account_name": "Demo Google",
        },
    )

    assert len(normalized) == 1
    assert normalized[0]["platform"] == "google_ads"
    assert normalized[0]["campaign_name"] == "Search"
    assert normalized[0]["ad_group_name"] == "Brand"
    assert normalized[0]["ad_name"] == "Brand Ad"
    assert normalized[0]["purchase"] == 2.0
    assert normalized[0]["purchase_value"] == 500.0
    assert normalized[0]["cpc"] == 5.0
    assert normalized[0]["roas"] == 10.0
