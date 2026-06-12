PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip

.PHONY: install install-dev test lint format run refresh-marts per-account-views backfill daily-sync daily-sync-deploy dispatch-reports web web-deploy web-image-build check ai-report-deploy-dry-run ai-report-status ai-report-ready ai-report-preflight ai-report-logs ai-report-post-run ai-report-verify clean

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements-dev.txt

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m compileall src tests

format:
	$(PYTHON) -m ruff check --fix src tests

run:
	$(PYTHON) -m src.main

# (Re)create the BigQuery reporting marts + Looker Studio views without
# re-syncing ad data. Run this once after a new view is added so it appears in
# Data Studio. Touches real BigQuery, so it is manual/opt-in here.
refresh-marts:
	$(PYTHON) -m src.refresh_marts

# Generate one Looker/Data Studio view per ad account (vw_acct_<platform>_<id>)
# so each Data Studio source maps to a single account. Thin filters over the wide
# views — no re-sync. DRY-RUN here; add --apply to actually create the views.
# Touches real BigQuery, so it is manual/opt-in.
per-account-views:
	$(PYTHON) scripts/generate_per_account_views.py

# One-time historical backfill of every workspace's selected accounts to the
# platform limit (~36 months), one ~30-day window at a time. Heavy + one-off.
# Touches real ad APIs + BigQuery, so it is manual/opt-in here.
backfill:
	$(PYTHON) -m src.sync.backfill

# Daily auto-sync of every workspace's selected accounts into BigQuery, then
# refresh the reporting views. Run daily in production via Cloud Scheduler ->
# Cloud Run Job. Touches real ad APIs + BigQuery, so it is manual/opt-in here.
daily-sync:
	$(PYTHON) -m src.sync.daily_sync

# Send every workspace report that is due today (the automatic dispatcher).
# Run daily in production via Cloud Scheduler -> Cloud Run Job. Touches real
# BigQuery/OpenAI/SMTP, so it is manual/opt-in here.
dispatch-reports:
	$(PYTHON) -m src.ai.dispatch_scheduled_reports

web:
	@echo "▶ Open http://localhost:8765  (use localhost, NOT 127.0.0.1 — OAuth cookies/redirect require it)"
	$(PYTHON) -m uvicorn src.web.server:app --host 127.0.0.1 --port 8765 --reload

# Deploy the web app to Cloud Run (reads .env, touches GCP/billing — manual/opt-in).
# Full walkthrough: docs/web_deployment_runbook.md
web-deploy:
	@echo "▶ Deploying web app to Cloud Run. See docs/web_deployment_runbook.md"
	bash deploy/deploy_cloud_run_web.sh

# Build + push the web image only (no service deploy).
web-image-build:
	gcloud builds submit --config=deploy/cloudbuild.web.yaml .

# Deploy the automatic sync to Cloud Run: a DAILY-scheduled daily_sync job and a
# manual backfill job (both read accounts from Cloud SQL). Touches GCP/billing.
# Full walkthrough: docs/web_deployment_runbook.md
daily-sync-deploy:
	@echo "▶ Deploying sync jobs to Cloud Run. See docs/web_deployment_runbook.md"
	bash deploy/deploy_daily_sync_job.sh

check:
	$(PYTHON) -m ruff check src tests && $(PYTHON) -m compileall src tests && $(PYTHON) -m pytest

ai-report-deploy-dry-run:
	DEPLOY_DRY_RUN=true bash deploy/deploy_account_ai_report_job.sh

ai-report-status:
	PYTHON_BIN=$(PYTHON) bash deploy/check_account_ai_report_status.sh

ai-report-ready:
	PYTHON_BIN=$(PYTHON) bash deploy/check_account_ai_report_ready.sh

ai-report-preflight:
	bash deploy/run_account_ai_report_preflight.sh

ai-report-logs:
	PYTHON_BIN=$(PYTHON) bash deploy/check_account_ai_report_logs.sh

ai-report-post-run:
	PYTHON_BIN=$(PYTHON) bash deploy/verify_account_ai_report_post_run.sh

ai-report-verify:
	PYTHON_BIN=$(PYTHON) bash deploy/verify_account_ai_report_ops.sh

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -prune -exec rm -rf {} +
