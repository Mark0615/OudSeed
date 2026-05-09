# Cloud Run Job + Cloud Scheduler Deployment

This guide deploys the v0.1 Meta Ads sync as a Cloud Run Job and schedules it to run every day at 04:00 Asia/Taipei.

The deployment uses:

- Cloud Run Jobs for the batch sync process
- Cloud Scheduler for the daily trigger
- Secret Manager for `META_ACCESS_TOKEN` and `config/clients.yaml`
- Artifact Registry for the container image
- A dedicated runtime service account for BigQuery and Secret Manager access

## Defaults

| Setting | Value |
|---|---|
| Project ID | `oudseed` |
| Project number | `252487346065` |
| Region | `asia-east1` |
| Artifact Registry repository | `ads-ai-pipeline` |
| Cloud Run Job | `oudseed-meta-ads-sync` |
| Cloud Scheduler Job | `oudseed-meta-ads-sync-daily` |
| Schedule | `0 4 * * *` |
| Timezone | `Asia/Taipei` |

## Prerequisites

Make sure local files exist:

```bash
.env
config/clients.yaml
```

Required `.env` values:

```bash
GCP_PROJECT_ID=oudseed
BIGQUERY_DATASET=ads_pipeline
META_ACCESS_TOKEN=your-meta-marketing-api-token
```

`GOOGLE_APPLICATION_CREDENTIALS` is useful for local runs, but Cloud Run does not use the local JSON key. Cloud Run uses the runtime service account created by the deployment script.

## Deploy

Run:

```bash
bash deploy/deploy_cloud_run_job.sh
```

The script will:

1. Enable required Google Cloud APIs.
2. Create the Artifact Registry repository if needed.
3. Create the runtime service account if needed.
4. Grant BigQuery access to the runtime service account.
5. Store `META_ACCESS_TOKEN` and `config/clients.yaml` in Secret Manager.
6. Build and push the Docker image.
7. Create or update the Cloud Run Job.
8. Create or update the Cloud Scheduler trigger.

Override defaults when needed:

```bash
REGION=asia-east1 SCHEDULE="0 4 * * *" bash deploy/deploy_cloud_run_job.sh
```

## Manual Execute

Run the job immediately:

```bash
gcloud run jobs execute oudseed-meta-ads-sync --region asia-east1 --wait
```

## Check Logs

View recent job logs:

```bash
gcloud run jobs logs read oudseed-meta-ads-sync --region asia-east1 --limit 100
```

## Check Scheduler

Describe the scheduler trigger:

```bash
gcloud scheduler jobs describe oudseed-meta-ads-sync-daily --location asia-east1
```

Run the scheduler trigger manually:

```bash
gcloud scheduler jobs run oudseed-meta-ads-sync-daily --location asia-east1
```

## Verify BigQuery

```sql
SELECT
  status,
  rows_fetched,
  rows_inserted,
  error_message,
  started_at,
  finished_at
FROM `oudseed.ads_pipeline.vw_looker_sync_status`
ORDER BY started_at DESC
LIMIT 10;
```

## Troubleshooting

If the latest sync log shows a Meta token error like:

```text
Error validating access token: Session has expired
```

Generate a new Meta Marketing API access token, update local `.env`, then rerun:

```bash
bash deploy/deploy_cloud_run_job.sh
gcloud run jobs execute oudseed-meta-ads-sync --region asia-east1 --wait
```

The deployment script will add a new Secret Manager version for `oudseed-meta-access-token` and update the Cloud Run Job to use the latest secret.

If a sync fails for any account, the pipeline writes a `failed` row to `sync_logs` and exits non-zero so Cloud Run job executions also show as failed.

## Notes

- The Cloud Run Job reads `CLIENTS_CONFIG_YAML` from Secret Manager.
- The local `config/clients.yaml` file is never committed.
- If you change local `config/clients.yaml` or `META_ACCESS_TOKEN`, rerun `bash deploy/deploy_cloud_run_job.sh` to add a new Secret Manager version and update the job.
