-- Refresh, columnstore and retention policies. Windows are chosen so that:
--  * late data up to 7 days old is picked up automatically by the 1m/1h refreshes;
--  * a cagg is never refreshed over a range whose source has been dropped by retention;
--  * columnstore conversion happens after a cagg's refresh window has passed.

-- Raw events: columnstore after 1 day, drop raw after 120 days (caggs keep history).
-- tsdb.hypertable auto-creates a default columnstore policy; replace it with ours.
CALL remove_columnstore_policy('usage_events', if_exists => true);
CALL add_columnstore_policy('usage_events', after => INTERVAL '1 day');
SELECT add_retention_policy('usage_events', drop_after => INTERVAL '120 days');

-- usage_1m: refresh every 30s; retention 30 days (1h/1d keep the history).
SELECT add_continuous_aggregate_policy('usage_1m',
  start_offset => INTERVAL '7 days', end_offset => INTERVAL '1 minute',
  schedule_interval => INTERVAL '30 seconds');
ALTER MATERIALIZED VIEW usage_1m SET (timescaledb.enable_columnstore = true, timescaledb.segmentby = 'api_key_id');
CALL add_columnstore_policy('usage_1m', after => INTERVAL '8 days');
SELECT add_retention_policy('usage_1m', drop_after => INTERVAL '30 days');

SELECT add_continuous_aggregate_policy('usage_1h',
  start_offset => INTERVAL '7 days', end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '5 minutes');
ALTER MATERIALIZED VIEW usage_1h SET (timescaledb.enable_columnstore = true, timescaledb.segmentby = 'api_key_id');
CALL add_columnstore_policy('usage_1h', after => INTERVAL '8 days');

SELECT add_continuous_aggregate_policy('usage_1d',
  start_offset => INTERVAL '14 days', end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 hour');
ALTER MATERIALIZED VIEW usage_1d SET (timescaledb.enable_columnstore = true, timescaledb.segmentby = 'api_key_id');
CALL add_columnstore_policy('usage_1d', after => INTERVAL '15 days');

SELECT add_continuous_aggregate_policy('spend_baseline',
  start_offset => INTERVAL '14 days', end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 hour');

CALL remove_columnstore_policy('accrual_snapshots', if_exists => true);
CALL add_columnstore_policy('accrual_snapshots', after => INTERVAL '30 days');
