"""SQLAlchemy ORM models for tenant identity and membership.

Slice 1 covers users, workspaces, and membership. Later slices add platform
connections (with encrypted tokens), clients/accounts, and report schedules.
Sync data and report logs stay in BigQuery and are referenced by id only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all storage models."""


def _new_id() -> str:
    """Return a compact, URL-safe unique id."""
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class User(Base):
    """A person who signed in to the product (via Google sign-in)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    # Google's stable subject identifier; the durable key for sign-in.
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    memberships: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Workspace(Base):
    """An account space that owns connections, clients, and schedules."""

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(255))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    members: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMember(Base):
    """Membership linking a user to a workspace with a role."""

    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    # "owner" or "member"; owners are created with the workspace.
    role: Mapped[str] = mapped_column(String(32), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


# Supported ad platforms for a connection.
SUPPORTED_PLATFORMS = ("meta_ads", "google_ads")

# Connection lifecycle states.
# "active" = selected for sync; "paused" = connected but not selected for sync;
# "needs_reconnect" = the stored token can no longer be renewed (revoked, or the
# user changed their password), so only a fresh authorization can fix it.
CONNECTION_STATUSES = (
    "pending",
    "active",
    "paused",
    "error",
    "revoked",
    "needs_reconnect",
)


class PlatformConnection(Base):
    """A workspace's authorized link to one ad-platform account.

    The OAuth token is stored encrypted (``encrypted_token``); plaintext never
    touches the database. Use the repository helpers to set/read the token.
    """

    __tablename__ = "platform_connections"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "platform",
            "external_account_id",
            name="uq_workspace_platform_account",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    # One of SUPPORTED_PLATFORMS.
    platform: Mapped[str] = mapped_column(String(32), index=True)
    # The platform's ad account / customer id (e.g. act_123, 1234567890).
    external_account_id: Mapped[str] = mapped_column(String(128))
    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # One of CONNECTION_STATUSES.
    status: Mapped[str] = mapped_column(String(32), default="pending")
    # Fernet-encrypted token blob; None until authorization completes.
    encrypted_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    workspace: Mapped[Workspace] = relationship()


# Report cadence and depth vocabularies (mirror config + src/ai/report_schedules).
REPORT_TYPES = ("weekly", "monthly")
REPORT_DEPTHS = ("brief", "standard", "deep")

# Customer-facing export destinations (where the data lands). Internally the
# product always stages in BigQuery; these are what the customer chooses to
# export to — "bigquery" here means the customer's own BigQuery.
SUPPORTED_DESTINATIONS = ("bigquery", "data_studio", "google_sheets")


class Client(Base):
    """A report-grouping customer within a workspace.

    One client may bind several platform connections (e.g. Meta + Google) so they
    are combined into a single account-grouped report. ``client_key`` is the
    stable id used across config and BigQuery (`client_id`).
    """

    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("workspace_id", "client_key", name="uq_workspace_client_key"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    client_key: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    accounts: Mapped[list[ClientAccount]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    report_schedules: Mapped[list[ReportSchedule]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    destinations: Mapped[list[ClientDestination]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )


class ClientAccount(Base):
    """Binds a platform connection (ad account) to a client for reporting."""

    __tablename__ = "client_accounts"
    __table_args__ = (
        UniqueConstraint(
            "client_id", "platform_connection_id", name="uq_client_account"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    platform_connection_id: Mapped[str] = mapped_column(
        ForeignKey("platform_connections.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    client: Mapped[Client] = relationship(back_populates="accounts")
    connection: Mapped[PlatformConnection] = relationship()


class ClientDestination(Base):
    """A data-export destination the customer selected for a client.

    ``kind`` is one of SUPPORTED_DESTINATIONS. Export connectors themselves are
    built later; for now this records the customer's chosen landing spots.
    """

    __tablename__ = "client_destinations"
    __table_args__ = (
        UniqueConstraint("client_id", "kind", name="uq_client_destination"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    client: Mapped[Client] = relationship(back_populates="destinations")


class ReportSchedule(Base):
    """A client's AI report schedule (cadence, delivery day, recipient).

    The recipient email is stored encrypted (``encrypted_email_to``).
    ``delivery_day`` is a string to hold both monthly day-of-month ("10") and
    weekly weekday ("monday"), matching the existing config vocabulary.
    """

    __tablename__ = "report_schedules"
    __table_args__ = (
        UniqueConstraint("client_id", "schedule_key", name="uq_client_schedule_key"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    schedule_key: Mapped[str] = mapped_column(String(128))
    report_type: Mapped[str] = mapped_column(String(16))
    delivery_day: Mapped[str] = mapped_column(String(16))
    channel: Mapped[str] = mapped_column(String(32), default="email")
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    depth: Mapped[str] = mapped_column(String(16), default="standard")
    encrypted_email_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_group_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    account_group_limit: Mapped[int | None] = mapped_column(nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    client: Mapped[Client] = relationship(back_populates="report_schedules")
