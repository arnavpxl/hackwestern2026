-- Local accounts and server-side sessions. Passwords are stored as scrypt hashes; session
-- tokens are stored only as SHA-256 hashes, so a database leak does not reveal live sessions.

CREATE TABLE users (
  id             serial PRIMARY KEY,
  email          text NOT NULL UNIQUE,
  name           text NOT NULL,
  role           text NOT NULL CHECK (role IN ('viewer', 'controller', 'admin')),
  password_hash  text NOT NULL,
  disabled       boolean NOT NULL DEFAULT false,
  created_at     timestamptz NOT NULL DEFAULT now(),
  last_login_at  timestamptz
);

CREATE TABLE sessions (
  token_hash  text PRIMARY KEY,
  user_id     int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at  timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz NOT NULL
);
CREATE INDEX ON sessions (expires_at);
