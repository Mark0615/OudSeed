# AI Report Operations Runbook

This runbook covers the MVP account-grouped AI report workflow. It is designed
for repeatable weekly/monthly report operations without exposing secrets or real
ad account IDs.

## Scope

Use this workflow for:

- listing account groups for a report period
- sending one account-group test report
- sending a capped batch
- sending the full account-grouped HTML report batch
- checking whether reports were generated and logged

This workflow does not configure SaaS users, OAuth, Google Sheets export, LINE
delivery, or platform connectors.

## Required Inputs

Confirm these inputs before a send:

| Input | Source | Notes |
|---|---|---|
| Report type | Operator decision | `weekly` or `monthly` |
| Period start date | Operator decision or schedule default | Leave empty only for scheduled jobs |
| Recipient | Operator decision | Use a test recipient before client delivery |
| Report depth | Operator decision | `standard` for client-ready reports, `deep` for diagnostic review |
| Account group | BigQuery account names | Use list mode to discover available names |

When a client has `report_schedules` configured in `config/clients.yaml`, set
`AI_REPORT_SCHEDULE_ID` instead of repeating report type, delivery day,
recipient, depth, and account-group defaults in every command.

## Environment Checklist

Set these values locally or in the Cloud Run Job environment:

```bash
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-5.2
OPENAI_REASONING_EFFORT=medium
OPENAI_TIMEOUT_SECONDS=60
AI_REPORT_TYPE=monthly
AI_REPORT_SCHEDULE_ID=monthly_email_default
AI_REPORT_PERIOD_START_DATE=2026-04-01
AI_REPORT_CLIENT_ID=your-client-id
AI_REPORT_LIMIT=50
AI_REPORT_DEPTH=standard
AI_REPORT_TIMEZONE=Asia/Taipei
AI_REPORT_EMAIL_TO=recipient@example.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-sender-email@example.com
SMTP_PASSWORD=your-smtp-or-app-password
SMTP_FROM_EMAIL=your-sender-email@example.com
SMTP_USE_TLS=true
```

For scheduled jobs, leave `AI_REPORT_PERIOD_START_DATE` empty. Monthly reports
default to the previous complete month. Weekly reports default to the previous
complete Monday-starting week.

## 1. List Account Groups

List mode confirms which account-group names exist for the selected period. It
does not call OpenAI and does not send email.

```bash
AI_REPORT_LIST_ACCOUNT_GROUPS=true \
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-04-01 \
.venv/bin/python -m src.ai.send_account_reports
```

Expected output includes only the group name, platforms, and account count. Do
not add real account IDs to runbook notes, screenshots, or committed files.

## 2. Send One Test Report

Send one specific account group to an internal recipient first:

```bash
AI_REPORT_ACCOUNT_GROUP_NAME="Example Account" \
AI_REPORT_EMAIL_TO=recipient@example.com \
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-04-01 \
AI_REPORT_DEPTH=deep \
.venv/bin/python -m src.ai.send_account_reports
```

Review the email for:

- correct account group and reporting period
- campaign table before the AI insight
- deterministic diagnostics section
- clear warnings for high-spend or sharply worsening items
- no visible Markdown artifacts such as raw `**`
- no exposed secrets, tokens, or real account IDs

## 3. Send a Capped Batch

Use a capped batch when validating a new period, recipient, or model setting:

```bash
AI_REPORT_ACCOUNT_GROUP_LIMIT=1 \
AI_REPORT_EMAIL_TO=recipient@example.com \
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-04-01 \
AI_REPORT_DEPTH=standard \
.venv/bin/python -m src.ai.send_account_reports
```

Increase `AI_REPORT_ACCOUNT_GROUP_LIMIT` gradually if multiple account groups
need internal review before a full send.

## 4. Send the Full Batch

After list mode and at least one test send pass review, remove
`AI_REPORT_ACCOUNT_GROUP_NAME`, `AI_REPORT_ACCOUNT_GROUP_LIMIT`, and
`AI_REPORT_LIST_ACCOUNT_GROUPS`.

```bash
AI_REPORT_EMAIL_TO=recipient@example.com \
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-04-01 \
AI_REPORT_DEPTH=standard \
.venv/bin/python -m src.ai.send_account_reports
```

The command sends one HTML email per account group.

## 5. Verify Logs

After a send, verify that each account group wrote a row to `ai_report_logs`.
Use placeholders in saved queries and docs:

```sql
SELECT
  report_id,
  report_type,
  period_start_date,
  account_id,
  status,
  error_message,
  created_at
FROM `oudseed.ads_pipeline.ai_report_logs`
WHERE period_start_date = DATE '2026-04-01'
ORDER BY created_at DESC;
```

Expected results:

- successful sends have `status = 'success'`
- failed generation or delivery attempts have `status = 'failed'`
- failed rows include an actionable `error_message`

## Troubleshooting

| Symptom | Likely Cause | Action |
|---|---|---|
| No account groups found | No summary data for the period or wrong client | Confirm `AI_REPORT_TYPE`, `AI_REPORT_PERIOD_START_DATE`, and `AI_REPORT_CLIENT_ID` |
| Account group filter fails | Name does not exactly match list mode output | Re-run list mode and copy the group name exactly |
| Email not received | SMTP or recipient issue | Confirm SMTP env vars and test with an internal recipient |
| Report is too long | Depth is too high for client delivery | Use `AI_REPORT_DEPTH=standard` or `brief` |
| Diagnostics are generic | Detail rows unavailable for the period | Check ad group/ad/keyword/search term marts and field coverage |

## Release Checklist

Before sending client-visible reports:

- `main` is deployed or the local checkout matches the intended release
- `make check` passes for code changes
- list mode returns the expected account groups
- one internal test email has been reviewed
- report depth is set intentionally
- recipient is correct
- no secrets, tokens, real ad account IDs, or real customer IDs are copied into
  docs, logs, screenshots, or PR comments

## Next Productization Step

Move the manual env-var workflow into account-level report schedule config. The
config should define cadence, delivery day, recipient, channel, default depth,
and optional account-group override without changing report generation logic.
