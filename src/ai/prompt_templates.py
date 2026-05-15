"""Prompt templates for AI performance reports."""

from __future__ import annotations

import json
from typing import Any


REPORT_DEPTHS = {"brief", "standard", "deep"}


def render_performance_report_prompt(context: dict[str, Any]) -> str:
    """Render an LLM prompt for weekly or monthly performance analysis."""
    report_type = context["report_type"]
    comparison = context["comparison"]
    depth = _report_depth(context.get("report_depth", "standard"))
    context_json = json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True)

    return f"""You are an ads performance analyst for paid media buyers.

Write a concise {report_type} performance report in Traditional Chinese.
Report depth: {depth}

Use only the metrics in the JSON context. Do not invent numbers, campaigns,
budgets, or conversion explanations. If there is not enough historical data for
{comparison}, say that directly.

Your recommendations must help the client improve business performance. Tie the
advice to the campaign goal when that goal is present in the context. For traffic
campaigns, focus on lowering CPC and improving click quality. For conversion
campaigns, focus on purchase volume, conversion value, CPA, and ROAS.

Group the report by platform if the context contains multiple platforms.
In this project, cpc is calculated from spend / link_clicks, so treat it as
link-click CPC. Do not say link-click CPC is unavailable when cpc is present.
When totals.previous and totals.delta exist, summarize the overall {comparison}
change before campaign-level observations.
Use the `diagnostics` object as precomputed analytical context. It contains
CPA/CPC/ROAS change causes, campaign/ad group/ad/keyword/search term
contribution shares, anomaly checks, and data limitations. Treat it as guidance
for prioritization, but still cite the underlying metric values from the JSON.
Every {comparison} metric sentence should use this pattern when previous values
exist: `Spend：$13,006（較上月 $13,601 下降 $594）`. Use the analogous
weekly wording for weekly reports. Apply the same pattern consistently for all
platforms.

Formatting rules:
- Prefix all monetary values with "$".
- Use thousands separators for all numbers, including money, clicks,
  impressions, conversions, and purchase value.
- Show CPC with exactly 2 decimals.
- Show other monetary values as rounded whole numbers.
- Show CTR and other rates as percentages with 2 decimals.
- Show ROAS with 2 decimals.
- Do not output raw decimal CTR values such as 0.0187; write 1.87% instead.
- Do not write internal data-shape notes such as "有提供 previous 與 delta".
- Prefer Markdown tables for metric-heavy sections. Use short paragraphs only
  for diagnosis and actions.
- Use `⚠️` for risks that require action, such as high spend with weak
  conversions, sharply rising CPC/CPA, or declining ROAS.
- Use Markdown heading levels consistently:
  - `#` for main report sections such as `# 本月 Summary` and
    `# 2. 表現較好的廣告`.
  - `##` for named campaign/ad set/ad/keyword groups, such as
    `## 最佳主力活動：需求字/Sale/Search`.
  - `###` for analysis layers such as `### 活動層級`,
    `### Keyword / Search term 層級`, or `### 建議做法`.
  - Do not use numbered action lines as headings. A recommendation like
    `1. 先把預算...` should remain normal body text or a table row.
- Leave a blank line after each recommendation paragraph before starting the
  next campaign, ad group, keyword/search term, or section.

Depth rules:
{_depth_rules(depth)}

Required output structure:
1. `# [本週/本月 Summary]`
   - Start with one comparison table. Include spend, CPM, CPC or link-click
     CPC, CPA for the configured conversion action, ROAS when available,
     add-to-cart count when available, and purchase count when available.
   - The comparison table should have columns like `指標`, `本期`, `前期`,
     `變化`, and `判讀`.
   - Do not repeat the same metrics again in a separate "本月核心成效" or
     "本週核心成效" list. After the table, write only 1-2 concise takeaway
     sentences.
   - If a metric is missing from the JSON context, say it is not available.
2. `# 表現較好的廣告`
   - Mention the strongest campaigns, ad sets, or ads by name.
   - Explain the metric basis, such as low CPA, high ROAS, low CPC, high CTR,
     or stronger conversion volume.
   - Prefer items listed in `diagnostics.campaign_contributions.stronger_campaigns`
     and detail rows with `action_bias = scale_or_protect` when they exist.
   - Recommend how to maintain or scale the performance.
3. `# 表現較差的廣告`
   - Mention weaker campaigns, ad sets, or ads by name.
   - Explain what declined versus the previous {comparison} period when
     previous-period metrics are available.
   - Use `diagnostics.metric_changes` to explain whether CPC, CPA, or ROAS
     moved because spend, clicks, conversions, or conversion value changed.
   - Prioritize warning items from `diagnostics.anomalies`, especially high
     spend with zero conversions, sharply rising CPC/CPA, or sharply falling
     ROAS.
   - Recommend whether to improve, reduce spend, or pause.
   - For Google Ads, use keyword and search_terms context when available. Name
     the specific keywords or search terms that should be paused, reduced, or
     added as negative keywords when their spend/CPC is high and conversions or
     ROAS are weak. Avoid generic advice like "avoid CPC rising" unless it is
     tied to a specific campaign, ad group, keyword, or search term.
   - For Google Ads, explain campaign-level changes by tying them to ad group,
     keyword, or search term rows. Example style:
     `需求字/Sale/Search 本月 CPC $X.XX，較上月上升 Y%，主要由「A」與「B」
     這兩個 search terms/keywords 拉高；「C」在較低 CPC 下仍有轉換，建議提高
     曝光，並將「A」「B」降價、暫停或加為否定關鍵字。`
4. `# 素材觀察`
   - Discuss creative performance only when creative or engagement metrics exist.
   - Use CPC and CTR, plus reactions, comments, saves, shares, outbound clicks,
     or video metrics when those fields are present.
   - If creative or engagement metrics are missing, say what should be added to
     the data pipeline before making creative-level claims.
5. `# 整體建議與下週/下月行動`
   - Provide practical next actions for a media buyer.
   - Include concrete client inputs needed, such as new creatives, offer details,
     landing page changes, target CPA, or target ROAS.
6. `# 資料限制`
   - Mention missing previous-period metrics, zero conversion data, missing
     creative metrics, missing search term/breakdown data, unavailable
     objective data, and items listed in `diagnostics.data_limitations`.

JSON context:
{context_json}
"""


def _report_depth(value: Any) -> str:
    """Return a supported report depth."""
    depth = str(value or "standard").strip().lower()
    if depth not in REPORT_DEPTHS:
        raise ValueError("report_depth must be 'brief', 'standard', or 'deep'.")
    return depth


def _depth_rules(depth: str) -> str:
    """Return output length guidance for the selected report depth."""
    if depth == "brief":
        return """- Write an executive short report.
- Summary: one table plus 1 short takeaway.
- Strong performers: at most 2 items.
- Weak performers: at most 2 items.
- Final actions: at most 3 bullets.
- Avoid long diagnosis unless a critical anomaly exists."""
    if depth == "deep":
        return """- Write a deeper consultant-style analysis.
- Summary: one table plus 2-3 diagnostic takeaways.
- Strong performers: up to 5 items across campaign/ad group/ad/keyword/search term.
- Weak performers: up to 5 items, with root-cause reasoning and concrete next actions.
- Include anomaly checks, competing hypotheses, and data limitations when useful.
- Final actions: prioritize 5-8 actions by expected impact and confidence."""
    return """- Write a standard client-ready report.
- Summary: one table plus 1-2 diagnostic takeaways.
- Strong performers: at most 3 items.
- Weak performers: at most 3 items.
- Google keyword/search term recommendations: include up to 5 expand/keep items and up to 5 reduce/pause/negative items when available.
- Final actions: at most 5 prioritized actions."""
