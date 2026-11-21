-- A paused simulator must freeze its clock, not merely stop ingestion while
-- simulated time keeps advancing. Keep the real timestamp at which the clock
-- froze and record pause/resume intervals for the demo UI.

ALTER TABLE sim_state ADD COLUMN paused_at timestamptz;
UPDATE sim_state SET paused_at = now() WHERE paused;
ALTER TABLE sim_state ADD CONSTRAINT sim_state_paused_at_check
  CHECK (NOT paused OR paused_at IS NOT NULL);

CREATE TABLE sim_pause_intervals (
  id              bigserial PRIMARY KEY,
  sim_at          timestamptz NOT NULL,
  real_started_at timestamptz NOT NULL DEFAULT now(),
  real_ended_at   timestamptz,
  CHECK (real_ended_at IS NULL OR real_ended_at >= real_started_at)
);
CREATE UNIQUE INDEX sim_pause_one_open ON sim_pause_intervals ((true))
  WHERE real_ended_at IS NULL;

-- Preserve the currently paused state when upgrading an active demo database.
INSERT INTO sim_pause_intervals (sim_at)
SELECT paused_at + sim_offset FROM sim_state WHERE paused;

CREATE OR REPLACE FUNCTION sim_now() RETURNS timestamptz
LANGUAGE sql STABLE AS $$
  SELECT (CASE WHEN paused THEN paused_at ELSE now() END) + sim_offset
  FROM sim_state WHERE id = 1
$$;
