-- BigQuery Standard SQL
-- Refresh weekly_performance_summary from unified_ads_daily.
--
-- This table is the stable input layer for future AI weekly reports. All
-- numeric metrics and WoW comparisons are calculated in SQL so downstream AI
-- should not invent or recalculate performance numbers.

CREATE OR REPLACE TABLE `oudseed.ads_pipeline.weekly_performance_summary`
PARTITION BY week_start_date
CLUSTER BY workspace_id, client_id, platform, account_id
AS
WITH weekly AS (
  SELECT
    DATE_TRUNC(date, WEEK(MONDAY)) AS week_start_date,
    DATE_ADD(DATE_TRUNC(date, WEEK(MONDAY)), INTERVAL 6 DAY) AS week_end_date,
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
    SUM(add_to_cart) AS add_to_cart,
    SUM(purchase) AS purchase,
    SUM(purchase_value) AS purchase_value,
    SAFE_DIVIDE(SUM(spend), SUM(add_to_cart)) AS cost_per_add_to_cart,
    SAFE_DIVIDE(SUM(spend), SUM(purchase)) AS cost_per_purchase,
    SUM(outbound_clicks) AS outbound_clicks,
    SUM(page_engagement) AS page_engagement,
    SUM(post_engagement) AS post_engagement,
    SUM(post_reactions) AS post_reactions,
    SUM(post_comments) AS post_comments,
    SUM(post_saves) AS post_saves,
    SUM(post_shares) AS post_shares,
    SAFE_DIVIDE(SUM(clicks), SUM(impressions)) AS ctr,
    SAFE_DIVIDE(SUM(spend), SUM(clicks)) AS cpc,
    SAFE_DIVIDE(SUM(spend) * 1000, SUM(impressions)) AS cpm,
    SAFE_DIVIDE(SUM(spend), SUM(conversions)) AS cpa,
    SAFE_DIVIDE(SUM(conversion_value), SUM(spend)) AS roas
  FROM `oudseed.ads_pipeline.unified_ads_daily`
  GROUP BY
    week_start_date,
    week_end_date,
    workspace_id,
    client_id,
    platform,
    account_id,
    campaign_id
),
with_previous AS (
  SELECT
    weekly.*,
    LAG(spend) OVER weekly_window AS previous_week_spend,
    LAG(clicks) OVER weekly_window AS previous_week_clicks,
    LAG(conversions) OVER weekly_window AS previous_week_conversions,
    LAG(add_to_cart) OVER weekly_window AS previous_week_add_to_cart,
    LAG(purchase) OVER weekly_window AS previous_week_purchase,
    LAG(cpc) OVER weekly_window AS previous_week_cpc,
    LAG(cpa) OVER weekly_window AS previous_week_cpa,
    LAG(roas) OVER weekly_window AS previous_week_roas
  FROM weekly
  WINDOW weekly_window AS (
    PARTITION BY workspace_id, client_id, platform, account_id, campaign_id
    ORDER BY week_start_date
  )
)
SELECT
  week_start_date,
  week_end_date,
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
  add_to_cart,
  purchase,
  purchase_value,
  cost_per_add_to_cart,
  cost_per_purchase,
  outbound_clicks,
  page_engagement,
  post_engagement,
  post_reactions,
  post_comments,
  post_saves,
  post_shares,
  ctr,
  cpc,
  cpm,
  cpa,
  roas,
  previous_week_spend,
  previous_week_clicks,
  previous_week_conversions,
  previous_week_add_to_cart,
  previous_week_purchase,
  previous_week_cpc,
  previous_week_cpa,
  previous_week_roas,
  spend - previous_week_spend AS spend_wow,
  clicks - previous_week_clicks AS clicks_wow,
  conversions - previous_week_conversions AS conversions_wow,
  add_to_cart - previous_week_add_to_cart AS add_to_cart_wow,
  purchase - previous_week_purchase AS purchase_wow,
  cpc - previous_week_cpc AS cpc_wow,
  cpa - previous_week_cpa AS cpa_wow,
  roas - previous_week_roas AS roas_wow,
  SAFE_DIVIDE(spend - previous_week_spend, previous_week_spend) AS spend_wow_rate,
  SAFE_DIVIDE(clicks - previous_week_clicks, previous_week_clicks) AS clicks_wow_rate,
  SAFE_DIVIDE(conversions - previous_week_conversions, previous_week_conversions) AS conversions_wow_rate,
  SAFE_DIVIDE(add_to_cart - previous_week_add_to_cart, previous_week_add_to_cart) AS add_to_cart_wow_rate,
  SAFE_DIVIDE(purchase - previous_week_purchase, previous_week_purchase) AS purchase_wow_rate,
  SAFE_DIVIDE(cpc - previous_week_cpc, previous_week_cpc) AS cpc_wow_rate,
  SAFE_DIVIDE(cpa - previous_week_cpa, previous_week_cpa) AS cpa_wow_rate,
  SAFE_DIVIDE(roas - previous_week_roas, previous_week_roas) AS roas_wow_rate,
  CURRENT_TIMESTAMP() AS created_at,
  CURRENT_TIMESTAMP() AS updated_at
FROM with_previous;
