#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

if [[ -z "${AI_REPORT_PERIOD_START_DATE:-}" ]]; then
  echo "Missing AI_REPORT_PERIOD_START_DATE. Set the report period to verify, for example 2026-05-01." >&2
  exit 1
fi

if [[ -z "${AI_REPORT_LOG_CREATED_AFTER:-}" ]]; then
  echo "Missing AI_REPORT_LOG_CREATED_AFTER. Set it to the scheduled batch start time." >&2
  echo "Example: AI_REPORT_LOG_CREATED_AFTER=2026-05-31T21:00:00Z" >&2
  exit 1
fi

AI_REPORT_LOG_REQUIRE_COMPLETE=true \
AI_REPORT_LOG_SHOW_ROWS="${AI_REPORT_LOG_SHOW_ROWS:-false}" \
PYTHON_BIN="${PYTHON_BIN}" \
bash deploy/check_account_ai_report_logs.sh
