"""One-time obligations (fine-tune jobs, reserved capacity) from purchase orders whose
service was delivered within the period and as of the close date."""

from datetime import datetime

from psycopg import AsyncConnection

from .base import Estimate, run_query

ONE_TIME_SQL = """
SELECT po.id AS po_id, po.po_number, po.kind, po.description, po.service_date, po.amount_cents
FROM purchase_orders po
WHERE po.id = %(po_id)s
  AND po.service_date >= %(period_start)s::date AND po.service_date < %(period_end)s::date
  AND po.service_date <= %(as_of)s::date
"""


async def estimate_one_time(
    conn: AsyncConnection, provider: str, po_id: int, period_start: datetime, period_end: datetime, as_of: datetime
) -> Estimate:
    q = await run_query(
        conn,
        ONE_TIME_SQL,
        {"po_id": po_id, "period_start": period_start, "period_end": period_end, "as_of": as_of},
    )
    total = sum(r["amount_cents"] for r in q.rows)
    desc = q.rows[0]["description"] if q.rows else "service not yet delivered"
    return Estimate(
        kind="one_time",
        provider_id=provider,
        amount_cents=int(total),
        confidence=0.97 if q.rows else 0.3,
        summary=f"PO {desc}",
        lines=q.rows,
        queries=[q],
    )
