"""FastAPI app. Every response carries synthetic=true: ALL DATA IS SYNTHETIC."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ..bench import metrics
from ..config import settings
from ..estimators.base import jsonable
from ..orchestrator import close, recon
from ..sim import world
from ..sim.profiles import month_start

log = logging.getLogger("tokentrueup.api")


class Hub:
    """LISTEN cases -> fan out to SSE subscribers."""

    def __init__(self) -> None:
        self.subs: set[asyncio.Queue] = set()

    async def listen(self) -> None:
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(settings.database_url, autocommit=True) as conn:
                    await conn.execute("LISTEN cases")
                    async for n in conn.notifies():
                        for q in list(self.subs):
                            q.put_nowait(n.payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("listen failed; retrying")
                await asyncio.sleep(2)


hub = Hub()
pool: AsyncConnectionPool
generator: world.LiveGenerator


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool, generator
    pool = AsyncConnectionPool(settings.database_url, min_size=2, max_size=10, open=False)
    await pool.open()
    tasks = [asyncio.create_task(hub.listen())]
    generator = world.LiveGenerator(pool)
    if os.environ.get("TTU_GENERATOR", "1") == "1":
        generator.start()
    yield
    await generator.stop()
    for t in tasks:
        t.cancel()
    await pool.close()


app = FastAPI(title="TokenTrueUp", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def ok(data: Any) -> dict:
    return {"synthetic": True, "data": jsonable(data)}


async def rows(conn, sql: str, params: Any = None) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        return await cur.fetchall()


# ------------------------------------------------------------------ state & live spend

@app.get("/api/state")
async def state():
    async with pool.connection() as conn:
        s = await world.get_state(conn)
        s["llm_mode"] = "live" if settings.llm_enabled else "fallback"
        s["llm_model"] = settings.anthropic_model if settings.llm_enabled else None
        return ok(s)


@app.get("/api/spend/live")
async def spend_live(minutes: int = 60):
    async with pool.connection() as conn:
        s = await world.get_state(conn)
        period = datetime.combine(s["close_period"], datetime.min.time(), s["sim_now"].tzinfo)
        end = month_start(period, 1)
        series = await rows(conn, """
            SELECT u.bucket, t.name AS team, round(sum(u.cost_estimate_cents)::numeric / 100, 4) AS dollars,
                   sum(u.events) AS events
            FROM usage_1m u JOIN api_keys k ON k.id = u.api_key_id JOIN teams t ON t.id = k.team_id
            WHERE u.bucket > sim_now() - make_interval(mins => %s) AND u.bucket <= sim_now()
            GROUP BY 1, 2 ORDER BY 1""", (minutes,))
        daily = await rows(conn, """
            SELECT c.bucket::date AS day, t.name AS team, round(sum(c.cost_cents) / 100, 2) AS dollars
            FROM usage_1d_cost c JOIN api_keys k ON k.id = c.api_key_id JOIN teams t ON t.id = k.team_id
            WHERE c.bucket >= %s AND c.bucket < LEAST(sim_now(), %s) GROUP BY 1, 2 ORDER BY 1""", (period, end))
        keys = await rows(conn, """
            WITH mtd AS (
              SELECT api_key_id, sum(cost_cents) AS mtd FROM usage_1d_cost
              WHERE bucket >= %(p)s AND bucket < LEAST(sim_now(), %(e)s) GROUP BY 1),
            rate AS (
              SELECT api_key_id, sum(cost_cents) / 24.0 AS per_hour FROM usage_1h_cost
              WHERE bucket >= sim_now() - interval '24 hours' AND bucket < sim_now() GROUP BY 1),
            last5 AS (
              SELECT api_key_id, sum(cost_estimate_cents) * 12 AS run_rate_hour FROM usage_1m
              WHERE bucket > sim_now() - interval '5 minutes' GROUP BY 1)
            SELECT k.id, k.label, k.provider_id, t.name AS team, o.name AS owner,
                   round(coalesce(m.mtd, 0) / 100, 2) AS mtd_dollars,
                   round(coalesce(r.per_hour, 0) / 100, 2) AS avg_hourly_24h,
                   round(coalesce(l.run_rate_hour, 0)::numeric / 100, 2) AS run_rate_hourly,
                   round((coalesce(m.mtd, 0) + coalesce(r.per_hour, 0)
                          * GREATEST(0, extract(epoch FROM (%(e)s::timestamptz - sim_now())) / 3600)) / 100, 2)
                     AS projected_month_end
            FROM api_keys k JOIN teams t ON t.id = k.team_id LEFT JOIN owners o ON o.id = k.owner_id
            LEFT JOIN mtd m ON m.api_key_id = k.id LEFT JOIN rate r ON r.api_key_id = k.id
            LEFT JOIN last5 l ON l.api_key_id = k.id ORDER BY mtd_dollars DESC""", {"p": period, "e": end})
        return ok({"series": series, "daily": daily, "keys": keys, "sim_now": s["sim_now"],
                   "period": s["close_period"], "period_end": end})


# ------------------------------------------------------------------ close & cases

@app.post("/api/close/run")
async def close_run():
    async with pool.connection() as conn:
        return ok(await close.run_close(conn))


@app.get("/api/close/summary")
async def close_summary():
    async with pool.connection() as conn:
        s = await world.get_state(conn)
        pol = await close.policy(conn)
        cases = await rows(conn, """
            SELECT c.id, c.type, c.status, c.title, c.provider_id, c.estimate_cents, c.confidence, c.opened_at,
                   c.approved_by, c.detection_latency_ms, k.label AS key_label
            FROM obligation_cases c LEFT JOIN api_keys k ON k.id = c.api_key_id
            WHERE c.period = %s ORDER BY c.type, c.estimate_cents DESC NULLS LAST""", (s["close_period"],))
        accrual = [c for c in cases if c["type"] != "anomaly" and c["status"] != "skipped_invoiced"]
        by_status: dict[str, int] = {}
        for c in cases:
            by_status[c["status"]] = by_status.get(c["status"], 0) + 1
        by_type: dict[str, int] = {}
        for c in accrual:
            by_type[c["type"]] = by_type.get(c["type"], 0) + int(c["estimate_cents"] or 0)
        return ok({"period": s["close_period"], "sim_now": s["sim_now"], "materiality_cents": pol["materiality_cents"],
                   "accrued_cents": sum(int(c["estimate_cents"] or 0) for c in accrual),
                   "approved_cents": sum(int(c["estimate_cents"] or 0) for c in accrual
                                         if c["status"] in ("approved", "reconciled")),
                   "by_status": by_status, "by_type_cents": by_type, "cases": cases})


@app.get("/api/cases/{case_id}")
async def case_detail(case_id: int):
    async with pool.connection() as conn:
        c = await rows(conn, """SELECT c.*, k.label AS key_label, p.name AS provider_name FROM obligation_cases c
                                LEFT JOIN api_keys k ON k.id = c.api_key_id JOIN providers p ON p.id = c.provider_id
                                WHERE c.id = %s""", (case_id,))
        if not c:
            raise HTTPException(404)
        return ok({
            "case": c[0],
            "evidence": await rows(conn, "SELECT * FROM evidence WHERE case_id = %s ORDER BY id", (case_id,)),
            "outreach": await rows(conn, """SELECT m.*, o.name AS owner_name, o.email FROM outreach_messages m
                                            LEFT JOIN owners o ON o.id = m.owner_id WHERE case_id = %s ORDER BY m.id""",
                                   (case_id,)),
            "audit": await rows(conn, "SELECT * FROM audit_log WHERE case_id = %s ORDER BY id", (case_id,)),
            "snapshots": await rows(conn, """SELECT ts, estimate_cents, confidence, reason FROM accrual_snapshots
                                             WHERE case_id = %s ORDER BY ts""", (case_id,)),
        })


class Reply(BaseModel):
    body: str


@app.post("/api/cases/{case_id}/reply")
async def case_reply(case_id: int, r: Reply):
    async with pool.connection() as conn:
        return ok(await close.handle_reply(conn, case_id, r.body))


@app.post("/api/cases/{case_id}/approve")
async def case_approve(case_id: int):
    async with pool.connection() as conn:
        await close.approve(conn, case_id)
        return ok({"approved": case_id})


@app.post("/api/cases/{case_id}/rerun/{query_index}")
async def case_rerun(case_id: int, query_index: int):
    """Re-execute the exact stored SQL + params: every number is reproducible."""
    async with pool.connection() as conn:
        c = await rows(conn, "SELECT calc FROM obligation_cases WHERE id = %s", (case_id,))
        calc = c[0]["calc"] if c else None
        if calc and "estimate" in calc:
            calc = calc["estimate"]
        if not calc or query_index >= len(calc.get("queries", [])):
            raise HTTPException(404)
        q = calc["queries"][query_index]
        params = {k: Jsonb(v) if isinstance(v, list | dict) else v for k, v in q["params"].items()
                  if f"%({k})s" in q["sql"]}
        t = asyncio.get_running_loop().time()
        result = jsonable(await rows(conn, q["sql"], params))
        ms = (asyncio.get_running_loop().time() - t) * 1000
        return ok({"rows": result, "ms": round(ms, 2), "matches_stored": result == q["rows"], "stored": q["rows"]})


@app.get("/api/approvals")
async def approvals():
    async with pool.connection() as conn:
        return ok(await rows(conn, """SELECT c.*, k.label AS key_label FROM obligation_cases c
                                      LEFT JOIN api_keys k ON k.id = c.api_key_id
                                      WHERE status = 'pending_approval' ORDER BY estimate_cents DESC"""))


# ------------------------------------------------------------------ reconciliation & rules

@app.get("/api/recon")
async def recon_view():
    async with pool.connection() as conn:
        s = await world.get_state(conn)
        invoices = await rows(conn, """SELECT id, provider_id, invoice_no, period_start, amount_cents, received_at,
                                              status, is_duplicate_of, recon, lines
                                       FROM ap_invoices WHERE received_at <= sim_now()
                                       ORDER BY period_start DESC, provider_id, id""")
        rules = await rows(conn, "SELECT * FROM learned_rules ORDER BY id")
        return ok({"period": s["close_period"], "invoices": invoices, "rules": rules})


@app.post("/api/recon/run")
async def recon_run():
    async with pool.connection() as conn:
        return ok(await recon.reconcile_pending(conn))


@app.post("/api/rules/{rule_id}/replay")
async def rule_replay(rule_id: int):
    async with pool.connection() as conn:
        return ok(await recon.replay_rule(conn, rule_id))


@app.post("/api/rules/{rule_id}/activate")
async def rule_activate(rule_id: int):
    async with pool.connection() as conn:
        await recon.activate_rule(conn, rule_id)
        return ok(await recon.replay_rule(conn, rule_id))


@app.post("/api/rules/{rule_id}/reject")
async def rule_reject(rule_id: int):
    async with pool.connection() as conn:
        await conn.execute("UPDATE learned_rules SET status = 'rejected' WHERE id = %s", (rule_id,))
        await close.audit(conn, "controller", None, "rule_rejected", {"rule_id": rule_id})
        await conn.commit()
        return ok({"rejected": rule_id})


# ------------------------------------------------------------------ simulator

class SimSpeed(BaseModel):
    eps: int


class FastForward(BaseModel):
    target: str = "month_end"  # 'month_end' | 'invoices' | 'hours'
    hours: float = 0


@app.post("/api/sim/{action}")
async def sim_action(action: str):
    async with pool.connection() as conn:
        if action in ("play", "pause"):
            await conn.execute("UPDATE sim_state SET paused = %s", (action == "pause",))
            await conn.commit()
        elif action == "reset":
            return ok(await world.reset_world(conn))
        else:
            raise HTTPException(404)
        return ok(await world.get_state(conn))


@app.post("/api/sim-speed")
async def sim_speed(s: SimSpeed):
    async with pool.connection() as conn:
        await conn.execute("UPDATE sim_state SET target_eps = %s", (max(100, min(s.eps, 20000)),))
        await conn.commit()
        return ok(await world.get_state(conn))


@app.post("/api/sim-fast-forward")
async def sim_fast_forward(ff: FastForward):
    async with pool.connection() as conn:
        s = await world.get_state(conn)
        period = datetime.combine(s["close_period"], datetime.min.time(), s["sim_now"].tzinfo)
        end = month_start(period, 1)
        if ff.target == "month_end":
            to = end + timedelta(minutes=5)
        elif ff.target == "invoices":
            lag = (await (await conn.execute("SELECT max(invoice_lag_days) FROM providers")).fetchone())[0]
            to = end + timedelta(days=lag, hours=1)
        else:
            to = s["sim_now"] + timedelta(hours=ff.hours)
        return ok(await world.fast_forward(conn, to))


@app.post("/api/scenario/{name}")
async def scenario(name: str, on: bool = True, key: str = world.RUNAWAY_KEY):
    async with pool.connection() as conn:
        fn = {
            "runaway": lambda: world.scenario_runaway(conn, on, key=key),
            "price_change": lambda: world.scenario_price_change(conn),
            "stealth_price": lambda: world.scenario_stealth_price(conn),
            "duplicate_invoice": lambda: world.scenario_duplicate_invoice(conn),
            "late_data": lambda: world.scenario_late_data(conn),
        }.get(name)
        if not fn:
            raise HTTPException(404)
        return ok(await fn())


@app.get("/api/late-data-check")
async def late_data_check(hour: datetime):
    async with pool.connection() as conn:
        return ok(await world.late_data_check(conn, hour))


# ------------------------------------------------------------------ under the hood

@app.get("/api/uth/stats")
async def uth_stats():
    async with pool.connection() as conn:
        return ok(await metrics.stats(conn))


@app.post("/api/uth/race")
async def uth_race():
    async with pool.connection() as conn:
        return ok(await metrics.race(conn))


@app.post("/api/uth/freshness")
async def uth_freshness():
    async with pool.connection() as conn:
        return ok(await metrics.freshness_probe(conn))


@app.get("/api/events")
async def events():
    q: asyncio.Queue = asyncio.Queue()
    hub.subs.add(q)

    async def gen():
        try:
            while True:
                payload = await q.get()
                yield {"event": "case", "data": payload}
        finally:
            hub.subs.discard(q)

    return EventSourceResponse(gen(), ping=15)


def main() -> None:
    import uvicorn

    uvicorn.run("tokentrueup.api.main:app", host="0.0.0.0", port=8000)


__all__ = ["app", "json"]
