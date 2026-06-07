"""FastAPI application: Google sign-in (the product's own login).

Routes:
- GET  /healthz                 health check
- GET  /auth/google/login       start Google sign-in (redirect to consent)
- GET  /oauth/google/callback   handle the redirect, create/find user, set session
- GET  /me                      current signed-in user
- POST /auth/logout             clear the session
"""

from __future__ import annotations

import html
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from src.storage.models import User
from src.storage.repository import (
    get_or_create_default_workspace,
    list_connections,
    list_workspaces_for_user,
    upsert_platform_connection,
    upsert_user_by_google_sub,
)
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
PLATFORM_LABELS = {"meta_ads": "Meta Ads", "google_ads": "Google Ads"}


def _render_connections(connections: list) -> str:
    """Render the connected ad accounts as a list."""
    if not connections:
        return "<p class='muted'>No ad accounts connected yet.</p>"
    items = []
    for conn in connections:
        label = html.escape(PLATFORM_LABELS.get(conn.platform, conn.platform))
        name = html.escape(conn.account_name or conn.external_account_id)
        status = html.escape(conn.status)
        items.append(
            f"<li><strong>{label}</strong> — {name} "
            f"<span class='muted'>({status})</span></li>"
        )
    return "<ul class='conn-list'>" + "".join(items) + "</ul>"


def _page(body: str) -> str:
    """Wrap body HTML in a minimal, on-brand page shell."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OudSeed</title>
<style>
  body {{ margin:0; min-height:100vh; display:grid; place-items:center;
    background:linear-gradient(180deg,#f4f7fa,#e7ebf0); color:#0f1419;
    font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif; }}
  .card {{ background:#fff; border:1px solid #e1e6ec; border-radius:18px;
    box-shadow:0 10px 30px rgba(22,32,50,.08); padding:40px 44px; max-width:520px; }}
  h1 {{ margin:0 0 10px; font-size:30px; letter-spacing:-.02em; }}
  h3 {{ margin:24px 0 8px; font-size:15px; text-transform:uppercase;
    letter-spacing:.08em; color:#69748a; }}
  .muted {{ color:#69748a; line-height:1.55; }}
  .actions {{ display:flex; gap:10px; flex-wrap:wrap; }}
  .conn-list {{ list-style:none; padding:0; margin:0; }}
  .conn-list li {{ padding:10px 14px; border:1px solid #e1e6ec; border-radius:10px;
    margin-bottom:8px; }}
  .btn, button {{ display:inline-block; margin-top:8px; border:0; cursor:pointer;
    background:linear-gradient(135deg,#415471,#29384f); color:#fff;
    padding:12px 22px; border-radius:12px; font-weight:700; text-decoration:none;
    box-shadow:0 10px 22px rgba(38,52,74,.24); font-size:15px; }}
</style></head>
<body><main class="card">{body}</main></body></html>"""


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

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
        user_id = request.session.get(SESSION_USER_KEY)
        user = db.get(User, user_id) if user_id else None
        if user is not None:
            name = html.escape(user.name or user.email)
            email = html.escape(user.email)
            workspaces = list_workspaces_for_user(db, user.id)
            connections = list_connections(db, workspaces[0].id) if workspaces else []
            body = (
                f"<h1>Welcome, {name}</h1>"
                f"<p class='muted'>Signed in as {email}</p>"
                "<h3>Connect ad accounts</h3>"
                "<p class='actions'>"
                "<a class='btn' href='/connect/meta/start'>Connect Meta</a> "
                "<a class='btn' href='/connect/google-ads/start'>Connect Google Ads</a>"
                "</p>"
                "<h3>Connected accounts</h3>"
                f"{_render_connections(connections)}"
                "<form method='post' action='/auth/logout'>"
                "<button type='submit'>Sign out</button></form>"
            )
        else:
            body = (
                "<h1>OudSeed</h1>"
                "<p class='muted'>Connect your ad accounts and get automatic AI performance reports.</p>"
                "<p><a class='btn' href='/auth/google/login'>Sign in with Google</a></p>"
            )
        return HTMLResponse(_page(body))

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

    # --- Ad-platform connect (Meta / Google Ads) ---

    def _require_user(request: Request, db: Session) -> User:
        user_id = request.session.get(SESSION_USER_KEY)
        user = db.get(User, user_id) if user_id else None
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in first.")
        return user

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
        return RedirectResponse(settings.app_base_url + "/", status_code=307)

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

    return app


app = create_app()
