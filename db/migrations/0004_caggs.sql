-- Hierarchical continuous aggregates: raw -> 1m -> 1h -> 1d, real-time aggregation ON
-- (materialized_only = false) so the newest un-materialized events are unioned in live.

CREATE MATERIALIZED VIEW usage_1m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 minute', ts) AS bucket,
       api_key_id, provider, model,
       sum(input_tokens)::bigint        AS input_tokens,
       sum(output_tokens)::bigint       AS output_tokens,
       sum(cached_tokens)::bigint       AS cached_tokens,
       sum(requests)::bigint            AS requests,
       sum(gpu_seconds)                 AS gpu_seconds,
       sum(cost_estimate_cents)         AS cost_estimate_cents,
       count(*)                         AS events
FROM usage_events
GROUP BY 1, 2, 3, 4
WITH NO DATA;

CREATE MATERIALIZED VIEW usage_1h
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 hour', bucket) AS bucket,
       api_key_id, provider, model,
       sum(input_tokens)::bigint  AS input_tokens,
       sum(output_tokens)::bigint AS output_tokens,
       sum(cached_tokens)::bigint AS cached_tokens,
       sum(requests)::bigint      AS requests,
       sum(gpu_seconds)           AS gpu_seconds,
       sum(cost_estimate_cents)   AS cost_estimate_cents,
       sum(events)::bigint        AS events
FROM usage_1m
GROUP BY 1, 2, 3, 4
WITH NO DATA;

CREATE MATERIALIZED VIEW usage_1d
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 day', bucket) AS bucket,
       api_key_id, provider, model,
       sum(input_tokens)::bigint  AS input_tokens,
       sum(output_tokens)::bigint AS output_tokens,
       sum(cached_tokens)::bigint AS cached_tokens,
       sum(requests)::bigint      AS requests,
       sum(gpu_seconds)           AS gpu_seconds,
       sum(cost_estimate_cents)   AS cost_estimate_cents,
       sum(events)::bigint        AS events
FROM usage_1h
GROUP BY 1, 2, 3, 4
WITH NO DATA;

-- Anomaly baseline: one toolkit stats_agg of hourly spend per key/model per day.
-- Trailing-14-day mean/stddev = rollup() of 14 daily aggregates — no raw scan ever.
CREATE MATERIALIZED VIEW spend_baseline
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 day', bucket) AS day,
       api_key_id, model,
       stats_agg(cost_estimate_cents) AS hourly_spend_stats
FROM usage_1h
GROUP BY 1, 2, 3
WITH NO DATA;

-- Cost views: tokens from caggs x rate in effect at each bucket (as-of join).
-- Hourly granularity means a mid-day price change is applied from its effective hour.
CREATE OR REPLACE VIEW usage_1h_cost AS
SELECT u.bucket, u.api_key_id, u.provider, u.model,
       u.input_tokens, u.output_tokens, u.cached_tokens, u.requests, u.gpu_seconds, u.events,
       r.ts AS rate_effective_from,
       r.input_rate, r.output_rate, r.cached_rate, r.request_rate, r.gpu_rate,
       (  u.input_tokens  * r.input_rate  / 1e6
        + u.output_tokens * r.output_rate / 1e6
        + u.cached_tokens * r.cached_rate / 1e6
        + u.requests      * r.request_rate / 1e3
        + u.gpu_seconds   * r.gpu_rate / 3600)::numeric(18,4) AS cost_cents,
       (u.cached_tokens * r.cached_rate / 1e6)::numeric(18,4) AS cached_cost_cents
FROM usage_1h u
CROSS JOIN LATERAL (
  SELECT * FROM price_changes p
  WHERE p.provider = u.provider AND p.model = u.model AND p.ts <= u.bucket
  ORDER BY p.ts DESC LIMIT 1
) r;

CREATE OR REPLACE VIEW usage_1d_cost AS
SELECT u.bucket, u.api_key_id, u.provider, u.model,
       u.input_tokens, u.output_tokens, u.cached_tokens, u.requests, u.gpu_seconds, u.events,
       r.ts AS rate_effective_from,
       (  u.input_tokens  * r.input_rate  / 1e6
        + u.output_tokens * r.output_rate / 1e6
        + u.cached_tokens * r.cached_rate / 1e6
        + u.requests      * r.request_rate / 1e3
        + u.gpu_seconds   * r.gpu_rate / 3600)::numeric(18,4) AS cost_cents
FROM usage_1d u
CROSS JOIN LATERAL (
  SELECT * FROM price_changes p
  WHERE p.provider = u.provider AND p.model = u.model AND p.ts <= u.bucket
  ORDER BY p.ts DESC LIMIT 1
) r;

-- Trailing 14-day hourly spend baseline per key/model (as of sim time).
CREATE OR REPLACE FUNCTION baseline_as_of(p_as_of timestamptz)
RETURNS TABLE (api_key_id int, model text, mean_cents double precision,
               stddev_cents double precision, n_hours bigint)
LANGUAGE sql STABLE AS $$
  SELECT api_key_id, model,
         average(rollup(hourly_spend_stats)),
         stddev(rollup(hourly_spend_stats)),
         num_vals(rollup(hourly_spend_stats))::bigint
  FROM spend_baseline
  WHERE day >= time_bucket('1 day', p_as_of) - interval '14 days'
    AND day <  time_bucket('1 day', p_as_of)
  GROUP BY api_key_id, model
$$;
