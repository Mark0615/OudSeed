"""Tests for the per-account Looker view generator."""

from __future__ import annotations

from types import SimpleNamespace

from scripts.generate_per_account_views import (
    VIEW_PREFIX,
    _safe_id,
    _view_name,
    generate,
    plan_per_account_views,
)

PROJECT = "proj"
DATASET = "ds"
SOURCES = {"meta": "vw_looker_meta_ads_wide", "google": "vw_looker_google_ads_wide"}


class FakeJob:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def result(self) -> list[object]:
        return self._rows


class FakeClient:
    """Returns distinct account ids per source view; records every SQL run."""

    def __init__(self, ids_by_view: dict[str, list[str]], *, raise_for: str | None = None) -> None:
        self.ids_by_view = ids_by_view
        self.raise_for = raise_for
        self.executed: list[str] = []

    def query(self, sql: str):  # noqa: ANN201 - test double
        self.executed.append(sql)
        if sql.strip().upper().startswith("SELECT DISTINCT"):
            for view, ids in self.ids_by_view.items():
                if view in sql:
                    if self.raise_for and self.raise_for in sql:
                        raise RuntimeError("view not found")
                    return FakeJob([SimpleNamespace(account_id=i) for i in ids])
            return FakeJob([])
        return FakeJob([])

    @property
    def ddl_statements(self) -> list[str]:
        return [s for s in self.executed if s.strip().upper().startswith("CREATE OR REPLACE VIEW")]


def _silent(_: str) -> None:
    return None


def test_safe_id_and_view_name_sanitize_identifiers() -> None:
    assert _safe_id("act_123-456") == "act_123_456"
    assert _view_name("meta", "act_123-456") == "vw_acct_meta_act_123_456"
    assert _view_name("google", "987654321") == "vw_acct_google_987654321"


def test_plan_builds_one_view_per_account_with_account_filter() -> None:
    client = FakeClient(
        {
            "vw_looker_meta_ads_wide": ["act_111", "act_222"],
            "vw_looker_google_ads_wide": ["333"],
        }
    )

    plans = plan_per_account_views(
        client, project_id=PROJECT, dataset_id=DATASET, source_views=SOURCES, log=_silent
    )

    names = [view_name for _, _, view_name, _ in plans]
    assert names == [
        "vw_acct_meta_act_111",
        "vw_acct_meta_act_222",
        "vw_acct_google_333",
    ]
    # Each DDL is a thin filter over the matching wide view for one account id.
    ddl_by_name = {view_name: ddl for _, _, view_name, ddl in plans}
    assert "WHERE account_id = 'act_111'" in ddl_by_name["vw_acct_meta_act_111"]
    assert "vw_looker_meta_ads_wide" in ddl_by_name["vw_acct_meta_act_111"]
    assert "WHERE account_id = '333'" in ddl_by_name["vw_acct_google_333"]
    assert "vw_looker_google_ads_wide" in ddl_by_name["vw_acct_google_333"]


def test_dry_run_does_not_issue_any_ddl() -> None:
    client = FakeClient({"vw_looker_meta_ads_wide": ["act_111"]})

    generate(
        client,
        project_id=PROJECT,
        dataset_id=DATASET,
        apply=False,
        source_views={"meta": "vw_looker_meta_ads_wide"},
        log=_silent,
    )

    assert client.ddl_statements == []


def test_apply_creates_one_view_per_account() -> None:
    client = FakeClient(
        {"vw_looker_meta_ads_wide": ["act_111", "act_222"]},
    )

    plans = generate(
        client,
        project_id=PROJECT,
        dataset_id=DATASET,
        apply=True,
        source_views={"meta": "vw_looker_meta_ads_wide"},
        log=_silent,
    )

    assert len(plans) == 2
    assert len(client.ddl_statements) == 2
    assert all(VIEW_PREFIX in ddl for ddl in client.ddl_statements)


def test_missing_source_view_is_skipped_not_fatal() -> None:
    client = FakeClient(
        {
            "vw_looker_meta_ads_wide": ["act_111"],
            "vw_looker_google_ads_wide": ["333"],
        },
        raise_for="vw_looker_google_ads_wide",
    )

    plans = plan_per_account_views(
        client, project_id=PROJECT, dataset_id=DATASET, source_views=SOURCES, log=_silent
    )

    # Google view errored -> skipped; Meta still planned.
    names = [view_name for _, _, view_name, _ in plans]
    assert names == ["vw_acct_meta_act_111"]


def test_output_redacts_full_account_ids() -> None:
    client = FakeClient({"vw_looker_meta_ads_wide": ["act_1354683164620230"]})
    lines: list[str] = []

    generate(
        client,
        project_id=PROJECT,
        dataset_id=DATASET,
        apply=False,
        source_views={"meta": "vw_looker_meta_ads_wide"},
        log=lines.append,
    )

    output = "\n".join(lines)
    # The full account id never appears in printed output (only a redacted tail).
    assert "act_1354683164620230" not in output
    assert "…0230" in output
