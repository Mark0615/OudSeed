"""Tests for token encryption and platform-connection storage.

Run on in-memory SQLite with an explicit encryption key, so no credentials or
environment variables are required.
"""

import pytest

from src.storage.crypto import decrypt_secret, encrypt_secret, generate_key
from src.storage.db import build_session_factory, create_all, create_db_engine, session_scope
from src.storage.repository import (
    create_platform_connection,
    create_workspace,
    get_connection,
    list_connections,
    read_connection_token,
    store_connection_token,
    upsert_user_by_google_sub,
)


@pytest.fixture
def session_factory():
    engine = create_db_engine("sqlite://")
    create_all(engine)
    return build_session_factory(engine)


@pytest.fixture
def key():
    return generate_key()


def _make_workspace(session):
    owner = upsert_user_by_google_sub(session, google_sub="g-1", email="o@example.com")
    return create_workspace(session, name="Acme", owner=owner)


def test_encrypt_round_trip(key):
    token = encrypt_secret("super-secret-token", key=key)
    assert token != "super-secret-token"
    assert decrypt_secret(token, key=key) == "super-secret-token"


def test_decrypt_with_wrong_key_fails(key):
    from cryptography.fernet import InvalidToken

    token = encrypt_secret("x", key=key)
    with pytest.raises(InvalidToken):
        decrypt_secret(token, key=generate_key())


def test_store_token_encrypts_at_rest(session_factory, key):
    with session_scope(session_factory) as session:
        workspace = _make_workspace(session)
        conn = create_platform_connection(
            session,
            workspace_id=workspace.id,
            platform="meta_ads",
            external_account_id="act_123",
            account_name="Demo",
        )
        assert conn.status == "pending"
        store_connection_token(conn, secret="refresh-token-xyz", key=key)
        conn_id = conn.id

    with session_scope(session_factory) as session:
        stored = get_connection(session, conn_id)
        assert stored.status == "active"
        # The raw column must not contain the plaintext.
        assert "refresh-token-xyz" not in (stored.encrypted_token or "")
        assert read_connection_token(stored, key=key) == "refresh-token-xyz"


def test_unsupported_platform_rejected(session_factory):
    with session_scope(session_factory) as session:
        workspace = _make_workspace(session)
        with pytest.raises(ValueError, match="platform"):
            create_platform_connection(
                session,
                workspace_id=workspace.id,
                platform="tiktok_ads",
                external_account_id="x",
            )


def test_list_connections_filters_by_platform(session_factory):
    with session_scope(session_factory) as session:
        workspace = _make_workspace(session)
        create_platform_connection(
            session, workspace_id=workspace.id, platform="meta_ads", external_account_id="act_1"
        )
        create_platform_connection(
            session, workspace_id=workspace.id, platform="google_ads", external_account_id="123"
        )

        assert len(list_connections(session, workspace.id)) == 2
        meta_only = list_connections(session, workspace.id, platform="meta_ads")
        assert [c.external_account_id for c in meta_only] == ["act_1"]


def test_read_token_returns_none_without_token(session_factory, key):
    with session_scope(session_factory) as session:
        workspace = _make_workspace(session)
        conn = create_platform_connection(
            session, workspace_id=workspace.id, platform="meta_ads", external_account_id="act_1"
        )
        assert read_connection_token(conn, key=key) is None
