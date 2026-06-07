"""Tests for the ad-platform connect flow (Meta / Google Ads).

Uses fake OAuth clients, a temp SQLite DB, and a generated encryption key, so no
network calls or real credentials are needed.
"""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.storage.crypto import generate_key
from src.storage.db import build_session_factory, create_all, create_db_engine
from src.storage.models import PlatformConnection
from src.storage.repository import read_connection_token
from src.web.ad_oauth import AdAccount, AdConnectionResult
from src.web.app import create_app
from src.web.deps import get_db, get_google_ads_oauth, get_google_oauth, get_meta_ads_oauth
from src.web.oauth import GoogleUser


class FakeSigninOAuth:
    def authorization_url(self, state: str) -> str:
        return f"https://accounts.example/auth?state={state}"

    def exchange_code(self, code: str) -> dict:
        return {"access_token": "fake"}

    def fetch_userinfo(self, access_token: str) -> GoogleUser:
        return GoogleUser(sub="g-1", email="mark@example.com", name="Mark")


class FakeMetaOAuth:
    platform = "meta_ads"

    def authorization_url(self, state: str) -> str:
        return f"https://meta.example/auth?state={state}"

    def fetch_connection(self, code: str) -> AdConnectionResult:
        return AdConnectionResult(
            secret="meta-long-token",
            scopes="ads_read",
            accounts=[AdAccount("act_111", "Acct One"), AdAccount("act_222", "Acct Two")],
        )


class FakeGoogleAdsOAuth:
    platform = "google_ads"

    def authorization_url(self, state: str) -> str:
        return f"https://g.example/auth?state={state}"

    def fetch_connection(self, code: str) -> AdConnectionResult:
        return AdConnectionResult(
            secret="ga-refresh-token",
            scopes="adwords",
            accounts=[AdAccount("1234567890", "Google Ads 1234567890")],
        )


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    engine = create_db_engine(f"sqlite:///{tmp_path}/web.db")
    create_all(engine)
    factory = build_session_factory(engine)

    def _get_db():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app = create_app()
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_google_oauth] = FakeSigninOAuth
    app.dependency_overrides[get_meta_ads_oauth] = FakeMetaOAuth
    app.dependency_overrides[get_google_ads_oauth] = FakeGoogleAdsOAuth
    return SimpleNamespace(client=TestClient(app), factory=factory)


def _sign_in(client):
    resp = client.get("/auth/google/login", follow_redirects=False)
    state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
    client.get(f"/oauth/google/callback?code=c&state={state}", follow_redirects=False)


def _connect(client, *, start_path: str, callback_path: str):
    resp = client.get(start_path, follow_redirects=False)
    assert resp.status_code == 307
    state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
    return client.get(f"{callback_path}?code=x&state={state}", follow_redirects=False)


def _all_connections(factory):
    with factory() as session:
        return list(session.scalars(select(PlatformConnection)))


def test_connect_requires_sign_in(ctx):
    assert ctx.client.get("/connect/meta/start", follow_redirects=False).status_code == 401


def test_meta_connect_creates_encrypted_connections(ctx):
    _sign_in(ctx.client)
    resp = _connect(
        ctx.client, start_path="/connect/meta/start", callback_path="/oauth/meta/callback"
    )
    assert resp.status_code == 307

    conns = _all_connections(ctx.factory)
    assert len(conns) == 2
    assert {c.external_account_id for c in conns} == {"act_111", "act_222"}
    for c in conns:
        assert c.platform == "meta_ads"
        assert c.status == "active"
        assert "meta-long-token" not in (c.encrypted_token or "")  # encrypted at rest
        assert read_connection_token(c) == "meta-long-token"

    home = ctx.client.get("/")
    assert "Acct One" in home.text and "Acct Two" in home.text


def test_google_ads_connect_creates_connection(ctx):
    _sign_in(ctx.client)
    resp = _connect(
        ctx.client,
        start_path="/connect/google-ads/start",
        callback_path="/oauth/google-ads/callback",
    )
    assert resp.status_code == 307

    conns = _all_connections(ctx.factory)
    assert len(conns) == 1
    assert conns[0].platform == "google_ads"
    assert conns[0].external_account_id == "1234567890"
    assert read_connection_token(conns[0]) == "ga-refresh-token"


def test_connect_rejects_bad_state(ctx):
    _sign_in(ctx.client)
    ctx.client.get("/connect/meta/start", follow_redirects=False)  # sets state
    resp = ctx.client.get(
        "/oauth/meta/callback?code=x&state=WRONG", follow_redirects=False
    )
    assert resp.status_code == 400


def test_reconnect_is_idempotent(ctx):
    _sign_in(ctx.client)
    _connect(ctx.client, start_path="/connect/meta/start", callback_path="/oauth/meta/callback")
    _connect(ctx.client, start_path="/connect/meta/start", callback_path="/oauth/meta/callback")
    # Re-authorizing the same accounts updates in place, not duplicates.
    assert len(_all_connections(ctx.factory)) == 2
