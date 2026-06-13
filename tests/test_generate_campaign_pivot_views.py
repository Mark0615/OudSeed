"""Tests for the campaign-pivot view generator (spend + a column per conversion action)."""

from __future__ import annotations

from types import SimpleNamespace

from scripts.generate_campaign_pivot_views import (
    VIEW_PREFIX,
    _aliased_actions,
    _col_alias,
    build_pivot_ddl,
    generate,
    plan_pivot_views,
)

PROJECT = "proj"
DATASET = "ds"


class FakeJob:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def result(self) -> list[object]:
        return self._rows


class FakeClient:
    def __init__(self, account_ids: list[str], actions_by_account: dict[str, list[str]]) -> None:
        self.account_ids = account_ids
        self.actions_by_account = actions_by_account
        self.executed: list[str] = []

    def query(self, sql: str):  # noqa: ANN201 - test double
        self.executed.append(sql)
        upper = sql.strip().upper()
        if upper.startswith("SELECT DISTINCT ACCOUNT_ID"):
            return FakeJob([SimpleNamespace(account_id=a) for a in self.account_ids])
        if upper.startswith("SELECT DISTINCT CONVERSION_ACTION_NAME"):
            for acct, actions in self.actions_by_account.items():
                if f"account_id = '{acct}'" in sql:
                    return FakeJob([SimpleNamespace(conversion_action_name=n) for n in actions])
            return FakeJob([])
        return FakeJob([])  # DDL

    @property
    def ddl_statements(self) -> list[str]:
        return [s for s in self.executed if s.strip().upper().startswith("CREATE OR REPLACE VIEW")]


def _silent(_: str) -> None:
    return None


def test_col_alias_keeps_letters_cjk_and_digits() -> None:
    assert _col_alias("Request quote (LINE)", 1) == "conv_Request_quote_LINE"
    assert _col_alias("加入詢價車", 2) == "conv_加入詢價車"
    assert _col_alias("3. Contact (立即預約PV)", 4) == "conv_3_Contact_立即預約PV"
    # Nothing usable -> indexed fallback.
    assert _col_alias("!!!", 3) == "conv_action_3"


def test_aliased_actions_dedupes_collisions() -> None:
    pairs = _aliased_actions(["購買", "購買", "Lead"])
    aliases = [alias for _, alias in pairs]
    assert aliases == ["conv_購買", "conv_購買_2", "conv_Lead"]


def test_build_pivot_ddl_pivots_actions_into_columns() -> None:
    view_name, ddl = build_pivot_ddl(
        project_id=PROJECT,
        dataset_id=DATASET,
        account_id="333",
        action_names=["Request quote (LINE)", "加入詢價車"],
    )

    assert view_name == "vw_acct_google_campaign_pivot_333"
    # Additive delivery metrics come from the ad-level wide view, aggregated per campaign.
    assert "FROM `proj.ds.vw_looker_google_ads_wide`" in ddl
    assert "SUM(spend) AS spend" in ddl
    assert "SUM(impressions) AS impressions" in ddl
    assert "WHERE account_id = '333'" in ddl
    # One pivoted column per conversion action (each action's own total count).
    assert (
        "SUM(IF(conversion_action_name = 'Request quote (LINE)', all_conversions, 0)) "
        "AS `conv_Request_quote_LINE`" in ddl
    )
    assert "AS `conv_加入詢價車`" in ddl
    # Joined back to the ad grain so spend is not duplicated per action.
    assert "LEFT JOIN conv USING (date, account_id, campaign_id)" in ddl


def test_build_pivot_ddl_without_actions_is_still_valid() -> None:
    view_name, ddl = build_pivot_ddl(
        project_id=PROJECT, dataset_id=DATASET, account_id="333", action_names=[]
    )
    assert view_name == "vw_acct_google_campaign_pivot_333"
    assert "SUM(spend) AS spend" in ddl
    assert "conv AS (" not in ddl
    assert "LEFT JOIN" not in ddl


def test_plan_builds_one_pivot_view_per_account() -> None:
    client = FakeClient(
        account_ids=["333", "444"],
        actions_by_account={"333": ["購買", "Lead"], "444": []},
    )

    plans = plan_pivot_views(client, project_id=PROJECT, dataset_id=DATASET, log=_silent)

    names = [view_name for _, view_name, _ in plans]
    assert names == [
        "vw_acct_google_campaign_pivot_333",
        "vw_acct_google_campaign_pivot_444",
    ]
    ddl_333 = next(ddl for acct, _, ddl in plans if acct == "333")
    assert "AS `conv_購買`" in ddl_333


def test_dry_run_issues_no_ddl_and_apply_creates_views() -> None:
    client = FakeClient(account_ids=["333"], actions_by_account={"333": ["購買"]})

    generate(client, project_id=PROJECT, dataset_id=DATASET, apply=False, log=_silent)
    assert client.ddl_statements == []

    generate(client, project_id=PROJECT, dataset_id=DATASET, apply=True, log=_silent)
    assert len(client.ddl_statements) == 1
    assert VIEW_PREFIX in client.ddl_statements[0]


def test_output_redacts_account_ids() -> None:
    client = FakeClient(account_ids=["1234567890"], actions_by_account={"1234567890": ["購買"]})
    lines: list[str] = []

    generate(client, project_id=PROJECT, dataset_id=DATASET, apply=False, log=lines.append)

    output = "\n".join(lines)
    assert "1234567890" not in output
    assert "…7890" in output
