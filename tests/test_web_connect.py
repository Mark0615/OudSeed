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
from src.web.send_now import SendNowResult


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


def _build_ctx(tmp_path) -> SimpleNamespace:
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


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    # Keep the data preview offline/deterministic: no BigQuery configured.
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("BIGQUERY_DATASET", raising=False)
    return _build_ctx(tmp_path)


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


def test_preview_shows_empty_state_when_bigquery_unconfigured(ctx):
    _select_meta(ctx.client, ctx.factory, ["act_111"])
    home = ctx.client.get("/")
    # The preview card renders with its range toggle, but shows the empty state
    # (no BigQuery configured in tests) rather than crashing.
    assert "Preview data" in home.text
    assert "Last 7 days" in home.text and "Last 30 days" in home.text
    assert "once" in home.text and "first sync" in home.text


def test_destination_tiles_use_committed_logo_files():
    from src.web.views import _ASSETS_DIR, DESTINATION_ICON_FILE, _dest_tile

    for kind, fname in DESTINATION_ICON_FILE.items():
        # The mapping must point at logo files that actually exist, so the tile
        # renders the brand logo (an <img>) instead of the letter fallback.
        assert (_ASSETS_DIR / fname).exists(), f"missing logo file: {fname}"
        assert f"/assets/{fname}" in _dest_tile(kind)


def test_preview_section_has_run_first_sync_button(ctx):
    _select_meta(ctx.client, ctx.factory, ["act_111"])
    home = ctx.client.get("/")
    assert "Run first sync" in home.text
    assert "action='/sync/run'" in home.text


def test_sync_run_requires_sign_in(ctx):
    resp = ctx.client.post("/sync/run", follow_redirects=False)
    assert resp.status_code == 401


def test_sync_run_without_selection_shows_notice(ctx):
    _sign_in(ctx.client)
    _connect(ctx.client, start_path="/connect/meta/start", callback_path="/oauth/meta/callback")
    # Connected but nothing selected for sync yet.
    resp = ctx.client.post("/sync/run")  # follows redirect to "/"
    assert "Select at least one account" in resp.text


def test_sync_run_without_bigquery_shows_notice(ctx):
    _select_meta(ctx.client, ctx.factory, ["act_111"])
    resp = ctx.client.post("/sync/run")  # follows redirect to "/"
    # No BigQuery configured in tests → friendly banner, no crash.
    assert "Data warehouse" in resp.text
    assert "banner error" in resp.text


def test_sync_run_never_500s_on_unexpected_error(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("GCP_PROJECT_ID", "proj")
    monkeypatch.setenv("BIGQUERY_DATASET", "ds")
    ctx = _build_ctx(tmp_path)

    # Make the sync blow up the way a flaky ad API / BigQuery call would.
    from src.web import first_sync as fs

    def boom(**kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(fs, "run_first_sync", boom)

    _select_meta(ctx.client, ctx.factory, ["act_111"])
    resp = ctx.client.post("/sync/run")  # follows redirect to "/"
    # Friendly banner, not a raw 500.
    assert resp.status_code == 200
    assert "banner error" in resp.text
    assert "unexpected error" in resp.text


def test_sync_run_surfaces_failure_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("GCP_PROJECT_ID", "proj")
    monkeypatch.setenv("BIGQUERY_DATASET", "ds")
    ctx = _build_ctx(tmp_path)

    from src.web import first_sync as fs
    from src.web.first_sync import AccountSyncResult, FirstSyncResult

    def fake_run(**kwargs):
        return FirstSyncResult(
            results=(
                AccountSyncResult(
                    "google_ads", "8058045945", "failed", error="PERMISSION_DENIED: token not approved"
                ),
            )
        )

    monkeypatch.setattr(fs, "run_first_sync", fake_run)

    _select_meta(ctx.client, ctx.factory, ["act_111"])
    resp = ctx.client.post("/sync/run")
    # The real reason is shown so the user can act on it.
    assert "PERMISSION_DENIED" in resp.text


def test_sync_run_refreshes_reporting_marts_on_success(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("GCP_PROJECT_ID", "proj")
    monkeypatch.setenv("BIGQUERY_DATASET", "ds")
    ctx = _build_ctx(tmp_path)

    import src.web.app as web_app
    from src.web import first_sync as fs
    from src.web.first_sync import AccountSyncResult, FirstSyncResult

    monkeypatch.setattr(web_app, "BigQueryDestination", lambda **_: object())
    monkeypatch.setattr(
        fs,
        "run_first_sync",
        lambda **_: FirstSyncResult(
            results=(AccountSyncResult("meta_ads", "act_111", "success", rows=5),)
        ),
    )
    calls: list = []
    monkeypatch.setattr(web_app, "refresh_reporting_marts", lambda **k: calls.append(k))

    _select_meta(ctx.client, ctx.factory, ["act_111"])
    resp = ctx.client.post("/sync/run")
    # A successful sync must refresh the marts so the report views see the data.
    assert resp.status_code == 200
    assert len(calls) == 1


def test_sync_run_skips_mart_refresh_when_all_accounts_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("GCP_PROJECT_ID", "proj")
    monkeypatch.setenv("BIGQUERY_DATASET", "ds")
    ctx = _build_ctx(tmp_path)

    import src.web.app as web_app
    from src.web import first_sync as fs
    from src.web.first_sync import AccountSyncResult, FirstSyncResult

    monkeypatch.setattr(web_app, "BigQueryDestination", lambda **_: object())
    monkeypatch.setattr(
        fs,
        "run_first_sync",
        lambda **_: FirstSyncResult(
            results=(AccountSyncResult("meta_ads", "act_111", "failed", error="boom"),)
        ),
    )
    calls: list = []
    monkeypatch.setattr(web_app, "refresh_reporting_marts", lambda **k: calls.append(k))

    _select_meta(ctx.client, ctx.factory, ["act_111"])
    resp = ctx.client.post("/sync/run")
    assert resp.status_code == 200
    assert calls == []  # nothing synced → nothing to refresh


def test_sync_run_mart_refresh_failure_keeps_success_banner(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("GCP_PROJECT_ID", "proj")
    monkeypatch.setenv("BIGQUERY_DATASET", "ds")
    ctx = _build_ctx(tmp_path)

    import src.web.app as web_app
    from src.web import first_sync as fs
    from src.web.first_sync import AccountSyncResult, FirstSyncResult

    monkeypatch.setattr(web_app, "BigQueryDestination", lambda **_: object())
    monkeypatch.setattr(
        fs,
        "run_first_sync",
        lambda **_: FirstSyncResult(
            results=(AccountSyncResult("meta_ads", "act_111", "success", rows=5),)
        ),
    )

    def boom(**_):
        raise RuntimeError("mart sql failed")

    monkeypatch.setattr(web_app, "refresh_reporting_marts", boom)

    _select_meta(ctx.client, ctx.factory, ["act_111"])
    resp = ctx.client.post("/sync/run")
    # A mart-refresh failure must not turn a successful sync into an error.
    assert resp.status_code == 200
    assert "banner ok" in resp.text


def _save_email(client, email_to="buyer@example.com"):
    """Save an enabled monthly AI report schedule with a recipient."""
    client.post(
        "/destination/save",
        data={"enabled": "on", "report_type": "monthly", "email_to": email_to},
        follow_redirects=False,
    )


def _send_now(client, *, email_to="buyer@example.com", report_type="monthly", enabled="on", **extra):
    """Post the destination form to /reports/send-now, like the test-send button."""
    data = {"report_type": report_type, "email_to": email_to, **extra}
    if enabled is not None:
        data["enabled"] = enabled
    return client.post("/reports/send-now", data=data)


def _patch_send_pipeline(monkeypatch, *, result=None):
    """Stub the BigQuery/SMTP construction so route tests stay offline."""
    import src.web.app as web_app

    monkeypatch.setattr(web_app, "BigQueryDestination", lambda **_: object())
    monkeypatch.setattr(web_app, "load_smtp_email_config_from_env", lambda: object())
    monkeypatch.setattr(web_app, "SMTPEmailSender", lambda *_: object())
    if result is not None:
        monkeypatch.setattr(
            web_app.send_now_mod, "send_workspace_reports_now", lambda **_: result
        )
    return web_app


def test_reports_send_now_requires_sign_in(ctx):
    resp = ctx.client.post("/reports/send-now", follow_redirects=False)
    assert resp.status_code == 401


def test_reports_send_now_without_recipient_shows_notice(ctx):
    _select_meta(ctx.client, ctx.factory, ["act_111"])
    # No recipient on screen → friendly "set it up first" banner.
    resp = _send_now(ctx.client, email_to="", enabled=None)
    assert "請先在上方開啟" in resp.text
    assert "banner error" in resp.text


def test_reports_send_now_without_bigquery_shows_notice(ctx):
    _select_meta(ctx.client, ctx.factory, ["act_111"])
    # Recipient on screen but no BigQuery configured in tests → friendly banner.
    resp = _send_now(ctx.client)
    assert "Data warehouse" in resp.text
    assert "banner error" in resp.text


def test_reports_send_now_without_openai_key_shows_notice(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("GCP_PROJECT_ID", "proj")
    monkeypatch.setenv("BIGQUERY_DATASET", "ds")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    ctx = _build_ctx(tmp_path)

    _select_meta(ctx.client, ctx.factory, ["act_111"])
    resp = _send_now(ctx.client)
    assert "OPENAI_API_KEY" in resp.text
    assert "banner error" in resp.text


def test_reports_send_now_success_banner(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("GCP_PROJECT_ID", "proj")
    monkeypatch.setenv("BIGQUERY_DATASET", "ds")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    ctx = _build_ctx(tmp_path)

    _patch_send_pipeline(monkeypatch, result=SendNowResult("sent", 1))

    _select_meta(ctx.client, ctx.factory, ["act_111"])
    resp = _send_now(ctx.client)
    assert resp.status_code == 200
    assert "報告已寄出" in resp.text
    assert "banner ok" in resp.text


def test_reports_send_now_saves_onscreen_cadence_before_sending(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("GCP_PROJECT_ID", "proj")
    monkeypatch.setenv("BIGQUERY_DATASET", "ds")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    ctx = _build_ctx(tmp_path)

    web_app = _patch_send_pipeline(monkeypatch)
    captured: dict = {}

    def fake_send(**kwargs):
        captured.update(kwargs)
        return SendNowResult("sent", 1)

    monkeypatch.setattr(web_app.send_now_mod, "send_workspace_reports_now", fake_send)

    _select_meta(ctx.client, ctx.factory, ["act_111"])
    # User switches to Weekly and clicks "send test" WITHOUT clicking Save first.
    resp = _send_now(ctx.client, report_type="weekly", weekly_day="friday")
    assert resp.status_code == 200

    # The on-screen weekly cadence is persisted before the send.
    from src.storage.models import ReportSchedule

    with ctx.factory() as session:
        schedule = session.scalars(select(ReportSchedule)).one()
        assert schedule.report_type == "weekly"
        assert schedule.delivery_day == "friday"
    # ...and the config handed to the sender reflects weekly, not a stale monthly.
    assert captured["config"]["clients"][0]["report_schedules"][0]["report_type"] == "weekly"


def test_reports_send_now_never_500s_on_unexpected_error(tmp_path, monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", generate_key())
    monkeypatch.setenv("GCP_PROJECT_ID", "proj")
    monkeypatch.setenv("BIGQUERY_DATASET", "ds")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    ctx = _build_ctx(tmp_path)

    web_app = _patch_send_pipeline(monkeypatch)

    def boom(**_):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(web_app.send_now_mod, "send_workspace_reports_now", boom)

    _select_meta(ctx.client, ctx.factory, ["act_111"])
    resp = _send_now(ctx.client)
    assert resp.status_code == 200
    assert "banner error" in resp.text


def test_send_now_button_appears_only_after_email_saved(ctx):
    _select_meta(ctx.client, ctx.factory, ["act_111"])
    # Before configuring email: no test-send button.
    assert "/reports/send-now" not in ctx.client.get("/").text
    _save_email(ctx.client)
    home = ctx.client.get("/").text
    assert "寄送測試報告" in home
    assert "formaction='/reports/send-now'" in home


def test_destination_save_requires_sign_in(ctx):
    resp = ctx.client.post(
        "/destination/save",
        data={"destination": ["bigquery"]},
        follow_redirects=False,
    )
    assert resp.status_code == 401


def test_format_google_ads_account_name():
    from src.web.ad_oauth import format_google_ads_account_name

    assert format_google_ads_account_name("123", "Acme Brand") == "Acme Brand | 123"
    # Missing/blank names fall back to the id-only label so connect never breaks.
    assert format_google_ads_account_name("123", "   ") == "Google Ads 123"
    assert format_google_ads_account_name("123", None) == "Google Ads 123"


def test_google_ads_search_endpoint_from_version():
    from src.web.ad_oauth import google_ads_search_endpoint

    assert google_ads_search_endpoint("v21", "123") == (
        "https://googleads.googleapis.com/v21/customers/123/googleAds:search"
    )


def test_google_ads_list_customers_labels_with_descriptive_name(monkeypatch):
    from src.web import ad_oauth

    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(
            200,
            json={"resourceNames": ["customers/1234567890"]},
            request=httpx.Request("GET", url),
        )

    def fake_post(url, headers=None, json=None, timeout=None):
        assert "googleAds:search" in url
        return httpx.Response(
            200,
            json={"results": [{"customer": {"id": "1234567890", "descriptiveName": "Acme Brand"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(ad_oauth.httpx, "get", fake_get)
    monkeypatch.setattr(ad_oauth.httpx, "post", fake_post)
    client = ad_oauth.GoogleAdsOAuthClient("id", "secret", "uri", "devtoken")
    accounts = client._list_customers("access-token")
    assert len(accounts) == 1
    assert accounts[0].external_account_id == "1234567890"
    assert accounts[0].account_name == "Acme Brand | 1234567890"


def test_google_ads_list_customers_falls_back_when_name_lookup_fails(monkeypatch):
    from src.web import ad_oauth

    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(
            200,
            json={"resourceNames": ["customers/999"]},
            request=httpx.Request("GET", url),
        )

    def fake_post(url, headers=None, json=None, timeout=None):
        # Name lookup denied — must not break connect.
        return httpx.Response(
            403,
            json={"error": {"status": "PERMISSION_DENIED", "message": "no"}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(ad_oauth.httpx, "get", fake_get)
    monkeypatch.setattr(ad_oauth.httpx, "post", fake_post)
    client = ad_oauth.GoogleAdsOAuthClient("id", "secret", "uri", "devtoken")
    accounts = client._list_customers("access-token")
    assert accounts[0].account_name == "Google Ads 999"


def test_settings_read_google_ads_login_customer_id(monkeypatch):
    from src.web.config import load_web_settings

    monkeypatch.setenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "123-456-7890")
    # Stored digits-only so it can be used directly as login-customer-id.
    assert load_web_settings().google_ads_login_customer_id == "1234567890"


def test_google_ads_name_fetch_uses_manager_login_customer_id(monkeypatch):
    from src.web import ad_oauth

    captured = {}

    def fake_get(url, headers=None, timeout=None):
        return httpx.Response(
            200, json={"resourceNames": ["customers/777"]}, request=httpx.Request("GET", url)
        )

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["login"] = headers.get("login-customer-id")
        return httpx.Response(
            200,
            json={"results": [{"customer": {"id": "777", "descriptiveName": "Acme"}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(ad_oauth.httpx, "get", fake_get)
    monkeypatch.setattr(ad_oauth.httpx, "post", fake_post)
    client = ad_oauth.GoogleAdsOAuthClient(
        "id", "secret", "uri", "devtoken", login_customer_id="123-456-7890"
    )
    accounts = client._list_customers("access-token")
    # The configured manager id (digits only) is sent, not the client account id.
    assert captured["login"] == "1234567890"
    assert accounts[0].account_name == "Acme | 777"


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
