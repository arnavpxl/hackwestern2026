-- TimescaleDB core + toolkit (hyperfunctions: stats_agg/rollup) + pgvector.
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS timescaledb_toolkit;
DO $$
BEGIN
  CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'pgvector not available; evidence retrieval falls back to full-text search';
END $$;
