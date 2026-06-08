"""Tests for the ad-platform connect flow (Meta / Google Ads).

Uses fake OAuth clients, a temp SQLite DB, and a generated encryption key, so no
network calls or real credentials are needed.
"""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.storage.crypto import generate_key
from src.storage.db import build_session_factory, create_all, create_db_engine
from src.storage.models import PlatformConnection
from src.storage.repository import read_connection_token
from src.web.ad_oauth import (
    GOOGLE_ADS_API_VERSION,
    AdAccount,
    AdConnectionResult,
    GoogleAdsOAuthClient,
    summarize_oauth_http_error,
)
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


class FakeFailingGoogleAdsOAuth(FakeGoogleAdsOAuth):
    """Simulates the Google Ads API rejecting listAccessibleCustomers."""

    def fetch_connection(self, code: str) -> AdConnectionResult:
        request = httpx.Request("GET", "https://googleads.example/customers")
        response = httpx.Response(
            403,
            json={"error": {"status": "PERMISSION_DENIED", "message": "Developer token is not approved."}},
            request=request,
        )
        raise httpx.HTTPStatusError("403", request=request, response=response)


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
    assert resp.status_code == 303

    conns = _all_connections(ctx.factory)
    assert len(conns) == 2
    assert {c.external_account_id for c in conns} == {"act_111", "act_222"}
    for c in conns:
        assert c.platform == "meta_ads"
        # Newly connected accounts start unselected (paused), not auto-synced.
        assert c.status == "paused"
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
    assert resp.status_code == 303

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


def test_dashboard_lists_connected_accounts_with_checkboxes(ctx):
    _sign_in(ctx.client)
    _connect(ctx.client, start_path="/connect/meta/start", callback_path="/oauth/meta/callback")
    home = ctx.client.get("/")
    assert "Acct One" in home.text and "Acct Two" in home.text
    assert "type='checkbox'" in home.text
    assert "Select accounts to sync" in home.text
    # Accounts start unselected and a "Select all" toggle is offered.
    assert "Select all" in home.text
    assert " checked>" not in home.text  # no checkbox is pre-checked


def test_account_selection_marks_active_and_paused(ctx):
    _sign_in(ctx.client)
    _connect(ctx.client, start_path="/connect/meta/start", callback_path="/oauth/meta/callback")
    # Keep only act_111 selected.
    ctx.client.post("/accounts/select", data={"platform": "meta_ads", "account": ["act_111"]})
    by_id = {c.external_account_id: c.status for c in _all_connections(ctx.factory)}
    assert by_id["act_111"] == "active"
    assert by_id["act_222"] == "paused"


def test_account_selection_requires_sign_in(ctx):
    resp = ctx.client.post(
        "/accounts/select",
        data={"platform": "meta_ads", "account": ["act_111"]},
        follow_redirects=False,
    )
    assert resp.status_code == 401


def test_connect_api_error_shows_readable_page_not_500(ctx):
    ctx.client.app.dependency_overrides[get_google_ads_oauth] = FakeFailingGoogleAdsOAuth
    _sign_in(ctx.client)
    resp = _connect(
        ctx.client,
        start_path="/connect/google-ads/start",
        callback_path="/oauth/google-ads/callback",
    )
    # Not a raw 500; a friendly page that names the platform and the reason.
    assert resp.status_code == 502
    assert "Couldn't connect Google Ads" in resp.text
    assert "Developer token is not approved." in resp.text
    # And nothing was persisted from the failed attempt.
    assert _all_connections(ctx.factory) == []


def test_google_ads_client_builds_endpoint_from_version():
    client = GoogleAdsOAuthClient("id", "secret", "uri", "devtoken", api_version="v22")
    assert client.list_customers_endpoint == (
        "https://googleads.googleapis.com/v22/customers:listAccessibleCustomers"
    )


def test_google_ads_default_version_is_not_sunset():
    # v20 and earlier are sunset by mid-2026 and 404; guard against regressing.
    assert GOOGLE_ADS_API_VERSION not in {"v17", "v18", "v19", "v20"}
    assert GOOGLE_ADS_API_VERSION.startswith("v")


def test_settings_read_google_ads_api_version_env(monkeypatch):
    from src.web.config import load_web_settings

    monkeypatch.setenv("GOOGLE_ADS_API_VERSION", "v23")
    assert load_web_settings().google_ads_api_version == "v23"


def _select_meta(client, factory, external_ids):
    _sign_in(client)
    _connect(client, start_path="/connect/meta/start", callback_path="/oauth/meta/callback")
    client.post("/accounts/select", data={"platform": "meta_ads", "account": external_ids})


def test_dashboard_shows_destination_step_after_selection(ctx):
    _select_meta(ctx.client, ctx.factory, ["act_111"])
    home = ctx.client.get("/")
    assert "Choose destination" in home.text
    # Multi-select destination cards + the independent AI email opt-in.
    assert "name='destination'" in home.text
    assert "BigQuery" in home.text and "Data Studio" in home.text and "Google Sheets" in home.text
    assert "AI report email" in home.text


def test_destination_save_persists_destinations_and_schedule(ctx):
    from src.storage.models import Client, ClientDestination, ReportSchedule
    from src.storage.repository import read_schedule_email_to

    _select_meta(ctx.client, ctx.factory, ["act_111"])
    resp = ctx.client.post(
        "/destination/save",
        data={
            "destination": ["bigquery", "data_studio"],
            "enabled": "on",
            "report_type": "monthly",
            "monthly_day": "10",
            "weekly_day": "monday",
            "depth": "deep",
            "email_to": "owner@example.com",
            "timezone": "Asia/Taipei",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    with ctx.factory() as session:
        client = session.scalars(select(Client)).one()
        dests = {
            d.kind: d.enabled
            for d in session.scalars(select(ClientDestination))
        }
        assert dests == {"bigquery": True, "data_studio": True}
        schedule = session.scalars(select(ReportSchedule)).one()
        assert schedule.client_id == client.id
        assert schedule.enabled is True
        assert schedule.report_type == "monthly"
        assert schedule.delivery_day == "10"
        assert schedule.depth == "deep"
        # Recipient email is encrypted at rest but decrypts back.
        assert "owner@example.com" not in (schedule.encrypted_email_to or "")
        assert read_schedule_email_to(schedule) == "owner@example.com"

    # Re-saving updates in place (idempotent), toggling email off and dropping one dest.
    ctx.client.post(
        "/destination/save",
        data={"destination": ["bigquery"], "report_type": "weekly", "weekly_day": "friday"},
        follow_redirects=False,
    )
    with ctx.factory() as session:
        dests = {
            d.kind: d.enabled
            for d in session.scalars(select(ClientDestination))
        }
        assert dests == {"bigquery": True, "data_studio": False}
        schedule = session.scalars(select(ReportSchedule)).one()
        assert schedule.enabled is False
        assert schedule.report_type == "weekly"
        assert schedule.delivery_day == "friday"


def test_destination_save_requires_sign_in(ctx):
    resp = ctx.client.post(
        "/destination/save",
        data={"destination": ["bigquery"]},
        follow_redirects=False,
    )
    assert resp.status_code == 401


def test_summarize_oauth_http_error_shapes():
    req = httpx.Request("GET", "https://x.example")
    # OAuth token endpoint shape
    token_err = httpx.HTTPStatusError(
        "400",
        request=req,
        response=httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "Bad code"}, request=req
        ),
    )
    assert summarize_oauth_http_error(token_err) == "invalid_grant: Bad code"
    # Google Ads API shape
    api_err = httpx.HTTPStatusError(
        "403",
        request=req,
        response=httpx.Response(
            403,
            json={"error": {"status": "PERMISSION_DENIED", "message": "Not approved"}},
            request=req,
        ),
    )
    assert summarize_oauth_http_error(api_err) == "PERMISSION_DENIED — Not approved"
    # Non-JSON body falls back to status code
    plain_err = httpx.HTTPStatusError(
        "500", request=req, response=httpx.Response(500, text="oops", request=req)
    )
    assert summarize_oauth_http_error(plain_err) == "HTTP 500"
