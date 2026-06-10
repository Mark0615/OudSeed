-- BigQuery Standard SQL
-- Windsor-style WIDE Google Ads view for Looker / Data Studio.
--
-- Flattens the Google Ads payload stored in raw_google_ads_daily.raw_payload
-- (JSON) into one named column per metric — the same shape Windsor.ai exposes —
-- so an existing Data Studio report can point at this view via the native
-- BigQuery connector. The raw table is untouched; adding a field = adding a
-- column here, no re-sync needed.
--
-- Unlike Meta, the Google payload is already flat scalars (no nested action
-- arrays), so this view is mostly SAFE_CAST. The raw table mixes report levels
-- (ad / keyword / search_term); this WIDE view filters to report_level = 'ad'
-- so spend/impressions are NOT multiplied across the keyword/search-term
-- breakdowns of the same ad. (Keyword/search-term grain can get its own view
-- later if needed.)

CREATE OR REPLACE VIEW `oudseed.ads_pipeline.vw_looker_google_ads_wide` AS
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
  JSON_VALUE(r.raw_payload, '$.ad_id') AS ad_id,
  JSON_VALUE(r.raw_payload, '$.ad_name') AS ad_name,
  JSON_VALUE(r.raw_payload, '$.ad_type') AS ad_type,

  -- ---- Additive metrics (safe to SUM in Looker) ----
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.impressions') AS INT64) AS impressions,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.clicks') AS INT64) AS clicks,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.spend') AS FLOAT64) AS spend,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.conversions') AS FLOAT64) AS conversions,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.conversion_value') AS FLOAT64) AS conversion_value,

  -- ---- Per-row ratios (DON'T SUM these in Looker — rebuild as
  --      SUM(clicks)/SUM(impressions) etc. so totals stay correct) ----
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.ctr') AS FLOAT64) AS ctr,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.cpc') AS FLOAT64) AS cpc,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.cpm') AS FLOAT64) AS cpm,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.cpa') AS FLOAT64) AS cpa
FROM `oudseed.ads_pipeline.raw_google_ads_daily` r
WHERE r.platform = 'google_ads'
  AND r.report_level = 'ad';
