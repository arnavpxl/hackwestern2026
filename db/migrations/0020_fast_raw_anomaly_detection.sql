-- The minute aggregate remains the efficient detector for sustained anomalies, but its
-- watermark can hide newly inserted events until a bucket refresh completes. Add a raw
-- 15-second fast path so live spikes do not wait for that refresh. The historical baseline
-- still comes from spend_baseline, keeping the hot query bounded to one recent raw slice.

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
  WITH minute_recent AS (
    SELECT u.api_key_id, u.provider, u.model, sum(u.cost_estimate_cents)::double precision AS cents,
           greatest(30.0, extract(epoch FROM (p_as_of - min(u.bucket)))) AS covered_s
    FROM usage_1m u
    WHERE u.bucket > p_as_of - w AND u.bucket <= p_as_of
    GROUP BY 1, 2, 3
  ), raw_recent AS (
    SELECT e.api_key_id, e.provider, e.model, sum(e.cost_estimate_cents)::double precision AS cents,
           greatest(5.0, extract(epoch FROM (p_as_of - min(e.ts)))) AS covered_s
    FROM usage_events e
    WHERE e.ts > p_as_of - interval '15 seconds' AND e.ts <= p_as_of
    GROUP BY 1, 2, 3
  ), candidates AS (
    SELECT r.*, r.cents * 3600.0 / r.covered_s AS projected FROM minute_recent r
    UNION ALL
    SELECT r.*, r.cents * 3600.0 / r.covered_s AS projected FROM raw_recent r
  ), scored AS (
    -- Prefer whichever bounded window observes the stronger run rate. During a fresh spike
    -- this is the raw path; after it is materialized the minute path takes over.
    SELECT DISTINCT ON (c.api_key_id, c.provider, c.model)
           c.api_key_id, c.provider, c.model, c.cents, c.projected
    FROM candidates c
    ORDER BY c.api_key_id, c.provider, c.model, c.projected DESC
  )
  SELECT s.api_key_id, s.provider, s.model, s.cents, s.projected,
         b.mean_cents, b.stddev_cents,
         b.mean_cents + pol.anomaly_sigma * greatest(b.stddev_cents, 0.1 * b.mean_cents)
  FROM scored s
  JOIN baseline_as_of(p_as_of) b USING (api_key_id, model)
  WHERE b.n_hours >= 7
    AND s.projected > b.mean_cents + pol.anomaly_sigma * greatest(b.stddev_cents, 0.1 * b.mean_cents)
    AND s.projected > pol.anomaly_min_cents_per_hour;
END $$;

-- Three scans fit comfortably inside the 20-second demo target even if one run overlaps
-- another database task. detect_anomalies already suppresses duplicate cases for six hours.
SELECT alter_job(job_id, schedule_interval => INTERVAL '3 seconds')
FROM timescaledb_information.jobs WHERE proc_name = 'detect_anomalies';
