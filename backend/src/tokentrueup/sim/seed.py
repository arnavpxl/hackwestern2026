"""Seed relational tables + price history. Idempotent: truncates everything first."""

from datetime import UTC, datetime

import psycopg
from psycopg.types.json import Jsonb

from ..config import settings
from .catalog import CONTRACTS, KEYS, MODELS, OWNERS, PROVIDERS, PURCHASE_ORDERS, TEAMS
from .profiles import backfill_start, month_start, rate_tables

TRUNCATE = """
TRUNCATE audit_log, outreach_messages, evidence, learned_rules, obligation_cases, ap_invoices,
         purchase_orders, contracts, api_keys, owners, teams, providers, bench_results
         RESTART IDENTITY CASCADE;
TRUNCATE usage_events, price_changes, accrual_snapshots;
TRUNCATE usage_1m, usage_1h, usage_1d, spend_baseline;
UPDATE sim_state SET sim_offset = '0', paused = true, scenario = '{}', ingest_eps = 0;
"""


def seed(conn: psycopg.Connection, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    start = backfill_start(now)
    with conn.cursor() as cur:
        cur.execute(TRUNCATE)
        team_ids = {}
        for name, cc in TEAMS:
            cur.execute("INSERT INTO teams (name, cost_center) VALUES (%s, %s) RETURNING id", (name, cc))
            team_ids[name] = cur.fetchone()[0]
        owner_ids = {}
        for name, email, team in OWNERS:
            cur.execute(
                "INSERT INTO owners (name, email, team_id) VALUES (%s, %s, %s) RETURNING id",
                (name, email, team_ids[team]),
            )
            owner_ids[email] = cur.fetchone()[0]
        cur.executemany("INSERT INTO providers VALUES (%s, %s, %s, %s)", PROVIDERS)
        for k in KEYS:
            cur.execute(
                """INSERT INTO api_keys (label, provider_id, team_id, owner_id, is_batch, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (k.label, k.provider, team_ids[k.team], owner_ids.get(k.owner_email), k.is_batch, start),
            )
        for c in CONTRACTS:
            cur.execute(
                """INSERT INTO contracts (provider_id, name, kind, fixed_monthly_cents, seats, seat_price_cents,
                       tiers, cached_discount_pct, batch_discount_pct, effective_from, source_text)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (c["provider_id"], c["name"], c["kind"], c.get("fixed_monthly_cents", 0), c.get("seats"),
                 c.get("seat_price_cents"), Jsonb(c.get("tiers", [{"from_tokens": 0, "discount_pct": 0}])),
                 c.get("cached_discount_pct", 0), c.get("batch_discount_pct", 0),
                 month_start(start, -12).date(), c["source_text"]),
            )
        for i, (m_off, day, provider, team, kind, desc, amount) in enumerate(PURCHASE_ORDERS):
            svc = month_start(now, m_off).replace(day=day).date()
            cur.execute(
                """INSERT INTO purchase_orders (po_number, provider_id, team_id, kind, description,
                       amount_cents, service_date) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (f"PO-{svc:%Y%m}-{100 + i}", provider, team_ids[team], kind, desc, amount, svc),
            )
        for (provider, model), history in rate_tables(start).items():
            for eff, (ri, ro, rc, rr, rg) in history:
                cur.execute(
                    """INSERT INTO price_changes (ts, provider, model, input_rate, output_rate, cached_rate,
                           request_rate, gpu_rate, note) VALUES (to_timestamp(%s),%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (eff, provider, model, ri, ro, rc, rr, rg,
                     "list price" if eff == history[0][0] else "published price change"),
                )
        assert len(MODELS) == cur.execute("SELECT count(DISTINCT (provider, model)) FROM price_changes").fetchone()[0]
    conn.commit()


def main() -> None:
    with psycopg.connect(settings.database_url) as conn:
        seed(conn)
    print("seeded synthetic catalog")
