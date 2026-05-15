"""Build deterministic diagnostic context for AI performance reports."""

from __future__ import annotations

from typing import Any


PRIMARY_METRICS = ("cpc", "cpa", "roas")
DETAIL_SECTIONS = ("ad_groups", "ads", "keywords", "search_terms")


def build_report_diagnostics(context: dict[str, Any]) -> dict[str, Any]:
    """Return root-cause hints and contribution rows for the report context."""
    totals = context.get("totals") or {}
    campaigns = _list_of_dicts(context.get("campaigns"))
    diagnostics = {
        "metric_changes": _metric_changes(totals),
        "campaign_contributions": _campaign_contributions(campaigns, totals),
        "detail_contributions": _detail_contributions(context, totals),
        "anomalies": _anomalies(context, totals),
        "data_limitations": _data_limitations(context, totals),
    }
    return diagnostics


def _metric_changes(totals: dict[str, Any]) -> dict[str, dict[str, Any]]:
    previous = totals.get("previous") if isinstance(totals.get("previous"), dict) else {}
    changes: dict[str, dict[str, Any]] = {}
    for metric in PRIMARY_METRICS:
        current_value = _to_float(totals.get(metric))
        previous_value = _to_float(previous.get(metric))
        delta = _subtract(current_value, previous_value)
        rate = _rate(delta, previous_value)
        changes[metric] = {
            "current": current_value,
            "previous": previous_value,
            "delta": delta,
            "delta_rate": rate,
            "direction": _direction(delta, higher_is_better=metric == "roas"),
            "likely_cause": _metric_cause(metric, totals, previous),
        }
    return changes


def _campaign_contributions(
    campaigns: list[dict[str, Any]],
    totals: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    annotated = [_annotate_campaign(row, totals) for row in campaigns]
    return {
        "top_spend_drivers": _top_by(annotated, "spend", reverse=True),
        "stronger_campaigns": _stronger_campaigns(annotated),
        "weaker_campaigns": _weaker_campaigns(annotated),
        "cpc_increase_drivers": _metric_delta_drivers(annotated, "cpc", positive=True),
        "cpa_increase_drivers": _metric_delta_drivers(annotated, "cpa", positive=True),
        "roas_decline_drivers": _metric_delta_drivers(annotated, "roas", positive=False),
    }


def _detail_contributions(
    context: dict[str, Any],
    totals: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    return {
        section: [_annotate_detail(row, totals, section) for row in _list_of_dicts(context.get(section))]
        for section in DETAIL_SECTIONS
    }


def _anomalies(
    context: dict[str, Any],
    totals: dict[str, Any],
) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    total_spend = _to_float(totals.get("spend")) or 0.0
    total_roas = _to_float(totals.get("roas"))
    for section in ("campaigns", *DETAIL_SECTIONS):
        for row in _list_of_dicts(context.get(section)):
            spend = _to_float(row.get("spend")) or 0.0
            if spend <= 0:
                continue
            spend_share = _share(spend, total_spend)
            conversions = _to_float(row.get("conversions")) or 0.0
            roas = _to_float(row.get("roas"))
            cpc_delta_rate = _to_float(row.get("cpc_delta_rate"))
            cpa_delta_rate = _to_float(row.get("cpa_delta_rate"))
            roas_delta_rate = _to_float(row.get("roas_delta_rate"))

            if spend_share is not None and spend_share >= 0.2 and conversions == 0:
                anomalies.append(_anomaly("high_spend_zero_conversions", section, row, spend_share))
            if total_roas and roas is not None and roas < total_roas * 0.6 and spend_share and spend_share >= 0.1:
                anomalies.append(_anomaly("low_roas_high_spend_share", section, row, spend_share))
            if cpc_delta_rate is not None and cpc_delta_rate >= 0.25:
                anomalies.append(_anomaly("sharp_cpc_increase", section, row, spend_share))
            if cpa_delta_rate is not None and cpa_delta_rate >= 0.25:
                anomalies.append(_anomaly("sharp_cpa_increase", section, row, spend_share))
            if roas_delta_rate is not None and roas_delta_rate <= -0.25:
                anomalies.append(_anomaly("sharp_roas_decline", section, row, spend_share))
    return anomalies[:12]


def _data_limitations(context: dict[str, Any], totals: dict[str, Any]) -> list[str]:
    limitations: list[str] = []
    previous = totals.get("previous") if isinstance(totals.get("previous"), dict) else {}
    if not previous or not any(_to_float(previous.get(metric)) for metric in ("spend", "link_clicks", "conversions")):
        limitations.append("previous_period_totals_missing_or_zero")
    if _to_float(totals.get("conversion_value")) in (None, 0.0):
        limitations.append("conversion_value_missing_or_zero_roas_less_reliable")
    if not _list_of_dicts(context.get("ad_groups")):
        limitations.append("ad_group_breakdown_missing")
    if not _list_of_dicts(context.get("ads")):
        limitations.append("ad_or_creative_breakdown_missing")
    if not _list_of_dicts(context.get("search_terms")):
        limitations.append("search_term_breakdown_missing")
    return limitations


def _annotate_campaign(row: dict[str, Any], totals: dict[str, Any]) -> dict[str, Any]:
    annotated = _base_annotation(row, totals)
    previous_spend = _to_float(row.get("previous_spend"))
    previous_clicks = _to_float(row.get("previous_link_clicks"))
    previous_conversions = _to_float(row.get("previous_conversions"))
    previous_cpc = _to_float(row.get("previous_cpc"))
    previous_cpa = _to_float(row.get("previous_cpa"))
    previous_roas = _to_float(row.get("previous_roas"))
    current_cpc = _to_float(row.get("cpc"))
    current_cpa = _to_float(row.get("cpa"))
    current_roas = _to_float(row.get("roas"))
    annotated.update(
        {
            "previous": {
                "spend": previous_spend,
                "link_clicks": previous_clicks,
                "conversions": previous_conversions,
                "cpc": previous_cpc,
                "cpa": previous_cpa,
                "roas": previous_roas,
            },
            "delta": {
                "spend": _subtract(_to_float(row.get("spend")), previous_spend),
                "link_clicks": _subtract(_to_float(row.get("link_clicks")), previous_clicks),
                "conversions": _subtract(_to_float(row.get("conversions")), previous_conversions),
                "cpc": _subtract(current_cpc, previous_cpc),
                "cpa": _subtract(current_cpa, previous_cpa),
                "roas": _subtract(current_roas, previous_roas),
            },
        }
    )
    annotated["cpc_delta_rate"] = _rate(annotated["delta"]["cpc"], previous_cpc)
    annotated["cpa_delta_rate"] = _rate(annotated["delta"]["cpa"], previous_cpa)
    annotated["roas_delta_rate"] = _rate(annotated["delta"]["roas"], previous_roas)
    annotated["diagnostic_note"] = _campaign_note(annotated)
    return annotated


def _annotate_detail(row: dict[str, Any], totals: dict[str, Any], section: str) -> dict[str, Any]:
    annotated = _base_annotation(row, totals)
    annotated["section"] = section
    annotated["action_bias"] = _action_bias(annotated)
    return annotated


def _base_annotation(row: dict[str, Any], totals: dict[str, Any]) -> dict[str, Any]:
    spend = _to_float(row.get("spend"))
    conversions = _to_float(row.get("conversions"))
    conversion_value = _to_float(row.get("conversion_value"))
    clicks = _to_float(row.get("link_clicks"))
    return {
        "platform": row.get("platform"),
        "account_id": row.get("account_id"),
        "campaign_id": row.get("campaign_id"),
        "campaign_name": row.get("campaign_name"),
        "ad_group_id": row.get("ad_group_id"),
        "ad_group_name": row.get("ad_group_name"),
        "ad_id": row.get("ad_id"),
        "ad_name": row.get("ad_name"),
        "criterion_id": row.get("criterion_id"),
        "keyword_text": row.get("keyword_text"),
        "keyword_match_type": row.get("keyword_match_type"),
        "search_term": row.get("search_term"),
        "spend": spend,
        "link_clicks": clicks,
        "conversions": conversions,
        "conversion_value": conversion_value,
        "cpc": _to_float(row.get("cpc")),
        "cpa": _to_float(row.get("cpa")),
        "roas": _to_float(row.get("roas")),
        "ctr": _to_float(row.get("ctr")),
        "spend_share": _share(spend, _to_float(totals.get("spend"))),
        "click_share": _share(clicks, _to_float(totals.get("link_clicks"))),
        "conversion_share": _share(conversions, _to_float(totals.get("conversions"))),
        "conversion_value_share": _share(conversion_value, _to_float(totals.get("conversion_value"))),
    }


def _metric_cause(metric: str, totals: dict[str, Any], previous: dict[str, Any]) -> str:
    spend_delta = _subtract(_to_float(totals.get("spend")), _to_float(previous.get("spend")))
    clicks_delta = _subtract(_to_float(totals.get("link_clicks")), _to_float(previous.get("link_clicks")))
    conversions_delta = _subtract(_to_float(totals.get("conversions")), _to_float(previous.get("conversions")))
    value_delta = _subtract(_to_float(totals.get("conversion_value")), _to_float(previous.get("conversion_value")))
    if metric == "cpc":
        return _ratio_cause("spend", spend_delta, "link_clicks", clicks_delta)
    if metric == "cpa":
        return _ratio_cause("spend", spend_delta, "conversions", conversions_delta)
    return _ratio_cause("conversion_value", value_delta, "spend", spend_delta)


def _ratio_cause(numerator_name: str, numerator_delta: float | None, denominator_name: str, denominator_delta: float | None) -> str:
    if numerator_delta is None or denominator_delta is None:
        return "insufficient_previous_period_data"
    if numerator_delta > 0 and denominator_delta <= 0:
        return f"{numerator_name}_increased_while_{denominator_name}_did_not"
    if numerator_delta <= 0 and denominator_delta > 0:
        return f"{numerator_name}_fell_or_flat_while_{denominator_name}_increased"
    if abs(numerator_delta) > abs(denominator_delta):
        return f"{numerator_name}_moved_more_than_{denominator_name}"
    return f"{denominator_name}_moved_more_than_{numerator_name}"


def _campaign_note(row: dict[str, Any]) -> str:
    cpa_delta = _to_float(row.get("delta", {}).get("cpa"))
    roas_delta = _to_float(row.get("delta", {}).get("roas"))
    conversions_delta = _to_float(row.get("delta", {}).get("conversions"))
    if roas_delta is not None and roas_delta > 0 and (conversions_delta or 0) >= 0:
        return "improving_efficiency_or_value"
    if cpa_delta is not None and cpa_delta > 0 and (conversions_delta or 0) <= 0:
        return "spend_efficiency_worsened_without_conversion_growth"
    if _to_float(row.get("spend")) and not _to_float(row.get("conversions")):
        return "spend_without_conversions"
    return "monitor_against_account_average"


def _action_bias(row: dict[str, Any]) -> str:
    conversions = _to_float(row.get("conversions")) or 0.0
    spend_share = _to_float(row.get("spend_share")) or 0.0
    roas = _to_float(row.get("roas"))
    cpa = _to_float(row.get("cpa"))
    if conversions > 0 and roas is not None and roas >= 2:
        return "scale_or_protect"
    if spend_share >= 0.1 and conversions == 0:
        return "reduce_pause_or_exclude"
    if cpa is not None and conversions > 0:
        return "optimize_bid_budget_or_landing_page"
    return "monitor"


def _stronger_campaigns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in rows
        if (_to_float(row.get("conversions")) or 0) > 0
        and (_to_float(row.get("roas_delta_rate")) is None or (_to_float(row.get("roas_delta_rate")) or 0) >= 0)
    ]
    return _top_by(candidates, "roas", reverse=True)


def _weaker_campaigns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [
        row
        for row in rows
        if (_to_float(row.get("conversions")) or 0) == 0
        or (_to_float(row.get("cpa_delta_rate")) is not None and (_to_float(row.get("cpa_delta_rate")) or 0) > 0)
        or (_to_float(row.get("roas_delta_rate")) is not None and (_to_float(row.get("roas_delta_rate")) or 0) < 0)
    ]
    return _top_by(candidates, "spend", reverse=True)


def _metric_delta_drivers(
    rows: list[dict[str, Any]],
    metric: str,
    positive: bool,
) -> list[dict[str, Any]]:
    key = f"{metric}_delta_rate"
    candidates = []
    for row in rows:
        value = _to_float(row.get(key))
        if value is None:
            continue
        if positive and value > 0:
            candidates.append(row)
        if not positive and value < 0:
            candidates.append(row)
    return _top_by(candidates, key, reverse=positive)


def _top_by(rows: list[dict[str, Any]], key: str, reverse: bool = True, limit: int = 5) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: _to_float(row.get(key)) or 0.0, reverse=reverse)[:limit]


def _anomaly(kind: str, section: str, row: dict[str, Any], spend_share: float | None) -> dict[str, Any]:
    return {
        "kind": kind,
        "section": section,
        "platform": row.get("platform"),
        "campaign_name": row.get("campaign_name"),
        "ad_group_name": row.get("ad_group_name"),
        "ad_name": row.get("ad_name"),
        "keyword_text": row.get("keyword_text"),
        "search_term": row.get("search_term"),
        "spend": _to_float(row.get("spend")),
        "spend_share": spend_share,
        "conversions": _to_float(row.get("conversions")),
        "cpc": _to_float(row.get("cpc")),
        "cpa": _to_float(row.get("cpa")),
        "roas": _to_float(row.get("roas")),
    }


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _subtract(value: float | None, previous_value: float | None) -> float | None:
    if value is None or previous_value is None:
        return None
    return value - previous_value


def _rate(delta: float | None, previous_value: float | None) -> float | None:
    if delta is None or previous_value in (None, 0):
        return None
    return delta / previous_value


def _share(value: float | None, total: float | None) -> float | None:
    if value is None or total in (None, 0):
        return None
    return value / total


def _direction(delta: float | None, higher_is_better: bool) -> str:
    if delta is None:
        return "unknown"
    if delta == 0:
        return "flat"
    improved = delta > 0 if higher_is_better else delta < 0
    return "improved" if improved else "worsened"
