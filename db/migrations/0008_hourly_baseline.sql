-- Hour-of-day aware baseline. A flat 14-day baseline mixes 3am and 3pm, inflating stddev
-- (~0.8x mean for business-hours keys) and delaying detection. Grouping by UTC hour of day
-- compares "now" with the same hour on the previous 14 days.

DROP MATERIALIZED VIEW spend_baseline CASCADE;

CREATE MATERIALIZED VIEW spend_baseline
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 day', bucket) AS day,
       api_key_id, model,
       date_part('hour', bucket AT TIME ZONE 'UTC')::int AS hour_of_day,
       stats_agg(cost_estimate_cents) AS hourly_spend_stats
FROM usage_1h
GROUP BY 1, 2, 3, 4
WITH NO DATA;

SELECT add_continuous_aggregate_policy('spend_baseline',
  start_offset => INTERVAL '14 days', end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 hour');

-- Trailing 14 days, same UTC hour of day (and the hour after, smoothing the boundary).
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
    AND hour_of_day IN (date_part('hour', p_as_of AT TIME ZONE 'UTC')::int,
                        (date_part('hour', p_as_of AT TIME ZONE 'UTC')::int + 1) % 24)
  GROUP BY api_key_id, model
$$;

-- scan_anomalies: require a week of same-hour samples.
CREATE OR REPLACE FUNCTION scan_anomalies(p_as_of timestamptz)
RETURNS TABLE (api_key_id int, provider text, model text, window_cents double precision,
               projected_hourly_cents double precision, mean_cents double precision,
               stddev_cents double precision, threshold_cents double precision)
LANGUAGE sql STABLE AS $$
  WITH pol AS (SELECT * FROM policies WHERE id = 1),
  recent AS (
    SELECT u.api_key_id, u.provider, u.model, sum(u.cost_estimate_cents) AS window_cents
    FROM usage_1m u, pol
    WHERE u.bucket >  p_as_of - make_interval(mins => pol.anomaly_window_minutes)
      AND u.bucket <= p_as_of
    GROUP BY 1, 2, 3
  )
  SELECT r.api_key_id, r.provider, r.model, r.window_cents,
         r.window_cents * 60.0 / pol.anomaly_window_minutes AS projected,
         b.mean_cents, b.stddev_cents,
         b.mean_cents + pol.anomaly_sigma * greatest(b.stddev_cents, 0.1 * b.mean_cents) AS threshold
  FROM recent r
  JOIN baseline_as_of(p_as_of) b USING (api_key_id, model)
  CROSS JOIN pol
  WHERE b.n_hours >= 7
    AND r.window_cents * 60.0 / pol.anomaly_window_minutes
        > b.mean_cents + pol.anomaly_sigma * greatest(b.stddev_cents, 0.1 * b.mean_cents)
    AND r.window_cents * 60.0 / pol.anomaly_window_minutes > pol.anomaly_min_cents_per_hour
$$;

-- (refreshed by the backfill / the policy above; CALL refresh can't run in the migration transaction)
