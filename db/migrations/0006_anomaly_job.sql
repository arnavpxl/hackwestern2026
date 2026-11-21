-- Anomaly detection runs INSIDE the database as a TimescaleDB background job.
-- Every 10s: spend in the last N minutes (real-time usage_1m) projected to an hourly
-- rate vs the trailing-14-day baseline (rollup of stats_agg). > sigma => open a case,
-- write the audit trail and NOTIFY the API (which pushes SSE to the browser).

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
  WHERE b.n_hours >= 24
    AND r.window_cents * 60.0 / pol.anomaly_window_minutes
        > b.mean_cents + pol.anomaly_sigma * greatest(b.stddev_cents, 0.1 * b.mean_cents)
    AND r.window_cents * 60.0 / pol.anomaly_window_minutes > pol.anomaly_min_cents_per_hour
$$;

CREATE OR REPLACE PROCEDURE detect_anomalies(job_id int, config jsonb)
LANGUAGE plpgsql AS $$
DECLARE
  v_now   timestamptz := sim_now();
  a       record;
  v_start timestamptz;
  v_case  int;
BEGIN
  FOR a IN SELECT * FROM scan_anomalies(v_now) LOOP
    -- one open anomaly case per key/model per 6h
    IF EXISTS (SELECT 1 FROM obligation_cases c
               WHERE c.type = 'anomaly' AND c.api_key_id = a.api_key_id
                 AND c.calc->>'model' = a.model
                 AND c.opened_at > v_now - INTERVAL '6 hours') THEN
      CONTINUE;
    END IF;

    -- Spike start: first minute in the last hour whose run-rate crossed the threshold,
    -- then the first raw event in that minute (hot, uncompressed chunk + index).
    SELECT min(e.ts) INTO v_start
    FROM usage_events e
    WHERE e.api_key_id = a.api_key_id AND e.model = a.model
      AND e.ts >= (SELECT min(m.bucket) FROM usage_1m m
                   WHERE m.api_key_id = a.api_key_id AND m.model = a.model
                     AND m.bucket > v_now - INTERVAL '1 hour'
                     AND m.cost_estimate_cents * 60 > a.threshold_cents)
      AND e.ts <= v_now;

    INSERT INTO obligation_cases (period, type, provider_id, api_key_id, status, title,
                                  opened_at, spike_started_at, detection_latency_ms, calc)
    VALUES (date_trunc('month', v_now)::date, 'anomaly', a.provider, a.api_key_id, 'needs_info',
            format('Runaway spend on key %s (%s): %s/h vs baseline %s/h',
                   (SELECT label FROM api_keys WHERE id = a.api_key_id), a.model,
                   to_char(a.projected_hourly_cents / 100, 'FM$999,999,990.00'),
                   to_char(a.mean_cents / 100, 'FM$999,999,990.00')),
            v_now, v_start,
            (extract(epoch FROM (v_now - coalesce(v_start, v_now))) * 1000)::bigint,
            jsonb_build_object('model', a.model,
                               'window_cents', a.window_cents,
                               'projected_hourly_cents', a.projected_hourly_cents,
                               'baseline_mean_cents', a.mean_cents,
                               'baseline_stddev_cents', a.stddev_cents,
                               'threshold_cents', a.threshold_cents,
                               'sql', 'SELECT * FROM scan_anomalies(sim_now())'))
    RETURNING id INTO v_case;

    INSERT INTO audit_log (actor, case_id, action, detail)
    VALUES ('db:anomaly_job', v_case, 'case_opened',
            jsonb_build_object('job_id', job_id, 'projected_hourly_cents', a.projected_hourly_cents,
                               'threshold_cents', a.threshold_cents));

    PERFORM pg_notify('cases', json_build_object('event', 'anomaly_opened', 'case_id', v_case,
                                                 'api_key_id', a.api_key_id)::text);
  END LOOP;
  COMMIT;
END $$;

SELECT add_job('detect_anomalies', INTERVAL '10 seconds', fixed_schedule => false);
