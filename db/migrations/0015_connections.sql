-- Provider connections: an API key a company pastes in so usage and cost data can be pulled.
-- The key is stored encrypted (AES-256-GCM, see backend/src/tokentrueup/vault.py). Only its last
-- four characters are kept in the clear, and encrypted_key is cleared when the connection is revoked.

INSERT INTO providers (id, name, kind, invoice_lag_days) VALUES
  ('anthropic', 'Anthropic', 'llm', 5),
  ('openai', 'OpenAI', 'llm', 5)
ON CONFLICT (id) DO NOTHING;

CREATE TABLE connections (
  id             serial PRIMARY KEY,
  provider_id    text NOT NULL REFERENCES providers(id),
  label          text NOT NULL UNIQUE,
  team_id        int  NOT NULL REFERENCES teams(id),
  key_kind       text NOT NULL CHECK (key_kind IN ('admin', 'api')),
  encrypted_key  text,
  key_last4      text NOT NULL,
  status         text NOT NULL DEFAULT 'connected' CHECK (status IN ('connected', 'revoked')),
  created_by     int REFERENCES users(id) ON DELETE SET NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  rotated_at     timestamptz,
  revoked_at     timestamptz,
  last_sync_at   timestamptz,
  last_error     text
);
