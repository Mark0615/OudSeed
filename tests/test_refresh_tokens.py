"""Tests for the Meta token renewal job (offline, no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from src.storage.crypto import encrypt_secret
from src.storage.db import build_session_factory, create_all, create_db_engine
from src.storage.models import PlatformConnection, User, Workspace
from src.storage.repository import read_connection_token
from src.sync.refresh_tokens import notify_failures, renew_meta_tokens

KEY = "8Zc1x0K4jH0nJ8xO2h1qk7yYyq5r5X2Yh1kQ0V9m3nM="
NOW = datetime(2026, 9, 4, tzinfo=UTC)


@pytest.fixture()
def session(tmp_path):
    engine = create_db_engine(f"sqlite:///{tmp_path/'t.db'}")
    create_all(engine)
    with build_session_factory(engine)() as s:
        s.add(User(id="u1", google_sub="sub-1", email="u1@example.com"))
        s.add(Workspace(id="w1", name="W1", owner_user_id="u1"))
        s.flush()
        yield s


def _add(session, *, account_id, token, expires_at, status="active", platform="meta_ads"):
    connection = PlatformConnection(
        workspace_id="w1",
        platform=platform,
        external_account_id=account_id,
        status=status,
        encrypted_token=encrypt_secret(token, key=KEY),
        token_expires_at=expires_at,
    )
    session.add(connection)
    session.flush()
    return connection


def test_renews_once_per_authorization_and_writes_back_to_all_accounts(session):
    """One token shared by three accounts must cost one exchange, not three."""
    soon = NOW + timedelta(days=5)
    shared = [_add(session, account_id=f"act_{i}", token="tok_old", expires_at=soon) for i in range(3)]

    calls: list[str] = []

    def renew(token):
        calls.append(token)
        return "tok_new", 60 * 24 * 3600  # 60 days

    results = renew_meta_tokens(session, renew=renew, now=NOW, encryption_key=KEY)

    assert calls == ["tok_old"]  # one exchange for the whole authorization
    assert [(r.accounts, r.status) for r in results] == [(3, "renewed")]
    for connection in shared:
        assert read_connection_token(connection, key=KEY) == "tok_new"
        assert connection.token_expires_at == NOW + timedelta(days=60)


def test_skips_tokens_that_are_not_close_to_expiry(session):
    _add(session, account_id="act_1", token="tok", expires_at=NOW + timedelta(days=45))

    def renew(token):  # pragma: no cover - must not be called
        raise AssertionError("should not renew a token that is not due")

    assert renew_meta_tokens(session, renew=renew, now=NOW, encryption_key=KEY) == []


def test_renews_when_expiry_is_unknown(session):
    """Connections authorized before expiries were recorded still get renewed."""
    connection = _add(session, account_id="act_1", token="tok_old", expires_at=None)

    results = renew_meta_tokens(
        session, renew=lambda t: ("tok_new", 5_184_000), now=NOW, encryption_key=KEY
    )

    assert [r.status for r in results] == ["renewed"]
    assert read_connection_token(connection, key=KEY) == "tok_new"


def test_preserves_paused_status_so_renewal_never_starts_an_unselected_sync(session):
    paused = _add(
        session,
        account_id="act_1",
        token="tok_old",
        expires_at=NOW + timedelta(days=3),
        status="paused",
    )

    renew_meta_tokens(
        session, renew=lambda t: ("tok_new", 5_184_000), now=NOW, encryption_key=KEY
    )

    assert paused.status == "paused"
    assert read_connection_token(paused, key=KEY) == "tok_new"


def test_flags_needs_reconnect_when_renewal_fails(session):
    dead = [
        _add(session, account_id=f"act_{i}", token="tok_dead", expires_at=NOW + timedelta(days=1))
        for i in range(2)
    ]

    def renew(token):
        request = httpx.Request("GET", "https://graph.facebook.com/oauth/access_token")
        response = httpx.Response(
            400,
            json={"error": {"type": "OAuthException", "message": "Session has expired"}},
            request=request,
        )
        raise httpx.HTTPStatusError("400", request=request, response=response)

    results = renew_meta_tokens(session, renew=renew, now=NOW, encryption_key=KEY)

    assert [(r.accounts, r.status) for r in results] == [(2, "failed")]
    assert all(c.status == "needs_reconnect" for c in dead)
    # The original token is left in place; only a fresh authorization replaces it.
    assert read_connection_token(dead[0], key=KEY) == "tok_dead"
    assert "Session has expired" in results[0].error


def test_ignores_google_ads_connections(session):
    """Google Ads refresh tokens have no fixed expiry and must not be touched."""
    _add(
        session,
        account_id="111",
        token="refresh_tok",
        expires_at=None,
        platform="google_ads",
    )

    def renew(token):  # pragma: no cover - must not be called
        raise AssertionError("google_ads must not be renewed here")

    assert renew_meta_tokens(session, renew=renew, now=NOW, encryption_key=KEY) == []


def _fail_renewal(token):
    request = httpx.Request("GET", "https://graph.facebook.com/oauth/access_token")
    response = httpx.Response(
        400,
        json={"error": {"type": "OAuthException", "message": "Session has expired"}},
        request=request,
    )
    raise httpx.HTTPStatusError("400", request=request, response=response)


def test_notifies_the_workspace_owner_when_renewal_fails(session):
    _add(session, account_id="act_1", token="tok", expires_at=NOW + timedelta(days=1))
    connection = session.query(PlatformConnection).one()
    connection.account_name = "Miniware TW"

    results = renew_meta_tokens(session, renew=_fail_renewal, now=NOW, encryption_key=KEY)

    sent: list[tuple[str, str, str]] = []
    count = notify_failures(
        results,
        session=session,
        send=lambda *args: sent.append(args),
        app_base_url="https://oudseed.example/",
    )

    assert count == 1
    recipient, subject, body = sent[0]
    assert recipient == "u1@example.com"  # the workspace owner
    assert "重新授權" in subject
    assert "Miniware TW" in body  # the owner needs to know which account
    assert "https://oudseed.example/" in body


def test_does_not_notify_when_everything_renewed(session):
    _add(session, account_id="act_1", token="tok_old", expires_at=NOW + timedelta(days=1))
    results = renew_meta_tokens(
        session, renew=lambda t: ("tok_new", 5_184_000), now=NOW, encryption_key=KEY
    )

    def send(*args):  # pragma: no cover - must not be called
        raise AssertionError("no email on a successful renewal")

    assert notify_failures(results, session=session, send=send) == 0


def test_email_failure_does_not_break_the_run(session):
    """A dropped notification must not roll back the needs_reconnect status."""
    _add(session, account_id="act_1", token="tok", expires_at=NOW + timedelta(days=1))
    results = renew_meta_tokens(session, renew=_fail_renewal, now=NOW, encryption_key=KEY)

    def send(*args):
        raise OSError("smtp unreachable")

    assert notify_failures(results, session=session, send=send) == 0
    assert session.query(PlatformConnection).one().status == "needs_reconnect"


def test_does_not_renew_already_flagged_connections(session):
    """A connection awaiting reauthorization must not be retried every day."""
    _add(
        session,
        account_id="act_1",
        token="tok",
        expires_at=NOW + timedelta(days=1),
        status="needs_reconnect",
    )

    def renew(token):  # pragma: no cover - must not be called
        raise AssertionError("needs_reconnect should be excluded")

    assert renew_meta_tokens(session, renew=renew, now=NOW, encryption_key=KEY) == []
