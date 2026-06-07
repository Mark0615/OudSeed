"""Tests for the FastAPI Google sign-in flow.

Uses a fake OAuth client and a temp SQLite DB via dependency overrides, so no
network calls or real credentials are needed.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from src.storage.db import build_session_factory, create_all, create_db_engine
from src.web.app import create_app
from src.web.deps import get_db, get_google_oauth
from src.web.oauth import GoogleUser


class FakeGoogleOAuth:
    """Stand-in for GoogleOAuthClient with no network calls."""

    def __init__(self) -> None:
        self.user = GoogleUser(sub="g-123", email="alice@example.com", name="Alice")

    def authorization_url(self, state: str) -> str:
        return f"https://accounts.example/auth?state={state}"

    def exchange_code(self, code: str) -> dict:
        return {"access_token": "fake-access-token"}

    def fetch_userinfo(self, access_token: str) -> GoogleUser:
        return self.user


@pytest.fixture
def client(tmp_path):
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
    app.dependency_overrides[get_google_oauth] = FakeGoogleOAuth
    return TestClient(app)


def _start_login(client) -> str:
    """Begin sign-in and return the CSRF state from the redirect."""
    resp = client.get("/auth/google/login", follow_redirects=False)
    assert resp.status_code == 307
    location = resp.headers["location"]
    return parse_qs(urlparse(location).query)["state"][0]


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_full_signin_flow_creates_user_and_session(client):
    state = _start_login(client)
    resp = client.get(
        f"/oauth/google/callback?code=abc&state={state}", follow_redirects=False
    )
    assert resp.status_code == 307

    me = client.get("/me")
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"
    assert me.json()["name"] == "Alice"


def test_callback_rejects_mismatched_state(client):
    _start_login(client)  # sets a real state in the session
    resp = client.get(
        "/oauth/google/callback?code=abc&state=WRONG", follow_redirects=False
    )
    assert resp.status_code == 400


def test_callback_requires_code(client):
    state = _start_login(client)
    resp = client.get(
        f"/oauth/google/callback?state={state}", follow_redirects=False
    )
    assert resp.status_code == 400


def test_me_requires_sign_in(client):
    assert client.get("/me").status_code == 401


def test_logout_clears_session(client):
    state = _start_login(client)
    client.get(f"/oauth/google/callback?code=abc&state={state}", follow_redirects=False)
    assert client.get("/me").status_code == 200

    client.post("/auth/logout")
    assert client.get("/me").status_code == 401
