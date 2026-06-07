"""FastAPI application: sign-in, ad-platform connect, and the onboarding dashboard.

Routes:
- GET  /                         dashboard (signed in) or sign-in page
- GET  /healthz                  health check
- GET  /auth/google/login        start Google sign-in
- GET  /oauth/google/callback    finish sign-in (create/find user, set session)
- GET  /me                       current signed-in user (JSON)
- POST /auth/logout              clear the session
- GET  /connect/{meta,google-ads}/start    start ad-platform OAuth
- GET  /oauth/{meta,google-ads}/callback   finish connect (store encrypted token)
- POST /accounts/select          choose which accounts sync (active vs paused)
"""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from src.storage.models import SUPPORTED_PLATFORMS, User
from src.storage.repository import (
    get_or_create_default_workspace,
    list_connections,
    list_workspaces_for_user,
    set_account_selection,
    upsert_platform_connection,
    upsert_user_by_google_sub,
)
from src.web import views
from src.web.ad_oauth import GoogleAdsOAuthClient, MetaAdsOAuthClient
from src.web.config import load_web_settings
from src.web.deps import (
    get_db,
    get_google_ads_oauth,
    get_google_oauth,
    get_meta_ads_oauth,
)
from src.web.oauth import GoogleOAuthClient

SESSION_STATE_KEY = "oauth_state"
SESSION_USER_KEY = "user_id"
CONNECT_STATE_KEY = "connect_state"

ASSETS_DIR = Path(__file__).resolve().parents[2] / "frontend" / "prototype" / "assets"


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
    if ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

    def _current_user(request: Request, db: Session) -> User | None:
        user_id = request.session.get(SESSION_USER_KEY)
        return db.get(User, user_id) if user_id else None

    def _require_user(request: Request, db: Session) -> User:
        user = _current_user(request, db)
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in first.")
        return user

    def _platform_views(db: Session, workspace_id: str | None) -> list[views.PlatformView]:
        result = []
        for platform in SUPPORTED_PLATFORMS:
            conns = list_connections(db, workspace_id, platform=platform) if workspace_id else []
            accounts = [
                views.AccountView(
                    external_account_id=c.external_account_id,
                    account_name=c.account_name or c.external_account_id,
                    selected=c.status == "active",
                )
                for c in conns
                if c.status != "revoked"
            ]
            result.append(views.PlatformView(platform=platform, accounts=accounts))
        return result

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
        user = _current_user(request, db)
        if user is None:
            return HTMLResponse(views.render_signin())
        workspaces = list_workspaces_for_user(db, user.id)
        workspace_id = workspaces[0].id if workspaces else None
        platforms = _platform_views(db, workspace_id)
        return HTMLResponse(views.render_dashboard(user.email, platforms))

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
        user = _current_user(request, db)
        if user is None:
            raise HTTPException(status_code=401, detail="Not signed in.")
        return {"id": user.id, "email": user.email, "name": user.name}

    @app.post("/auth/logout")
    def logout(request: Request) -> RedirectResponse:
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    # --- Ad-platform connect (Meta / Google Ads) ---

    def _start_connect(request: Request, client) -> RedirectResponse:
        state = secrets.token_urlsafe(24)
        request.session[CONNECT_STATE_KEY] = state
        return RedirectResponse(client.authorization_url(state), status_code=307)

    def _finish_connect(
        request: Request, db: Session, client, code: str | None, state: str | None
    ) -> RedirectResponse:
        expected_state = request.session.pop(CONNECT_STATE_KEY, None)
        if not code or not state or not expected_state or state != expected_state:
            raise HTTPException(status_code=400, detail="Invalid OAuth state or missing code.")
        user = _require_user(request, db)
        result = client.fetch_connection(code)
        workspace = get_or_create_default_workspace(db, user)
        for account in result.accounts:
            upsert_platform_connection(
                db,
                workspace_id=workspace.id,
                platform=client.platform,
                external_account_id=account.external_account_id,
                account_name=account.account_name,
                token=result.secret,
                scopes=result.scopes,
            )
        return RedirectResponse(settings.app_base_url + "/", status_code=303)

    @app.get("/connect/meta/start")
    def connect_meta_start(
        request: Request,
        oauth: MetaAdsOAuthClient = Depends(get_meta_ads_oauth),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        _require_user(request, db)
        return _start_connect(request, oauth)

    @app.get("/oauth/meta/callback")
    def meta_callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        oauth: MetaAdsOAuthClient = Depends(get_meta_ads_oauth),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        return _finish_connect(request, db, oauth, code, state)

    @app.get("/connect/google-ads/start")
    def connect_google_ads_start(
        request: Request,
        oauth: GoogleAdsOAuthClient = Depends(get_google_ads_oauth),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        _require_user(request, db)
        return _start_connect(request, oauth)

    @app.get("/oauth/google-ads/callback")
    def google_ads_callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        oauth: GoogleAdsOAuthClient = Depends(get_google_ads_oauth),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        return _finish_connect(request, db, oauth, code, state)

    @app.post("/accounts/select")
    def accounts_select(
        request: Request,
        platform: str = Form(...),
        account: list[str] = Form(default=[]),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        user = _require_user(request, db)
        workspace = get_or_create_default_workspace(db, user)
        set_account_selection(
            db,
            workspace_id=workspace.id,
            platform=platform,
            selected_external_ids=account,
        )
        return RedirectResponse("/", status_code=303)

    return app


app = create_app()
