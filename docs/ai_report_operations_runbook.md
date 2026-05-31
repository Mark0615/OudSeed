# AI Report Operations Runbook

This runbook covers the MVP account-grouped AI report workflow. It is designed
for repeatable weekly/monthly report operations without exposing secrets or real
ad account IDs.

## Scope

Use this workflow for:

- listing account groups for a report period
- listing configured report schedules
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
OPENAI_TIMEOUT_SECONDS=180
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

Use `AI_REPORT_PREFLIGHT=true` to verify a scheduled account report without
calling OpenAI or sending email. Preflight prints resolved report settings,
group count, and account group names while hiding recipient emails and account
IDs.

## 1. List Report Schedules

List schedules first when `config/clients.yaml` contains `report_schedules`.
This confirms schedule ids, cadence, delivery day, depth, enabled state, and
whether a recipient is configured without printing recipient emails.

```bash
AI_REPORT_LIST_SCHEDULES=true \
.venv/bin/python -m src.ai.send_account_reports
```

## 2. List Account Groups

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

## 3. Send One Test Report

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

## 4. Send a Capped Batch

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

## 5. Send the Full Batch

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

## 6. Verify Logs

After a send, verify that each account group wrote a row to `ai_report_logs`.
Use the safe checker for routine operations:

```bash
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-04-01 \
make ai-report-logs
```

When the same period has older test runs, verify only a specific batch:

```bash
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-04-01 \
AI_REPORT_LOG_CREATED_AFTER=2026-05-28T13:52:00Z \
make ai-report-logs
```

For automation, fail the command when the fetched window is incomplete or has
failures:

```bash
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-04-01 \
AI_REPORT_LOG_CREATED_AFTER=2026-05-28T13:52:00Z \
AI_REPORT_LOG_REQUIRE_COMPLETE=true \
make ai-report-logs
```

Use `AI_REPORT_LOG_SHOW_ROWS=false` for summary-only output. The combined
`make ai-report-verify` target uses summary-only log output by default.

Run the full operations verification flow after a deployment or scheduled send:

```bash
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-04-01 \
AI_REPORT_LOG_CREATED_AFTER=2026-05-28T13:52:00Z \
make ai-report-verify
```

This runs the deploy preview, Cloud Run/Scheduler status check, and report-log
completeness check. When `AI_REPORT_LOG_CREATED_AFTER` is set, the log check
defaults to `AI_REPORT_LOG_REQUIRE_COMPLETE=true`; without it, the log check is
informational so older test runs do not fail the whole verification.

After the scheduled monthly run, verify the new batch only:

```bash
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-05-01 \
AI_REPORT_LOG_CREATED_AFTER=2026-05-31T21:00:00Z \
make ai-report-post-run
```

`make ai-report-post-run` requires both `AI_REPORT_PERIOD_START_DATE` and
`AI_REPORT_LOG_CREATED_AFTER`, and it always runs the log check in strict mode.
For the `2026-06-01 05:00 Asia/Taipei` scheduled run, use
`AI_REPORT_PERIOD_START_DATE=2026-05-01` and
`AI_REPORT_LOG_CREATED_AFTER=2026-05-31T21:00:00Z`.

Expected output:

- `expected_group_count` equals the account groups found in reporting marts
- `successful_group_count` equals the number of expected groups with at least
  one successful report log in the fetched result window
- `success_log_count` may be higher than `successful_group_count` if the same
  period was tested multiple times
- `failed_log_count=0`
- `delivery_failure_count=0`
- `unconfirmed_group_count=0`

Use placeholders in saved ad-hoc queries and docs:

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
- failed generation attempts have `status = 'failed'`
- failed email delivery attempts add a second row for the same `report_id` with
  `status = 'failed'` and `error_message` prefixed by `email_delivery_failed:`
- failed rows include an actionable `error_message`

## Troubleshooting

| Symptom | Likely Cause | Action |
|---|---|---|
| Schedule id not found | Wrong `AI_REPORT_SCHEDULE_ID` or config not deployed | Run `AI_REPORT_LIST_SCHEDULES=true` locally and confirm Secret Manager config |
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

## Cloud Run Operations

Use these commands for the deployed account-grouped monthly report job.

Example deployment:

```bash
bash deploy/deploy_account_ai_report_job.sh
```

Account-report deployments default to `OPENAI_TIMEOUT_SECONDS=180`,
`OPENAI_MAX_OUTPUT_TOKENS=5000`, and `JOB_MAX_RETRIES=0` for production email
sends. The longer timeout gives the Responses API enough room for account-level
HTML reports, and zero job-level retries avoids duplicate emails after a partial
send.

Preview effective deploy settings before touching GCP:

```bash
make ai-report-deploy-dry-run
```

The preview prints only sanitized flags and effective runtime settings. Values
passed directly to the deploy command take priority over `.env`, which prevents
older local defaults from overriding production account-report settings.
The account-report wrapper defaults `AI_REPORT_SCHEDULE_ID` to
`monthly_email_default`; override it only for a different scheduled report
variant.
Dry-run can run without real secrets; it reports configured flags such as
`openai_api_key_configured` and `clients_config_file_exists` without printing
secret values.

Run the combined operations check after deployment or after a scheduled send:

```bash
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-04-01 \
AI_REPORT_LOG_CREATED_AFTER=2026-05-28T13:52:00Z \
make ai-report-verify
```

Safe Cloud Run verification:

```bash
make ai-report-preflight
```

The helper enables `AI_REPORT_PREFLIGHT`, executes the Cloud Run Job, prints the
sanitized preflight logs, and removes `AI_REPORT_PREFLIGHT` on exit so the next
scheduled run sends the real report.

Check deployed job and scheduler state:

```bash
make ai-report-status
```

Run the readiness gate before a scheduled send:

```bash
make ai-report-ready
```

The readiness gate exits non-zero when production settings are unsafe, including
enabled preflight, disabled Scheduler, missing schedule/recipient/secrets, wrong
module, wrong model, low timeout/tokens, or non-zero Cloud Run retries.

Expected production state:

- `ready=True`
- `max_retries=0`
- `openai_timeout_seconds=180`
- `preflight_enabled=false`
- `scheduler_state=ENABLED`
- `recipient_configured=true`
- `openai_secret_configured=true`
- `clients_config_secret_configured=true`
- `smtp_password_secret_configured=true`
