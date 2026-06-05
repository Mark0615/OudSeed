"""Thin repository functions over the storage models.

These take an active :class:`~sqlalchemy.orm.Session` and never commit; callers
manage the transaction (e.g. via :func:`src.storage.db.session_scope`). All
workspace-scoped reads require a ``workspace_id`` to keep tenants isolated.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.storage.models import User, Workspace, WorkspaceMember


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
