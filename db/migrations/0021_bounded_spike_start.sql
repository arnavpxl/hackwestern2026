-- Once scan_anomalies finds a candidate, detect_anomalies calls spike_start to timestamp the
-- beginning of the burst. The previous implementation could group an hour of raw events
-- (millions of rows in the demo), making case creation take ~50 seconds even though the anomaly
-- itself was visible immediately. Detection runs every three seconds, so the relevant change
-- point is necessarily in a small recent window.

CREATE OR REPLACE FUNCTION spike_start(p_key int, p_model text, p_threshold double precision, p_as_of timestamptz)
RETURNS timestamptz LANGUAGE sql STABLE AS $$
  WITH per_s AS (
    SELECT time_bucket('1 second', e.ts) AS s, sum(e.cost_estimate_cents) AS c, min(e.ts) AS first_ts
    FROM usage_events e
    WHERE e.api_key_id = p_key AND e.model = p_model
      AND e.ts > p_as_of - interval '30 seconds' AND e.ts <= p_as_of
    GROUP BY 1
  ), rolling AS (
    SELECT s, first_ts,
           sum(c) OVER (ORDER BY s RANGE BETWEEN interval '4 seconds' PRECEDING AND CURRENT ROW) AS c5
    FROM per_s
  ), calm AS (
    SELECT max(s) AS s FROM rolling WHERE c5 * 720 <= p_threshold
  )
  SELECT min(r.first_ts)
  FROM rolling r, calm
  WHERE r.s > coalesce(calm.s, '-infinity')
$$;
