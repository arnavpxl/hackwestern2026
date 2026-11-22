-- A real signed-in user can ask the synthetic demo to email them when its runaway
-- scenario opens an anomaly case. The public demo user is never enrolled. Keeping
-- enrollment and delivery state in Postgres makes notification creation atomic with
-- case creation and prevents duplicate emails when events are replayed.

CREATE TABLE demo_email_enrollments (
  user_id       int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  api_key_id    int NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
  started_at    timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL,
  PRIMARY KEY (user_id, api_key_id)
);
CREATE INDEX demo_email_enrollments_active_idx ON demo_email_enrollments (api_key_id, expires_at);

CREATE TABLE demo_email_notifications (
  id              bigserial PRIMARY KEY,
  case_id         int NOT NULL REFERENCES obligation_cases(id) ON DELETE CASCADE,
  user_id         int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  recipient       text NOT NULL,
  recipient_name  text NOT NULL,
  status          text NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'sending', 'sent', 'failed')),
  attempts        int NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  last_error      text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  sent_at         timestamptz,
  UNIQUE (case_id, user_id)
);
CREATE INDEX demo_email_notifications_queue_idx
  ON demo_email_notifications (next_attempt_at, id) WHERE status = 'pending';

CREATE OR REPLACE FUNCTION enqueue_demo_anomaly_email()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.type = 'anomaly' AND NEW.api_key_id IS NOT NULL THEN
    INSERT INTO demo_email_notifications (case_id, user_id, recipient, recipient_name)
    SELECT NEW.id, e.user_id, u.email, u.name
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

CREATE TRIGGER obligation_case_demo_email
AFTER INSERT ON obligation_cases
FOR EACH ROW EXECUTE FUNCTION enqueue_demo_anomaly_email();
