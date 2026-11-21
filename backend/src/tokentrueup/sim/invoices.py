"""Synthetic AP invoices — the provider's billing system. It knows things our
estimator does not (INVOICE_TRUTH, stealth price changes, ownerless keys), which is
exactly what reconciliation has to diagnose. ALL SYNTHETIC."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..estimators.usage import contract_params, estimate_usage
from .catalog import INVOICE_TRUTH
from .profiles import month_start

LINES_SQL = """
SELECT model, rate_effective_from,
       (rate_effective_from >= %(stealth_from)s::timestamptz OR bucket >= %(stealth_from)s::timestamptz) AS after_stealth,
       sum(input_tokens)::bigint AS input_tokens, sum(output_tokens)::bigint AS output_tokens,
       sum(cached_tokens)::bigint AS cached_tokens, sum(requests)::bigint AS requests,
       sum(gpu_seconds) / 3600.0 AS gpu_hours,
       max(input_rate) AS input_rate, max(output_rate) AS output_rate, max(cached_rate) AS cached_rate,
       max(request_rate) AS request_rate, max(gpu_rate) AS gpu_rate,
       sum(cached_cost_cents) AS cached_list_cents
FROM usage_1h_cost
WHERE provider = %(provider)s AND bucket >= %(start)s AND bucket < %(end)s
GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
"""

COMPONENTS = [
    ("input_tokens", "input_rate", "1M input tokens", 1e6),
    ("output_tokens", "output_rate", "1M output tokens", 1e6),
    ("cached_tokens", "cached_rate", "1M cached input tokens", 1e6),
    ("requests", "request_rate", "1k requests", 1e3),
    ("gpu_hours", "gpu_rate", "GPU-hour", 1),
]


async def build_invoice(
    conn: AsyncConnection, provider: str, start: datetime, end: datetime, stealth: dict | None = None
) -> tuple[int, list[dict[str, Any]]]:
    truth = INVOICE_TRUTH.get(provider, {})
    p = await contract_params(conn, provider, start)
    p.cached_discount_pct = truth.get("cached_discount_pct", p.cached_discount_pct)
    p.uplift_pct = truth.get("uplift_pct", 0)
    p.include_orphans = True  # the provider bills every key on the account
    est = await estimate_usage(conn, provider, start, end, end, p)

    stealth = stealth if stealth and stealth.get("provider") == provider else None
    stealth_from = datetime.fromisoformat(stealth["from"]) if stealth else end + timedelta(days=3650)
    lines: list[dict[str, Any]] = []
    gross = 0.0
    cached_list = 0.0
    stealth_delta = 0.0
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(LINES_SQL, {"provider": provider, "start": start, "end": end, "stealth_from": stealth_from})
        rows = await cur.fetchall()
    # merge segments that differ only by the stealth flag when no stealth rate applies
    for r in rows:
        cached_list += float(r["cached_list_cents"] or 0)
        for qty_col, rate_col, unit, per in COMPONENTS:
            qty = float(r[qty_col] or 0)
            if qty <= 0:
                continue
            if qty_col == "gpu_hours" and p.uplift_pct:
                qty *= 1 + p.uplift_pct / 100
            rate = float(r[rate_col])
            if stealth and r["after_stealth"] and stealth["model"] == r["model"] and stealth["component"] == qty_col:
                new_rate = float(stealth["rate"])
                stealth_delta += qty / per * (new_rate - rate)
                rate = new_rate
            amount = qty / per * rate
            if qty_col != "gpu_hours":
                gross += amount
            else:
                gross += qty / (1 + p.uplift_pct / 100) / per * float(r[rate_col])
            lines.append({
                "kind": "usage", "model": r["model"], "component": qty_col,
                "rate_effective_from": r["rate_effective_from"].isoformat(),
                "quantity": round(qty / per, 4), "unit": unit, "unit_rate_cents": rate,
                "amount_cents": round(amount),
            })
    if p.cached_discount_pct and cached_list:
        lines.append({"kind": "discount", "description": f"Cached input discount ({p.cached_discount_pct:g}%)",
                      "amount_cents": -round(cached_list * p.cached_discount_pct / 100)})
    usage_lines_total = sum(line["amount_cents"] for line in lines)
    target = est.amount_cents + round(stealth_delta)
    remainder = target - usage_lines_total
    if abs(remainder) > 1:
        lines.append({"kind": "discount", "description": "Volume tier & batch discounts", "amount_cents": remainder})

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """SELECT id, name, fixed_monthly_cents FROM contracts WHERE provider_id = %s AND kind IN ('fixed','committed')
               AND effective_from < %s::date AND (effective_to IS NULL OR effective_to >= %s::date)""",
            (provider, end, start),
        )
        for c in await cur.fetchall():
            lines.append({"kind": "fixed", "contract_id": c["id"], "description": c["name"],
                          "amount_cents": int(c["fixed_monthly_cents"])})
        await cur.execute(
            """SELECT id, po_number, description, amount_cents FROM purchase_orders
               WHERE provider_id = %s AND service_date >= %s::date AND service_date < %s::date""",
            (provider, start, end),
        )
        for po in await cur.fetchall():
            lines.append({"kind": "po", "po_id": po["id"], "po_number": po["po_number"],
                          "description": po["description"], "amount_cents": int(po["amount_cents"])})
    return sum(line["amount_cents"] for line in lines), lines


async def insert_invoice(
    conn: AsyncConnection, provider: str, start: datetime, received_at: datetime, amount: int, lines: list,
    suffix: str = "",
) -> int:
    cur = await conn.execute(
        """INSERT INTO ap_invoices (provider_id, invoice_no, period_start, amount_cents, lines, received_at)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (provider, f"INV-{provider[:4].upper()}-{start:%Y%m}{suffix}", start.date(), amount, Jsonb(lines), received_at),
    )
    return (await cur.fetchone())[0]


async def generate_history(conn: AsyncConnection, now: datetime, months: int = 3) -> int:
    """Invoices for the last `months` complete months (used by rule replay)."""
    n = 0
    providers = await (await conn.execute("SELECT id, invoice_lag_days FROM providers ORDER BY id")).fetchall()
    for m in range(-months, 0):
        start, end = month_start(now, m), month_start(now, m + 1)
        for provider, lag in providers:
            amount, lines = await build_invoice(conn, provider, start, end)
            await insert_invoice(conn, provider, start, end + timedelta(days=lag, hours=9), amount, lines)
            n += 1
    await conn.execute("UPDATE ap_invoices SET status = 'matched'")
    await conn.commit()
    return n
