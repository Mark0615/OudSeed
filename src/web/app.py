"""FastAPI application: Google sign-in (the product's own login).

Routes:
- GET  /healthz                 health check
- GET  /auth/google/login       start Google sign-in (redirect to consent)
- GET  /oauth/google/callback   handle the redirect, create/find user, set session
- GET  /me                      current signed-in user
- POST /auth/logout             clear the session
"""

from __future__ import annotations

import secrets

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from src.storage.models import User
from src.storage.repository import upsert_user_by_google_sub
from src.web.config import load_web_settings
from src.web.deps import get_db, get_google_oauth
from src.web.oauth import GoogleOAuthClient

SESSION_STATE_KEY = "oauth_state"
SESSION_USER_KEY = "user_id"


def create_app() -> FastAPI:
    """Build the FastAPI app."""
    settings = load_web_settings()
    app = FastAPI(title="OudSeed")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        same_site="lax",
        https_only=False,
    )

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/auth/google/login")
    def google_login(
        request: Request,
        oauth: GoogleOAuthClient = Depends(get_google_oauth),
    ) -> RedirectResponse:
        state = secrets.token_urlsafe(24)
        request.session[SESSION_STATE_KEY] = state
        return RedirectResponse(oauth.authorization_url(state), status_code=307)

    @app.get("/oauth/google/callback")
    def google_callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        oauth: GoogleOAuthClient = Depends(get_google_oauth),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        expected_state = request.session.pop(SESSION_STATE_KEY, None)
        if not code or not state or not expected_state or state != expected_state:
            raise HTTPException(status_code=400, detail="Invalid OAuth state or missing code.")

        tokens = oauth.exchange_code(code)
        access_token = tokens.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="No access token returned by Google.")

        google_user = oauth.fetch_userinfo(access_token)
        user = upsert_user_by_google_sub(
            db, google_sub=google_user.sub, email=google_user.email, name=google_user.name
        )
        request.session[SESSION_USER_KEY] = user.id
        return RedirectResponse(settings.app_base_url + "/", status_code=307)

    @app.get("/me")
    def me(request: Request, db: Session = Depends(get_db)) -> dict:
        user_id = request.session.get(SESSION_USER_KEY)
        user = db.get(User, user_id) if user_id else None
        if user is None:
            raise HTTPException(status_code=401, detail="Not signed in.")
        return {"id": user.id, "email": user.email, "name": user.name}

    @app.post("/auth/logout")
    def logout(request: Request) -> dict:
        request.session.clear()
        return {"status": "signed out"}

    return app


app = create_app()
