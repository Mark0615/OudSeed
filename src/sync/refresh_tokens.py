"""Renew Meta long-lived tokens before they expire.

Meta issues no refresh token for user access tokens: a long-lived token lasts
~60 days and the only way to keep a connection alive without asking the user to
sign in again is to re-exchange the current token before it dies, which resets
the clock. Run this daily (Cloud Scheduler -> Cloud Run Job) and connections
renew themselves; a user only has to reconnect when renewal genuinely fails
(they revoked access, or changed their Facebook password).

Run locally:  ``python -m src.sync.refresh_tokens``

Google Ads needs nothing here — its OAuth refresh token has no fixed expiry.

One authorization stores the *same* token on every ad account it granted, so
connections are grouped by token and each distinct token is renewed once, not
once per account. A renewed token is written back to every row that shared it,
preserving each row's status: a ``paused`` account must not silently become
``active`` (that would start syncing an account the user did not select).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from src.main import _redacted_identifier
from src.notifications.email_delivery import (
    SMTPEmailSender,
    load_smtp_email_config_from_env,
)
from src.storage.db import build_session_factory, create_db_engine, session_scope
from src.storage.models import PlatformConnection
from src.storage.repository import (
    get_workspace_owner_email,
    list_connections_due_for_renewal,
    read_connection_token,
    store_connection_token,
)
from src.web.ad_oauth import MetaAdsOAuthClient, summarize_oauth_http_error
from src.web.config import load_web_settings

# Renew this far ahead of expiry. Wide enough that a few consecutive failed runs
# (or a missed day) still leave room to recover before the token actually dies.
DEFAULT_RENEW_WITHIN_DAYS = 14

MAX_LOGGED_ERROR_CHARS = 200

# token -> (new_token, expires_in_seconds)
TokenRenewer = Callable[[str], tuple[str, int | None]]
# (recipient, subject, body) -> None
Notifier = Callable[[str, str, str], None]


@dataclass(frozen=True)
class RenewalResult:
    """Outcome of renewing one authorization (one token, N account rows)."""

    accounts: int
    status: str  # "renewed" | "failed"
    error: str = ""
    # Who to tell, and which accounts to name, when renewal failed.
    workspace_id: str = ""
    account_names: tuple[str, ...] = ()


def _log(event: str, **fields: object) -> None:
    payload = " ".join(f"{key}={value}" for key, value in fields.items())
    print(f"event={event} {payload}".strip(), flush=True)


def _group_by_token(
    connections: list[PlatformConnection], *, encryption_key: str | None
) -> dict[str, list[PlatformConnection]]:
    """Group connections by their decrypted token, skipping unreadable ones."""
    groups: dict[str, list[PlatformConnection]] = {}
    for connection in connections:
        try:
            token = read_connection_token(connection, key=encryption_key)
        except Exception:
            # An undecryptable token (e.g. the encryption key was rotated) is not
            # something renewal can fix; leave it for a human.
            _log(
                "token_renewal_unreadable",
                account_id=_redacted_identifier(connection.external_account_id),
            )
            continue
        if token:
            groups.setdefault(token, []).append(connection)
    return groups


def renew_meta_tokens(
    session: Session,
    *,
    renew: TokenRenewer,
    now: datetime,
    renew_within_days: int = DEFAULT_RENEW_WITHIN_DAYS,
    encryption_key: str | None = None,
) -> list[RenewalResult]:
    """Renew every Meta token close to expiry; one exchange per authorization."""
    cutoff = now + timedelta(days=renew_within_days)
    due = list_connections_due_for_renewal(session, platform="meta_ads", cutoff=cutoff)
    results: list[RenewalResult] = []

    for token, connections in _group_by_token(due, encryption_key=encryption_key).items():
        try:
            new_token, expires_in = renew(token)
        except Exception as exc:
            reason = _describe(exc)
            # The token can no longer be renewed; only a fresh authorization
            # fixes it, so stop syncing it and flag it for the user.
            for connection in connections:
                connection.status = "needs_reconnect"
                _log(
                    "token_renewal_failed",
                    account_id=_redacted_identifier(connection.external_account_id),
                    error=reason,
                )
            results.append(
                RenewalResult(
                    len(connections),
                    "failed",
                    reason,
                    workspace_id=connections[0].workspace_id,
                    account_names=tuple(
                        c.account_name or c.external_account_id for c in connections
                    ),
                )
            )
            continue

        expires_at = (
            now + timedelta(seconds=expires_in) if expires_in else None
        )
        for connection in connections:
            store_connection_token(
                connection,
                secret=new_token,
                key=encryption_key,
                expires_at=expires_at,
                # Keep the user's own selection: renewal must never promote a
                # paused account into the daily sync.
                mark_active=False,
            )
        _log(
            "token_renewed",
            accounts=len(connections),
            expires_at=expires_at.date().isoformat() if expires_at else "unknown",
        )
        results.append(RenewalResult(len(connections), "renewed"))

    return results


def notify_failures(
    results: list[RenewalResult],
    *,
    session: Session,
    send: Notifier,
    app_base_url: str = "",
) -> int:
    """Email each affected workspace owner that a connection needs reauthorizing.

    Returns how many emails were sent. Sending is best-effort: a mail failure is
    logged but never raises — the job's exit code already reports the renewal
    failure, and a dropped email must not roll back the status change alongside
    it.
    """
    by_workspace: dict[str, list[RenewalResult]] = {}
    for result in results:
        if result.status == "failed" and result.workspace_id:
            by_workspace.setdefault(result.workspace_id, []).append(result)

    sent = 0
    for workspace_id, failures in by_workspace.items():
        recipient = get_workspace_owner_email(session, workspace_id)
        if not recipient:
            _log("token_renewal_notify_skipped", reason="no_owner_email")
            continue
        names = [name for f in failures for name in f.account_names]
        try:
            send(recipient, _NOTIFY_SUBJECT, _notify_body(names, app_base_url))
        except Exception as exc:  # noqa: BLE001 - log the type only, never secrets
            _log("token_renewal_notify_failed", error=type(exc).__name__)
            continue
        _log("token_renewal_notified", accounts=len(names))
        sent += 1
    return sent


_NOTIFY_SUBJECT = "OudSeed｜Facebook 廣告連線需要重新授權"


def _notify_body(account_names: list[str], app_base_url: str) -> str:
    """Plain-text body telling the owner exactly what to do."""
    lines = [
        "以下廣告帳號的 Facebook 授權已無法自動續期，資料同步已暫停：",
        "",
        *(f"  • {name}" for name in account_names),
        "",
        "常見原因是你在 Facebook 撤銷了這個應用程式的權限，或變更了密碼。",
        "重新連接後就會恢復每日同步，過去的資料不受影響。",
        "",
    ]
    if app_base_url:
        lines += [f"重新連接：{app_base_url.rstrip('/')}/", ""]
    lines += ["-- ", "OudSeed"]
    return "\n".join(lines)


def _describe(exc: Exception) -> str:
    """Short, secret-free reason for a renewal failure."""
    if isinstance(exc, httpx.HTTPStatusError):
        return summarize_oauth_http_error(exc)[:MAX_LOGGED_ERROR_CHARS]
    return type(exc).__name__


def _build_notifier() -> Notifier:
    """Return a notifier backed by SMTP, or a no-op when mail isn't configured.

    Renewal must keep working on a deployment without SMTP settings; the missed
    notification is logged rather than crashing the run.
    """
    try:
        sender = SMTPEmailSender(load_smtp_email_config_from_env())
    except ValueError as exc:
        _log("token_renewal_notify_unconfigured", error=str(exc))
        return lambda recipient, subject, body: None

    def send(recipient: str, subject: str, body: str) -> None:
        sender.send(recipient=recipient, subject=subject, body=body)

    return send


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def main() -> None:
    """Renew Meta tokens nearing expiry; exit non-zero if any renewal failed."""
    load_dotenv()
    settings = load_web_settings()
    client = MetaAdsOAuthClient(
        app_id=settings.meta_app_id,
        app_secret=settings.meta_app_secret,
        redirect_uri=settings.meta_redirect_uri,
    )
    renew_within_days = _int_env("TOKEN_RENEW_WITHIN_DAYS", DEFAULT_RENEW_WITHIN_DAYS)

    engine = create_db_engine()
    session_factory = build_session_factory(engine)
    notified = 0
    with session_scope(session_factory) as session:
        results = renew_meta_tokens(
            session,
            renew=client.renew_long_lived,
            now=datetime.now(UTC),
            renew_within_days=renew_within_days,
            encryption_key=os.getenv("TOKEN_ENCRYPTION_KEY"),
        )
        if any(r.status == "failed" for r in results):
            notified = notify_failures(
                results,
                session=session,
                send=_build_notifier(),
                app_base_url=os.getenv("APP_BASE_URL", ""),
            )

    renewed = sum(1 for r in results if r.status == "renewed")
    failed = sum(1 for r in results if r.status == "failed")
    accounts_flagged = sum(r.accounts for r in results if r.status == "failed")
    print(
        "token_renewal_done=true "
        f"authorizations={len(results)} renewed={renewed} failed={failed} "
        f"accounts_needing_reconnect={accounts_flagged} notified={notified} "
        f"renew_within_days={renew_within_days}",
        flush=True,
    )

    # A failure here means a user must reauthorize — surface it as a red run
    # rather than letting the connection quietly rot until data stops arriving.
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
