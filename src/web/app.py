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
import os
import secrets
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from src.ai.openai_client import OpenAITextClient
from src.connectors.google_ads import GoogleAdsConnector
from src.connectors.meta_ads import MetaAdsConnector
from src.destinations.bigquery import BigQueryDestination
from src.main import refresh_reporting_marts
from src.notifications.email_delivery import (
    SMTPEmailSender,
    load_smtp_email_config_from_env,
)
from src.storage.models import REPORT_DEPTHS, REPORT_TYPES, SUPPORTED_PLATFORMS, User
from src.storage.repository import (
    bind_connections_to_client,
    get_or_create_default_client,
    get_or_create_default_workspace,
    list_client_destinations,
    list_clients,
    list_connections,
    list_report_schedules,
    list_workspaces_for_user,
    read_schedule_email_to,
    set_account_selection,
    set_client_destinations,
    upsert_platform_connection,
    upsert_report_schedule,
    upsert_user_by_google_sub,
)
from src.utils.date_utils import get_default_sync_range
from src.web import first_sync as first_sync_mod
from src.web import preview as preview_mod
from src.web import send_now as send_now_mod
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
# Session key for a one-shot status banner after a "Run first sync".
SYNC_FLASH_KEY = "sync_flash"
# How many days back the on-demand first sync pulls (matches the 30-day preview).
FIRST_SYNC_DAYS = 30


def _first_failure_reason(result: first_sync_mod.FirstSyncResult) -> str:
    """Return a short, single-line reason from the first failed account."""
    for r in result.failed:
        if r.error:
            return " ".join(r.error.split())[:200]
    return "Please try again."


def _int_env(name: str, default: int) -> int:
    """Read a positive int env var, falling back to a default on missing/garbage."""
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _persist_onboarding_schedule(
    db: Session,
    workspace,
    *,
    report_type: str,
    monthly_day: str,
    weekly_day: str,
    depth: str,
    email_to: str,
    timezone: str,
    enabled: bool,
):
    """Upsert the workspace's single onboarding report schedule from form values.

    Shared by /destination/save and /reports/send-now so the test-send button
    writes the on-screen cadence/recipient before sending (no stale settings).
    Returns the default client the schedule is attached to.
    """
    client = get_or_create_default_client(db, workspace)
    active = [c for c in list_connections(db, workspace.id) if c.status == "active"]
    bind_connections_to_client(db, client=client, connections=active)
    report_type = report_type if report_type in REPORT_TYPES else "monthly"
    depth = depth if depth in REPORT_DEPTHS else "standard"
    delivery_day = weekly_day if report_type == "weekly" else (monthly_day or "1")
    upsert_report_schedule(
        db,
        client_id=client.id,
        schedule_key=ONBOARDING_SCHEDULE_KEY,
        report_type=report_type,
        delivery_day=delivery_day,
        timezone=timezone or None,
        depth=depth,
        email_to=email_to.strip() or None,
        enabled=enabled,
    )
    return client


def _send_now_flash(result: send_now_mod.SendNowResult) -> dict:
    """Map a send-now outcome to a one-shot dashboard banner (no recipient echoed)."""
    if result.status == "sent":
        return {
            "kind": "ok",
            "text": (
                f"報告已寄出（{result.group_count} 封）到你設定的收件信箱，請查收。"
            ),
        }
    if result.status == "no_groups":
        period = f"（報告週期起算日 {result.detail}）" if result.detail else ""
        return {
            "kind": "warn",
            "text": (
                f"這個報告週期{period}還沒有可用的成效資料。"
                "請先按上方「Run first sync」把資料拉進來，或改用涵蓋範圍內的週期再寄送。"
            ),
        }
    if result.status == "no_recipient":
        return {
            "kind": "error",
            "text": "請先在上方開啟「AI report email」並填好收件人，再寄送測試報告。",
        }
    return {"kind": "error", "text": f"報告產生失敗：{result.detail or '請稍後再試。'}"}

logger = logging.getLogger(__name__)

ASSETS_DIR = Path(__file__).resolve().parent / "assets"


def create_app() -> FastAPI:
    """Build the FastAPI app."""
    settings = load_web_settings()
    app = FastAPI(title="OudSeed")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        same_site="lax",
        https_only=settings.session_cookie_secure,
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
        client = clients[0]
        selected = tuple(
            d.kind for d in list_client_destinations(db, client.id) if d.enabled
        )
        schedule = next(
            (
                s
                for s in list_report_schedules(db, client.id)
                if s.schedule_key == ONBOARDING_SCHEDULE_KEY
            ),
            None,
        )
        configured = bool(selected) or schedule is not None
        if schedule is None:
            return views.DestinationView(configured=configured, selected=selected)
        return views.DestinationView(
            configured=configured,
            selected=selected,
            email_enabled=schedule.enabled,
            report_type=schedule.report_type,
            delivery_day=schedule.delivery_day,
            depth=schedule.depth,
            email_to=read_schedule_email_to(schedule) or "",
            timezone=schedule.timezone or "Asia/Taipei",
        )

    def _preview_view(db: Session, workspace_id: str | None) -> preview_mod.PreviewData | None:
        """Build the data preview for the workspace's selected accounts.

        Best-effort: returns None when BigQuery isn't configured, no accounts are
        selected, or the query fails — the view then shows the empty state instead
        of breaking the page.
        """
        if not workspace_id or not settings.bigquery_project or not settings.bigquery_dataset:
            return None
        active_ids = [
            c.external_account_id
            for c in list_connections(db, workspace_id)
            if c.status == "active"
        ]
        if not active_ids:
            return None
        try:
            destination = BigQueryDestination(
                project_id=settings.bigquery_project,
                dataset_id=settings.bigquery_dataset,
            )
            return preview_mod.build_preview(
                destination, workspace_id=workspace_id, account_ids=active_ids
            )
        except Exception:
            # Preview is best-effort and must never break the dashboard.
            logger.warning("Preview unavailable for workspace; showing empty state.")
            return None

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
        preview = _preview_view(db, workspace_id)
        notice = request.session.pop(SYNC_FLASH_KEY, None)
        return HTMLResponse(
            views.render_dashboard(
                user.email, platforms, destination, preview, notice=notice
            )
        )

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
        destination: list[str] = Form(default=[]),
        enabled: str | None = Form(None),
        report_type: str = Form("monthly"),
        monthly_day: str = Form("1"),
        weekly_day: str = Form("monday"),
        depth: str = Form("standard"),
        email_to: str = Form(""),
        timezone: str = Form("Asia/Taipei"),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        user = _require_user(request, db)
        workspace = get_or_create_default_workspace(db, user)
        # Group the workspace's selected (active) accounts into one default client
        # so the chosen destinations and report schedule apply to them.
        # AI report email is an independent opt-in, separate from destinations.
        client = _persist_onboarding_schedule(
            db,
            workspace,
            report_type=report_type,
            monthly_day=monthly_day,
            weekly_day=weekly_day,
            depth=depth,
            email_to=email_to,
            timezone=timezone,
            enabled=bool(enabled),
        )
        set_client_destinations(db, client=client, selected_kinds=destination)
        return RedirectResponse("/", status_code=303)

    def _meta_connector_factory(token: str) -> MetaAdsConnector:
        return MetaAdsConnector(access_token=token)

    def _google_connector_factory(token: str) -> GoogleAdsConnector:
        return GoogleAdsConnector(
            developer_token=settings.google_ads_developer_token,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            refresh_token=token,
            login_customer_id=settings.google_ads_login_customer_id or None,
        )

    @app.post("/sync/run")
    def sync_run(
        request: Request, db: Session = Depends(get_db)
    ) -> RedirectResponse:
        """On-demand first sync: pull recent data for selected accounts into BigQuery."""
        user = _require_user(request, db)
        workspace = get_or_create_default_workspace(db, user)
        active = [c for c in list_connections(db, workspace.id) if c.status == "active"]

        if not active:
            request.session[SYNC_FLASH_KEY] = {
                "kind": "error",
                "text": "Select at least one account to sync first.",
            }
            return RedirectResponse("/", status_code=303)
        if not settings.bigquery_project or not settings.bigquery_dataset:
            request.session[SYNC_FLASH_KEY] = {
                "kind": "error",
                "text": "Data warehouse isn't configured yet, so the sync can't run.",
            }
            return RedirectResponse("/", status_code=303)

        client = get_or_create_default_client(db, workspace)
        bind_connections_to_client(db, client=client, connections=active)
        start_date, end_date = get_default_sync_range(
            days_back=FIRST_SYNC_DAYS, timezone="Asia/Taipei"
        )
        # Calling real ad APIs + BigQuery can fail or time out; never let that turn
        # into a raw 500 — always return a readable status banner.
        try:
            destination = BigQueryDestination(
                project_id=settings.bigquery_project,
                dataset_id=settings.bigquery_dataset,
            )
            result = first_sync_mod.run_first_sync(
                connections=active,
                destination=destination,
                workspace_id=workspace.id,
                client_id=client.client_key,
                start_date=start_date,
                end_date=end_date,
                meta_connector_factory=_meta_connector_factory,
                google_connector_factory=_google_connector_factory,
            )
        except Exception as exc:
            # Log only the exception type to avoid leaking ids/secrets.
            logger.warning("First sync stopped unexpectedly: %s", type(exc).__name__)
            request.session[SYNC_FLASH_KEY] = {
                "kind": "error",
                "text": "The sync hit an unexpected error and stopped. Please try again.",
            }
            return RedirectResponse("/", status_code=303)

        # Refresh the reporting marts so the AI report views (which read the
        # weekly/monthly summary tables, not unified_ads_daily) see the new data.
        # The preview reads unified_ads_daily directly, so it works without this;
        # the report does not. Best-effort: a refresh failure must not turn a
        # successful sync into an error banner.
        if result.succeeded:
            try:
                refresh_reporting_marts(destination=destination)
            except Exception as exc:
                logger.warning(
                    "Reporting marts refresh failed after first sync: %s",
                    type(exc).__name__,
                )

        if result.has_failures and not result.succeeded:
            request.session[SYNC_FLASH_KEY] = {
                "kind": "error",
                "text": f"Sync couldn't pull data: {_first_failure_reason(result)}",
            }
        elif result.has_failures:
            request.session[SYNC_FLASH_KEY] = {
                "kind": "warn",
                "text": (
                    f"Synced {len(result.succeeded)} of {result.attempted} accounts. "
                    f"Some failed: {_first_failure_reason(result)}"
                ),
            }
        else:
            request.session[SYNC_FLASH_KEY] = {
                "kind": "ok",
                "text": (
                    f"Synced {result.attempted} account(s). "
                    "Your preview below now shows recent data."
                ),
            }
        return RedirectResponse("/", status_code=303)

    @app.post("/reports/send-now")
    def reports_send_now(
        request: Request,
        report_type: str = Form("monthly"),
        monthly_day: str = Form("1"),
        weekly_day: str = Form("monday"),
        depth: str = Form("standard"),
        email_to: str = Form(""),
        timezone: str = Form("Asia/Taipei"),
        enabled: str | None = Form(None),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        """Send a test AI report now, using the on-screen schedule + recipient.

        Saves the submitted cadence/recipient first (so the test send reflects
        exactly what's on screen, not a stale saved value), then sends.
        """
        user = _require_user(request, db)
        workspace = get_or_create_default_workspace(db, user)
        client = _persist_onboarding_schedule(
            db,
            workspace,
            report_type=report_type,
            monthly_day=monthly_day,
            weekly_day=weekly_day,
            depth=depth,
            email_to=email_to,
            timezone=timezone,
            enabled=bool(enabled),
        )
        schedule = next(
            (
                s
                for s in list_report_schedules(db, client.id)
                if s.schedule_key == ONBOARDING_SCHEDULE_KEY
            ),
            None,
        )
        recipient = read_schedule_email_to(schedule) if schedule else None
        if schedule is None or not schedule.enabled or not recipient:
            request.session[SYNC_FLASH_KEY] = _send_now_flash(
                send_now_mod.SendNowResult("no_recipient")
            )
            return RedirectResponse("/", status_code=303)
        if not settings.bigquery_project or not settings.bigquery_dataset:
            request.session[SYNC_FLASH_KEY] = {
                "kind": "error",
                "text": "Data warehouse isn't configured yet, so the report can't be generated.",
            }
            return RedirectResponse("/", status_code=303)
        if not os.getenv("OPENAI_API_KEY"):
            request.session[SYNC_FLASH_KEY] = {
                "kind": "error",
                "text": "OPENAI_API_KEY isn't set yet, so the report can't be generated.",
            }
            return RedirectResponse("/", status_code=303)

        # Building config + calling OpenAI/SMTP/BigQuery can fail or time out;
        # never let that become a raw 500 — always show a readable banner.
        try:
            config = send_now_mod.build_workspace_report_config(
                db,
                workspace.id,
                bigquery_project=settings.bigquery_project,
                bigquery_dataset=settings.bigquery_dataset,
                encryption_key=os.getenv("TOKEN_ENCRYPTION_KEY"),
            )
            destination = BigQueryDestination(
                project_id=settings.bigquery_project,
                dataset_id=settings.bigquery_dataset,
            )
            openai_client = OpenAITextClient(
                api_key=os.environ["OPENAI_API_KEY"],
                model=os.getenv("OPENAI_MODEL", "gpt-5.2"),
                reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "medium"),
                timeout_seconds=_int_env("OPENAI_TIMEOUT_SECONDS", 120),
            )
            sender = SMTPEmailSender(load_smtp_email_config_from_env())
            result = send_now_mod.send_workspace_reports_now(
                config=config,
                destination=destination,
                openai_client=openai_client,
                sender=sender,
                schedule_id=ONBOARDING_SCHEDULE_KEY,
                max_output_tokens=_int_env("OPENAI_MAX_OUTPUT_TOKENS", 5000),
            )
        except Exception as exc:
            # Log only the exception type to avoid leaking ids/secrets.
            logger.warning("Send-now report stopped unexpectedly: %s", type(exc).__name__)
            request.session[SYNC_FLASH_KEY] = {
                "kind": "error",
                "text": "Couldn't generate the report this time. Please try again.",
            }
            return RedirectResponse("/", status_code=303)

        request.session[SYNC_FLASH_KEY] = _send_now_flash(result)
        return RedirectResponse("/", status_code=303)

    return app


app = create_app()
