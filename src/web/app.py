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
from src.storage.repository import upsert_user_by_google_sub
from src.web.config import load_web_settings
from src.web.deps import get_db, get_google_oauth
from src.web.oauth import GoogleOAuthClient

SESSION_STATE_KEY = "oauth_state"
SESSION_USER_KEY = "user_id"


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
    box-shadow:0 10px 30px rgba(22,32,50,.08); padding:40px 44px; max-width:440px; }}
  h1 {{ margin:0 0 10px; font-size:30px; letter-spacing:-.02em; }}
  .muted {{ color:#69748a; line-height:1.55; }}
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
            body = (
                f"<h1>Welcome, {name}</h1>"
                f"<p class='muted'>Signed in as {email}</p>"
                "<p>Next: connect your ad accounts (coming soon).</p>"
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

    return app


app = create_app()
