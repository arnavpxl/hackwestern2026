"""Close orchestrator. Deterministic state machine; agents are only called for text.

open -> (needs_info) -> estimated -> pending_approval | approved -> reconciled
                    \\-> skipped_invoiced (AP invoice already exists: no accrual)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..agents import runner
from ..estimators.anomaly import estimate_anomaly
from ..estimators.base import Estimate
from ..estimators.fixed import estimate_fixed
from ..estimators.one_time import estimate_one_time
from ..estimators.usage import estimate_usage
from ..sim.profiles import month_start
from ..sim.world import get_state, scenario_runaway
from .rules import params_for

ENSURE_CASES = """
INSERT INTO obligation_cases (period, type, provider_id, contract_id, po_id, title)
SELECT %(period)s::date, 'usage', c.provider_id, c.id, NULL::int, p.name || ' — usage'
FROM contracts c JOIN providers p ON p.id = c.provider_id WHERE c.kind = 'usage'
UNION ALL
SELECT %(period)s::date, 'fixed', c.provider_id, c.id, NULL::int, c.name
FROM contracts c WHERE c.kind IN ('fixed', 'committed')
  AND c.effective_from < %(period_end)s AND (c.effective_to IS NULL OR c.effective_to >= %(period)s)
UNION ALL
SELECT %(period)s::date, 'one_time', po.provider_id, NULL::int, po.id, po.po_number || ' — ' || po.description
FROM purchase_orders po WHERE po.service_date >= %(period)s AND po.service_date < %(period_end)s
ON CONFLICT (period, type, provider_id, coalesce(api_key_id, 0), coalesce(po_id, 0), coalesce(contract_id, 0))
  WHERE type <> 'anomaly' DO NOTHING
"""

FINAL = ("approved", "reconciled", "skipped_invoiced")


async def audit(conn: AsyncConnection, actor: str, case_id: int | None, action: str, detail: dict) -> None:
    await conn.execute(
        "INSERT INTO audit_log (actor, case_id, action, detail) VALUES (%s, %s, %s, %s)",
        (actor, case_id, action, Jsonb(detail)),
    )


async def policy(conn: AsyncConnection) -> dict:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM policies WHERE id = 1")
        return await cur.fetchone()


async def fetch_cases(conn: AsyncConnection, where: str, params: tuple) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"SELECT * FROM obligation_cases WHERE {where} ORDER BY id", params)
        return await cur.fetchall()


def period_bounds(state: dict) -> tuple[datetime, datetime]:
    start = datetime.combine(state["close_period"], datetime.min.time(), UTC)
    return start, month_start(start, 1)


async def invoiced(conn: AsyncConnection, case: dict) -> int | None:
    """Dedupe: an AP invoice for this provider/period already covers this obligation."""
    kind_filter = {
        "usage": "l->>'kind' = 'usage'",
        "fixed": "(l->>'contract_id')::int = %(contract_id)s",
        "one_time": "(l->>'po_id')::int = %(po_id)s",
    }.get(case["type"])
    if not kind_filter:
        return None
    cur = await conn.execute(
        f"""SELECT i.id FROM ap_invoices i, jsonb_array_elements(i.lines) l
            WHERE i.provider_id = %(provider)s AND i.period_start = %(period)s AND i.status <> 'duplicate'
              AND i.received_at <= sim_now() AND {kind_filter} LIMIT 1""",
        {"provider": case["provider_id"], "period": case["period"], "contract_id": case["contract_id"],
         "po_id": case["po_id"]},
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def resolved_anomaly_windows(conn: AsyncConnection, provider: str, period) -> list[dict]:
    rows = await fetch_cases(
        conn, "type = 'anomaly' AND provider_id = %s AND period = %s AND calc ? 'exclude_window'",
        (provider, period),
    )
    return [r["calc"]["exclude_window"] for r in rows]


async def estimate_case(conn: AsyncConnection, case: dict, start: datetime, end: datetime,
                        as_of: datetime) -> Estimate:
    p = case["provider_id"]
    if case["type"] == "usage":
        params = await params_for(conn, p, start)
        params.exclude_windows = await resolved_anomaly_windows(conn, p, case["period"])
        est = await estimate_usage(conn, p, start, end, as_of, params)
        open_anoms = await fetch_cases(
            conn, "type = 'anomaly' AND provider_id = %s AND period = %s AND status NOT IN ('approved', 'reconciled')",
            (p, case["period"]),
        )
        if open_anoms:
            est.flags.append("open_anomaly")
        return est
    if case["type"] == "fixed":
        return await estimate_fixed(conn, p, case["contract_id"], start, end)
    if case["type"] == "one_time":
        return await estimate_one_time(conn, p, case["po_id"], start, end, as_of)
    calc = case["calc"] or {}
    window_end = datetime.fromisoformat(calc["resolved_at"]) if calc.get("resolved_at") else as_of
    est = await estimate_anomaly(conn, p, case["api_key_id"], calc["model"], case["spike_started_at"] or
                                 case["opened_at"], window_end)
    return est


async def ask(conn: AsyncConnection, case: dict, owner_id: int | None, body: str) -> None:
    await conn.execute(
        "INSERT INTO outreach_messages (case_id, direction, owner_id, body) VALUES (%s, 'out', %s, %s)",
        (case["id"], owner_id, body),
    )
    await audit(conn, "system", case["id"], "outreach_sent", {"owner_id": owner_id, "body": body})


async def outreach_if_needed(conn: AsyncConnection, case: dict, est: Estimate) -> bool:
    """Targeted owner questions. Returns True if the case is waiting on an answer."""
    cur = await conn.execute(
        "SELECT direction, parsed FROM outreach_messages WHERE case_id = %s ORDER BY id", (case["id"],))
    msgs = await cur.fetchall()
    answered = any(d == "in" and parsed and parsed.get("intent") != "unclear" for d, parsed in msgs)
    if case["type"] == "anomaly":
        if case["status"] in FINAL or answered:
            return False
        if not msgs:
            cur = await conn.execute(
                """SELECT k.label, coalesce(o.id, lead.id), coalesce(o.name, lead.name)
                   FROM api_keys k LEFT JOIN owners o ON o.id = k.owner_id
                   LEFT JOIN LATERAL (SELECT * FROM owners WHERE team_id = k.team_id ORDER BY id LIMIT 1) lead ON true
                   WHERE k.id = %s""", (case["api_key_id"],))
            label, owner_id, owner_name = await cur.fetchone()
            calc = case["calc"]
            await ask(conn, case, owner_id,
                      f"Hi {owner_name.split()[0]} — key {label} ({calc['model']}) is spending "
                      f"${calc['projected_hourly_cents'] / 100:,.2f}/h vs a baseline of "
                      f"${calc['baseline_mean_cents'] / 100:,.2f}/h since "
                      f"{case['spike_started_at']:%H:%M} UTC. Is this expected, or a runaway job? "
                      "If it's a bug, please stop it and tell us when.")
        return True
    if "orphan_key_excluded" in est.flags:
        if answered:
            return False
        if not msgs:
            orphan = next(q for q in est.queries if "owner_id IS NULL" in q.sql).rows[0]
            cur = await conn.execute(
                """SELECT o.id, o.name, t.name FROM api_keys k JOIN teams t ON t.id = k.team_id
                   JOIN owners o ON o.team_id = t.id WHERE k.id = %s ORDER BY o.id LIMIT 1""",
                (orphan["api_key_id"],))
            owner_id, name, team = await cur.fetchone()
            await ask(conn, case, owner_id,
                      f"Hi {name.split()[0]} — key {orphan['key_label']} (billed to {team}) has no owner on file "
                      f"and ${orphan['list_cents'] / 100:,.2f} of usage this period. Who owns it? "
                      "Reply with their email so we can accrue it to the right cost center.")
        return True
    return False


async def save_contract_evidence(conn: AsyncConnection, case_id: int, name: str, text: str, parsed) -> None:
    await conn.execute(
        "INSERT INTO evidence (case_id, kind, ref, content) VALUES (%s, 'contract', %s, %s)",
        (case_id, name, Jsonb({"text": text, "parsed": parsed.output.model_dump(), "agent": parsed.audit()})),
    )


async def evaluate(conn: AsyncConnection, case: dict, start: datetime, end: datetime, as_of: datetime,
                   pol: dict, deferred: list | None = None) -> dict:
    """(Re)estimate one case and move it through the state machine. With `deferred`, the
    explainer (an LLM call in live mode, no DB access) is queued for run_close to run
    concurrently instead of being awaited here; the numbers and status never wait on it."""
    if case["status"] in FINAL:
        return case
    if inv := await invoiced(conn, case):
        await conn.execute("UPDATE obligation_cases SET status = 'skipped_invoiced', invoice_id = %s WHERE id = %s",
                           (inv, case["id"]))
        await audit(conn, "system", case["id"], "skipped_already_invoiced", {"invoice_id": inv})
        return case

    est = await estimate_case(conn, case, start, end, as_of)
    first = case["estimate_cents"] is None
    if first and case["contract_id"]:
        cur = await conn.execute("SELECT name, source_text FROM contracts WHERE id = %s", (case["contract_id"],))
        name, text = await cur.fetchone()
        if deferred is not None:
            deferred.append(("contract", case["id"], (name, text)))
        else:
            await save_contract_evidence(conn, case["id"], name, text, await runner.contract_parser(text))
    if first and case["po_id"]:
        await conn.execute(
            "INSERT INTO evidence (case_id, kind, ref, content) SELECT %s, 'po', po_number, to_jsonb(po)"
            " FROM purchase_orders po WHERE id = %s", (case["id"], case["po_id"]))
    await conn.execute("DELETE FROM evidence WHERE case_id = %s AND kind = 'query'", (case["id"],))
    for q in est.queries:
        await conn.execute("INSERT INTO evidence (case_id, kind, ref, content) VALUES (%s, 'query', %s, %s)",
                           (case["id"], f"{q.ms:.1f} ms", Jsonb(q.model_dump())))

    waiting = await outreach_if_needed(conn, case, est)
    if est.amount_cents != case["estimate_cents"]:
        await conn.execute(
            "INSERT INTO accrual_snapshots (ts, case_id, estimate_cents, confidence, reason) VALUES (sim_now(), %s, %s, %s, %s)",
            (case["id"], est.amount_cents, est.confidence, "initial" if first else "re-estimate"))

    explain_args = (case, est.model_dump(), est.facts(), list(pol["allowed_actions"]))
    exp = None if deferred is not None else await runner.explainer(*explain_args)
    blocking = waiting or ("open_anomaly" in est.flags and case["type"] == "usage")
    if case["type"] == "anomaly":
        status = "needs_info" if waiting else case["status"]
        if case["status"] in ("open", "needs_info") and not waiting:
            status = "estimated"
    elif blocking:
        status = "needs_info"
    elif est.amount_cents >= pol["materiality_cents"]:
        status = "pending_approval"
    else:
        status = "approved"
    calc = est.model_dump()
    if case["type"] == "anomaly":
        calc = {**(case["calc"] or {}), "estimate": calc}
    if deferred is not None:
        deferred.append(("explain", case["id"], explain_args))
    await conn.execute(
        """UPDATE obligation_cases SET estimate_cents = %s, confidence = %s, calc = %s,
               explanation = COALESCE(%s, explanation), status = %s,
               approved_by = CASE WHEN %s = 'approved' AND approved_by IS NULL THEN 'policy:below_materiality'
                                  ELSE approved_by END,
               approved_at = CASE WHEN %s = 'approved' AND approved_at IS NULL THEN sim_now() ELSE approved_at END
           WHERE id = %s""",
        (est.amount_cents, est.confidence, Jsonb(calc),
         Jsonb({**exp.output.model_dump(), "agent": exp.audit()}) if exp else None,
         status, status, status, case["id"]),
    )
    if status != case["status"] or first:
        await audit(conn, "system", case["id"], "estimated",
                    {"amount_cents": est.amount_cents, "status": status, "flags": est.flags,
                     "explainer": exp.mode if exp else "deferred",
                     "verified": exp.verification.ok if exp else None})
    return {**case, "status": status, "estimate_cents": est.amount_cents}


async def run_close(conn: AsyncConnection, provider: str | None = None) -> dict[str, Any]:
    state = await get_state(conn)
    start, end = period_bounds(state)
    as_of = min(state["sim_now"], end)
    pol = await policy(conn)
    await conn.execute(ENSURE_CASES, {"period": start.date(), "period_end": end.date()})
    where, params = "period = %s", (start.date(),)
    if provider:
        where, params = "period = %s AND provider_id = %s", (start.date(), provider)
    cases = await fetch_cases(conn, where, params)
    # anomalies first: their resolution affects the usage cases
    cases.sort(key=lambda c: (c["type"] != "anomaly", c["id"]))
    deferred: list = []
    out = [await evaluate(conn, c, start, end, as_of, pol, deferred) for c in cases]
    await conn.commit()
    # explanations are text only: run them concurrently, then attach (every number is already stored)
    runs = await asyncio.gather(*(runner.explainer(*args) if kind == "explain" else runner.contract_parser(args[1])
                                  for kind, _, args in deferred))
    for (kind, case_id, args), run in zip(deferred, runs, strict=True):
        if kind == "contract":
            await save_contract_evidence(conn, case_id, *args, run)
            continue
        await conn.execute("UPDATE obligation_cases SET explanation = %s WHERE id = %s",
                           (Jsonb({**run.output.model_dump(), "agent": run.audit()}), case_id))
        await audit(conn, f"agent:explainer({run.mode})", case_id, "explained",
                    {"verified": run.verification.ok})
    await conn.commit()
    await conn.execute("SELECT pg_notify('cases', '{\"event\":\"close_run\"}')")
    await conn.commit()
    return {"period": start.date().isoformat(), "as_of": as_of.isoformat(), "cases": len(out),
            "by_status": _count(out)}


def _count(cases: list[dict]) -> dict[str, int]:
    c: dict[str, int] = {}
    for x in cases:
        c[x["status"]] = c.get(x["status"], 0) + 1
    return c


async def handle_reply(conn: AsyncConnection, case_id: int, body: str) -> dict[str, Any]:
    """Owner reply -> agent interprets (schema + verifier) -> deterministic action -> re-evaluate."""
    case = (await fetch_cases(conn, "id = %s", (case_id,)))[0]
    pol = await policy(conn)
    cur = await conn.execute(
        "SELECT body, owner_id FROM outreach_messages WHERE case_id = %s AND direction = 'out' ORDER BY id DESC LIMIT 1",
        (case_id,))
    q = await cur.fetchone()
    run = await runner.reply_interpreter(body, {**case, "question": q[0] if q else ""}, list(pol["allowed_actions"]))
    parsed = run.output
    await conn.execute(
        "INSERT INTO outreach_messages (case_id, direction, owner_id, body, parsed) VALUES (%s, 'in', %s, %s, %s)",
        (case_id, q[1] if q else None, body, Jsonb({**parsed.model_dump(), "agent": run.audit()})))
    await audit(conn, f"agent:reply_interpreter({run.mode})", case_id, "reply_interpreted", parsed.model_dump())
    state = await get_state(conn)
    effect: dict[str, Any] = {"intent": parsed.intent}

    if case["type"] == "anomaly":
        calc = dict(case["calc"] or {})
        if parsed.intent in ("bug_fixed", "confirm_expected"):
            calc["resolved_at"] = state["sim_now"].isoformat()
            calc["owner_decision"] = parsed.intent
            calc["credit_expected"] = parsed.credit_expected
            if parsed.intent == "bug_fixed":
                # the spike is real usage (billed) but must not drive the run-rate projection
                calc["exclude_window"] = {"api_key_id": case["api_key_id"],
                                          "start_ts": (case["spike_started_at"] or case["opened_at"]).isoformat(),
                                          "end_ts": state["sim_now"].isoformat()}
                run_state = (state["scenario"] or {}).get("runaway") or {}
                if run_state.get("active"):
                    await scenario_runaway(conn, on=False, key=run_state["key"])  # owner killed the loop
                    effect["runaway_stopped"] = True
            await conn.execute("UPDATE obligation_cases SET calc = %s, status = 'approved', approved_by = %s,"
                               " approved_at = sim_now() WHERE id = %s",
                               (Jsonb(calc), f"owner:{parsed.intent}", case_id))
            await audit(conn, "system", case_id, "anomaly_resolved", {"decision": parsed.intent})
        elif parsed.intent == "bug_ongoing":
            await conn.execute("UPDATE obligation_cases SET status = 'pending_approval' WHERE id = %s", (case_id,))
            await audit(conn, "system", case_id, "escalated_to_controller", {})
    elif parsed.intent == "assign_owner" and parsed.owner_email:
        est = case["calc"] or {}
        orphan_rows = [r for q_ in est.get("queries", []) if "owner_id IS NULL" in q_["sql"] for r in q_["rows"]]
        cur = await conn.execute("SELECT id FROM owners WHERE lower(email) = lower(%s)", (parsed.owner_email,))
        owner = await cur.fetchone()
        if owner and orphan_rows:
            await conn.execute("UPDATE api_keys SET owner_id = %s WHERE id = %s",
                               (owner[0], orphan_rows[0]["api_key_id"]))
            await audit(conn, "system", case_id, "owner_assigned",
                        {"api_key_id": orphan_rows[0]["api_key_id"], "owner_id": owner[0]})
            effect["owner_assigned"] = owner[0]
        else:
            effect["owner_unknown"] = parsed.owner_email
    await conn.commit()
    summary = await run_close(conn, provider=case["provider_id"])
    return {"interpretation": parsed.model_dump(), "agent_mode": run.mode, "effect": effect, "close": summary}


async def approve(conn: AsyncConnection, case_id: int, actor: str = "controller") -> None:
    await conn.execute(
        "UPDATE obligation_cases SET status = 'approved', approved_by = %s, approved_at = sim_now()"
        " WHERE id = %s AND status = 'pending_approval'", (actor, case_id))
    await audit(conn, actor, case_id, "approved", {})
    await conn.commit()
