-- BigQuery Standard SQL
-- Project: oudseed
-- Dataset: ads_pipeline
--
-- Run this script in BigQuery to create the v0.1 warehouse schema.
-- Reusable application code should still read project and dataset values
-- from config or environment variables instead of hardcoding them.

CREATE SCHEMA IF NOT EXISTS `oudseed.ads_pipeline`
OPTIONS (
  location = "US"
);

CREATE TABLE IF NOT EXISTS `oudseed.ads_pipeline.raw_meta_ads_daily` (
  date DATE NOT NULL,
  workspace_id STRING NOT NULL,
  client_id STRING NOT NULL,
  platform STRING NOT NULL,
  account_id STRING NOT NULL,
  report_level STRING NOT NULL,
  attribution_setting STRING,
  timezone_setting STRING,
  raw_payload JSON NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
PARTITION BY date
CLUSTER BY workspace_id, client_id, platform, account_id;

CREATE TABLE IF NOT EXISTS `oudseed.ads_pipeline.raw_google_ads_daily` (
  date DATE NOT NULL,
  workspace_id STRING NOT NULL,
  client_id STRING NOT NULL,
  platform STRING NOT NULL,
  account_id STRING NOT NULL,
  report_level STRING NOT NULL,
  attribution_setting STRING,
  timezone_setting STRING,
  raw_payload JSON NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
PARTITION BY date
CLUSTER BY workspace_id, client_id, platform, account_id;

CREATE TABLE IF NOT EXISTS `oudseed.ads_pipeline.raw_line_ads_daily` (
  date DATE NOT NULL,
  workspace_id STRING NOT NULL,
  client_id STRING NOT NULL,
  platform STRING NOT NULL,
  account_id STRING NOT NULL,
  report_level STRING NOT NULL,
  attribution_setting STRING,
  timezone_setting STRING,
  raw_payload JSON NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
PARTITION BY date
CLUSTER BY workspace_id, client_id, platform, account_id;

CREATE TABLE IF NOT EXISTS `oudseed.ads_pipeline.unified_ads_daily` (
  date DATE NOT NULL,
  workspace_id STRING NOT NULL,
  client_id STRING NOT NULL,
  platform STRING NOT NULL,
  account_id STRING NOT NULL,
  account_name STRING,
  campaign_id STRING,
  campaign_name STRING,
  ad_group_id STRING,
  ad_group_name STRING,
  ad_id STRING,
  ad_name STRING,
  impressions INT64,
  clicks INT64,
  spend FLOAT64,
  conversions FLOAT64,
  conversion_value FLOAT64,
  ctr FLOAT64,
  cpc FLOAT64,
  cpm FLOAT64,
  cpa FLOAT64,
  roas FLOAT64,
  currency STRING,
  source_updated_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
PARTITION BY date
CLUSTER BY workspace_id, client_id, platform, account_id;

CREATE TABLE IF NOT EXISTS `oudseed.ads_pipeline.sync_logs` (
  sync_id STRING NOT NULL,
  workspace_id STRING NOT NULL,
  client_id STRING NOT NULL,
  platform STRING NOT NULL,
  account_id STRING NOT NULL,
  sync_start_date DATE NOT NULL,
  sync_end_date DATE NOT NULL,
  status STRING NOT NULL,
  rows_fetched INT64,
  rows_inserted INT64,
  error_message STRING,
  attribution_setting STRING,
  timezone_setting STRING,
  scheduler_timezone STRING,
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP
)
PARTITION BY DATE(started_at)
CLUSTER BY workspace_id, client_id, platform, account_id;

CREATE TABLE IF NOT EXISTS `oudseed.ads_pipeline.weekly_performance_summary` (
  week_start_date DATE NOT NULL,
  week_end_date DATE NOT NULL,
  workspace_id STRING NOT NULL,
  client_id STRING NOT NULL,
  platform STRING NOT NULL,
  account_id STRING,
  campaign_id STRING,
  campaign_name STRING,
  impressions INT64,
  clicks INT64,
  spend FLOAT64,
  conversions FLOAT64,
  conversion_value FLOAT64,
  ctr FLOAT64,
  cpc FLOAT64,
  cpa FLOAT64,
  roas FLOAT64,
  spend_wow FLOAT64,
  conversions_wow FLOAT64,
  cpa_wow FLOAT64,
  roas_wow FLOAT64,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
PARTITION BY week_start_date
CLUSTER BY workspace_id, client_id, platform, account_id;

CREATE TABLE IF NOT EXISTS `oudseed.ads_pipeline.ai_report_logs` (
  report_id STRING NOT NULL,
  workspace_id STRING NOT NULL,
  client_id STRING NOT NULL,
  week_start_date DATE,
  week_end_date DATE,
  report_type STRING NOT NULL,
  prompt_payload JSON,
  report_text STRING,
  model_name STRING,
  status STRING NOT NULL,
  error_message STRING,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY workspace_id, client_id, report_type, status;
