-- Keep the real-time tail of usage_1m short under a 3-10k events/s stream: the anomaly
-- scan unions only rows above the watermark, so a 15s refresh bounds that work.
SELECT alter_job(job_id, schedule_interval => INTERVAL '15 seconds')
FROM timescaledb_information.jobs
WHERE proc_name = 'policy_refresh_continuous_aggregate' AND hypertable_name = 'usage_1m';

ALTER TABLE sim_state ALTER COLUMN target_eps SET DEFAULT 3000;
UPDATE sim_state SET target_eps = 3000;

-- Spike start = change point: after the last "quiet" minute in the past hour, the first raw
-- event whose cost exceeds 3x the p90 event cost of that quiet minute.
CREATE OR REPLACE FUNCTION spike_start(p_key int, p_model text, p_threshold double precision, p_as_of timestamptz)
RETURNS timestamptz LANGUAGE sql STABLE AS $$
  WITH quiet AS (
    SELECT max(bucket) AS b FROM usage_1m
    WHERE api_key_id = p_key AND model = p_model
      AND bucket > p_as_of - interval '1 hour' AND bucket < time_bucket('1 minute', p_as_of)
      AND cost_estimate_cents * 60 <= p_threshold
  ), typical AS (
    SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY e.cost_estimate_cents) AS p90
    FROM usage_events e, quiet q
    WHERE e.api_key_id = p_key AND e.model = p_model AND e.ts >= q.b AND e.ts < q.b + interval '1 minute'
  )
  SELECT min(e.ts) FROM usage_events e, quiet q, typical t
  WHERE e.api_key_id = p_key AND e.model = p_model
    AND e.ts >= coalesce(q.b, p_as_of - interval '1 hour') AND e.ts <= p_as_of
    AND e.cost_estimate_cents > 3 * coalesce(t.p90, 0)
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
    IF EXISTS (SELECT 1 FROM obligation_cases c
               WHERE c.type = 'anomaly' AND c.api_key_id = a.api_key_id
                 AND c.calc->>'model' = a.model
                 AND c.opened_at > v_now - INTERVAL '6 hours') THEN
      CONTINUE;
    END IF;
    v_start := spike_start(a.api_key_id, a.model, a.threshold_cents, v_now);

    INSERT INTO obligation_cases (period, type, provider_id, api_key_id, status, title,
                                  opened_at, spike_started_at, detection_latency_ms, calc)
    VALUES (date_trunc('month', v_now)::date, 'anomaly', a.provider, a.api_key_id, 'needs_info',
            format('Runaway spend on key %s (%s): %s/h vs baseline %s/h',
                   (SELECT label FROM api_keys WHERE id = a.api_key_id), a.model,
                   to_char(a.projected_hourly_cents / 100, 'FM$999,999,990.00'),
                   to_char(a.mean_cents / 100, 'FM$999,999,990.00')),
            clock_timestamp() + (v_now - now()), v_start,
            (extract(epoch FROM (clock_timestamp() + (v_now - now()) - coalesce(v_start, v_now))) * 1000)::bigint,
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
