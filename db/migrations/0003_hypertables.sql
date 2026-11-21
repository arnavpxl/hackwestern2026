-- Time-series side. Rates are cents per 1M tokens; gpu_rate is cents per GPU-hour.

CREATE TABLE usage_events (
  ts                  timestamptz      NOT NULL,
  api_key_id          int              NOT NULL,
  provider            text             NOT NULL,
  model               text             NOT NULL,
  input_tokens        bigint           NOT NULL DEFAULT 0,
  output_tokens       bigint           NOT NULL DEFAULT 0,
  cached_tokens       bigint           NOT NULL DEFAULT 0,
  requests            int              NOT NULL DEFAULT 1,
  gpu_seconds         double precision NOT NULL DEFAULT 0,
  cost_estimate_cents double precision NOT NULL DEFAULT 0  -- list-rate estimate at ingest (for fast burn/anomaly)
) WITH (
  tsdb.hypertable,
  tsdb.partition_column = 'ts',
  tsdb.chunk_interval   = '1 day',
  tsdb.segmentby        = 'api_key_id',
  tsdb.orderby          = 'ts DESC'
);
CREATE INDEX ON usage_events (api_key_id, ts DESC);

CREATE TABLE price_changes (
  ts           timestamptz NOT NULL,     -- effective from
  provider     text        NOT NULL,
  model        text        NOT NULL,
  input_rate   numeric     NOT NULL,     -- cents / 1M input tokens
  output_rate  numeric     NOT NULL,     -- cents / 1M output tokens
  cached_rate  numeric     NOT NULL,     -- cents / 1M cached input tokens
  request_rate numeric     NOT NULL DEFAULT 0, -- cents / 1k requests
  gpu_rate     numeric     NOT NULL DEFAULT 0, -- cents / GPU-hour
  note         text
) WITH (
  tsdb.hypertable,
  tsdb.partition_column = 'ts',
  tsdb.chunk_interval   = '365 days'
);
CREATE UNIQUE INDEX ON price_changes (provider, model, ts DESC);

CREATE TABLE accrual_snapshots (
  ts             timestamptz NOT NULL DEFAULT now(),
  case_id        int         NOT NULL,
  estimate_cents bigint      NOT NULL,
  confidence     numeric(4,3) NOT NULL,
  reason         text
) WITH (
  tsdb.hypertable,
  tsdb.partition_column = 'ts',
  tsdb.chunk_interval   = '7 days',
  tsdb.segmentby        = 'case_id'
);

-- Rate in effect for (provider, model) at a given instant: the as-of lookup every
-- cost calculation uses. STABLE + index on (provider, model, ts DESC) => index-only probe.
CREATE OR REPLACE FUNCTION rate_at(p_provider text, p_model text, p_ts timestamptz)
RETURNS price_changes LANGUAGE sql STABLE AS $$
  SELECT * FROM price_changes
  WHERE provider = p_provider AND model = p_model AND ts <= p_ts
  ORDER BY ts DESC LIMIT 1
$$;
