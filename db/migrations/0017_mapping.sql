-- Maps a provider's own key (and workspace) to one of our api_keys, which carries the team and owner.
-- Until a provider key is mapped, its usage is listed as unmapped and is not attributed to any team.

CREATE TABLE key_mappings (
  connection_id   int NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
  provider_key_id text NOT NULL DEFAULT '',
  workspace_id    text NOT NULL DEFAULT '',
  api_key_id      int NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
  mapped_by       text NOT NULL,
  mapped_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (connection_id, provider_key_id, workspace_id)
);
