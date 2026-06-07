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

import logging
import secrets
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from src.storage.models import REPORT_DEPTHS, REPORT_TYPES, SUPPORTED_PLATFORMS, User
from src.storage.repository import (
    bind_connections_to_client,
    get_or_create_default_client,
    get_or_create_default_workspace,
    list_clients,
    list_connections,
    list_report_schedules,
    list_workspaces_for_user,
    read_schedule_email_to,
    set_account_selection,
    upsert_platform_connection,
    upsert_report_schedule,
    upsert_user_by_google_sub,
)
from src.web import views
from src.web.ad_oauth import (
    GoogleAdsOAuthClient,
    MetaAdsOAuthClient,
    summarize_oauth_http_error,
)
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
# Single onboarding-managed email report schedule per workspace's default client.
ONBOARDING_SCHEDULE_KEY = "onboarding_email"

logger = logging.getLogger(__name__)

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

    def _destination_view(db: Session, workspace_id: str | None) -> views.DestinationView:
        if not workspace_id:
            return views.DestinationView()
        clients = list_clients(db, workspace_id)
        if not clients:
            return views.DestinationView()
        schedule = next(
            (
                s
                for s in list_report_schedules(db, clients[0].id)
                if s.schedule_key == ONBOARDING_SCHEDULE_KEY
            ),
            None,
        )
        if schedule is None:
            return views.DestinationView()
        return views.DestinationView(
            configured=True,
            enabled=schedule.enabled,
            report_type=schedule.report_type,
            delivery_day=schedule.delivery_day,
            depth=schedule.depth,
            email_to=read_schedule_email_to(schedule) or "",
            timezone=schedule.timezone or "Asia/Taipei",
        )

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
        destination = _destination_view(db, workspace_id)
        return HTMLResponse(views.render_dashboard(user.email, platforms, destination))

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
    ) -> Response:
        expected_state = request.session.pop(CONNECT_STATE_KEY, None)
        if not code or not state or not expected_state or state != expected_state:
            raise HTTPException(status_code=400, detail="Invalid OAuth state or missing code.")
        user = _require_user(request, db)
        label = views.PLATFORM_LABELS.get(client.platform, client.platform)
        # Surface provider/auth failures as a readable page instead of a raw 500.
        try:
            result = client.fetch_connection(code)
        except httpx.HTTPStatusError as exc:
            reason = summarize_oauth_http_error(exc)
            logger.warning("Connect failed (%s): %s", client.platform, reason)
            return HTMLResponse(views.render_connect_error(label, reason), status_code=502)
        except httpx.RequestError as exc:
            logger.warning("Connect network error (%s): %s", client.platform, type(exc).__name__)
            return HTMLResponse(
                views.render_connect_error(label, f"Couldn't reach {label}. Please try again."),
                status_code=504,
            )
        except ValueError as exc:
            logger.warning("Connect rejected (%s): %s", client.platform, exc)
            return HTMLResponse(views.render_connect_error(label, str(exc)), status_code=400)
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
                # Newly connected accounts start unselected; the user opts in
                # which accounts to sync on the next step.
                mark_active=False,
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
    ) -> Response:
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
    ) -> Response:
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

    @app.post("/destination/save")
    def destination_save(
        request: Request,
        enabled: str | None = Form(default=None),
        report_type: str = Form(default="monthly"),
        monthly_day: str = Form(default="1"),
        weekly_day: str = Form(default="monday"),
        depth: str = Form(default="standard"),
        email_to: str = Form(default=""),
        timezone: str = Form(default="Asia/Taipei"),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        user = _require_user(request, db)
        workspace = get_or_create_default_workspace(db, user)
        # Group the workspace's selected (active) accounts into the default client.
        active = [
            c for c in list_connections(db, workspace.id) if c.status == "active"
        ]
        client = get_or_create_default_client(db, workspace)
        bind_connections_to_client(db, client=client, connections=active)

        report_type = report_type if report_type in REPORT_TYPES else "monthly"
        depth = depth if depth in REPORT_DEPTHS else "standard"
        delivery_day = monthly_day if report_type == "monthly" else weekly_day
        upsert_report_schedule(
            db,
            client_id=client.id,
            schedule_key=ONBOARDING_SCHEDULE_KEY,
            report_type=report_type,
            delivery_day=str(delivery_day),
            depth=depth,
            email_to=email_to.strip() or None,
            timezone=timezone,
            enabled=bool(enabled),
        )
        return RedirectResponse("/", status_code=303)

    return app


app = create_app()
