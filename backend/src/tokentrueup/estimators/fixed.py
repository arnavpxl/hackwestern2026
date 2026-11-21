"""Fixed recurring obligations (seat plans, committed-use minimums) from contract terms,
prorated by the days the contract is effective within the period."""

from datetime import datetime

from psycopg import AsyncConnection

from .base import Estimate, run_query

FIXED_SQL = """
SELECT c.id AS contract_id, c.name, c.kind, c.seats, c.seat_price_cents, c.fixed_monthly_cents,
       (LEAST(COALESCE(c.effective_to + 1, %(period_end)s::date), %(period_end)s::date)
        - GREATEST(c.effective_from, %(period_start)s::date)) AS active_days,
       (%(period_end)s::date - %(period_start)s::date) AS period_days,
       round(c.fixed_monthly_cents
             * (LEAST(COALESCE(c.effective_to + 1, %(period_end)s::date), %(period_end)s::date)
                - GREATEST(c.effective_from, %(period_start)s::date))::numeric
             / (%(period_end)s::date - %(period_start)s::date))::bigint AS amount_cents
FROM contracts c
WHERE c.provider_id = %(provider)s AND c.kind IN ('fixed', 'committed') AND c.id = %(contract_id)s
  AND c.effective_from < %(period_end)s::date
  AND (c.effective_to IS NULL OR c.effective_to >= %(period_start)s::date)
"""


async def estimate_fixed(
    conn: AsyncConnection, provider: str, contract_id: int, period_start: datetime, period_end: datetime
) -> Estimate:
    q = await run_query(
        conn,
        FIXED_SQL,
        {"provider": provider, "contract_id": contract_id, "period_start": period_start, "period_end": period_end},
    )
    total = sum(r["amount_cents"] for r in q.rows)
    name = q.rows[0]["name"] if q.rows else f"contract {contract_id}"
    return Estimate(
        kind="fixed",
        provider_id=provider,
        amount_cents=int(total),
        confidence=0.99 if q.rows else 0.0,
        summary=f"{name}: contract terms prorated over the period",
        lines=q.rows,
        queries=[q],
    )
