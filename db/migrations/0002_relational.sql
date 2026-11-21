-- Relational side of the single Postgres DB. ALL DATA IS SYNTHETIC.

CREATE TABLE teams (
  id          serial PRIMARY KEY,
  name        text NOT NULL UNIQUE,
  cost_center text NOT NULL
);

CREATE TABLE owners (
  id      serial PRIMARY KEY,
  name    text NOT NULL,
  email   text NOT NULL UNIQUE,
  team_id int NOT NULL REFERENCES teams(id)
);

CREATE TABLE providers (
  id               text PRIMARY KEY,           -- slug, e.g. 'nimbus-llm'
  name             text NOT NULL,
  kind             text NOT NULL CHECK (kind IN ('llm', 'gpu', 'cloud')),
  invoice_lag_days int  NOT NULL DEFAULT 5     -- invoice arrives N days after month end
);

CREATE TABLE api_keys (
  id          serial PRIMARY KEY,
  label       text NOT NULL UNIQUE,
  provider_id text NOT NULL REFERENCES providers(id),
  team_id     int  NOT NULL REFERENCES teams(id),
  owner_id    int  REFERENCES owners(id),       -- NULL = orphaned key scenario
  is_batch    boolean NOT NULL DEFAULT false,   -- batch API usage gets batch discount
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- Contract terms. Tiers apply on cumulative monthly billable tokens per provider:
-- tiers = [{"from_tokens": 0, "discount_pct": 0}, {"from_tokens": 2000000000, "discount_pct": 8}]
CREATE TABLE contracts (
  id                  serial PRIMARY KEY,
  provider_id         text NOT NULL REFERENCES providers(id),
  name                text NOT NULL,
  kind                text NOT NULL CHECK (kind IN ('usage', 'fixed', 'committed')),
  fixed_monthly_cents bigint NOT NULL DEFAULT 0,  -- seat plans / committed-use minimums
  seats               int,
  seat_price_cents    bigint,
  tiers               jsonb  NOT NULL DEFAULT '[{"from_tokens":0,"discount_pct":0}]',
  cached_discount_pct numeric(5,2) NOT NULL DEFAULT 0, -- extra discount on cached-token line
  batch_discount_pct  numeric(5,2) NOT NULL DEFAULT 0,
  effective_from      date NOT NULL,
  effective_to        date,                         -- NULL = open-ended
  source_text         text                          -- raw (synthetic) contract text for agents
);

CREATE TABLE purchase_orders (
  id           serial PRIMARY KEY,
  po_number    text NOT NULL UNIQUE,
  provider_id  text NOT NULL REFERENCES providers(id),
  team_id      int  NOT NULL REFERENCES teams(id),
  kind         text NOT NULL CHECK (kind IN ('fine_tune', 'reserved_capacity', 'other')),
  description  text NOT NULL,
  amount_cents bigint NOT NULL,
  service_date date NOT NULL
);

CREATE TABLE ap_invoices (
  id              serial PRIMARY KEY,
  provider_id     text NOT NULL REFERENCES providers(id),
  invoice_no      text NOT NULL,
  period_start    date NOT NULL,                  -- first day of billed month
  amount_cents    bigint NOT NULL,
  lines           jsonb NOT NULL DEFAULT '[]',
  received_at     timestamptz NOT NULL,
  is_duplicate_of int REFERENCES ap_invoices(id),
  status          text NOT NULL DEFAULT 'received' CHECK (status IN ('received', 'matched', 'duplicate', 'disputed'))
);
CREATE INDEX ON ap_invoices (provider_id, period_start);

-- Single-row policy table: thresholds and the allow-list the verifier enforces.
CREATE TABLE policies (
  id                        int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  materiality_cents         bigint  NOT NULL DEFAULT 500000,  -- $5,000 needs controller approval
  anomaly_sigma             numeric NOT NULL DEFAULT 3,
  anomaly_min_cents_per_hour numeric NOT NULL DEFAULT 2000,   -- ignore spikes under $20/h
  anomaly_window_minutes    int     NOT NULL DEFAULT 5,
  allowed_actions           text[]  NOT NULL DEFAULT ARRAY[
    'ask_owner', 'accrue', 'accrue_with_adjustment', 'exclude_from_accrual',
    'escalate_to_controller', 'mark_duplicate', 'propose_rule', 'no_action']
);
INSERT INTO policies DEFAULT VALUES;

CREATE TABLE obligation_cases (
  id                  serial PRIMARY KEY,
  period              date NOT NULL,                 -- first day of close month
  type                text NOT NULL CHECK (type IN ('fixed', 'usage', 'one_time', 'anomaly')),
  provider_id         text NOT NULL REFERENCES providers(id),
  api_key_id          int REFERENCES api_keys(id),
  po_id               int REFERENCES purchase_orders(id),
  contract_id         int REFERENCES contracts(id),
  status              text NOT NULL DEFAULT 'open' CHECK (status IN (
                        'open', 'needs_info', 'estimated', 'pending_approval',
                        'approved', 'skipped_invoiced', 'reconciled')),
  title               text NOT NULL,
  estimate_cents      bigint,
  confidence          numeric(4,3),
  calc                jsonb,       -- line-by-line calc incl. exact SQL + params + result rows
  explanation         jsonb,       -- verified agent explanation
  opened_at           timestamptz NOT NULL DEFAULT now(),
  spike_started_at    timestamptz, -- anomaly: first event ts of the spike
  detection_latency_ms bigint,     -- anomaly: opened_at - spike_started_at (wall clock)
  approved_by         text,
  approved_at         timestamptz,
  invoice_id          int REFERENCES ap_invoices(id)
);
CREATE INDEX ON obligation_cases (period, status);
CREATE UNIQUE INDEX one_case_per_obligation ON obligation_cases
  (period, type, provider_id, coalesce(api_key_id, 0), coalesce(po_id, 0), coalesce(contract_id, 0))
  WHERE type <> 'anomaly';

CREATE TABLE evidence (
  id         serial PRIMARY KEY,
  case_id    int NOT NULL REFERENCES obligation_cases(id) ON DELETE CASCADE,
  kind       text NOT NULL,        -- 'contract', 'po', 'query', 'owner_reply', 'invoice', 'price_change'
  ref        text,
  content    jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON evidence (case_id);

CREATE TABLE outreach_messages (
  id         serial PRIMARY KEY,
  case_id    int NOT NULL REFERENCES obligation_cases(id) ON DELETE CASCADE,
  direction  text NOT NULL CHECK (direction IN ('out', 'in')),
  owner_id   int REFERENCES owners(id),
  body       text NOT NULL,
  parsed     jsonb,                -- schema-validated interpretation of an inbound reply
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
  id      bigserial PRIMARY KEY,
  ts      timestamptz NOT NULL DEFAULT now(),
  actor   text NOT NULL,           -- 'system', 'agent:<name>', 'controller', 'db:anomaly_job'
  case_id int REFERENCES obligation_cases(id) ON DELETE CASCADE,
  action  text NOT NULL,
  detail  jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX ON audit_log (case_id, ts);

CREATE TABLE learned_rules (
  id           serial PRIMARY KEY,
  created_at   timestamptz NOT NULL DEFAULT now(),
  status       text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'active', 'rejected')),
  kind         text NOT NULL CHECK (kind IN ('late_data_buffer', 'rate_effective_dating', 'cached_discount', 'include_orphan_keys')),
  provider_id  text REFERENCES providers(id),
  params       jsonb NOT NULL DEFAULT '{}',
  rationale    text NOT NULL,
  source_case_id int REFERENCES obligation_cases(id),
  replay       jsonb,             -- before/after error by month + runtime ms
  activated_at timestamptz
);

-- Simulator clock. sim_now() = now() + offset so live data always lands above the
-- cagg watermark and real-time aggregation shows it immediately.
CREATE TABLE sim_state (
  id         int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  sim_offset interval NOT NULL DEFAULT '0',
  paused     boolean  NOT NULL DEFAULT true,
  target_eps int      NOT NULL DEFAULT 3000,
  ingest_eps numeric  NOT NULL DEFAULT 0,
  scenario   jsonb    NOT NULL DEFAULT '{}',   -- active scenario flags read by the generator
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO sim_state DEFAULT VALUES;

CREATE OR REPLACE FUNCTION sim_now() RETURNS timestamptz
LANGUAGE sql STABLE AS $$ SELECT now() + sim_offset FROM sim_state WHERE id = 1 $$;

CREATE TABLE bench_results (
  id     bigserial PRIMARY KEY,
  ts     timestamptz NOT NULL DEFAULT now(),
  metric text NOT NULL,
  value  double precision NOT NULL,
  unit   text NOT NULL,
  detail jsonb NOT NULL DEFAULT '{}'
);
