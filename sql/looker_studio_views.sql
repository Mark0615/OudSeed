-- BigQuery Standard SQL
-- Looker Studio friendly views for the OudSeed v0.1 dashboard.
--
-- These views keep raw table storage separate from reporting semantics.
-- Ratio metrics are recalculated from aggregated numerators/denominators
-- so Looker Studio charts do not average row-level rates by mistake.

CREATE OR REPLACE VIEW `oudseed.ads_pipeline.vw_looker_ads_ad_daily` AS
SELECT
  date,
  workspace_id,
  client_id,
  platform,
  account_id,
  account_name,
  campaign_id,
  campaign_name,
  ad_group_id,
  ad_group_name,
  ad_id,
  ad_name,
  impressions,
  clicks AS link_clicks,
  spend,
  conversions,
  conversion_value,
  SAFE_DIVIDE(clicks, impressions) AS ctr,
  SAFE_DIVIDE(spend, clicks) AS cpc,
  SAFE_DIVIDE(spend * 1000, impressions) AS cpm,
  SAFE_DIVIDE(spend, conversions) AS cpa,
  SAFE_DIVIDE(conversion_value, spend) AS roas,
  currency,
  source_updated_at,
  created_at,
  updated_at
FROM `oudseed.ads_pipeline.unified_ads_daily`;

CREATE OR REPLACE VIEW `oudseed.ads_pipeline.vw_looker_ads_campaign_daily` AS
SELECT
  date,
  workspace_id,
  client_id,
  platform,
  account_id,
  ANY_VALUE(account_name) AS account_name,
  campaign_id,
  ANY_VALUE(campaign_name) AS campaign_name,
  SUM(impressions) AS impressions,
  SUM(clicks) AS link_clicks,
  SUM(spend) AS spend,
  SUM(conversions) AS conversions,
  SUM(conversion_value) AS conversion_value,
  SAFE_DIVIDE(SUM(clicks), SUM(impressions)) AS ctr,
  SAFE_DIVIDE(SUM(spend), SUM(clicks)) AS cpc,
  SAFE_DIVIDE(SUM(spend) * 1000, SUM(impressions)) AS cpm,
  SAFE_DIVIDE(SUM(spend), SUM(conversions)) AS cpa,
  SAFE_DIVIDE(SUM(conversion_value), SUM(spend)) AS roas,
  ANY_VALUE(currency) AS currency,
  MAX(updated_at) AS updated_at
FROM `oudseed.ads_pipeline.unified_ads_daily`
GROUP BY
  date,
  workspace_id,
  client_id,
  platform,
  account_id,
  campaign_id;

CREATE OR REPLACE VIEW `oudseed.ads_pipeline.vw_looker_sync_status` AS
SELECT
  sync_id,
  workspace_id,
  client_id,
  platform,
  account_id,
  sync_start_date,
  sync_end_date,
  status,
  rows_fetched,
  rows_inserted,
  error_message,
  attribution_setting,
  timezone_setting,
  scheduler_timezone,
  started_at,
  finished_at,
  TIMESTAMP_DIFF(finished_at, started_at, SECOND) AS duration_seconds
FROM `oudseed.ads_pipeline.sync_logs`;
