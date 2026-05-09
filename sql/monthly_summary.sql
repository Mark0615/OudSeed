-- BigQuery Standard SQL
-- Refresh monthly_performance_summary from unified_ads_daily.
--
-- This table is the stable input layer for future AI monthly reports. All
-- numeric metrics and MoM comparisons are calculated in SQL so downstream AI
-- should not invent or recalculate performance numbers.

CREATE OR REPLACE TABLE `oudseed.ads_pipeline.monthly_performance_summary`
PARTITION BY month_start_date
CLUSTER BY workspace_id, client_id, platform, account_id
AS
WITH monthly AS (
  SELECT
    DATE_TRUNC(date, MONTH) AS month_start_date,
    DATE_SUB(DATE_ADD(DATE_TRUNC(date, MONTH), INTERVAL 1 MONTH), INTERVAL 1 DAY) AS month_end_date,
    workspace_id,
    client_id,
    platform,
    account_id,
    ANY_VALUE(account_name) AS account_name,
    campaign_id,
    ANY_VALUE(campaign_name) AS campaign_name,
    SUM(impressions) AS impressions,
    SUM(clicks) AS clicks,
    SUM(spend) AS spend,
    SUM(conversions) AS conversions,
    SUM(conversion_value) AS conversion_value,
    SAFE_DIVIDE(SUM(clicks), SUM(impressions)) AS ctr,
    SAFE_DIVIDE(SUM(spend), SUM(clicks)) AS cpc,
    SAFE_DIVIDE(SUM(spend) * 1000, SUM(impressions)) AS cpm,
    SAFE_DIVIDE(SUM(spend), SUM(conversions)) AS cpa,
    SAFE_DIVIDE(SUM(conversion_value), SUM(spend)) AS roas
  FROM `oudseed.ads_pipeline.unified_ads_daily`
  GROUP BY
    month_start_date,
    month_end_date,
    workspace_id,
    client_id,
    platform,
    account_id,
    campaign_id
),
with_previous AS (
  SELECT
    monthly.*,
    LAG(spend) OVER monthly_window AS previous_month_spend,
    LAG(clicks) OVER monthly_window AS previous_month_clicks,
    LAG(conversions) OVER monthly_window AS previous_month_conversions,
    LAG(cpc) OVER monthly_window AS previous_month_cpc,
    LAG(cpa) OVER monthly_window AS previous_month_cpa,
    LAG(roas) OVER monthly_window AS previous_month_roas
  FROM monthly
  WINDOW monthly_window AS (
    PARTITION BY workspace_id, client_id, platform, account_id, campaign_id
    ORDER BY month_start_date
  )
)
SELECT
  month_start_date,
  month_end_date,
  workspace_id,
  client_id,
  platform,
  account_id,
  account_name,
  campaign_id,
  campaign_name,
  impressions,
  clicks,
  spend,
  conversions,
  conversion_value,
  ctr,
  cpc,
  cpm,
  cpa,
  roas,
  previous_month_spend,
  previous_month_clicks,
  previous_month_conversions,
  previous_month_cpc,
  previous_month_cpa,
  previous_month_roas,
  spend - previous_month_spend AS spend_mom,
  clicks - previous_month_clicks AS clicks_mom,
  conversions - previous_month_conversions AS conversions_mom,
  cpc - previous_month_cpc AS cpc_mom,
  cpa - previous_month_cpa AS cpa_mom,
  roas - previous_month_roas AS roas_mom,
  SAFE_DIVIDE(spend - previous_month_spend, previous_month_spend) AS spend_mom_rate,
  SAFE_DIVIDE(clicks - previous_month_clicks, previous_month_clicks) AS clicks_mom_rate,
  SAFE_DIVIDE(conversions - previous_month_conversions, previous_month_conversions) AS conversions_mom_rate,
  SAFE_DIVIDE(cpc - previous_month_cpc, previous_month_cpc) AS cpc_mom_rate,
  SAFE_DIVIDE(cpa - previous_month_cpa, previous_month_cpa) AS cpa_mom_rate,
  SAFE_DIVIDE(roas - previous_month_roas, previous_month_roas) AS roas_mom_rate,
  CURRENT_TIMESTAMP() AS created_at,
  CURRENT_TIMESTAMP() AS updated_at
FROM with_previous;
