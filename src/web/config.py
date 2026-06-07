"""Web app settings sourced from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WebSettings:
    """Runtime settings for the FastAPI app."""

    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    session_secret: str
    app_base_url: str
    database_url: str


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
    )
