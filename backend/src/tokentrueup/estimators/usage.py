"""Usage-based obligations: hourly cagg (usage_1h_cost = usage_1h x rate in effect) with
contract tiers, batch and cached discounts, plus a run-rate projection to period end."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from .base import Estimate, run_query

USAGE_SQL = """
WITH hours AS (
  SELECT c.bucket, c.api_key_id, k.label AS key_label, k.is_batch, c.model,
         (c.input_tokens + c.output_tokens + c.cached_tokens) AS tokens,
         c.cost_cents, c.cached_cost_cents
  FROM usage_1h_cost c
  JOIN api_keys k ON k.id = c.api_key_id
  WHERE c.provider = %(provider)s
    AND c.bucket >= %(period_start)s::timestamptz
    AND c.bucket <  LEAST(%(as_of)s::timestamptz, %(period_end)s::timestamptz)
    AND (%(include_orphans)s OR k.owner_id IS NOT NULL)
),
priced AS (
  SELECT h.*,
         (h.cost_cents - h.cached_cost_cents * %(cached_discount_pct)s / 100.0)
           * CASE WHEN h.is_batch THEN 1 - %(batch_discount_pct)s / 100.0 ELSE 1 END AS net_cents,
         COALESCE(SUM(h.tokens) OVER (ORDER BY h.bucket, h.api_key_id, h.model
                  ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS cum_tokens_before
  FROM hours h
),
tiered AS (
  SELECT p.*,
         COALESCE((SELECT (t->>'discount_pct')::numeric
                   FROM jsonb_array_elements(%(tiers)s::jsonb) t
                   WHERE (t->>'from_tokens')::numeric <= p.cum_tokens_before
                   ORDER BY (t->>'from_tokens')::numeric DESC LIMIT 1), 0) AS tier_pct
  FROM priced p
),
mtd AS (
  SELECT api_key_id, key_label, model,
         sum(tokens) AS tokens, sum(cost_cents) AS list_cents, sum(cached_cost_cents) AS cached_list_cents,
         sum(net_cents * (1 - tier_pct / 100.0)) AS mtd_cents, max(tier_pct) AS tier_pct
  FROM tiered GROUP BY 1, 2, 3
),
trail AS (  -- trailing 7-day mean hourly net spend drives the projection
  SELECT c.api_key_id, c.model,
         sum((c.cost_cents - c.cached_cost_cents * %(cached_discount_pct)s / 100.0)
             * CASE WHEN k.is_batch THEN 1 - %(batch_discount_pct)s / 100.0 ELSE 1 END) / 168.0 AS hourly_cents
  FROM usage_1h_cost c JOIN api_keys k ON k.id = c.api_key_id
  WHERE c.provider = %(provider)s
    AND c.bucket >= %(as_of)s::timestamptz - interval '7 days' AND c.bucket < %(as_of)s::timestamptz
    AND (%(include_orphans)s OR k.owner_id IS NOT NULL)
  GROUP BY 1, 2
),
remaining AS (
  SELECT GREATEST(0, EXTRACT(EPOCH FROM (%(period_end)s::timestamptz
           - GREATEST(%(as_of)s::timestamptz, %(period_start)s::timestamptz))) / 3600.0) AS hours
)
SELECT m.api_key_id, m.key_label, m.model, m.tokens::bigint AS tokens,
       round(m.list_cents)::bigint AS list_cents,
       round(m.cached_list_cents)::bigint AS cached_list_cents,
       round(m.mtd_cents)::bigint AS mtd_cents,
       m.tier_pct::float AS tier_pct,
       round(COALESCE(t.hourly_cents, 0) * r.hours * (1 - m.tier_pct / 100.0))::bigint AS projected_cents,
       round(r.hours, 1)::float AS remaining_hours,
       round((m.mtd_cents + COALESCE(t.hourly_cents, 0) * r.hours * (1 - m.tier_pct / 100.0))
             * (1 + %(uplift_pct)s / 100.0))::bigint AS line_total_cents
FROM mtd m CROSS JOIN remaining r LEFT JOIN trail t USING (api_key_id, model)
ORDER BY line_total_cents DESC
"""

ORPHAN_SQL = """
SELECT k.id AS api_key_id, k.label AS key_label, round(sum(c.cost_cents))::bigint AS list_cents
FROM usage_1h_cost c JOIN api_keys k ON k.id = c.api_key_id
WHERE c.provider = %(provider)s AND k.owner_id IS NULL
  AND c.bucket >= %(period_start)s::timestamptz
  AND c.bucket <  LEAST(%(as_of)s::timestamptz, %(period_end)s::timestamptz)
GROUP BY 1, 2
"""


@dataclass
class UsageParams:
    """Contract terms + active learned rules, all explicit so the calc is reproducible."""

    tiers: list[dict] = field(default_factory=lambda: [{"from_tokens": 0, "discount_pct": 0}])
    batch_discount_pct: float = 0
    cached_discount_pct: float = 0
    uplift_pct: float = 0
    include_orphans: bool = False
    applied_rules: list[int] = field(default_factory=list)


async def contract_params(conn: AsyncConnection, provider: str, at: datetime) -> UsageParams:
    cur = await conn.execute(
        """SELECT tiers, batch_discount_pct, cached_discount_pct FROM contracts
           WHERE provider_id = %s AND kind = 'usage' AND effective_from <= %s::date
             AND (effective_to IS NULL OR effective_to >= %s::date)
           ORDER BY effective_from DESC LIMIT 1""",
        (provider, at, at),
    )
    row = await cur.fetchone()
    if not row:
        return UsageParams()
    return UsageParams(tiers=row[0], batch_discount_pct=float(row[1]), cached_discount_pct=float(row[2]))


async def estimate_usage(
    conn: AsyncConnection,
    provider: str,
    period_start: datetime,
    period_end: datetime,
    as_of: datetime,
    params: UsageParams,
) -> Estimate:
    p: dict[str, Any] = {
        "provider": provider,
        "period_start": period_start,
        "period_end": period_end,
        "as_of": as_of,
        "tiers": Jsonb(params.tiers),
        "batch_discount_pct": params.batch_discount_pct,
        "cached_discount_pct": params.cached_discount_pct,
        "uplift_pct": params.uplift_pct,
        "include_orphans": params.include_orphans,
    }
    q = await run_query(conn, USAGE_SQL, p)
    q.params["tiers"] = params.tiers
    q.params["applied_rules"] = params.applied_rules
    total = sum(r["line_total_cents"] for r in q.rows)
    mtd = sum(r["mtd_cents"] for r in q.rows)
    projected = sum(r["projected_cents"] for r in q.rows)
    queries = [q]
    flags = []
    if not params.include_orphans:
        oq = await run_query(conn, ORPHAN_SQL, {k: p[k] for k in ("provider", "period_start", "period_end", "as_of")})
        if oq.rows:
            queries.append(oq)
            flags.append("orphan_key_excluded")
    # Confidence: more of the period observed => higher; projections and exclusions lower it.
    observed = mtd / total if total else 1.0
    confidence = round(min(0.99, 0.6 + 0.39 * observed) - (0.15 if flags else 0), 3)
    return Estimate(
        kind="usage",
        provider_id=provider,
        amount_cents=int(total),
        confidence=max(0.05, confidence),
        summary=f"MTD {mtd / 100:,.2f} + projected {projected / 100:,.2f} across {len(q.rows)} key/model lines",
        lines=[{**r} for r in q.rows],
        queries=queries,
        flags=flags,
    )


def params_dict(p: UsageParams) -> dict:
    return asdict(p)
