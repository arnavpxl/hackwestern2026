-- Detection remains immediate and detection_latency_ms stays truthful, but the demo's email
-- notification waits briefly so the graph has time to visibly develop before the alert lands.

CREATE OR REPLACE FUNCTION enqueue_demo_anomaly_email()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.type = 'anomaly' AND NEW.api_key_id IS NOT NULL THEN
    INSERT INTO demo_email_notifications
      (case_id, user_id, recipient, recipient_name, next_attempt_at)
    SELECT NEW.id, e.user_id, u.email, u.name, now() + interval '5 seconds'
    FROM demo_email_enrollments e
    JOIN users u ON u.id = e.user_id
    WHERE e.api_key_id = NEW.api_key_id
      AND e.expires_at > now()
      AND NOT u.disabled
      AND lower(u.email) <> 'demo@tokentrueup.local'
    ON CONFLICT (case_id, user_id) DO NOTHING;
  END IF;
  RETURN NEW;
END $$;
