-- BigQuery Standard SQL
-- Windsor-style WIDE Google Ads CONVERSION-ACTION view for Looker / Data Studio.
--
-- One row per (date, account, campaign, conversion action). Surfaces the
-- per-conversion-action breakdown in long / "dimension" form so a Data Studio
-- table can group by conversion_action_name. CUSTOM conversions show up here
-- automatically — in the Google Ads API a custom conversion is just a conversion
-- action with its own name, so it lands in this view like any other.
--
-- IMPORTANT: this grain carries ONLY conversion counts/values — no
-- spend/impressions/clicks. Those would be duplicated across every conversion
-- action of the same campaign, so they are intentionally excluded (use the
-- ad-level vw_looker_google_ads_wide for spend). Filtered to
-- report_level = 'conversion_action' so it never mixes with the other grains.
--
-- Unlike the keyword / search-term views, this data is NEW: it needs the
-- connector's conversion-action query, so a sync/backfill must run to populate
-- report_level = 'conversion_action' rows before this view returns anything.

CREATE OR REPLACE VIEW `oudseed.ads_pipeline.vw_looker_google_ads_conversion_action_wide` AS
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
  -- The conversion action itself, exposed as DIMENSIONS (group Looker tables by
  -- these). conversion_action_name includes custom conversions by name.
  JSON_VALUE(r.raw_payload, '$.conversion_action_name') AS conversion_action_name,
  JSON_VALUE(r.raw_payload, '$.conversion_action_category') AS conversion_action_category,

  -- ---- Additive conversion metrics (safe to SUM in Looker) ----
  -- conversions       = actions flagged "include in Conversions"
  -- all_conversions   = every conversion action (incl. those excluded above)
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.conversions') AS FLOAT64) AS conversions,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.conversion_value') AS FLOAT64) AS conversion_value,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.all_conversions') AS FLOAT64) AS all_conversions,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.all_conversions_value') AS FLOAT64) AS all_conversions_value
FROM `oudseed.ads_pipeline.raw_google_ads_daily` r
WHERE r.platform = 'google_ads'
  AND r.report_level = 'conversion_action';
