-- BigQuery Standard SQL
-- Windsor-style WIDE Meta Ads view for Looker / Data Studio.
--
-- Flattens the nested Meta Insights payload stored in raw_meta_ads_daily.raw_payload
-- (JSON) into one named column per metric — the same shape Windsor.ai exposes —
-- so an existing Data Studio report can point at this view via the native
-- BigQuery connector. The raw table is untouched; adding a field = adding a column
-- here, no re-sync needed.
--
-- Conversion columns use Meta's unified "omni_*" action types where available
-- (these match what Ads Manager shows as "Purchases", "Adds to Cart", etc.).
-- If a specific account's pixel/setup reports a different action_type, adjust the
-- relevant COALESCE/action_type below — those are the only data-dependent bits.

CREATE OR REPLACE VIEW `oudseed.ads_pipeline.vw_looker_meta_ads_wide` AS
SELECT
  -- ---- Dimensions ----
  r.date AS date,
  r.workspace_id AS workspace_id,
  r.client_id AS client_id,
  r.account_id AS account_id,
  JSON_VALUE(r.raw_payload, '$.account_name') AS account_name,
  JSON_VALUE(r.raw_payload, '$.campaign_id') AS campaign_id,
  JSON_VALUE(r.raw_payload, '$.campaign_name') AS campaign_name,
  JSON_VALUE(r.raw_payload, '$.adset_id') AS adset_id,
  JSON_VALUE(r.raw_payload, '$.adset_name') AS adset_name,
  JSON_VALUE(r.raw_payload, '$.ad_id') AS ad_id,
  JSON_VALUE(r.raw_payload, '$.ad_name') AS ad_name,
  JSON_VALUE(r.raw_payload, '$.objective') AS objective,

  -- ---- Core delivery metrics (scalars) ----
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.spend') AS FLOAT64) AS spend,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.impressions') AS INT64) AS impressions,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.reach') AS INT64) AS reach,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.frequency') AS FLOAT64) AS frequency,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.clicks') AS INT64) AS clicks,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.unique_clicks') AS INT64) AS unique_clicks,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.inline_link_clicks') AS INT64) AS link_clicks,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.cpc') AS FLOAT64) AS cpc,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.cpm') AS FLOAT64) AS cpm,
  SAFE_CAST(JSON_VALUE(r.raw_payload, '$.ctr') AS FLOAT64) AS ctr,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS INT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.outbound_clicks')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'outbound_click' LIMIT 1) AS outbound_clicks,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.outbound_clicks_ctr')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'outbound_click' LIMIT 1) AS outbound_ctr,

  -- ---- Conversion counts (from actions[]) ----
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'landing_page_view' LIMIT 1) AS landing_page_views,
  COALESCE(
    (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x WHERE JSON_VALUE(x, '$.action_type') = 'omni_purchase' LIMIT 1),
    (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x WHERE JSON_VALUE(x, '$.action_type') = 'offsite_conversion.fb_pixel_purchase' LIMIT 1),
    (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x WHERE JSON_VALUE(x, '$.action_type') = 'purchase' LIMIT 1)
  ) AS purchases,
  COALESCE(
    (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x WHERE JSON_VALUE(x, '$.action_type') = 'omni_add_to_cart' LIMIT 1),
    (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x WHERE JSON_VALUE(x, '$.action_type') = 'offsite_conversion.fb_pixel_add_to_cart' LIMIT 1)
  ) AS adds_to_cart,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'omni_initiated_checkout' LIMIT 1) AS checkouts_initiated,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'omni_view_content' LIMIT 1) AS content_views,
  COALESCE(
    (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x WHERE JSON_VALUE(x, '$.action_type') = 'lead' LIMIT 1),
    (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x WHERE JSON_VALUE(x, '$.action_type') = 'offsite_conversion.fb_pixel_lead' LIMIT 1),
    (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x WHERE JSON_VALUE(x, '$.action_type') = 'onsite_conversion.lead_grouped' LIMIT 1)
  ) AS leads,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'omni_complete_registration' LIMIT 1) AS registrations_completed,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'omni_search' LIMIT 1) AS searches,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'omni_add_payment_info' LIMIT 1) AS adds_payment_info,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'page_engagement' LIMIT 1) AS page_engagement,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'post_engagement' LIMIT 1) AS post_engagement,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'post_reaction' LIMIT 1) AS post_reactions,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'comment' LIMIT 1) AS post_comments,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'onsite_conversion.post_save' LIMIT 1) AS post_saves,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.actions')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'like' LIMIT 1) AS page_likes,

  -- ---- Conversion values (from action_values[]) ----
  COALESCE(
    (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.action_values')) x WHERE JSON_VALUE(x, '$.action_type') = 'omni_purchase' LIMIT 1),
    (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.action_values')) x WHERE JSON_VALUE(x, '$.action_type') = 'offsite_conversion.fb_pixel_purchase' LIMIT 1)
  ) AS purchases_value,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.action_values')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'omni_add_to_cart' LIMIT 1) AS adds_to_cart_value,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.action_values')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'omni_initiated_checkout' LIMIT 1) AS checkouts_initiated_value,

  -- ---- ROAS ----
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.purchase_roas')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'omni_purchase' LIMIT 1) AS purchase_roas,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64)
   FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.website_purchase_roas')) x
   WHERE JSON_VALUE(x, '$.action_type') = 'offsite_conversion.fb_pixel_purchase' LIMIT 1) AS website_purchase_roas,

  -- ---- Video engagement (arrays keyed by 'video_view') ----
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.video_play_actions')) x WHERE JSON_VALUE(x, '$.action_type') = 'video_view' LIMIT 1) AS video_plays,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.video_thruplay_watched_actions')) x WHERE JSON_VALUE(x, '$.action_type') = 'video_view' LIMIT 1) AS thruplays,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.video_p25_watched_actions')) x WHERE JSON_VALUE(x, '$.action_type') = 'video_view' LIMIT 1) AS video_watched_25,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.video_p50_watched_actions')) x WHERE JSON_VALUE(x, '$.action_type') = 'video_view' LIMIT 1) AS video_watched_50,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.video_p75_watched_actions')) x WHERE JSON_VALUE(x, '$.action_type') = 'video_view' LIMIT 1) AS video_watched_75,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.video_p100_watched_actions')) x WHERE JSON_VALUE(x, '$.action_type') = 'video_view' LIMIT 1) AS video_watched_100,
  (SELECT SAFE_CAST(JSON_VALUE(x, '$.value') AS FLOAT64) FROM UNNEST(JSON_QUERY_ARRAY(r.raw_payload, '$.video_avg_time_watched_actions')) x WHERE JSON_VALUE(x, '$.action_type') = 'video_view' LIMIT 1) AS video_avg_time_watched
FROM `oudseed.ads_pipeline.raw_meta_ads_daily` r
WHERE r.platform = 'meta_ads';
