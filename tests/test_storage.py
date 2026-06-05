"""Tests for the durable storage skeleton (users, workspaces, membership).

These run on in-memory SQLite, so they need no credentials or running server.
"""

import pytest

from src.storage.db import build_session_factory, create_all, create_db_engine, session_scope
from src.storage.models import User
from src.storage.repository import (
    add_member,
    create_workspace,
    get_user_by_google_sub,
    list_members,
    list_workspaces_for_user,
    upsert_user_by_google_sub,
)


@pytest.fixture
def session_factory():
    """An isolated in-memory SQLite database per test."""
    engine = create_db_engine("sqlite://")
    create_all(engine)
    return build_session_factory(engine)


def test_upsert_user_creates_then_returns_same_user(session_factory):
    with session_scope(session_factory) as session:
        created = upsert_user_by_google_sub(
            session, google_sub="g-1", email="a@example.com", name="A"
        )
        created_id = created.id

    with session_scope(session_factory) as session:
        again = upsert_user_by_google_sub(
            session, google_sub="g-1", email="a@example.com", name="A"
        )
        assert again.id == created_id


def test_upsert_user_refreshes_profile_on_sign_in(session_factory):
    with session_scope(session_factory) as session:
        upsert_user_by_google_sub(session, google_sub="g-1", email="old@example.com", name="Old")

    with session_scope(session_factory) as session:
        updated = upsert_user_by_google_sub(
            session, google_sub="g-1", email="new@example.com", name="New"
        )
        assert updated.email == "new@example.com"
        assert updated.name == "New"


def test_google_sub_is_unique(session_factory):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), session_scope(session_factory) as session:
        session.add(User(google_sub="dup", email="a@example.com"))
        session.add(User(google_sub="dup", email="b@example.com"))


def test_create_workspace_adds_owner_as_member(session_factory):
    with session_scope(session_factory) as session:
        owner = upsert_user_by_google_sub(session, google_sub="g-1", email="o@example.com")
        workspace = create_workspace(session, name="Acme", owner=owner)

        members = list_members(session, workspace.id)
        assert len(members) == 1
        assert members[0].user_id == owner.id
        assert members[0].role == "owner"


def test_list_workspaces_scoped_to_user(session_factory):
    with session_scope(session_factory) as session:
        owner = upsert_user_by_google_sub(session, google_sub="owner", email="o@example.com")
        other = upsert_user_by_google_sub(session, google_sub="other", email="x@example.com")
        ws_a = create_workspace(session, name="A", owner=owner)
        create_workspace(session, name="B", owner=other)
        add_member(session, workspace=ws_a, user=other)

        owner_ids = {w.id for w in list_workspaces_for_user(session, owner.id)}
        other_ids = {w.id for w in list_workspaces_for_user(session, other.id)}

        assert owner_ids == {ws_a.id}
        assert ws_a.id in other_ids
        assert len(other_ids) == 2


def test_get_user_by_google_sub_returns_none_when_absent(session_factory):
    with session_scope(session_factory) as session:
        assert get_user_by_google_sub(session, "missing") is None
