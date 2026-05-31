# OudSeed Productization Status

This note tracks the current product-shaped MVP state for account-grouped AI
reports. It should stay operational and avoid secrets, real account IDs, or raw
recipient values.

## Current State

- Main deployed report job: `oudseed-account-ai-report`
- Region: `asia-east1`
- Scheduler job: `oudseed-account-ai-report-monthly`
- Scheduler cadence: `0 5 1 * *`, `Asia/Taipei`
- Runtime module: `src.ai.send_account_reports`
- OpenAI model: `gpt-5.2`
- Account-report defaults: `OPENAI_TIMEOUT_SECONDS=180`,
  `OPENAI_MAX_OUTPUT_TOKENS=5000`, `JOB_MAX_RETRIES=0`
- Schedule id: `monthly_email_default`
- Delivery: HTML email, one email per account group

## Operational Commands

Preview deployment settings without touching GCP:

```bash
make ai-report-deploy-dry-run
```

Check deployed Cloud Run and Scheduler status:

```bash
make ai-report-status
```

Run strict readiness checks before a scheduled send:

```bash
make ai-report-ready
```

Run safe preflight without sending email:

```bash
make ai-report-preflight
```

Verify a specific send batch:

```bash
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-04-01 \
AI_REPORT_LOG_CREATED_AFTER=2026-05-28T13:52:00Z \
make ai-report-verify
```

Verify only post-run report logs after a scheduled send:

```bash
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-05-01 \
AI_REPORT_LOG_CREATED_AFTER=2026-05-31T21:00:00Z \
make ai-report-post-run
```

## Next Scheduled Monthly Run

The configured monthly scheduler fires at `2026-06-01 05:00:00 Asia/Taipei`,
which is `2026-05-31T21:00:00Z`. It should generate the May 2026 monthly report
period:

```bash
AI_REPORT_TYPE=monthly \
AI_REPORT_PERIOD_START_DATE=2026-05-01 \
AI_REPORT_LOG_CREATED_AFTER=2026-05-31T21:00:00Z \
make ai-report-post-run
```

Expected healthy post-run values:

- `expected_group_count=2`
- `successful_group_count=2`
- `failed_log_count=0`
- `delivery_failure_count=0`
- `unconfirmed_group_count=0`

## Expected Healthy State

- `account_report_ready=true`
- `ready=True`
- `max_retries=0`
- `openai_model=gpt-5.2`
- `openai_timeout_seconds=180`
- `openai_max_output_tokens=5000`
- `preflight_enabled=false`
- `schedule_id_configured=true`
- `recipient_configured=true`
- `openai_secret_configured=true`
- `clients_config_secret_configured=true`
- `smtp_password_secret_configured=true`
- `scheduler_state=ENABLED`

## Reporting Observability

`vw_looker_ai_report_logs` exposes operational fields for Looker Studio:

- `account_group_name`
- `status`
- `is_email_delivery_failure`
- `has_report_text`
- `report_text_chars`

Use `make ai-report-logs` or `make ai-report-verify` for routine checks. Use
`AI_REPORT_LOG_CREATED_AFTER` when a reporting period has older test runs.

## Current Limitations

- `ai_report_logs` does not yet store `account_group_name` as a first-class
  column; the current view infers it from report context.
- `make ai-report-ready` depends on local `gcloud` responsiveness and exits
  non-zero if GCP reads time out.
- Scheduler success after the next real run still needs post-run verification
  with `AI_REPORT_LOG_CREATED_AFTER` set to the batch start time.
- LINE delivery, SaaS users, OAuth, and payment remain out of MVP scope.
