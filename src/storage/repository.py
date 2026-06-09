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
    REPORT_DEPTHS,
    REPORT_TYPES,
    SUPPORTED_DESTINATIONS,
    SUPPORTED_PLATFORMS,
    Client,
    ClientAccount,
    ClientDestination,
    PlatformConnection,
    ReportSchedule,
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


def list_all_workspaces(session: Session) -> list[Workspace]:
    """Return every workspace, oldest first (for cross-tenant batch jobs)."""
    stmt = select(Workspace).order_by(Workspace.created_at, Workspace.id)
    return list(session.scalars(stmt))


def get_or_create_default_workspace(session: Session, user: User) -> Workspace:
    """Return the user's first workspace, creating one if they have none."""
    existing = list_workspaces_for_user(session, user.id)
    if existing:
        return existing[0]
    label = user.name or user.email
    return create_workspace(session, name=f"{label}'s workspace", owner=user)


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


def upsert_platform_connection(
    session: Session,
    *,
    workspace_id: str,
    platform: str,
    external_account_id: str,
    account_name: str | None = None,
    token: str | None = None,
    key: str | None = None,
    scopes: str | None = None,
    expires_at: datetime | None = None,
    mark_active: bool = True,
) -> PlatformConnection:
    """Create or update a connection for (workspace, platform, account).

    If a token is provided it is encrypted. When ``mark_active`` is true the
    connection is marked active (selected for sync); when false a newly created
    connection is left ``paused`` (connected but not selected) and an existing
    connection keeps its current selection status. Re-authorizing an existing
    account refreshes its token in place.
    """
    existing = session.scalar(
        select(PlatformConnection).where(
            PlatformConnection.workspace_id == workspace_id,
            PlatformConnection.platform == platform,
            PlatformConnection.external_account_id == external_account_id,
        )
    )
    is_new = existing is None
    if is_new:
        connection = create_platform_connection(
            session,
            workspace_id=workspace_id,
            platform=platform,
            external_account_id=external_account_id,
            account_name=account_name,
        )
    else:
        connection = existing
        if account_name:
            connection.account_name = account_name

    if token:
        store_connection_token(
            connection,
            secret=token,
            key=key,
            scopes=scopes,
            expires_at=expires_at,
            mark_active=mark_active,
        )
    # New connections that aren't auto-activated start "paused": connected but
    # not selected for sync, so the user opts in explicitly.
    if is_new and not mark_active:
        connection.status = "paused"
    session.flush()
    return connection


def set_account_selection(
    session: Session,
    *,
    workspace_id: str,
    platform: str,
    selected_external_ids: list[str],
) -> list[PlatformConnection]:
    """Mark selected accounts active and the rest paused, for one platform.

    Revoked connections are left untouched. Returns the platform's connections.
    """
    selected = set(selected_external_ids)
    connections = list_connections(session, workspace_id, platform=platform)
    for connection in connections:
        if connection.status == "revoked":
            continue
        connection.status = (
            "active" if connection.external_account_id in selected else "paused"
        )
    session.flush()
    return connections


# --- Clients, account bindings, report schedules --------------------------


def create_client(
    session: Session, *, workspace_id: str, client_key: str, name: str
) -> Client:
    """Create a report-grouping client within a workspace."""
    client = Client(workspace_id=workspace_id, client_key=client_key, name=name)
    session.add(client)
    session.flush()
    return client


def list_clients(session: Session, workspace_id: str) -> list[Client]:
    """Return a workspace's clients, oldest first."""
    stmt = (
        select(Client)
        .where(Client.workspace_id == workspace_id)
        .order_by(Client.created_at, Client.id)
    )
    return list(session.scalars(stmt))


def get_or_create_default_client(
    session: Session, workspace: Workspace, *, name: str | None = None
) -> Client:
    """Return the workspace's first client, creating a default one if none exist.

    Onboarding groups a workspace's selected accounts into one default client.
    ``client_key`` is stable so exported config / BigQuery ``client_id`` agree.
    """
    existing = list_clients(session, workspace.id)
    if existing:
        return existing[0]
    return create_client(
        session,
        workspace_id=workspace.id,
        client_key="default",
        name=name or workspace.name,
    )


def bind_connections_to_client(
    session: Session, *, client: Client, connections: list[PlatformConnection]
) -> list[ClientAccount]:
    """Bind any not-yet-bound connections to the client (idempotent)."""
    existing_ids = {
        b.platform_connection_id for b in list_client_accounts(session, client.id)
    }
    created: list[ClientAccount] = []
    for connection in connections:
        if connection.id in existing_ids:
            continue
        created.append(bind_account(session, client=client, connection=connection))
    return created


def list_client_destinations(
    session: Session, client_id: str
) -> list[ClientDestination]:
    """Return a client's export destinations, oldest first."""
    stmt = (
        select(ClientDestination)
        .where(ClientDestination.client_id == client_id)
        .order_by(ClientDestination.created_at, ClientDestination.id)
    )
    return list(session.scalars(stmt))


def set_client_destinations(
    session: Session, *, client: Client, selected_kinds: list[str]
) -> list[ClientDestination]:
    """Enable the selected export destinations and disable the rest.

    Rows are created on first selection and toggled on re-save (idempotent).
    Unsupported kinds are ignored. Returns the client's destination rows.
    """
    selected = {k for k in selected_kinds if k in SUPPORTED_DESTINATIONS}
    existing = {d.kind: d for d in list_client_destinations(session, client.id)}
    for kind in SUPPORTED_DESTINATIONS:
        chosen = kind in selected
        if kind in existing:
            existing[kind].enabled = chosen
        elif chosen:
            session.add(ClientDestination(client_id=client.id, kind=kind, enabled=True))
    session.flush()
    return list_client_destinations(session, client.id)


def bind_account(
    session: Session, *, client: Client, connection: PlatformConnection
) -> ClientAccount:
    """Bind a platform connection to a client for reporting.

    Both must belong to the same workspace (tenant isolation).
    """
    if client.workspace_id != connection.workspace_id:
        raise ValueError("Cannot bind a connection from a different workspace.")
    binding = ClientAccount(client_id=client.id, platform_connection_id=connection.id)
    session.add(binding)
    session.flush()
    return binding


def list_client_accounts(session: Session, client_id: str) -> list[ClientAccount]:
    """Return the account bindings for a client, oldest first."""
    stmt = (
        select(ClientAccount)
        .where(ClientAccount.client_id == client_id)
        .order_by(ClientAccount.created_at, ClientAccount.id)
    )
    return list(session.scalars(stmt))


def create_report_schedule(
    session: Session,
    *,
    client_id: str,
    schedule_key: str,
    report_type: str,
    delivery_day: str,
    channel: str = "email",
    timezone: str | None = None,
    depth: str = "standard",
    email_to: str | None = None,
    key: str | None = None,
    account_group_name: str | None = None,
    account_group_limit: int | None = None,
    enabled: bool = True,
) -> ReportSchedule:
    """Create a client report schedule; the recipient email is encrypted.

    Raises ValueError for an unsupported report type or depth.
    """
    if report_type not in REPORT_TYPES:
        raise ValueError(f"Unsupported report_type: {report_type!r}")
    if depth not in REPORT_DEPTHS:
        raise ValueError(f"Unsupported depth: {depth!r}")
    schedule = ReportSchedule(
        client_id=client_id,
        schedule_key=schedule_key,
        report_type=report_type,
        delivery_day=str(delivery_day),
        channel=channel,
        timezone=timezone,
        depth=depth,
        encrypted_email_to=encrypt_secret(email_to, key=key) if email_to else None,
        account_group_name=account_group_name,
        account_group_limit=account_group_limit,
        enabled=enabled,
    )
    session.add(schedule)
    session.flush()
    return schedule


def upsert_report_schedule(
    session: Session,
    *,
    client_id: str,
    schedule_key: str,
    report_type: str,
    delivery_day: str,
    channel: str = "email",
    timezone: str | None = None,
    depth: str = "standard",
    email_to: str | None = None,
    key: str | None = None,
    enabled: bool = True,
) -> ReportSchedule:
    """Create or update a client's report schedule, keyed by ``schedule_key``.

    Used by onboarding so re-saving the destination updates the existing schedule
    in place instead of duplicating. The recipient email is encrypted. Raises
    ValueError for an unsupported report type or depth.
    """
    if report_type not in REPORT_TYPES:
        raise ValueError(f"Unsupported report_type: {report_type!r}")
    if depth not in REPORT_DEPTHS:
        raise ValueError(f"Unsupported depth: {depth!r}")
    existing = session.scalar(
        select(ReportSchedule).where(
            ReportSchedule.client_id == client_id,
            ReportSchedule.schedule_key == schedule_key,
        )
    )
    if existing is None:
        return create_report_schedule(
            session,
            client_id=client_id,
            schedule_key=schedule_key,
            report_type=report_type,
            delivery_day=delivery_day,
            channel=channel,
            timezone=timezone,
            depth=depth,
            email_to=email_to,
            key=key,
            enabled=enabled,
        )
    existing.report_type = report_type
    existing.delivery_day = str(delivery_day)
    existing.channel = channel
    existing.timezone = timezone
    existing.depth = depth
    existing.enabled = enabled
    existing.encrypted_email_to = (
        encrypt_secret(email_to, key=key) if email_to else None
    )
    session.flush()
    return existing


def read_schedule_email_to(
    schedule: ReportSchedule, *, key: str | None = None
) -> str | None:
    """Return the decrypted recipient email, or None when unset."""
    if not schedule.encrypted_email_to:
        return None
    return decrypt_secret(schedule.encrypted_email_to, key=key)


def list_report_schedules(session: Session, client_id: str) -> list[ReportSchedule]:
    """Return a client's report schedules, oldest first."""
    stmt = (
        select(ReportSchedule)
        .where(ReportSchedule.client_id == client_id)
        .order_by(ReportSchedule.created_at, ReportSchedule.id)
    )
    return list(session.scalars(stmt))
