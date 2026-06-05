"""Thin repository functions over the storage models.

These take an active :class:`~sqlalchemy.orm.Session` and never commit; callers
manage the transaction (e.g. via :func:`src.storage.db.session_scope`). All
workspace-scoped reads require a ``workspace_id`` to keep tenants isolated.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.crypto import decrypt_secret, encrypt_secret
from src.storage.models import (
    CONNECTION_STATUSES,
    SUPPORTED_PLATFORMS,
    PlatformConnection,
    User,
    Workspace,
    WorkspaceMember,
)


def get_user_by_google_sub(session: Session, google_sub: str) -> User | None:
    """Return the user with the given Google subject id, or None."""
    return session.scalar(select(User).where(User.google_sub == google_sub))


def upsert_user_by_google_sub(
    session: Session, *, google_sub: str, email: str, name: str | None = None
) -> User:
    """Return the existing user for a Google sign-in, creating it if new.

    Refreshes email/name on each sign-in so profile changes are reflected.
    """
    user = get_user_by_google_sub(session, google_sub)
    if user is None:
        user = User(google_sub=google_sub, email=email, name=name)
        session.add(user)
        session.flush()
        return user
    user.email = email
    user.name = name
    session.flush()
    return user


def create_workspace(session: Session, *, name: str, owner: User) -> Workspace:
    """Create a workspace owned by ``owner`` and add the owner as a member."""
    workspace = Workspace(name=name, owner_user_id=owner.id)
    session.add(workspace)
    session.flush()
    session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner")
    )
    session.flush()
    return workspace


def add_member(
    session: Session, *, workspace: Workspace, user: User, role: str = "member"
) -> WorkspaceMember:
    """Add a user to a workspace with the given role."""
    member = WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=role)
    session.add(member)
    session.flush()
    return member


def list_workspaces_for_user(session: Session, user_id: str) -> list[Workspace]:
    """Return all workspaces the user belongs to, oldest first."""
    stmt = (
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user_id)
        .order_by(Workspace.created_at, Workspace.id)
    )
    return list(session.scalars(stmt))


def list_members(session: Session, workspace_id: str) -> list[WorkspaceMember]:
    """Return all members of a workspace, oldest first."""
    stmt = (
        select(WorkspaceMember)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.created_at, WorkspaceMember.id)
    )
    return list(session.scalars(stmt))


# --- Platform connections -------------------------------------------------


def create_platform_connection(
    session: Session,
    *,
    workspace_id: str,
    platform: str,
    external_account_id: str,
    account_name: str | None = None,
    status: str = "pending",
) -> PlatformConnection:
    """Create a platform connection (without a token yet).

    Raises ValueError for an unsupported platform or status.
    """
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"Unsupported platform: {platform!r}")
    if status not in CONNECTION_STATUSES:
        raise ValueError(f"Unsupported connection status: {status!r}")
    connection = PlatformConnection(
        workspace_id=workspace_id,
        platform=platform,
        external_account_id=external_account_id,
        account_name=account_name,
        status=status,
    )
    session.add(connection)
    session.flush()
    return connection


def store_connection_token(
    connection: PlatformConnection,
    *,
    secret: str,
    key: str | None = None,
    expires_at: datetime | None = None,
    scopes: str | None = None,
    mark_active: bool = True,
) -> None:
    """Encrypt and store an OAuth token on a connection.

    The plaintext ``secret`` is encrypted before it is written; it never reaches
    the database. By default the connection is marked ``active``.
    """
    connection.encrypted_token = encrypt_secret(secret, key=key)
    if expires_at is not None:
        connection.token_expires_at = expires_at
    if scopes is not None:
        connection.scopes = scopes
    if mark_active:
        connection.status = "active"


def read_connection_token(
    connection: PlatformConnection, *, key: str | None = None
) -> str | None:
    """Return the decrypted token, or None when the connection has none."""
    if not connection.encrypted_token:
        return None
    return decrypt_secret(connection.encrypted_token, key=key)


def get_connection(session: Session, connection_id: str) -> PlatformConnection | None:
    """Return a connection by id, or None."""
    return session.get(PlatformConnection, connection_id)


def list_connections(
    session: Session, workspace_id: str, *, platform: str | None = None
) -> list[PlatformConnection]:
    """Return a workspace's connections, optionally filtered by platform."""
    stmt = select(PlatformConnection).where(
        PlatformConnection.workspace_id == workspace_id
    )
    if platform is not None:
        stmt = stmt.where(PlatformConnection.platform == platform)
    stmt = stmt.order_by(PlatformConnection.created_at, PlatformConnection.id)
    return list(session.scalars(stmt))
