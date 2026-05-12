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
from src.ai.report_generator import generate_and_log_report
from src.destinations.bigquery import BigQueryDestination
from src.notifications.email_delivery import SMTPEmailSender, load_smtp_email_config_from_env
from src.utils.date_utils import get_default_report_period_start


def main() -> None:
    """Generate account-grouped reports and send one email per account group."""
    load_dotenv()
    config = _load_runtime_config()
    destination = _destination_from_config(config)
    report_type = _report_type(os.getenv("AI_REPORT_TYPE", "monthly"))
    timezone_name = config.get("defaults", {}).get("timezone", "Asia/Taipei")
    period_start_date = os.getenv("AI_REPORT_PERIOD_START_DATE") or get_default_report_period_start(
        report_type=report_type,
        timezone=os.getenv("AI_REPORT_TIMEZONE", timezone_name),
    )
    client_id = os.getenv("AI_REPORT_CLIENT_ID") or _first_enabled_client_id(config)
    recipient = _required_env("AI_REPORT_EMAIL_TO")
    limit = _positive_int_env("AI_REPORT_LIMIT", 50)
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

    openai_client = OpenAITextClient(
        api_key=_required_env("OPENAI_API_KEY"),
        model=os.getenv("OPENAI_MODEL", "gpt-5.4 mini"),
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
        sections.append("<h3>Insight</h3>")
    sections.append(_render_report_text_html(report_text))

    return f"""<!doctype html>
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;color:#1f2937;line-height:1.55;">
  <h1 style="font-size:22px;margin:0 0 12px;">OudSeed 廣告成效報告｜{html.escape(account_group_name)}</h1>
  <p style="margin:0 0 16px;color:#4b5563;">
    Report ID: {html.escape(report_id)}<br>
    Client: {html.escape(client_id)}<br>
    Period: {html.escape(str(context.get("period_start_date")))} - {html.escape(str(context.get("period_end_date")))}
  </p>
  {''.join(sections)}
</body>
</html>"""


def _campaign_table_html(context: dict[str, Any], platform: str) -> str:
    rows = [row for row in context.get("campaigns", []) if row.get("platform") == platform]
    totals = _sum_campaign_rows(rows)
    table_rows = rows + [{"campaign_name": "總計", **totals}]
    body = "".join(_campaign_table_row_html(row, is_total=row.get("campaign_name") == "總計") for row in table_rows)
    return f"""
<table style="border-collapse:collapse;width:100%;font-size:13px;margin:8px 0 20px;">
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
</table>"""


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
        if re.match(r"^\d+\.\s", stripped):
            paragraphs.append(f"<h2>{rendered}</h2>")
        elif stripped.startswith("⚠️"):
            paragraphs.append(
                "<div style='background:#fff7ed;border-left:4px solid #f97316;"
                f"padding:10px 12px;margin:10px 0;'>{rendered}</div>"
            )
        elif stripped.startswith("- "):
            paragraphs.append(f"<p style='margin:4px 0 4px 18px;'>{rendered[2:]}</p>")
        else:
            paragraphs.append(f"<p>{rendered}</p>")
        index += 1
    return "\n".join(paragraphs)


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
        "<table style='border-collapse:collapse;width:100%;font-size:13px;margin:10px 0 18px;'>"
        f"<thead><tr style='background:#f3f4f6;'>{header_html}</tr></thead>"
        f"<tbody>{body_html}</tbody></table>"
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


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _safe_divide(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


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


if __name__ == "__main__":
    main()
