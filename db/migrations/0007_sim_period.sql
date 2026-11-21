-- Close period under simulation (first day of the month being closed).
ALTER TABLE sim_state ADD COLUMN close_period date NOT NULL DEFAULT date_trunc('month', now())::date;
ALTER TABLE sim_state ADD COLUMN eps_updated_at timestamptz;

-- Evidence retrieval over contract text lives in the same DB (full-text search).
ALTER TABLE contracts ADD COLUMN source_tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('english', coalesce(source_text, ''))) STORED;
CREATE INDEX contracts_source_tsv ON contracts USING gin (source_tsv);
