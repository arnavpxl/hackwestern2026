-- Change point by spend RATE, not per-event size: the spike starts right after the LAST second
-- (since the last quiet minute) whose trailing 5-second spend, scaled to an hour, was at or below
-- the anomaly threshold. Using the last calm second, not the first hot one, ignores isolated
-- fat events before the spike.
-- Per-event p95 (0012) depended on event granularity: after a fast-forward (5-minute events)
-- the "typical" event was huge and no runaway event cleared 4x of it, so this returned NULL.
CREATE OR REPLACE FUNCTION spike_start(p_key int, p_model text, p_threshold double precision, p_as_of timestamptz)
RETURNS timestamptz LANGUAGE sql STABLE AS $$
  WITH quiet AS (
    SELECT coalesce(max(bucket), p_as_of - interval '1 hour') AS b FROM usage_1m
    WHERE api_key_id = p_key AND model = p_model
      AND bucket > p_as_of - interval '1 hour' AND bucket < time_bucket('1 minute', p_as_of)
      AND cost_estimate_cents * 60 <= p_threshold
  ), per_s AS (
    SELECT time_bucket('1 second', e.ts) AS s, sum(e.cost_estimate_cents) AS c, min(e.ts) AS first_ts
    FROM usage_events e, quiet q
    WHERE e.api_key_id = p_key AND e.model = p_model AND e.ts >= q.b AND e.ts <= p_as_of
    GROUP BY 1
  ), rolling AS (
    SELECT s, first_ts,
           sum(c) OVER (ORDER BY s RANGE BETWEEN interval '4 seconds' PRECEDING AND CURRENT ROW) AS c5
    FROM per_s
  ), calm AS (
    SELECT max(s) AS s FROM rolling WHERE c5 * 720 <= p_threshold
  )
  SELECT min(r.first_ts) FROM rolling r, calm WHERE r.s > coalesce(calm.s, '-infinity')
$$;
