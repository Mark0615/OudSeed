"""Web app settings sourced from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from src.web import ad_oauth


@dataclass(frozen=True)
class WebSettings:
    """Runtime settings for the FastAPI app."""

    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    session_secret: str
    app_base_url: str
    database_url: str
    # Ad-platform connect (Phase 3 slice 2)
    meta_app_id: str
    meta_app_secret: str
    meta_redirect_uri: str
    google_ads_redirect_uri: str
    google_ads_developer_token: str
    google_ads_api_version: str
    # BigQuery (for the onboarding data preview). Empty when not configured.
    bigquery_project: str
    bigquery_dataset: str


def load_web_settings() -> WebSettings:
    """Load web settings from the environment (with sensible local defaults)."""
    return WebSettings(
        google_client_id=os.getenv("GOOGLE_OAUTH_CLIENT_ID", ""),
        google_client_secret=os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", ""),
        google_redirect_uri=os.getenv(
            "GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8765/oauth/google/callback"
        ),
        # Falls back to a dev value so local runs/tests work; production must set it.
        session_secret=os.getenv("SESSION_SECRET", "dev-insecure-session-secret"),
        app_base_url=os.getenv("APP_BASE_URL", "http://localhost:8765"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///.local/oudseed.db"),
        meta_app_id=os.getenv("META_APP_ID", ""),
        meta_app_secret=os.getenv("META_APP_SECRET", ""),
        meta_redirect_uri=os.getenv(
            "META_OAUTH_REDIRECT_URI", "http://localhost:8765/oauth/meta/callback"
        ),
        google_ads_redirect_uri=os.getenv(
            "GOOGLE_ADS_OAUTH_REDIRECT_URI", "http://localhost:8765/oauth/google-ads/callback"
        ),
        google_ads_developer_token=os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", ""),
        google_ads_api_version=os.getenv(
            "GOOGLE_ADS_API_VERSION", ad_oauth.GOOGLE_ADS_API_VERSION
        ),
        bigquery_project=os.getenv("GCP_PROJECT_ID", ""),
        bigquery_dataset=os.getenv("BIGQUERY_DATASET", ""),
    )
