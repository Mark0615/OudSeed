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
  add_to_cart FLOAT64,
  purchase FLOAT64,
  purchase_value FLOAT64,
  cost_per_add_to_cart FLOAT64,
  cost_per_purchase FLOAT64,
  outbound_clicks INT64,
  page_engagement FLOAT64,
  post_engagement FLOAT64,
  post_reactions FLOAT64,
  post_comments FLOAT64,
  post_saves FLOAT64,
  post_shares FLOAT64,
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

ALTER TABLE `oudseed.ads_pipeline.unified_ads_daily`
ADD COLUMN IF NOT EXISTS add_to_cart FLOAT64,
ADD COLUMN IF NOT EXISTS purchase FLOAT64,
ADD COLUMN IF NOT EXISTS purchase_value FLOAT64,
ADD COLUMN IF NOT EXISTS cost_per_add_to_cart FLOAT64,
ADD COLUMN IF NOT EXISTS cost_per_purchase FLOAT64,
ADD COLUMN IF NOT EXISTS outbound_clicks INT64,
ADD COLUMN IF NOT EXISTS page_engagement FLOAT64,
ADD COLUMN IF NOT EXISTS post_engagement FLOAT64,
ADD COLUMN IF NOT EXISTS post_reactions FLOAT64,
ADD COLUMN IF NOT EXISTS post_comments FLOAT64,
ADD COLUMN IF NOT EXISTS post_saves FLOAT64,
ADD COLUMN IF NOT EXISTS post_shares FLOAT64;

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
  account_name STRING,
  campaign_id STRING,
  campaign_name STRING,
  impressions INT64,
  clicks INT64,
  spend FLOAT64,
  conversions FLOAT64,
  conversion_value FLOAT64,
  add_to_cart FLOAT64,
  purchase FLOAT64,
  purchase_value FLOAT64,
  cost_per_add_to_cart FLOAT64,
  cost_per_purchase FLOAT64,
  outbound_clicks INT64,
  page_engagement FLOAT64,
  post_engagement FLOAT64,
  post_reactions FLOAT64,
  post_comments FLOAT64,
  post_saves FLOAT64,
  post_shares FLOAT64,
  ctr FLOAT64,
  cpc FLOAT64,
  cpm FLOAT64,
  cpa FLOAT64,
  roas FLOAT64,
  previous_week_spend FLOAT64,
  previous_week_clicks INT64,
  previous_week_conversions FLOAT64,
  previous_week_add_to_cart FLOAT64,
  previous_week_purchase FLOAT64,
  previous_week_cpc FLOAT64,
  previous_week_cpa FLOAT64,
  previous_week_roas FLOAT64,
  spend_wow FLOAT64,
  clicks_wow INT64,
  conversions_wow FLOAT64,
  add_to_cart_wow FLOAT64,
  purchase_wow FLOAT64,
  cpc_wow FLOAT64,
  cpa_wow FLOAT64,
  roas_wow FLOAT64,
  spend_wow_rate FLOAT64,
  clicks_wow_rate FLOAT64,
  conversions_wow_rate FLOAT64,
  add_to_cart_wow_rate FLOAT64,
  purchase_wow_rate FLOAT64,
  cpc_wow_rate FLOAT64,
  cpa_wow_rate FLOAT64,
  roas_wow_rate FLOAT64,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
PARTITION BY week_start_date
CLUSTER BY workspace_id, client_id, platform, account_id;

CREATE TABLE IF NOT EXISTS `oudseed.ads_pipeline.monthly_performance_summary` (
  month_start_date DATE NOT NULL,
  month_end_date DATE NOT NULL,
  workspace_id STRING NOT NULL,
  client_id STRING NOT NULL,
  platform STRING NOT NULL,
  account_id STRING,
  account_name STRING,
  campaign_id STRING,
  campaign_name STRING,
  impressions INT64,
  clicks INT64,
  spend FLOAT64,
  conversions FLOAT64,
  conversion_value FLOAT64,
  add_to_cart FLOAT64,
  purchase FLOAT64,
  purchase_value FLOAT64,
  cost_per_add_to_cart FLOAT64,
  cost_per_purchase FLOAT64,
  outbound_clicks INT64,
  page_engagement FLOAT64,
  post_engagement FLOAT64,
  post_reactions FLOAT64,
  post_comments FLOAT64,
  post_saves FLOAT64,
  post_shares FLOAT64,
  ctr FLOAT64,
  cpc FLOAT64,
  cpm FLOAT64,
  cpa FLOAT64,
  roas FLOAT64,
  previous_month_spend FLOAT64,
  previous_month_clicks INT64,
  previous_month_conversions FLOAT64,
  previous_month_add_to_cart FLOAT64,
  previous_month_purchase FLOAT64,
  previous_month_cpc FLOAT64,
  previous_month_cpa FLOAT64,
  previous_month_roas FLOAT64,
  spend_mom FLOAT64,
  clicks_mom INT64,
  conversions_mom FLOAT64,
  add_to_cart_mom FLOAT64,
  purchase_mom FLOAT64,
  cpc_mom FLOAT64,
  cpa_mom FLOAT64,
  roas_mom FLOAT64,
  spend_mom_rate FLOAT64,
  clicks_mom_rate FLOAT64,
  conversions_mom_rate FLOAT64,
  add_to_cart_mom_rate FLOAT64,
  purchase_mom_rate FLOAT64,
  cpc_mom_rate FLOAT64,
  cpa_mom_rate FLOAT64,
  roas_mom_rate FLOAT64,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
)
PARTITION BY month_start_date
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
