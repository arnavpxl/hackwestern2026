-- Faster detection: 2-minute window projected by the time it actually covers
-- (minute buckets are aligned, so "last N minutes" includes a partial minute), job every 5s.
UPDATE policies SET anomaly_window_minutes = 2;

SELECT alter_job(job_id, schedule_interval => INTERVAL '5 seconds')
FROM timescaledb_information.jobs WHERE proc_name = 'detect_anomalies';

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
    SELECT u.api_key_id, u.provider, u.model, sum(u.cost_estimate_cents) AS window_cents,
           greatest(30, extract(epoch FROM (p_as_of - min(u.bucket)))) AS covered_s
    FROM usage_1m u
    WHERE u.bucket > p_as_of - w AND u.bucket <= p_as_of
    GROUP BY 1, 2, 3
  ), scored AS (
    SELECT r.*, r.window_cents * 3600.0 / r.covered_s AS projected FROM recent r
  )
  SELECT s.api_key_id, s.provider, s.model, s.window_cents, s.projected,
         b.mean_cents, b.stddev_cents,
         b.mean_cents + pol.anomaly_sigma * greatest(b.stddev_cents, 0.1 * b.mean_cents)
  FROM scored s
  JOIN baseline_as_of(p_as_of) b USING (api_key_id, model)
  WHERE b.n_hours >= 7
    AND s.projected > b.mean_cents + pol.anomaly_sigma * greatest(b.stddev_cents, 0.1 * b.mean_cents)
    AND s.projected > pol.anomaly_min_cents_per_hour;
END $$;

-- Stricter change point: 4x the p95 event cost of the last quiet minute.
CREATE OR REPLACE FUNCTION spike_start(p_key int, p_model text, p_threshold double precision, p_as_of timestamptz)
RETURNS timestamptz LANGUAGE sql STABLE AS $$
  WITH quiet AS (
    SELECT max(bucket) AS b FROM usage_1m
    WHERE api_key_id = p_key AND model = p_model
      AND bucket > p_as_of - interval '1 hour' AND bucket < time_bucket('1 minute', p_as_of)
      AND cost_estimate_cents * 60 <= p_threshold
  ), typical AS (
    SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY e.cost_estimate_cents) AS p95
    FROM usage_events e, quiet q
    WHERE e.api_key_id = p_key AND e.model = p_model AND e.ts >= q.b AND e.ts < q.b + interval '1 minute'
  )
  SELECT min(e.ts) FROM usage_events e, quiet q, typical t
  WHERE e.api_key_id = p_key AND e.model = p_model
    AND e.ts >= coalesce(q.b, p_as_of - interval '1 hour') AND e.ts <= p_as_of
    AND e.cost_estimate_cents > 4 * coalesce(t.p95, 0)
$$;
