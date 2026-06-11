-- BigQuery Standard SQL
-- Windsor-style WIDE Google Ads KEYWORD view for Looker / Data Studio.
--
-- The Google connector already fetches keyword-level rows (report_level =
-- 'keyword') into raw_google_ads_daily; this view just exposes them flattened,
-- one named column per field. No re-sync needed — adding this view surfaces data
-- that is already in the raw table.
--
-- Grain: one row per (date, account, campaign, ad group, keyword). Filtered to
-- report_level = 'keyword' so spend is not mixed with the ad / search-term grains.

CREATE OR REPLACE VIEW `oudseed.ads_pipeline.vw_looker_google_ads_keyword_wide` AS
SELECT
  -- ---- Dimensions ----
  r.date AS date,
  r.workspace_id AS workspace_id,
  r.client_id AS client_id,
  r.account_id AS account_id,
  JSON_VALUE(r.raw_payload, '$.account_name') AS account_name,
  JSON_VALUE(r.raw_payload, '$.currency') AS currency,
  JSON_VALUE(r.raw_payload, '$.campaign_id') AS campaign_id,
  JSON_VALUE(r.raw_payload, '$.campaign_name') AS campaign_name,
  JSON_VALUE(r.raw_payload, '$.campaign_status') AS campaign_status,
  JSON_VALUE(r.raw_payload, '$.campaign_channel_type') AS campaign_channel_type,
  JSON_VALUE(r.raw_payload, '$.ad_group_id') AS ad_group_id,
  JSON_VALUE(r.raw_payload, '$.ad_group_name') AS ad_group_name,
  JSON_VALUE(r.raw_payload, '$.criterion_id') AS criterion_id,
  JSON_VALUE(r.raw_payload, '$.keyword_text') AS keyword_text,
  JSON_VALUE(r.raw_payload, '$.keyword_match_type') AS keyword_match_type,
  JSON_VALUE(r.raw_payload, '$.criterion_status') AS criterion_status,

  -- ---- Additive metrics (safe to SUM in Looker) ----
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.impressions') AS INT64) AS impressions,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.clicks') AS INT64) AS clicks,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.spend') AS FLOAT64) AS spend,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.conversions') AS FLOAT64) AS conversions,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.conversion_value') AS FLOAT64) AS conversion_value,

  -- ---- Per-row ratios (rebuild as SUM()/SUM() in Looker; don't SUM directly) ----
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.ctr') AS FLOAT64) AS ctr,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.cpc') AS FLOAT64) AS cpc,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.cpm') AS FLOAT64) AS cpm,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.cpa') AS FLOAT64) AS cpa
FROM `oudseed.ads_pipeline.raw_google_ads_daily` r
WHERE r.platform = 'google_ads'
  AND r.report_level = 'keyword';
