#!/usr/bin/env bash
set -euo pipefail

JOB_NAME="${JOB_NAME:-oudseed-account-ai-report}" \
SCHEDULER_JOB_NAME="${SCHEDULER_JOB_NAME:-oudseed-account-ai-report-monthly}" \
SCHEDULE="${SCHEDULE:-0 5 1 * *}" \
AI_REPORT_MODULE="${AI_REPORT_MODULE:-src.ai.send_account_reports}" \
AI_REPORT_TYPE="${AI_REPORT_TYPE:-monthly}" \
OPENAI_MAX_OUTPUT_TOKENS="${OPENAI_MAX_OUTPUT_TOKENS:-5000}" \
OPENAI_TIMEOUT_SECONDS="${OPENAI_TIMEOUT_SECONDS:-180}" \
JOB_MAX_RETRIES="${JOB_MAX_RETRIES:-0}" \
bash deploy/deploy_ai_report_job.sh
