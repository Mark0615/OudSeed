#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-oudseed}"
REGION="${REGION:-asia-east1}"
SCHEDULER_REGION="${SCHEDULER_REGION:-asia-east1}"
JOB_NAME="${JOB_NAME:-oudseed-account-ai-report}"
SCHEDULER_JOB_NAME="${SCHEDULER_JOB_NAME:-oudseed-account-ai-report-monthly}"
EXPECTED_SCHEDULE="${EXPECTED_SCHEDULE:-0 5 1 * *}"
EXPECTED_TIME_ZONE="${EXPECTED_TIME_ZONE:-Asia/Taipei}"
EXPECTED_MODULE="${EXPECTED_MODULE:-src.ai.send_account_reports}"
EXPECTED_MODEL="${EXPECTED_MODEL:-gpt-5.2}"
MIN_OPENAI_TIMEOUT_SECONDS="${MIN_OPENAI_TIMEOUT_SECONDS:-180}"
MIN_OPENAI_MAX_OUTPUT_TOKENS="${MIN_OPENAI_MAX_OUTPUT_TOKENS:-5000}"
GCLOUD_TIMEOUT_SECONDS="${GCLOUD_TIMEOUT_SECONDS:-60}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

export PROJECT_ID
export REGION
export SCHEDULER_REGION
export JOB_NAME
export SCHEDULER_JOB_NAME
export EXPECTED_SCHEDULE
export EXPECTED_TIME_ZONE
export EXPECTED_MODULE
export EXPECTED_MODEL
export MIN_OPENAI_TIMEOUT_SECONDS
export MIN_OPENAI_MAX_OUTPUT_TOKENS
export GCLOUD_TIMEOUT_SECONDS

"${PYTHON_BIN}" - <<'PY'
import json
import os
import subprocess


def env(name: str) -> str:
    return os.environ[name]


def gcloud_json(args: list[str]) -> dict:
    timeout_seconds = int(env("GCLOUD_TIMEOUT_SECONDS"))
    result = subprocess.run(
        ["gcloud", *args, "--format=json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    return json.loads(result.stdout)


try:
    job = gcloud_json(
        [
            "run",
            "jobs",
            "describe",
            env("JOB_NAME"),
            f"--region={env('REGION')}",
            f"--project={env('PROJECT_ID')}",
        ]
    )
    scheduler = gcloud_json(
        [
            "scheduler",
            "jobs",
            "describe",
            env("SCHEDULER_JOB_NAME"),
            f"--location={env('SCHEDULER_REGION')}",
            f"--project={env('PROJECT_ID')}",
        ]
    )
except subprocess.TimeoutExpired as exc:
    print("account_report_ready=false failed_count=1")
    print(f"ready_check=gcloud_timeout ok=false actual={exc.timeout}s")
    raise SystemExit(1) from exc
except subprocess.CalledProcessError as exc:
    print("account_report_ready=false failed_count=1")
    print(f"ready_check=gcloud_command ok=false actual=exit_{exc.returncode}")
    raise SystemExit(1) from exc

template_spec = job["spec"]["template"]["spec"]["template"]["spec"]
container = template_spec["containers"][0]
env_items = {item.get("name"): item for item in container.get("env", [])}
plain_env = {
    name: item.get("value")
    for name, item in env_items.items()
    if "value" in item
}
conditions = {
    condition.get("type"): condition.get("status")
    for condition in job.get("status", {}).get("conditions", [])
}


def module_name() -> str:
    args = container.get("args", [])
    if "-m" in args:
        module_index = args.index("-m") + 1
        if module_index < len(args):
            return str(args[module_index])
    return str(plain_env.get("AI_REPORT_MODULE") or "-")


def int_env(name: str) -> int:
    try:
        return int(str(plain_env.get(name) or "0"))
    except ValueError:
        return 0


checks = [
    ("job_ready", conditions.get("Ready") == "True", conditions.get("Ready", "-")),
    ("module", module_name() == env("EXPECTED_MODULE"), module_name()),
    ("max_retries", template_spec.get("maxRetries") == 0, template_spec.get("maxRetries", "-")),
    ("openai_model", plain_env.get("OPENAI_MODEL") == env("EXPECTED_MODEL"), plain_env.get("OPENAI_MODEL", "-")),
    (
        "openai_timeout_seconds",
        int_env("OPENAI_TIMEOUT_SECONDS") >= int(env("MIN_OPENAI_TIMEOUT_SECONDS")),
        plain_env.get("OPENAI_TIMEOUT_SECONDS", "-"),
    ),
    (
        "openai_max_output_tokens",
        int_env("OPENAI_MAX_OUTPUT_TOKENS") >= int(env("MIN_OPENAI_MAX_OUTPUT_TOKENS")),
        plain_env.get("OPENAI_MAX_OUTPUT_TOKENS", "-"),
    ),
    ("preflight_disabled", plain_env.get("AI_REPORT_PREFLIGHT") != "true", plain_env.get("AI_REPORT_PREFLIGHT", "-")),
    ("schedule_id_configured", "AI_REPORT_SCHEDULE_ID" in env_items, str("AI_REPORT_SCHEDULE_ID" in env_items).lower()),
    ("recipient_configured", "AI_REPORT_EMAIL_TO" in env_items, str("AI_REPORT_EMAIL_TO" in env_items).lower()),
    ("openai_secret_configured", "OPENAI_API_KEY" in env_items, str("OPENAI_API_KEY" in env_items).lower()),
    ("clients_config_secret_configured", "CLIENTS_CONFIG_YAML" in env_items, str("CLIENTS_CONFIG_YAML" in env_items).lower()),
    ("smtp_password_secret_configured", "SMTP_PASSWORD" in env_items, str("SMTP_PASSWORD" in env_items).lower()),
    ("scheduler_enabled", scheduler.get("state") == "ENABLED", scheduler.get("state", "-")),
    ("scheduler_schedule", scheduler.get("schedule") == env("EXPECTED_SCHEDULE"), scheduler.get("schedule", "-")),
    ("scheduler_time_zone", scheduler.get("timeZone") == env("EXPECTED_TIME_ZONE"), scheduler.get("timeZone", "-")),
    ("scheduler_next_schedule_time", bool(scheduler.get("scheduleTime")), scheduler.get("scheduleTime", "-")),
]

failed = [name for name, passed, _ in checks if not passed]
print(f"account_report_ready={str(not failed).lower()} failed_count={len(failed)}")
for name, passed, actual in checks:
    print(f"ready_check={name} ok={str(passed).lower()} actual={actual}")

if failed:
    raise SystemExit(1)
PY
