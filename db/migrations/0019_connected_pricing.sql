-- Public list-price catalog for real provider usage. This is intentionally separate from
-- price_changes, which belongs to the synthetic demo. Rates are USD per million tokens.
CREATE TABLE provider_model_prices (
  id                 serial PRIMARY KEY,
  provider_id        text NOT NULL,
  model_pattern      text NOT NULL,
  input_per_million  numeric(12,6) NOT NULL,
  output_per_million numeric(12,6) NOT NULL,
  cache_read_per_million  numeric(12,6) NOT NULL,
  cache_write_per_million numeric(12,6) NOT NULL,
  effective_from     date NOT NULL,
  effective_to       date,
  priority           int NOT NULL DEFAULT 0,
  source_url         text NOT NULL,
  CHECK (effective_to IS NULL OR effective_to > effective_from),
  UNIQUE (provider_id, model_pattern, effective_from)
);

CREATE INDEX provider_model_prices_lookup
  ON provider_model_prices (provider_id, effective_from DESC, priority DESC);

-- Seed the models most likely to appear in a new connection. Unknown models are never assigned
-- a fallback price: the connected dashboard reports them as unpriced instead.
INSERT INTO provider_model_prices
  (provider_id, model_pattern, input_per_million, output_per_million,
   cache_read_per_million, cache_write_per_million, effective_from, priority, source_url)
VALUES
  ('anthropic', 'claude-opus-5-5%',    4.00, 20.00, 0.20, 5.00, '2026-01-01', 20, 'https://platform.claude.com/docs/en/about-claude/pricing'),
  ('anthropic', 'claude-sonnet-5-5%',  2.00, 10.00, 0.10, 2.50, '2026-01-01', 20, 'https://platform.claude.com/docs/en/about-claude/pricing'),
  ('anthropic', 'claude-haiku-5-5%',   0.10,  0.50, 0.01, 0.125,'2026-01-01', 20, 'https://platform.claude.com/docs/en/about-claude/pricing'),
  ('anthropic', 'claude-opus-5%',      5.00, 25.00, 0.50, 6.25, '2026-01-01', 10, 'https://platform.claude.com/docs/en/about-claude/pricing'),
  ('anthropic', 'claude-sonnet-5%',    2.00, 10.00, 0.20, 2.50, '2026-01-01', 10, 'https://platform.claude.com/docs/en/about-claude/pricing'),
  ('anthropic', 'claude-opus-4-5%',    5.00, 25.00, 0.50, 6.25, '2025-01-01', 10, 'https://platform.claude.com/docs/en/about-claude/pricing'),
  ('anthropic', 'claude-sonnet-4-5%',  3.00, 15.00, 0.30, 3.75, '2025-01-01', 10, 'https://platform.claude.com/docs/en/about-claude/pricing'),
  ('anthropic', 'claude-haiku-4-5%',   1.00,  5.00, 0.10, 1.25, '2025-01-01', 10, 'https://platform.claude.com/docs/en/about-claude/pricing'),
  ('openai', 'gpt-6.2-astra%',          8.00, 40.00, 0.40,10.00, '2026-01-01', 20, 'https://developers.openai.com/api/docs/pricing'),
  ('openai', 'gpt-6.2-sol%',            2.00, 10.00, 0.10, 2.50, '2026-01-01', 20, 'https://developers.openai.com/api/docs/pricing'),
  ('openai', 'gpt-6.1-sol%',            2.00, 10.00, 0.10, 2.50, '2026-01-01', 20, 'https://developers.openai.com/api/docs/pricing'),
  ('openai', 'gpt-6.1-terra%',          1.00,  5.00, 0.05, 1.25, '2026-01-01', 20, 'https://developers.openai.com/api/docs/pricing'),
  ('openai', 'gpt-6-luna%',             0.10,  0.50, 0.01, 0.125,'2026-01-01', 20, 'https://developers.openai.com/api/docs/pricing'),
  ('openai', 'gpt-5.6-sol%',            4.00, 20.00, 0.40, 5.00, '2026-01-01', 20, 'https://developers.openai.com/api/docs/pricing'),
  ('openai', 'gpt-5.3-codex%',          1.75, 14.00, 0.175,2.1875,'2026-01-01',20, 'https://developers.openai.com/api/docs/pricing');
