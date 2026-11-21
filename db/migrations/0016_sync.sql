-- Provider-reported usage, kept apart from the simulator's usage_events so real and simulated data never mix.
-- Rows are keyed by the provider's own identifiers; mapping them to our api_keys/teams comes in phase 3.

CREATE TABLE provider_usage_hourly (
  connection_id   int NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
  bucket          timestamptz NOT NULL,
  model           text NOT NULL,
  workspace_id    text NOT NULL DEFAULT '',
  provider_key_id text NOT NULL DEFAULT '',
  input_tokens    bigint NOT NULL DEFAULT 0,
  output_tokens   bigint NOT NULL DEFAULT 0,
  cache_read_tokens   bigint NOT NULL DEFAULT 0,
  cache_write_tokens  bigint NOT NULL DEFAULT 0,
  synced_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (connection_id, bucket, model, workspace_id, provider_key_id)
);
CREATE INDEX ON provider_usage_hourly (connection_id, bucket);

CREATE TABLE sync_runs (
  id              bigserial PRIMARY KEY,
  connection_id   int NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz,
  status          text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'error')),
  synced_from     timestamptz,
  synced_through  timestamptz,
  rows_loaded     int NOT NULL DEFAULT 0,
  error           text
);
CREATE INDEX ON sync_runs (connection_id, finished_at DESC);
