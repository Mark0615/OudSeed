# AGENTS.md

You are working on the GitHub repository `Mark0615/OudSeed`.

Local development path:

```text
/Users/mark/Desktop/OudSeed
```

## Project context

This project is an automated ads performance assistant. It syncs advertising data
into BigQuery, exposes reporting datasets to Looker Studio first and Google
Sheets later, then generates recurring AI performance insights for media buyers.

Current MVP priority:

```text
Meta Ads → BigQuery → Looker Studio → AI report logs
```

Future order:

```text
Google Ads → LINE Ads → Google Sheets export → Email/LINE delivery → SaaS features
```

Read this file and `docs/ads_ai_pipeline_codex_development_spec.md` before making changes.

---

## Current implementation scope

Current target version: `v0.4` product-shaped MVP.

Current implemented foundation:

- Meta Ads daily sync to BigQuery
- Raw Meta Ads payload storage
- Unified daily ads table
- Weekly/monthly BigQuery summary marts
- Looker Studio reporting views
- Cloud Run Job + Cloud Scheduler for Meta sync
- OpenAI-powered weekly/monthly report generation
- AI report Cloud Run Job + monthly Cloud Scheduler
- Sync and AI report logs for failure tracking

Current product focus:

- Improve Meta field coverage for reporting and AI analysis
- Make Looker Studio expose both performance data and generated AI reports
- Improve AI report structure so it matches media buyer workflows
- Keep platform-specific raw/wide fields available without bloating the unified table

Do not implement these unless explicitly requested:

- Google Ads connector
- LINE Ads connector
- OAuth login
- SaaS user system
- Payment
- Google Sheet export
- Frontend dashboard
- Email delivery
- LINE delivery

## Product reporting rules

AI reports should be useful to a media buyer, not just descriptive summaries.
For each client/account report:

- Group results by advertising platform when multiple platforms exist.
- Include weekly/monthly spend, CPM, CPC/link-click CPC, CPA for the configured
  conversion action, ROAS when conversion value exists, add-to-cart count when
  available, and purchase count when available.
- Identify stronger ads/campaigns/ad sets, explain the metric basis, and suggest
  how to maintain or scale performance.
- Identify weaker ads/campaigns/ad sets, explain the metric basis, and suggest
  whether to improve, reduce spend, or pause.
- Include creative observations when creative or engagement data exists. Use
  CTR/CPC plus engagement signals such as reactions, comments, saves, shares,
  outbound clicks, or video metrics when available.
- Tie recommendations to the campaign objective. Traffic campaigns should focus
  on lower CPC and higher-quality clicks. Conversion campaigns should focus on
  purchase count, conversion value, CPA, and ROAS.
- Ask for concrete client inputs when needed, such as new creatives, offer
  details, landing page changes, target CPA, or target ROAS.
- Support user-configurable report schedules over time. Users should be able to
  choose weekly or monthly cadence and the delivery day, such as every Monday or
  the 10th day of each month. WoW/MoM comparison windows must be derived from
  the user's configured report cadence and delivery date.
- Format report numbers consistently: prefix all money values with `$` including
  spend, CPC, CPM, CPA, cost per add-to-cart, purchase value, and similar fields;
  use thousands separators for all numbers; show CPC with 2 decimals; show other
  money values as rounded whole numbers unless a later product setting requires
  currency-specific precision; show CTR and other rates as percentages with 2
  decimals; show ROAS with 2 decimals.
- WoW/MoM comparisons should consistently show current value, previous value,
  and absolute movement, such as
  `Spend：$13,006（較上月 $13,601 下降 $594）`. Previous-period totals must be
  calculated from the complete previous period, not only from campaigns that
  still exist in the current period.
- Reporting and recommendations must evolve beyond campaign-level only. Use
  campaign, ad set, and ad/creative-level data when available so the report can
  recommend which ad sets have scaling potential, which should be reduced or
  paused, and which creatives should be learned from, refreshed, or stopped.
- Report delivery should be grouped by customer/account identity. MVP may use
  normalized `account_name` as the grouping key: same account name across
  platforms can be combined into one email, while different account names should
  be sent as separate emails. Later SaaS customer mapping can override this.
- Email reports should be HTML, not raw Markdown. Put a campaign-level table
  after the period header for each platform, include a total row, use thousands
  separators for numbers, and render emphasis with HTML instead of visible `**`.
- Keep the email scannable. Metric-heavy summary and comparison sections should
  be tables instead of long repeated text lists. Do not repeat the same MoM/WoW
  metrics in both "overall change" and "core performance" sections. Use warning
  callouts, such as `⚠️`, for high-spend/low-result or sharply worsening items.
- Report headings must follow Markdown hierarchy before HTML rendering: `#` for
  major sections, `##` for named campaign/ad set/ad/keyword groups, and `###`
  for analysis layers such as campaign level, keyword/search-term level, and
  recommended actions. Numbered recommendation sentences should remain body
  text, not large headings. Leave visual breathing room after each
  recommendation before the next item.
- Report length should be product-controlled through `AI_REPORT_DEPTH`, not left
  entirely to the model. Supported depths are `brief`, `standard`, and `deep`.
  Standard is the default client-ready monthly/weekly report; deep may include
  more root-cause reasoning, anomaly checks, and consultant-style hypotheses.
- Google Ads recommendations should use keyword and search-term context when
  available and name specific keywords/search terms to pause, reduce, expand, or
  add as negatives. Avoid generic budget/CPC advice when deeper data exists.
  Campaign-level Google diagnosis should explain which ad groups, keywords, or
  search terms moved CPC/CPA/ROAS and which lower-cost converting terms should
  be expanded.
- Google Ads UI custom columns are product configuration, not a generic
  one-call reporting surface. When users need custom columns, preserve and sync
  the underlying conversion actions or metrics into BigQuery, then rebuild the
  custom column formulas in SQL/reporting config.

## Meta field coverage strategy

The goal is Windsor-like coverage over time, but not by forcing every platform
field into `unified_ads_daily`.

- Preserve full raw API payloads.
- Keep a compact cross-platform unified table for common metrics.
- Add platform-specific raw/wide tables or views for Meta-only reporting fields.
- Keep field sets configurable by report preset instead of hardcoding one giant
  API call.
- Track field availability in a field catalog when coverage grows.
- Do not assume every Ads Manager UI column is available from one endpoint. Some
  fields require Insights, creative, campaign, ad set, ad, or breakdown endpoints.
- Be careful with breakdowns because age, gender, country, placement, device, and
  publisher platform can multiply rows and are not all freely combinable.

---

## Working rules

1. Only implement the task explicitly requested by the user.
2. Do not implement future roadmap items unless explicitly requested.
3. Before editing, inspect existing code and docs to avoid duplicate or conflicting logic.
4. Build on top of the existing foundation instead of recreating files from scratch.
5. Keep changes small, modular, and easy to review.
6. Prefer simple, readable code over clever abstractions.
7. Use Python 3.11+.
8. Use type hints for new Python functions.
9. Add or update tests when changing logic.
10. Preserve raw API responses when implementing ad platform connectors.
11. Never silently drop unknown API fields.
12. If API field names are uncertain, keep them configurable and clearly mark assumptions.
13. Before finishing, summarize:
    - files changed
    - what was implemented
    - how to test it
    - assumptions or limitations
    - recommended next step

---

## Security rules

Never expose, print, log, or commit:

- API keys
- access tokens
- refresh tokens
- client secrets
- service account JSON
- real ad account IDs
- real customer IDs
- `.env`
- `config/clients.yaml`

Use placeholders only in committed files.

Allowed committed examples:

- `.env.example`
- `config/clients.example.yaml`
- fake sample fixtures

---

## BigQuery project

Use these project defaults when examples are needed:

| Item | Value |
|---|---|
| GCP project name | `oudseed` |
| GCP project id | `oudseed` |
| GCP project number | `252487346065` |
| BigQuery dataset | `ads_pipeline` |

Do not hardcode these values into reusable library functions. Prefer environment variables or config files.

---

## Testing expectations

When possible, run:

```bash
make check
```

If `make check` is not available yet, run:

```bash
python -m compileall src tests
pytest
```

If tests cannot be run, explain why and provide the exact command the user should run locally.

---

## Branch and PR expectations

The user prefers local testing before pushing to GitHub.

Recommended workflow:

```text
local feature branch → local test → push branch → open PR → review → merge to main
```

Do not assume direct commits to `main`.
