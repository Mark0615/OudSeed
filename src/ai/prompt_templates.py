"""Prompt templates for AI performance reports."""

from __future__ import annotations

import json
from typing import Any


def render_performance_report_prompt(context: dict[str, Any]) -> str:
    """Render an LLM prompt for weekly or monthly performance analysis."""
    report_type = context["report_type"]
    comparison = context["comparison"]
    context_json = json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True)

    return f"""You are an ads performance analyst.

Write a concise {report_type} performance report in Traditional Chinese.

Use only the metrics in the JSON context. Do not invent numbers, campaigns,
budgets, or conversion explanations. If there is not enough historical data for
{comparison}, say that directly.

Required output:
1. Executive summary: 2-3 bullets.
2. What changed: explain the biggest spend and click movement.
3. Campaign observations: mention the strongest and weakest campaigns by name.
4. Recommended next actions: 3 practical actions for a media buyer.
5. Data caveats: mention missing previous-period metrics or zero conversion data.

JSON context:
{context_json}
"""
