-- 1) Pass the window as a parameter: a bound computed from a joined policies row is not
--    known at executor startup, so ChunkAppend could not exclude old usage_1m chunks
--    (scan took ~3.8s). With a parameter, startup exclusion prunes to the newest chunk.
-- 2) Refresh usage_1m every 10s up to the last complete minute (end_offset 0), so the
--    real-time tail unioned from raw usage_events stays ~1 minute long.

DROP FUNCTION IF EXISTS scan_anomalies(timestamptz);

CREATE OR REPLACE FUNCTION scan_anomalies(p_as_of timestamptz, p_window interval DEFAULT NULL)
RETURNS TABLE (api_key_id int, provider text, model text, window_cents double precision,
               projected_hourly_cents double precision, mean_cents double precision,
               stddev_cents double precision, threshold_cents double precision)
LANGUAGE plpgsql STABLE AS $$
DECLARE
  pol policies;
  w interval;
BEGIN
  SELECT * INTO pol FROM policies WHERE id = 1;
  w := coalesce(p_window, make_interval(mins => pol.anomaly_window_minutes));
  RETURN QUERY
  WITH recent AS (
    SELECT u.api_key_id, u.provider, u.model, sum(u.cost_estimate_cents) AS window_cents
    FROM usage_1m u
    WHERE u.bucket > p_as_of - w AND u.bucket <= p_as_of
    GROUP BY 1, 2, 3
  )
  SELECT r.api_key_id, r.provider, r.model, r.window_cents,
         r.window_cents * 3600.0 / extract(epoch FROM w),
         b.mean_cents, b.stddev_cents,
         b.mean_cents + pol.anomaly_sigma * greatest(b.stddev_cents, 0.1 * b.mean_cents)
  FROM recent r
  JOIN baseline_as_of(p_as_of) b USING (api_key_id, model)
  WHERE b.n_hours >= 7
    AND r.window_cents * 3600.0 / extract(epoch FROM w)
        > b.mean_cents + pol.anomaly_sigma * greatest(b.stddev_cents, 0.1 * b.mean_cents)
    AND r.window_cents * 3600.0 / extract(epoch FROM w) > pol.anomaly_min_cents_per_hour;
END $$;

SELECT remove_continuous_aggregate_policy('usage_1m');
SELECT add_continuous_aggregate_policy('usage_1m',
  start_offset => INTERVAL '7 days', end_offset => INTERVAL '0 minutes',
  schedule_interval => INTERVAL '10 seconds');
