"""Reconciliation: invoice arrives -> compare to accrual -> deterministic diagnosis ->
propose learned rule -> replay it over prior months (fast: it runs on caggs) -> controller
activates. The LLM only narrates the diagnosis; it never computes it."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..agents import runner
from ..estimators.base import jsonable
from ..estimators.usage import UsageParams, estimate_usage
from ..sim.invoices import apply_rate_override
from ..sim.profiles import month_start
from ..sim.world import get_state
from .close import audit, fetch_cases
from .rules import params_for

OUR_QTY_SQL = """
SELECT model,
       sum(input_tokens)::float AS input_tokens, sum(output_tokens)::float AS output_tokens,
       sum(cached_tokens)::float AS cached_tokens, sum(requests)::float AS requests,
       sum(gpu_seconds) / 3600.0 AS gpu_hours
FROM usage_1h_cost c JOIN api_keys k ON k.id = c.api_key_id
WHERE c.provider = %(provider)s AND c.bucket >= %(start)s AND c.bucket < %(end)s
GROUP BY model
"""

FIXED_PO_SQL = """
SELECT (SELECT coalesce(sum(fixed_monthly_cents), 0) FROM contracts
        WHERE provider_id = %(provider)s AND kind IN ('fixed', 'committed')
          AND effective_from < %(end)s::date AND (effective_to IS NULL OR effective_to >= %(start)s::date))::bigint
     + (SELECT coalesce(sum(amount_cents), 0) FROM purchase_orders
        WHERE provider_id = %(provider)s AND service_date >= %(start)s::date AND service_date < %(end)s::date)::bigint
"""


def _dt(d) -> datetime:
    return datetime.combine(d, datetime.min.time(), UTC) if not isinstance(d, datetime) else d


async def accrual_at_close(conn: AsyncConnection, provider: str, start: datetime, end: datetime,
                           params: UsageParams) -> int:
    """What we'd accrue at close (as_of = period end) with these params: usage + fixed + POs."""
    est = await estimate_usage(conn, provider, start, end, end, params)
    cur = await conn.execute(FIXED_PO_SQL, {"provider": provider, "start": start, "end": end})
    return est.amount_cents + int((await cur.fetchone())[0])


async def diagnose(conn: AsyncConnection, inv: dict, accrued: int) -> dict[str, Any]:
    provider, start = inv["provider_id"], _dt(inv["period_start"])
    end = month_start(start, 1)
    params = await params_for(conn, provider, start)
    causes: list[dict[str, Any]] = []
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(OUR_QTY_SQL, {"provider": provider, "start": start, "end": end})
        ours = {r["model"]: r for r in await cur.fetchall()}
    est_now = await estimate_usage(conn, provider, start, end, end, params)

    # 1) unit-rate mismatches (price change we never ingested)
    for line in inv["lines"]:
        if line.get("kind") != "usage":
            continue
        cur = await conn.execute(
            "SELECT input_rate, output_rate, cached_rate, request_rate, gpu_rate FROM rate_at(%s, %s, %s)",
            (provider, line["model"], line["service_from"]))
        r = await cur.fetchone()
        comp = line["component"]
        our_rate = float(dict(zip(["input_tokens", "output_tokens", "cached_tokens", "requests", "gpu_hours"],
                                  r, strict=True))[comp])
        if abs(our_rate - float(line["unit_rate_cents"])) > 1e-6:
            p = {"model": line["model"], "component": comp, "rate": float(line["unit_rate_cents"]),
                 "from": line["service_from"]}
            async with conn.transaction(force_rollback=True):  # same discounts as the accrual
                await apply_rate_override(conn, provider, p, "diagnosis what-if")
                impact = (await estimate_usage(conn, provider, start, end, end, params)).amount_cents
            impact -= est_now.amount_cents
            causes.append({"cause": "rate_change", "amount_cents": impact,
                           "detail": f"{line['model']} {comp}: invoiced {line['unit_rate_cents']} vs our "
                                     f"{our_rate} cents/{line['unit']} from {line['service_from'][:10]}",
                           "rule": {"kind": "rate_effective_dating",
                                    "params": {"model": line["model"], "component": comp,
                                               "rate": float(line["unit_rate_cents"]),
                                               "from": line["service_from"]}}})
    # 2) contract discount the CLM record is missing
    for line in inv["lines"]:
        m = re.search(r"Cached input discount \((\d+(?:\.\d+)?)%\)", line.get("description", ""))
        if m and params.cached_discount_pct == 0:
            causes.append({"cause": "contract_discount_missed", "amount_cents": int(line["amount_cents"]),
                           "detail": f"Invoice applies a {m.group(1)}% cached-input discount not in our contract record",
                           "rule": {"kind": "cached_discount", "params": {"pct": float(m.group(1))}}})
    # 3) quantity gaps
    for comp in ("gpu_hours", "requests", "input_tokens", "output_tokens"):
        inv_qty: dict[str, float] = {}
        inv_amt: dict[str, float] = {}
        per = {"gpu_hours": 1, "requests": 1e3}.get(comp, 1e6)
        for line in inv["lines"]:
            if line.get("kind") == "usage" and line["component"] == comp:
                inv_qty[line["model"]] = inv_qty.get(line["model"], 0) + line["quantity"] * per
                inv_amt[line["model"]] = inv_amt.get(line["model"], 0) + line["amount_cents"]
        for model, q_inv in inv_qty.items():
            q_ours = float(ours.get(model, {}).get(comp) or 0)
            if q_ours <= 0 or q_inv <= q_ours * 1.002:
                continue
            ratio = q_inv / q_ours
            impact = round(inv_amt[model] * (1 - 1 / ratio))
            if comp == "gpu_hours":
                causes.append({"cause": "late_or_unmetered_usage", "amount_cents": impact,
                               "detail": f"Invoice bills {ratio * 100 - 100:.2f}% more {model} GPU-hours than we metered",
                               "rule": {"kind": "late_data_buffer", "params": {"pct": round(ratio * 100 - 100, 2)}}})
    if "orphan_key_excluded" in est_now.flags:
        orphan = next(q for q in est_now.queries if "owner_id IS NULL" in q.sql).rows
        amt = sum(r["list_cents"] for r in orphan)
        causes.append({"cause": "missed_usage_ownerless_key", "amount_cents": amt,
                       "detail": "Usage on " + ", ".join(r["key_label"] for r in orphan) +
                                 " was excluded (no owner) but the provider bills every key",
                       "rule": {"kind": "include_orphan_keys", "params": {}}})
    variance = int(inv["amount_cents"]) - accrued
    explained = sum(c["amount_cents"] for c in causes)
    residual = variance - explained
    if abs(residual) > max(100, 0.002 * inv["amount_cents"]):
        causes.append({"cause": "projection_or_late_data", "amount_cents": residual,
                       "detail": "Difference between the run-rate projection / data at accrual time and final usage "
                                 "(late-arriving events are already absorbed by cagg refresh)"})
    return {"invoice_cents": int(inv["amount_cents"]), "accrued_cents": accrued, "variance_cents": variance,
            "variance_pct": round(variance / inv["amount_cents"] * 100, 2) if inv["amount_cents"] else 0.0,
            "recomputed_now_cents": est_now.amount_cents, "causes": causes}


def _facts(diag: dict) -> set[float]:
    out: set[float] = set()

    def walk(v):
        if isinstance(v, bool):
            return
        if isinstance(v, int | float):
            out.update({float(v), float(v) / 100})
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str):
            for m in re.finditer(r"\d+(?:\.\d+)?", v):
                out.add(float(m.group(0)))
    walk(diag)
    return out


async def reconcile(conn: AsyncConnection, invoice_id: int) -> dict[str, Any]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM ap_invoices WHERE id = %s", (invoice_id,))
        inv = await cur.fetchone()
        # duplicate detection: same provider, period, amount and lines as an earlier invoice
        await cur.execute(
            """SELECT id, invoice_no FROM ap_invoices WHERE provider_id = %s AND period_start = %s AND id < %s
                 AND amount_cents = %s AND lines = %s AND status <> 'duplicate' ORDER BY id LIMIT 1""",
            (inv["provider_id"], inv["period_start"], inv["id"], inv["amount_cents"], Jsonb(inv["lines"])))
        dup = await cur.fetchone()
    if dup:
        result = {"duplicate_of": dup["id"], "duplicate_of_invoice_no": dup["invoice_no"],
                  "action": "mark_duplicate", "detail": "Same provider, period, amount and line items"}
        await conn.execute("UPDATE ap_invoices SET status = 'duplicate', is_duplicate_of = %s, recon = %s,"
                           " reconciled_at = sim_now() WHERE id = %s", (dup["id"], Jsonb(result), invoice_id))
        await audit(conn, "system", None, "invoice_marked_duplicate", {"invoice_id": invoice_id, **result})
        await conn.commit()
        return result

    cases = await fetch_cases(conn, "provider_id = %s AND period = %s AND type <> 'anomaly'",
                              (inv["provider_id"], inv["period_start"]))
    accrued = sum(int(c["estimate_cents"] or 0) for c in cases if c["status"] != "skipped_invoiced")
    diag = await diagnose(conn, inv, accrued)
    narr = await runner.variance_narrator(diag, _facts(diag))
    proposed = []
    for c in diag["causes"]:
        if "rule" not in c:
            continue
        rule_id = await propose_rule(conn, inv["provider_id"], c, cases[0]["id"] if cases else None)
        if rule_id:
            proposed.append(rule_id)
    result = {**diag, "narrative": narr.output.model_dump(), "agent": narr.audit(), "proposed_rules": proposed}
    await conn.execute("UPDATE ap_invoices SET status = 'matched', recon = %s, reconciled_at = sim_now() WHERE id = %s",
                       (Jsonb(jsonable(result)), invoice_id))
    for c in cases:
        if c["status"] in ("approved", "pending_approval", "estimated", "needs_info"):
            await conn.execute("UPDATE obligation_cases SET status = 'reconciled', invoice_id = %s WHERE id = %s",
                               (invoice_id, c["id"]))
    await audit(conn, "system", None, "invoice_reconciled",
                {"invoice_id": invoice_id, "variance_cents": diag["variance_cents"], "proposed_rules": proposed})
    await conn.commit()
    for rid in proposed:
        await replay_rule(conn, rid)
    return result


async def propose_rule(conn: AsyncConnection, provider: str, cause: dict, case_id: int | None) -> int | None:
    rule = cause["rule"]
    cur = await conn.execute(
        """SELECT id FROM learned_rules WHERE provider_id = %s AND kind = %s AND status IN ('proposed', 'active')
             AND (kind <> 'rate_effective_dating' OR params->>'model' = %s)""",
        (provider, rule["kind"], rule["params"].get("model", "")))
    if await cur.fetchone():
        return None
    cur = await conn.execute(
        """INSERT INTO learned_rules (kind, provider_id, params, rationale, source_case_id)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (rule["kind"], provider, Jsonb(rule["params"]), cause["detail"], case_id))
    rid = (await cur.fetchone())[0]
    await audit(conn, "system", case_id, "rule_proposed", {"rule_id": rid, **rule})
    return rid


async def replay_rule(conn: AsyncConnection, rule_id: int) -> dict[str, Any]:
    """Re-run close-time accruals for every invoiced month (3 prior + current) with and
    without the rule. Runs on usage_1h_cost (cagg) so a full replay takes milliseconds."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM learned_rules WHERE id = %s", (rule_id,))
        rule = await cur.fetchone()
        await cur.execute(
            "SELECT period_start, amount_cents FROM ap_invoices WHERE provider_id = %s AND status <> 'duplicate'"
            " ORDER BY period_start", (rule["provider_id"],))
        invoices = await cur.fetchall()
    t = time.perf_counter()
    months = []
    for inv in invoices:
        start = _dt(inv["period_start"])
        end = month_start(start, 1)
        before_p = await params_for(conn, rule["provider_id"], start, exclude_rule_ids={rule_id})
        before = await accrual_at_close(conn, rule["provider_id"], start, end, before_p)
        if rule["kind"] == "rate_effective_dating":
            async with conn.transaction(force_rollback=True):  # what-if: backdated rate, then roll back
                await apply_rate_override(conn, rule["provider_id"], rule["params"], "replay")
                after = await accrual_at_close(conn, rule["provider_id"], start, end, before_p)
        else:
            after_p = await params_for(conn, rule["provider_id"], start, exclude_rule_ids={rule_id},
                                       extra_rules=[{"kind": rule["kind"], "params": rule["params"]}])
            after = await accrual_at_close(conn, rule["provider_id"], start, end, after_p)
        amt = int(inv["amount_cents"])
        months.append({"period": start.date().isoformat(), "invoice_cents": amt, "before_cents": before,
                       "after_cents": after, "before_err_pct": round((before - amt) / amt * 100, 3),
                       "after_err_pct": round((after - amt) / amt * 100, 3)})
    ms = (time.perf_counter() - t) * 1000
    replay = {"months": months, "ms": round(ms, 1),
              "mape_before": round(sum(abs(m["before_err_pct"]) for m in months) / max(1, len(months)), 3),
              "mape_after": round(sum(abs(m["after_err_pct"]) for m in months) / max(1, len(months)), 3),
              "source": "usage_1h_cost (continuous aggregate x rate history)"}
    await conn.execute("UPDATE learned_rules SET replay = %s WHERE id = %s", (Jsonb(replay), rule_id))
    await audit(conn, "system", rule["source_case_id"], "rule_replayed", {"rule_id": rule_id, **replay})
    await conn.commit()
    return replay


async def activate_rule(conn: AsyncConnection, rule_id: int, actor: str = "controller") -> None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM learned_rules WHERE id = %s", (rule_id,))
        rule = await cur.fetchone()
    if rule["kind"] == "rate_effective_dating":
        await apply_rate_override(conn, rule["provider_id"], rule["params"], f"learned rule #{rule_id}")
    await conn.execute("UPDATE learned_rules SET status = 'active', activated_at = sim_now() WHERE id = %s",
                       (rule_id,))
    await audit(conn, actor, rule["source_case_id"], "rule_activated", {"rule_id": rule_id})
    await conn.commit()


async def reconcile_pending(conn: AsyncConnection) -> list[dict]:
    state = await get_state(conn)
    cur = await conn.execute(
        "SELECT id FROM ap_invoices WHERE status = 'received' AND period_start = %s AND received_at <= sim_now()"
        " ORDER BY id", (state["close_period"],))
    ids = [r[0] for r in await cur.fetchall()]
    return [{"invoice_id": i, **(await reconcile(conn, i))} for i in ids]
