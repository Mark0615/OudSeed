"""Generate and email account-name grouped AI reports."""

from __future__ import annotations

import html
import os
import re
from typing import Any

from dotenv import load_dotenv
from google.cloud import bigquery

from src.ai.generate_report import _first_enabled_client_id, _load_runtime_config, _report_type
from src.ai.openai_client import OpenAITextClient
from src.ai.report_schedules import ReportSchedule, find_report_schedule
from src.ai.report_generator import generate_and_log_report
from src.destinations.bigquery import BigQueryDestination
from src.notifications.email_delivery import SMTPEmailSender, load_smtp_email_config_from_env
from src.utils.date_utils import get_default_report_period_start, get_scheduled_report_period_start


def main() -> None:
    """Generate account-grouped reports and send one email per account group."""
    load_dotenv()
    config = _load_runtime_config()
    destination = _destination_from_config(config)
    schedule = find_report_schedule(config, os.getenv("AI_REPORT_SCHEDULE_ID"))
    report_type = _report_type(
        _schedule_value(schedule, "report_type") or os.getenv("AI_REPORT_TYPE") or "monthly"
    )
    timezone_name = (
        _schedule_value(schedule, "timezone")
        or os.getenv("AI_REPORT_TIMEZONE")
        or config.get("defaults", {}).get("timezone", "Asia/Taipei")
    )
    period_start_date = os.getenv("AI_REPORT_PERIOD_START_DATE") or _default_period_start(
        report_type=report_type,
        timezone=timezone_name,
        schedule=schedule,
    )
    client_id = _schedule_value(schedule, "client_id") or os.getenv("AI_REPORT_CLIENT_ID") or _first_enabled_client_id(config)
    limit = _positive_int_env("AI_REPORT_LIMIT", 50)
    account_group_name = os.getenv("AI_REPORT_ACCOUNT_GROUP_NAME") or _schedule_value(schedule, "account_group_name")
    account_group_limit = _optional_positive_int_env("AI_REPORT_ACCOUNT_GROUP_LIMIT")
    if account_group_limit is None:
        account_group_limit = _schedule_value(schedule, "account_group_limit")
    list_account_groups = _bool_env("AI_REPORT_LIST_ACCOUNT_GROUPS", False)
    report_depth = _report_depth(os.getenv("AI_REPORT_DEPTH") or _schedule_value(schedule, "depth") or "standard")
    max_output_tokens = _positive_int_env("OPENAI_MAX_OUTPUT_TOKENS", 5000)
    openai_timeout_seconds = _positive_int_env("OPENAI_TIMEOUT_SECONDS", 120)

    groups = discover_account_report_groups(
        destination=destination,
        report_type=report_type,
        workspace_id=config["workspace_id"],
        client_id=client_id,
        period_start_date=period_start_date,
    )
    if not groups:
        raise ValueError("No account groups found for the requested report period.")
    groups = _filter_report_groups(groups, account_group_name)
    groups = _limit_report_groups(groups, account_group_limit)
    if list_account_groups:
        for line in _format_report_group_lines(
            groups=groups,
            report_type=report_type,
            period_start_date=period_start_date,
        ):
            print(line)
        return

    recipient = os.getenv("AI_REPORT_EMAIL_TO") or _schedule_value(schedule, "email_to")
    if not recipient:
        raise ValueError("Missing required environment variable or schedule value: AI_REPORT_EMAIL_TO")
    openai_client = OpenAITextClient(
        api_key=_required_env("OPENAI_API_KEY"),
        model=os.getenv("OPENAI_MODEL", "gpt-5.2"),
        reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "medium"),
        timeout_seconds=openai_timeout_seconds,
    )
    sender = SMTPEmailSender(load_smtp_email_config_from_env())

    for group in groups:
        result = generate_and_log_report(
            destination=destination,
            openai_client=openai_client,
            report_type=report_type,
            workspace_id=config["workspace_id"],
            client_id=client_id,
            period_start_date=period_start_date,
            account_ids=group["account_ids"],
            limit=limit,
            max_output_tokens=max_output_tokens,
            report_depth=report_depth,
        )
        subject = _default_subject(
            report_type=report_type,
            account_group_name=group["account_group_name"],
            period_start_date=period_start_date,
        )
        body = _format_text_email(
            report_id=result["report_id"],
            client_id=client_id,
            context=result["context"],
            report_text=result["report_text"],
        )
        html_body = format_html_email(
            report_id=result["report_id"],
            client_id=client_id,
            context=result["context"],
            report_text=result["report_text"],
            account_group_name=group["account_group_name"],
        )
        sender.send(
            recipient=recipient,
            subject=subject,
            body=body,
            html_body=html_body,
        )
        print(
            "account_report_email_sent=true "
            f"report_id={result['report_id']} account_group={group['account_group_name']} "
            f"recipient={recipient}"
        )


def discover_account_report_groups(
    destination: BigQueryDestination,
    report_type: str,
    workspace_id: str,
    client_id: str,
    period_start_date: str,
) -> list[dict[str, Any]]:
    """Discover report groups by account_name for a report period."""
    if report_type == "weekly":
        view_name = "vw_looker_ads_campaign_weekly"
        start_field = "week_start_date"
    else:
        view_name = "vw_looker_ads_campaign_monthly"
        start_field = "month_start_date"

    query = f"""
    SELECT
      COALESCE(NULLIF(account_name, ''), account_id) AS account_group_name,
      ARRAY_AGG(DISTINCT account_id IGNORE NULLS ORDER BY account_id) AS account_ids,
      ARRAY_AGG(DISTINCT platform IGNORE NULLS ORDER BY platform) AS platforms
    FROM `{destination._table_id(view_name)}`
    WHERE {start_field} = @period_start_date
      AND workspace_id = @workspace_id
      AND client_id = @client_id
    GROUP BY account_group_name
    ORDER BY account_group_name
    """
    rows = destination.query_rows(
        query,
        query_parameters=[
            bigquery.ScalarQueryParameter("period_start_date", "DATE", period_start_date),
            bigquery.ScalarQueryParameter("workspace_id", "STRING", workspace_id),
            bigquery.ScalarQueryParameter("client_id", "STRING", client_id),
        ],
    )
    return [
        {
            "account_group_name": row["account_group_name"],
            "account_ids": list(row["account_ids"]),
            "platforms": list(row["platforms"]),
        }
        for row in rows
        if row.get("account_ids")
    ]


def _limit_report_groups(
    groups: list[dict[str, Any]],
    limit: int | None,
) -> list[dict[str, Any]]:
    """Return at most limit account groups for safe one-off test sends."""
    if limit is None:
        return groups
    return groups[:limit]


def _filter_report_groups(
    groups: list[dict[str, Any]],
    account_group_name: str | None,
) -> list[dict[str, Any]]:
    """Return account groups matching an explicit account-group name."""
    if not account_group_name:
        return groups

    matches = [
        group
        for group in groups
        if group.get("account_group_name") == account_group_name
    ]
    if not matches:
        available = ", ".join(str(group.get("account_group_name")) for group in groups)
        raise ValueError(
            "No account group matched AI_REPORT_ACCOUNT_GROUP_NAME="
            f"{account_group_name!r}. Available account groups: {available}"
        )
    return matches


def _format_report_group_lines(
    groups: list[dict[str, Any]],
    report_type: str,
    period_start_date: str,
) -> list[str]:
    """Return printable account-group summary lines without exposing account ids."""
    lines = [
        "account_report_groups=true "
        f"report_type={report_type} period_start_date={period_start_date} "
        f"group_count={len(groups)}"
    ]
    for index, group in enumerate(groups, start=1):
        platforms = ",".join(str(platform) for platform in group.get("platforms", []))
        lines.append(
            "account_report_group="
            f"{index} name={group.get('account_group_name')} "
            f"platforms={platforms or '-'} "
            f"account_count={len(group.get('account_ids', []))}"
        )
    return lines


def format_html_email(
    report_id: str,
    client_id: str,
    context: dict[str, Any],
    report_text: str,
    account_group_name: str,
) -> str:
    """Build an HTML email with campaign tables and rendered insights."""
    sections = []
    for platform in _platforms(context):
        sections.append(f"<h2>{html.escape(_platform_label(platform))}</h2>")
        sections.append(_campaign_table_html(context, platform))
        sections.append(_diagnostics_html(context, platform))
        sections.append("<h3>Insight</h3>")
    sections.append(_render_report_text_html(report_text))

    return f"""<!doctype html>
<html>
<body style="margin:0;padding:0;background:#ffffff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,'PingFang TC','Microsoft JhengHei',sans-serif;color:#1f2937;line-height:1.65;">
  <div style="padding:24px 28px 32px;background:#ffffff;">
    <div style="padding:0 0 18px;border-bottom:1px solid #e5dccb;margin-bottom:22px;">
      <div style="font-size:11px;letter-spacing:1.8px;text-transform:uppercase;color:#b45309;font-weight:700;margin-bottom:10px;">OudSeed Ads Intelligence</div>
      <h1 style="font-size:26px;line-height:1.25;margin:0 0 12px;color:#111827;">OudSeed 廣告成效報告｜{html.escape(account_group_name)}</h1>
      <p style="margin:0;color:#6b7280;font-size:13px;">
        Report ID: {html.escape(report_id)}<br>
        Client: {html.escape(client_id)}<br>
        Period: {html.escape(str(context.get("period_start_date")))} - {html.escape(str(context.get("period_end_date")))}
      </p>
    </div>
    {''.join(sections)}
  </div>
</body>
</html>"""


def _campaign_table_html(context: dict[str, Any], platform: str) -> str:
    rows = [row for row in context.get("campaigns", []) if row.get("platform") == platform]
    totals = _sum_campaign_rows(rows)
    table_rows = rows + [{"campaign_name": "總計", **totals}]
    body = "".join(_campaign_table_row_html(row, is_total=row.get("campaign_name") == "總計") for row in table_rows)
    return f"""
<div style="overflow-x:auto;width:100%;margin:8px 0 20px;">
<table style="border-collapse:collapse;width:100%;min-width:980px;font-size:13px;">
  <thead>
    <tr style="background:#f3f4f6;">
      <th style="{_th()}">Campaign name</th>
      <th style="{_th()}">Spent</th>
      <th style="{_th()}">Clicks</th>
      <th style="{_th()}">CPC</th>
      <th style="{_th()}">CPM</th>
      <th style="{_th()}">Add to cart</th>
      <th style="{_th()}">CPA(add_to_cart)</th>
      <th style="{_th()}">Purchase</th>
      <th style="{_th()}">CPA(purchase)</th>
      <th style="{_th()}">Purchase value</th>
      <th style="{_th()}">ROAS</th>
    </tr>
  </thead>
  <tbody>{body}</tbody>
</table>
</div>"""


def _diagnostics_html(context: dict[str, Any], platform: str) -> str:
    """Render deterministic diagnostics before the model-written insight."""
    diagnostics = context.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return ""

    parts = [
        "<h3 style='font-size:18px;line-height:1.35;margin:18px 0 10px;color:#111827;font-weight:800;'>"
        "診斷重點</h3>"
    ]
    metric_table = _diagnostic_metric_table_html(diagnostics)
    if metric_table:
        parts.append(metric_table)

    anomalies = _platform_rows(diagnostics.get("anomalies"), platform)
    if anomalies:
        parts.append(_diagnostic_warning_html(anomalies[:4]))

    contribution_rows = _diagnostic_contribution_rows(diagnostics, platform)
    if contribution_rows:
        parts.append(_diagnostic_contribution_table_html(contribution_rows[:6]))

    if len(parts) == 1:
        return ""
    return "\n".join(parts)


def _diagnostic_metric_table_html(diagnostics: dict[str, Any]) -> str:
    metric_changes = diagnostics.get("metric_changes")
    if not isinstance(metric_changes, dict):
        return ""

    rows = []
    for metric, label in (("cpc", "CPC"), ("cpa", "CPA"), ("roas", "ROAS")):
        change = metric_changes.get(metric)
        if not isinstance(change, dict):
            continue
        current = change.get("current")
        previous = change.get("previous")
        delta = change.get("delta")
        rows.append(
            "<tr>"
            f"<td style='{_td()}'>{label}</td>"
            f"<td style='{_td_num()}'>{_diagnostic_value(metric, current)}</td>"
            f"<td style='{_td_num()}'>{_diagnostic_value(metric, previous)}</td>"
            f"<td style='{_td_num()}'>{_diagnostic_delta(metric, delta)}</td>"
            f"<td style='{_td()}'>{html.escape(_likely_cause_label(change.get('likely_cause')))}</td>"
            "</tr>"
        )
    if not rows:
        return ""

    return (
        "<div style='overflow-x:auto;width:100%;margin:8px 0 16px;'>"
        "<table style='border-collapse:collapse;width:100%;min-width:720px;font-size:13px;background:#fff;'>"
        "<thead><tr style='background:#f3f4f6;'>"
        f"<th style='{_th()}'>指標</th>"
        f"<th style='{_th()}'>本期</th>"
        f"<th style='{_th()}'>前期</th>"
        f"<th style='{_th()}'>變化</th>"
        f"<th style='{_th()}'>可能原因</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _diagnostic_warning_html(anomalies: list[dict[str, Any]]) -> str:
    items = []
    for anomaly in anomalies:
        label = _diagnostic_object_name(anomaly)
        items.append(
            "<div style='background:#fff7ed;border-left:4px solid #f97316;color:#7c2d12;"
            "padding:10px 12px;margin:8px 0;font-size:13px;line-height:1.55;'>"
            f"<strong>⚠️ {html.escape(_anomaly_label(str(anomaly.get('kind') or 'warning')))}</strong>"
            f"｜{html.escape(label)}"
            f"｜花費 {_money(anomaly.get('spend'))}"
            f"｜轉換 {_count(anomaly.get('conversions'))}"
            f"｜ROAS {_ratio(anomaly.get('roas'))}"
            "</div>"
        )
    return "".join(items)


def _diagnostic_contribution_rows(
    diagnostics: dict[str, Any],
    platform: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    detail_contributions = diagnostics.get("detail_contributions")
    if isinstance(detail_contributions, dict):
        for section in ("search_terms", "keywords", "ad_groups", "ads"):
            rows.extend(_platform_rows(detail_contributions.get(section), platform))

    campaign_contributions = diagnostics.get("campaign_contributions")
    if isinstance(campaign_contributions, dict):
        rows.extend(_platform_rows(campaign_contributions.get("weaker_campaigns"), platform))
        rows.extend(_platform_rows(campaign_contributions.get("stronger_campaigns"), platform))

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in rows:
        key = (
            row.get("campaign_name"),
            row.get("ad_group_name"),
            row.get("ad_name"),
            row.get("keyword_text"),
            row.get("search_term"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return sorted(deduped, key=_diagnostic_sort_value, reverse=True)


def _diagnostic_contribution_table_html(rows: list[dict[str, Any]]) -> str:
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td style='{_td()}'>{html.escape(_diagnostic_object_name(row))}</td>"
            f"<td style='{_td()}'>{html.escape(_diagnostic_label(row))}</td>"
            f"<td style='{_td_num()}'>{_money(row.get('spend'))}</td>"
            f"<td style='{_td_num()}'>{_money(_nested_value(row, 'previous', 'spend'))}</td>"
            f"<td style='{_td_num()}'>{_diagnostic_delta('cpa', _nested_value(row, 'delta', 'spend'))}</td>"
            f"<td style='{_td_num()}'>{_percent(row.get('spend_share'))}</td>"
            f"<td style='{_td_num()}'>{_count(row.get('conversions'))}</td>"
            f"<td style='{_td_num()}'>{_count(_nested_value(row, 'previous', 'conversions'))}</td>"
            f"<td style='{_td_num()}'>{_money(row.get('cpa'))}</td>"
            f"<td style='{_td_num()}'>{_diagnostic_delta('cpa', _nested_value(row, 'delta', 'cpa'))}</td>"
            f"<td style='{_td_num()}'>{_ratio(row.get('roas'))}</td>"
            f"<td style='{_td_num()}'>{_diagnostic_delta('roas', _nested_value(row, 'delta', 'roas'))}</td>"
            "</tr>"
        )
    return (
        "<div style='overflow-x:auto;width:100%;margin:10px 0 20px;'>"
        "<table style='border-collapse:collapse;width:100%;min-width:860px;font-size:13px;background:#fff;'>"
        "<thead><tr style='background:#f3f4f6;'>"
        f"<th style='{_th()}'>對象</th>"
        f"<th style='{_th()}'>診斷</th>"
        f"<th style='{_th()}'>本期花費</th>"
        f"<th style='{_th()}'>前期花費</th>"
        f"<th style='{_th()}'>花費變化</th>"
        f"<th style='{_th()}'>花費占比</th>"
        f"<th style='{_th()}'>本期轉換</th>"
        f"<th style='{_th()}'>前期轉換</th>"
        f"<th style='{_th()}'>CPA</th>"
        f"<th style='{_th()}'>CPA 變化</th>"
        f"<th style='{_th()}'>ROAS</th>"
        f"<th style='{_th()}'>ROAS 變化</th>"
        "</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _campaign_table_row_html(row: dict[str, Any], is_total: bool = False) -> str:
    style = "font-weight:700;background:#f9fafb;" if is_total else ""
    return f"""
    <tr style="{style}">
      <td style="{_td()}">{html.escape(str(row.get("campaign_name") or "-"))}</td>
      <td style="{_td_num()}">{_money(row.get("spend"))}</td>
      <td style="{_td_num()}">{_count(row.get("link_clicks"))}</td>
      <td style="{_td_num()}">{_money(row.get("cpc"), decimals=2)}</td>
      <td style="{_td_num()}">{_money(row.get("cpm"))}</td>
      <td style="{_td_num()}">{_count(row.get("add_to_cart"))}</td>
      <td style="{_td_num()}">{_money(row.get("cost_per_add_to_cart"))}</td>
      <td style="{_td_num()}">{_count(row.get("purchase"))}</td>
      <td style="{_td_num()}">{_money(row.get("cost_per_purchase"))}</td>
      <td style="{_td_num()}">{_money(row.get("purchase_value"))}</td>
      <td style="{_td_num()}">{_ratio(row.get("roas"))}</td>
    </tr>"""


def _sum_campaign_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "spend": sum(_num(row.get("spend")) for row in rows),
        "link_clicks": sum(_num(row.get("link_clicks")) for row in rows),
        "impressions": sum(_num(row.get("impressions")) for row in rows),
        "add_to_cart": sum(_num(row.get("add_to_cart")) for row in rows),
        "purchase": sum(_num(row.get("purchase")) for row in rows),
        "purchase_value": sum(_num(row.get("purchase_value")) for row in rows),
    }
    totals["cpc"] = _safe_divide(totals["spend"], totals["link_clicks"])
    totals["cpm"] = _safe_divide(totals["spend"] * 1000, totals["impressions"])
    totals["cost_per_add_to_cart"] = _safe_divide(totals["spend"], totals["add_to_cart"])
    totals["cost_per_purchase"] = _safe_divide(totals["spend"], totals["purchase"])
    totals["roas"] = _safe_divide(totals["purchase_value"], totals["spend"])
    return totals


def _render_report_text_html(text: str) -> str:
    escaped = html.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(
        r"`(.+?)`",
        r"<strong style='font-weight:800;color:#111827;'>\1</strong>",
        escaped,
    )
    paragraphs = []
    lines = escaped.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped == "---":
            index += 1
            continue
        if _is_markdown_table_start(lines, index):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            paragraphs.append(_markdown_table_html(table_lines))
            continue
        rendered = _normalize_inline_numbers(stripped)
        heading = _parse_markdown_heading(rendered)
        if heading:
            level, content = heading
            paragraphs.append(_heading_html(level, content))
        elif _is_legacy_section_heading(stripped):
            paragraphs.append(_heading_html(1, rendered))
        elif stripped.startswith("⚠️"):
            paragraphs.append(
                "<div style='background:#fff7ed;border-left:4px solid #f97316;color:#7c2d12;"
                f"padding:12px 14px;margin:14px 0 18px;font-weight:650;'>{rendered}</div>"
            )
        elif re.match(r"^\d+\.\s", stripped):
            paragraphs.append(f"<p style='{_paragraph_style()}margin-left:16px;'>{rendered}</p>")
        elif stripped.startswith("- "):
            paragraphs.append(f"<p style='{_paragraph_style()}margin-left:18px;'>{rendered[2:]}</p>")
        else:
            paragraphs.append(f"<p style='{_paragraph_style()}'>{rendered}</p>")
        index += 1
    return "\n".join(paragraphs)


def _parse_markdown_heading(value: str) -> tuple[int, str] | None:
    """Parse Markdown heading syntax and return a normalized report heading level."""
    match = re.match(r"^(#{1,4})\s+(.+)$", value)
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def _is_legacy_section_heading(value: str) -> bool:
    """Return whether an older numbered line should still render as a section heading."""
    if not re.match(r"^\d+\.\s", value):
        return False
    return bool(re.search(r"Summary|表現較好|表現較差|素材觀察|整體建議|資料限制", value))


def _heading_html(level: int, content: str) -> str:
    """Render report headings with a clear hierarchy."""
    if level <= 1:
        return (
            "<h2 style='font-size:26px;line-height:1.3;margin:30px 0 14px;"
            f"color:#111827;font-weight:800;border-top:1px solid #e5dccb;padding-top:22px;'>{content}</h2>"
        )
    if level == 2:
        return (
            "<h3 style='font-size:20px;line-height:1.35;margin:24px 0 12px;"
            f"color:#111827;font-weight:800;'>{content}</h3>"
        )
    return (
        "<h4 style='font-size:16px;line-height:1.4;margin:20px 0 8px;"
        f"color:#374151;font-weight:750;'>{content}</h4>"
    )


def _paragraph_style() -> str:
    """Return default paragraph spacing for report prose."""
    return "font-size:15px;line-height:1.8;margin:8px 0 18px;color:#1f2937;"


def _is_markdown_table_start(lines: list[str], index: int) -> bool:
    """Return whether a Markdown table starts at the current line."""
    if index + 1 >= len(lines):
        return False
    current = lines[index].strip()
    separator = lines[index + 1].strip()
    return current.startswith("|") and separator.startswith("|") and re.search(r"\|[\s:-]+\|", separator)


def _markdown_table_html(table_lines: list[str]) -> str:
    """Render a simple Markdown pipe table as email-safe HTML."""
    parsed_rows = [_parse_markdown_table_row(line) for line in table_lines]
    rows = [row for row in parsed_rows if row and not all(re.fullmatch(r":?-{3,}:?", cell) for cell in row)]
    if not rows:
        return ""

    header, *body_rows = rows
    header_html = "".join(f"<th style='{_th()}'>{_normalize_inline_numbers(cell)}</th>" for cell in header)
    body_html = "".join(
        "<tr>"
        + "".join(f"<td style='{_td()}'>{_normalize_inline_numbers(cell)}</td>" for cell in row)
        + "</tr>"
        for row in body_rows
    )
    return (
        "<div style='overflow-x:auto;width:100%;margin:12px 0 24px;'>"
        "<table style='border-collapse:collapse;width:100%;min-width:720px;font-size:13px;background:#fff;'>"
        f"<thead><tr style='background:#f3f4f6;'>{header_html}</tr></thead>"
        f"<tbody>{body_html}</tbody></table></div>"
    )


def _parse_markdown_table_row(line: str) -> list[str]:
    """Parse one Markdown pipe table row."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _normalize_inline_numbers(value: str) -> str:
    """Add thousands separators to money and large standalone numbers in rendered report text."""
    value = re.sub(r"(?<![\w/])(-?)\$(\d{4,})(\.\d+)?", _format_money_match, value)
    return re.sub(r"(?<![\w/$.-])(\d{4,})(?![\w/.-])", _format_count_match, value)


def _format_money_match(match: re.Match[str]) -> str:
    sign, integer, decimal = match.groups()
    return f"{sign}${int(integer):,}{decimal or ''}"


def _format_count_match(match: re.Match[str]) -> str:
    return f"{int(match.group(1)):,}"


def _format_text_email(
    report_id: str,
    client_id: str,
    context: dict[str, Any],
    report_text: str,
) -> str:
    return "\n".join(
        [
            "OudSeed AI 廣告成效報告",
            f"Report ID: {report_id}",
            f"Client: {client_id}",
            f"Period: {context.get('period_start_date')} - {context.get('period_end_date')}",
            "",
            re.sub(r"\*\*(.+?)\*\*", r"\1", report_text),
        ]
    )


def _platforms(context: dict[str, Any]) -> list[str]:
    platforms = [row.get("platform") for row in context.get("campaigns", []) if row.get("platform")]
    return list(dict.fromkeys(platforms))


def _platform_label(platform: str) -> str:
    return {"meta_ads": "Meta Ads", "google_ads": "Google Ads"}.get(platform, platform)


def _default_subject(report_type: str, account_group_name: str, period_start_date: str) -> str:
    report_type_label = "週報" if report_type == "weekly" else "月報"
    return f"OudSeed 廣告成效{report_type_label}｜{account_group_name}｜{period_start_date}"


def _default_period_start(
    report_type: str,
    timezone: str,
    schedule: ReportSchedule | None,
) -> str:
    """Return the report period start from schedule cadence or legacy defaults."""
    if schedule is None:
        return get_default_report_period_start(report_type=report_type, timezone=timezone)
    return get_scheduled_report_period_start(
        report_type=report_type,
        delivery_day=schedule.delivery_day,
        timezone=timezone,
    )


def _schedule_value(schedule: ReportSchedule | None, name: str) -> Any:
    """Read an optional field from a resolved schedule."""
    if schedule is None:
        return None
    return getattr(schedule, name)


def _report_depth(value: str) -> str:
    """Validate report depth."""
    if value not in {"brief", "standard", "deep"}:
        raise ValueError("AI_REPORT_DEPTH must be 'brief', 'standard', or 'deep'.")
    return value


def _destination_from_config(config: dict[str, Any]) -> BigQueryDestination:
    bigquery_config = config.get("bigquery", {})
    project_id = os.getenv("GCP_PROJECT_ID") or bigquery_config.get("project_id")
    dataset_id = os.getenv("BIGQUERY_DATASET") or bigquery_config.get("dataset")
    if not project_id:
        raise ValueError("GCP project id is required via GCP_PROJECT_ID or config.bigquery.project_id.")
    if not dataset_id:
        raise ValueError("BigQuery dataset is required via BIGQUERY_DATASET or config.bigquery.dataset.")
    return BigQueryDestination(project_id=project_id, dataset_id=dataset_id)


def _money(value: Any, decimals: int = 0) -> str:
    if value is None:
        return "-"
    return f"${float(value):,.{decimals}f}"


def _count(value: Any) -> str:
    if value is None:
        return "-"
    number = float(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.1f}"


def _ratio(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value):,.2f}"


def _percent(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:,.2f}%"


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _safe_divide(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _diagnostic_value(metric: str, value: Any) -> str:
    if metric in {"cpc", "cpa"}:
        return _money(value, decimals=2 if metric == "cpc" else 0)
    return _ratio(value)


def _diagnostic_delta(metric: str, value: Any) -> str:
    if value is None:
        return "-"
    number = float(value)
    if metric in {"cpc", "cpa"}:
        decimals = 2 if metric == "cpc" else 0
        sign = "+" if number > 0 else "-" if number < 0 else ""
        return f"{sign}${abs(number):,.{decimals}f}"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:,.2f}"


def _diagnostic_sort_value(row: dict[str, Any]) -> float:
    spend = _num(row.get("spend"))
    previous_spend = _num(_nested_value(row, "previous", "spend"))
    spend_delta = abs(_num(_nested_value(row, "delta", "spend")))
    return max(spend, previous_spend, spend_delta)


def _nested_value(row: dict[str, Any], parent_key: str, child_key: str) -> Any:
    parent = row.get(parent_key)
    if not isinstance(parent, dict):
        return None
    return parent.get(child_key)


def _diagnostic_object_name(row: dict[str, Any]) -> str:
    for key, prefix in (
        ("search_term", "搜尋字詞"),
        ("keyword_text", "關鍵字"),
        ("ad_name", "廣告"),
        ("ad_group_name", "廣告組合"),
        ("campaign_name", "活動"),
    ):
        value = row.get(key)
        if value:
            return f"{prefix}: {value}"
    return "-"


def _platform_rows(value: Any, platform: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict) and row.get("platform") == platform]


def _anomaly_label(kind: str) -> str:
    return {
        "high_spend_zero_conversions": "高花費但零轉換",
        "low_roas_high_spend_share": "高花費占比但 ROAS 偏低",
        "sharp_cpc_increase": "CPC 明顯上升",
        "sharp_cpa_increase": "CPA 明顯上升",
        "sharp_roas_decline": "ROAS 明顯下滑",
    }.get(kind, kind)


def _likely_cause_label(value: Any) -> str:
    if value is None:
        return "-"
    raw = str(value)
    labels = {
        "insufficient_previous_period_data": "前期資料不足，無法拆解變化原因",
        "spend_increased_while_link_clicks_did_not": "花費增加，但連結點擊沒有同步增加",
        "spend_fell_or_flat_while_link_clicks_increased": "花費持平或下降，但連結點擊增加",
        "spend_moved_more_than_link_clicks": "花費變動幅度大於連結點擊，推動 CPC 變化",
        "link_clicks_moved_more_than_spend": "連結點擊變動幅度大於花費，推動 CPC 變化",
        "spend_increased_while_conversions_did_not": "花費增加，但轉換沒有同步增加",
        "spend_fell_or_flat_while_conversions_increased": "花費持平或下降，但轉換增加",
        "spend_moved_more_than_conversions": "花費變動幅度大於轉換，推動 CPA 變化",
        "conversions_moved_more_than_spend": "轉換變動幅度大於花費，推動 CPA 變化",
        "conversion_value_increased_while_spend_did_not": "轉換價值增加，且花費沒有同步增加",
        "conversion_value_fell_or_flat_while_spend_increased": "轉換價值持平或下降，但花費增加",
        "conversion_value_moved_more_than_spend": "轉換價值變動幅度大於花費，推動 ROAS 變化",
        "spend_moved_more_than_conversion_value": "花費變動幅度大於轉換價值，推動 ROAS 變化",
    }
    return labels.get(raw, raw.replace("_", " "))


def _diagnostic_label(row: dict[str, Any]) -> str:
    value = row.get("action_bias") or row.get("diagnostic_note")
    if value is None:
        return "-"
    raw = str(value)
    labels = {
        "scale_or_protect": "表現具放大或保護價值",
        "reduce_pause_or_exclude": "高花費低回收，建議降預算、暫停或排除",
        "review_stopped_or_missing_item": "前期有花費，本期已停止或資料缺失，請確認是否為刻意調整",
        "recover_lost_conversions_or_reduce": "前期有轉換但本期流失，建議修復或降低投入",
        "optimize_bid_budget_or_landing_page": "已有轉換，建議優化出價、預算或落地頁",
        "monitor": "持續觀察，等更多資料再判斷",
        "improving_efficiency_or_value": "效率或轉換價值正在改善",
        "spend_efficiency_worsened_without_conversion_growth": "花費效率變差，轉換沒有同步成長",
        "spend_without_conversions": "已有花費但沒有轉換",
        "detail_spend_stopped_or_missing_current_period": "前期有花費，本期已停止或資料缺失",
        "detail_new_spend_this_period": "本期新增花費，需觀察是否建立穩定轉換",
        "detail_cpa_worsened": "CPA 較前期惡化",
        "detail_roas_declined": "ROAS 較前期下滑",
        "detail_conversion_growth_with_stable_efficiency": "轉換成長且效率大致穩定",
        "monitor_against_account_average": "需和帳戶平均表現一起觀察",
    }
    return labels.get(raw, raw.replace("_", " "))


def _th() -> str:
    return "border:1px solid #d1d5db;padding:8px;text-align:left;white-space:nowrap;"


def _td() -> str:
    return "border:1px solid #e5e7eb;padding:8px;vertical-align:top;"


def _td_num() -> str:
    return _td() + "text-align:right;white-space:nowrap;"


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _positive_int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value in {None, ""}:
        return default
    value = int(raw_value)
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


def _optional_positive_int_env(name: str) -> int | None:
    raw_value = os.getenv(name)
    if raw_value in {None, ""}:
        return None
    value = int(raw_value)
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


def _bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value in {None, ""}:
        return default
    value = raw_value.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


if __name__ == "__main__":
    main()
