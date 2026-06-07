"""FastAPI dependencies: database session and OAuth client.

Both are dependency-injected so tests can override them via
``app.dependency_overrides`` without real databases or network calls.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from src.storage.db import build_session_factory, create_all, create_db_engine
from src.web.ad_oauth import GoogleAdsOAuthClient, MetaAdsOAuthClient
from src.web.config import load_web_settings
from src.web.oauth import GoogleOAuthClient


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Build (once) the session factory from DATABASE_URL.

    Tables are created via metadata for local SQLite; production uses migrations.
    """
    settings = load_web_settings()
    engine = create_db_engine(settings.database_url)
    create_all(engine)
    return build_session_factory(engine)


def get_db() -> Iterator[Session]:
    """Yield a transactional DB session (commit on success, rollback on error)."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_google_oauth() -> GoogleOAuthClient:
    """Build a Google sign-in OAuth client from settings."""
    settings = load_web_settings()
    return GoogleOAuthClient(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        redirect_uri=settings.google_redirect_uri,
    )


def get_meta_ads_oauth() -> MetaAdsOAuthClient:
    """Build a Meta Ads connect client from settings."""
    settings = load_web_settings()
    return MetaAdsOAuthClient(
        app_id=settings.meta_app_id,
        app_secret=settings.meta_app_secret,
        redirect_uri=settings.meta_redirect_uri,
    )


def get_google_ads_oauth() -> GoogleAdsOAuthClient:
    """Build a Google Ads connect client from settings (reuses the Google web client)."""
    settings = load_web_settings()
    return GoogleAdsOAuthClient(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        redirect_uri=settings.google_ads_redirect_uri,
        developer_token=settings.google_ads_developer_token,
    )
