"""FastAPI app for the isolated synthetic demo and authenticated provider workspace."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Annotated, Any

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .. import auth, connected_spend, connections
from ..bench import metrics
from ..config import settings
from ..estimators.base import jsonable
from ..ingest import mapping as ingest_mapping
from ..ingest import sync as ingest_sync
from ..orchestrator import close, recon
from ..sim import world
from ..sim.catalog import PROVIDERS as SYNTHETIC_PROVIDERS
from ..sim.profiles import month_start

log = logging.getLogger("tokentrueup.api")


class Hub:
    """LISTEN cases -> fan out to SSE subscribers."""

    def __init__(self) -> None:
        self.subs: set[asyncio.Queue] = set()

    async def listen(self) -> None:
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    settings.database_url, autocommit=True
                ) as conn:
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
    if os.environ.get("TTU_SYNC_ENABLED", "1") == "1":
        tasks.append(asyncio.create_task(ingest_sync.run_scheduler(pool)))
    generator = world.LiveGenerator(pool)
    if os.environ.get("TTU_GENERATOR", "1") == "1":
        generator.start()
    yield
    await generator.stop()
    for t in tasks:
        t.cancel()
    await pool.close()


app = FastAPI(title="TokenTrueUp", lifespan=lifespan)
# Only the web app's origins may call the API with cookies (a wildcard origin cannot be used with credentials).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.web_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def current_user(request: Request) -> dict:
    token = request.cookies.get(auth.COOKIE)
    if not token:
        raise HTTPException(401, "not signed in")
    async with pool.connection() as conn:
        user = await auth.user_from_session(conn, token)
    if user is None:
        raise HTTPException(401, "session expired; sign in again")
    return user


CurrentUser = Annotated[dict, Depends(current_user)]


def require(role: str):
    async def check(user: CurrentUser) -> dict:
        if not auth.has_role(user["role"], role):
            raise HTTPException(403, f"this needs the {role} role")
        return user

    return check


VIEW = [Depends(require("viewer"))]
CONTROL = [Depends(require("controller"))]
ADMIN = [Depends(require("admin"))]


def ok(data: Any) -> dict:
    return {"synthetic": True, "data": jsonable(data)}


def connected_ok(data: Any) -> dict:
    """Envelope for authenticated provider data; never label it synthetic."""
    return {"synthetic": False, "data": jsonable(data)}


async def rows(conn, sql: str, params: Any = None) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        return await cur.fetchall()


SYNTHETIC_PROVIDER_IDS = tuple(provider[0] for provider in SYNTHETIC_PROVIDERS)


async def synthetic_key_rows(conn, period: datetime, end: datetime) -> list[dict]:
    """Spend metadata for demo-owned keys only; never returns key names or connected-workspace keys."""
    return await rows(
        conn,
        """
        WITH mtd AS (
          SELECT api_key_id, sum(cost_cents) AS mtd FROM usage_1d_cost
          WHERE bucket >= %(p)s AND bucket < LEAST(sim_now(), %(e)s) GROUP BY 1),
        rate AS (
          SELECT api_key_id, sum(cost_cents) / 24.0 AS per_hour FROM usage_1h_cost
          WHERE bucket >= sim_now() - interval '24 hours' AND bucket < sim_now() GROUP BY 1),
        last5 AS (
          SELECT api_key_id, sum(cost_estimate_cents) * 12 AS run_rate_hour FROM usage_1m
          WHERE bucket > sim_now() - interval '5 minutes' GROUP BY 1)
        SELECT k.id, k.provider_id, t.name AS team, o.name AS owner,
               round(coalesce(m.mtd, 0) / 100, 2) AS mtd_dollars,
               round(coalesce(r.per_hour, 0) / 100, 2) AS avg_hourly_24h,
               round(coalesce(l.run_rate_hour, 0)::numeric / 100, 2) AS run_rate_hourly,
               round((coalesce(m.mtd, 0) + coalesce(r.per_hour, 0)
                      * GREATEST(0, extract(epoch FROM (%(e)s::timestamptz - sim_now())) / 3600)) / 100, 2)
                 AS projected_month_end
        FROM api_keys k JOIN teams t ON t.id = k.team_id LEFT JOIN owners o ON o.id = k.owner_id
        LEFT JOIN mtd m ON m.api_key_id = k.id LEFT JOIN rate r ON r.api_key_id = k.id
        LEFT JOIN last5 l ON l.api_key_id = k.id
        WHERE k.provider_id = ANY(%(providers)s)
        ORDER BY mtd_dollars DESC""",
        {"p": period, "e": end, "providers": list(SYNTHETIC_PROVIDER_IDS)},
    )


# ------------------------------------------------------------------ accounts & sessions

login_guard = auth.LoginGuard()


class Login(BaseModel):
    email: str
    password: str


class NewUser(BaseModel):
    email: str
    name: str
    role: str
    password: str


class Signup(BaseModel):
    email: str
    name: str
    password: str


@app.post("/api/auth/login")
async def login(body: Login, response: Response):
    email = body.email.strip().lower()
    if login_guard.blocked(email):
        raise HTTPException(429, "too many failed sign-ins; try again in 15 minutes")
    async with pool.connection() as conn:
        user = await auth.authenticate(conn, email, body.password)
        if user is None:
            login_guard.fail(email)
            raise HTTPException(401, "email or password is incorrect")
        login_guard.clear(email)
        token = await auth.create_session(conn, user["id"])
        await conn.commit()
    response.set_cookie(
        auth.COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=int(auth.SESSION_TTL.total_seconds()),
        path="/",
    )
    return ok(user)


@app.post("/api/auth/signup")
async def signup(body: Signup, response: Response):
    """Create a self-serve account and sign it in."""
    async with pool.connection() as conn:
        try:
            uid = await auth.create_user(conn, body.email, body.name, body.password, "admin")
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        except psycopg.errors.UniqueViolation:
            raise HTTPException(409, "that email already has an account") from None
        token = await auth.create_session(conn, uid)
        await conn.commit()
    user = {"id": uid, "email": body.email.strip().lower(), "name": body.name.strip(), "role": "admin"}
    response.set_cookie(
        auth.COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=int(auth.SESSION_TTL.total_seconds()),
        path="/",
    )
    return ok(user)


@app.post("/api/auth/demo")
async def demo_session(response: Response):
    """Issue an invisible session for the public synthetic demo."""
    email = "demo@tokentrueup.local"
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT id, email, name, role FROM users WHERE email = %s", (email,))
            user = await cur.fetchone()
        if user is None:
            try:
                uid = await auth.create_user(conn, email, "Demo visitor", secrets.token_urlsafe(24), "admin")
            except psycopg.errors.UniqueViolation:
                await conn.rollback()
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute("SELECT id, email, name, role FROM users WHERE email = %s", (email,))
                    user = await cur.fetchone()
            else:
                user = {"id": uid, "email": email, "name": "Demo visitor", "role": "admin"}
        token = await auth.create_session(conn, user["id"])
        await conn.commit()
    response.set_cookie(
        auth.COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=int(auth.SESSION_TTL.total_seconds()),
        path="/",
    )
    return ok(user)


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get(auth.COOKIE)
    if token:
        async with pool.connection() as conn:
            await auth.delete_session(conn, token)
            await conn.commit()
    response.delete_cookie(auth.COOKIE, path="/")
    return ok({"signed_out": True})


@app.get("/api/auth/me")
async def me(user: CurrentUser):
    return ok(user)


@app.get("/api/auth/users", dependencies=ADMIN)
async def users():
    async with pool.connection() as conn:
        return ok(await auth.list_users(conn))


@app.post("/api/auth/users", dependencies=ADMIN)
async def new_user(body: NewUser):
    async with pool.connection() as conn:
        try:
            uid = await auth.create_user(conn, body.email, body.name, body.password, body.role)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        except psycopg.errors.UniqueViolation:
            raise HTTPException(409, "that email already has an account") from None
        await conn.commit()
    return ok({"id": uid, "email": body.email.strip().lower(), "role": body.role})


# ------------------------------------------------------------------ provider connections
# Keys are write-only: they are accepted here, encrypted, and never returned by any route.


class NewConnection(BaseModel):
    provider_id: str
    label: str
    team_id: int
    key_kind: str = "admin"
    key: str


class KeyUpdate(BaseModel):
    key: str


@app.get("/api/connections", dependencies=VIEW)
async def connections_list(user: CurrentUser):
    async with pool.connection() as conn:
        return ok(await connections.list_connections(conn, user["id"]))


@app.post("/api/connections", dependencies=ADMIN)
async def connection_add(body: NewConnection, user: CurrentUser):
    async with pool.connection() as conn:
        try:
            cid = await connections.add_connection(
                conn,
                user["id"],
                user["email"],
                provider_id=body.provider_id,
                label=body.label,
                team_id=body.team_id,
                key_kind=body.key_kind,
                key=body.key,
            )
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from None
        except psycopg.errors.UniqueViolation:
            raise HTTPException(409, "a connection with that name already exists") from None
        await conn.commit()
    return ok({"id": cid})


@app.post("/api/connections/{connection_id}/rotate", dependencies=ADMIN)
async def connection_rotate(connection_id: int, body: KeyUpdate, user: CurrentUser):
    async with pool.connection() as conn:
        try:
            await connections.rotate_key(conn, user["email"], connection_id, body.key)
        except LookupError:
            raise HTTPException(404, "no such connection") from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        except RuntimeError as e:
            raise HTTPException(503, str(e)) from None
        await conn.commit()
    return ok({"rotated": connection_id})


@app.post("/api/connections/{connection_id}/sync", dependencies=ADMIN)
async def connection_sync(connection_id: int):
    async with pool.connection() as conn:
        try:
            result = await ingest_sync.sync_connection(conn, connection_id)
        except LookupError:
            raise HTTPException(404, "no such connection") from None
    return ok(result)


class MapKey(BaseModel):
    provider_key_id: str
    workspace_id: str = ""
    api_key_id: int | None = None
    new_key: dict | None = None


class UnmapKey(BaseModel):
    provider_key_id: str
    workspace_id: str = ""


@app.get("/api/connections/{connection_id}", dependencies=VIEW)
async def connection_detail(connection_id: int):
    async with pool.connection() as conn:
        try:
            return ok(await ingest_mapping.connection_detail(conn, connection_id))
        except LookupError:
            raise HTTPException(404, "no such connection") from None


@app.post("/api/connections/{connection_id}/mappings", dependencies=ADMIN)
async def connection_map_key(connection_id: int, body: MapKey, user: CurrentUser):
    async with pool.connection() as conn:
        try:
            api_key_id = await ingest_mapping.map_key(
                conn,
                user["email"],
                connection_id,
                provider_key_id=body.provider_key_id,
                workspace_id=body.workspace_id,
                api_key_id=body.api_key_id,
                new_key=body.new_key,
            )
        except LookupError:
            raise HTTPException(404, "no such connection") from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        except psycopg.errors.UniqueViolation:
            raise HTTPException(409, "a key with that name already exists") from None
        await conn.commit()
    return ok({"api_key_id": api_key_id})


@app.post("/api/connections/{connection_id}/mappings/remove", dependencies=ADMIN)
async def connection_unmap_key(connection_id: int, body: UnmapKey, user: CurrentUser):
    async with pool.connection() as conn:
        await ingest_mapping.unmap_key(
            conn,
            user["email"],
            connection_id,
            provider_key_id=body.provider_key_id,
            workspace_id=body.workspace_id,
        )
        await conn.commit()
    return ok({"removed": True})


@app.post("/api/connections/{connection_id}/revoke", dependencies=ADMIN)
async def connection_revoke(connection_id: int, user: CurrentUser):
    async with pool.connection() as conn:
        try:
            await connections.revoke(conn, user["email"], connection_id)
        except LookupError:
            raise HTTPException(404, "no such connection") from None
        await conn.commit()
    return ok({"revoked": connection_id})


# ------------------------------------------------------------------ state & live spend


@app.get("/api/state", dependencies=VIEW)
async def state():
    async with pool.connection() as conn:
        s = await world.get_state(conn)
        s["llm_mode"] = "live" if settings.llm_enabled else "fallback"
        s["llm_model"] = settings.anthropic_model if settings.llm_enabled else None
        return ok(s)


@app.get("/api/spend/live", dependencies=VIEW)
async def spend_live(minutes: int = 60):
    async with pool.connection() as conn:
        s = await world.get_state(conn)
        period = datetime.combine(s["close_period"], datetime.min.time(), s["sim_now"].tzinfo)
        end = month_start(period, 1)
        series = await rows(
            conn,
            """
            SELECT u.bucket, t.name AS team,
                   round(sum(u.cost_estimate_cents)::numeric / 100 *
                     CASE WHEN u.bucket = time_bucket('1 minute', sim_now())
                          THEN 60.0 / greatest(extract(epoch FROM (sim_now() - u.bucket)), 1)
                          ELSE 1 END, 4) AS dollars,
                   sum(u.events) AS events
            FROM usage_1m u JOIN api_keys k ON k.id = u.api_key_id JOIN teams t ON t.id = k.team_id
            WHERE u.bucket > sim_now() - make_interval(mins => %s) AND u.bucket <= sim_now()
            GROUP BY 1, 2 ORDER BY 1""",
            (minutes,),
        )
        pauses = await rows(
            conn,
            """
            SELECT sim_at, real_started_at, real_ended_at,
                   extract(epoch FROM (coalesce(real_ended_at, now()) - real_started_at)) AS duration_seconds
            FROM sim_pause_intervals
            WHERE sim_at > sim_now() - make_interval(mins => %s) AND sim_at <= sim_now()
            ORDER BY sim_at""",
            (minutes,),
        )
        daily = await rows(
            conn,
            """
            SELECT c.bucket::date AS day, t.name AS team, round(sum(c.cost_cents) / 100, 2) AS dollars
            FROM usage_1d_cost c JOIN api_keys k ON k.id = c.api_key_id JOIN teams t ON t.id = k.team_id
            WHERE c.bucket >= %s AND c.bucket < LEAST(sim_now(), %s) GROUP BY 1, 2 ORDER BY 1""",
            (period, end),
        )
        keys = await synthetic_key_rows(conn, period, end)
        return ok(
            {
                "series": series,
                "pauses": pauses,
                "daily": daily,
                "keys": keys,
                "sim_now": s["sim_now"],
                "paused": s["paused"],
                "period": s["close_period"],
                "period_end": end,
            }
        )


@app.get("/api/spend/connected", dependencies=VIEW)
async def spend_connected(user: CurrentUser, hours: int = 168):
    """Estimated analytics from only the signed-in user's provider connections."""
    async with pool.connection() as conn:
        return connected_ok(await connected_spend.dashboard(conn, user["id"], hours=hours))


# ------------------------------------------------------------------ close & cases


@app.post("/api/close/run", dependencies=CONTROL)
async def close_run():
    async with pool.connection() as conn:
        return ok(await close.run_close(conn))


@app.get("/api/close/summary", dependencies=VIEW)
async def close_summary():
    async with pool.connection() as conn:
        s = await world.get_state(conn)
        pol = await close.policy(conn)
        cases = await rows(
            conn,
            """
            SELECT c.id, c.type, c.status, c.title, c.provider_id, c.estimate_cents, c.confidence, c.opened_at,
                   c.approved_by, c.detection_latency_ms, k.label AS key_label
            FROM obligation_cases c LEFT JOIN api_keys k ON k.id = c.api_key_id
            WHERE c.period = %s ORDER BY c.type, c.estimate_cents DESC NULLS LAST""",
            (s["close_period"],),
        )
        accrual = [c for c in cases if c["type"] != "anomaly" and c["status"] != "skipped_invoiced"]
        by_status: dict[str, int] = {}
        for c in cases:
            by_status[c["status"]] = by_status.get(c["status"], 0) + 1
        by_type: dict[str, int] = {}
        for c in accrual:
            by_type[c["type"]] = by_type.get(c["type"], 0) + int(c["estimate_cents"] or 0)
        return ok(
            {
                "period": s["close_period"],
                "sim_now": s["sim_now"],
                "materiality_cents": pol["materiality_cents"],
                "accrued_cents": sum(int(c["estimate_cents"] or 0) for c in accrual),
                "approved_cents": sum(
                    int(c["estimate_cents"] or 0)
                    for c in accrual
                    if c["status"] in ("approved", "reconciled")
                ),
                "by_status": by_status,
                "by_type_cents": by_type,
                "cases": cases,
            }
        )


@app.get("/api/cases/{case_id}", dependencies=VIEW)
async def case_detail(case_id: int):
    async with pool.connection() as conn:
        c = await rows(
            conn,
            """SELECT c.*, k.label AS key_label, p.name AS provider_name FROM obligation_cases c
                                LEFT JOIN api_keys k ON k.id = c.api_key_id JOIN providers p ON p.id = c.provider_id
                                WHERE c.id = %s""",
            (case_id,),
        )
        if not c:
            raise HTTPException(404)
        return ok(
            {
                "case": c[0],
                "evidence": await rows(
                    conn, "SELECT * FROM evidence WHERE case_id = %s ORDER BY id", (case_id,)
                ),
                "outreach": await rows(
                    conn,
                    """SELECT m.*, o.name AS owner_name, o.email FROM outreach_messages m
                                            LEFT JOIN owners o ON o.id = m.owner_id WHERE case_id = %s ORDER BY m.id""",
                    (case_id,),
                ),
                "audit": await rows(
                    conn, "SELECT * FROM audit_log WHERE case_id = %s ORDER BY id", (case_id,)
                ),
                "snapshots": await rows(
                    conn,
                    """SELECT ts, estimate_cents, confidence, reason FROM accrual_snapshots
                                             WHERE case_id = %s ORDER BY ts""",
                    (case_id,),
                ),
            }
        )


class Reply(BaseModel):
    body: str


@app.post("/api/cases/{case_id}/reply", dependencies=CONTROL)
async def case_reply(case_id: int, r: Reply):
    async with pool.connection() as conn:
        return ok(await close.handle_reply(conn, case_id, r.body))


@app.post("/api/cases/{case_id}/approve", dependencies=CONTROL)
async def case_approve(case_id: int):
    async with pool.connection() as conn:
        await close.approve(conn, case_id)
        return ok({"approved": case_id})


@app.post("/api/cases/{case_id}/rerun/{query_index}", dependencies=CONTROL)
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
        params = {
            k: Jsonb(v) if isinstance(v, list | dict) else v
            for k, v in q["params"].items()
            if f"%({k})s" in q["sql"]
        }
        t = asyncio.get_running_loop().time()
        result = jsonable(await rows(conn, q["sql"], params))
        ms = (asyncio.get_running_loop().time() - t) * 1000
        return ok(
            {"rows": result, "ms": round(ms, 2), "matches_stored": result == q["rows"], "stored": q["rows"]}
        )


@app.get("/api/approvals", dependencies=VIEW)
async def approvals():
    async with pool.connection() as conn:
        return ok(
            await rows(
                conn,
                """SELECT c.*, k.label AS key_label FROM obligation_cases c
                                      LEFT JOIN api_keys k ON k.id = c.api_key_id
                                      WHERE status = 'pending_approval' ORDER BY estimate_cents DESC""",
            )
        )


# ------------------------------------------------------------------ reconciliation & rules


@app.get("/api/recon", dependencies=VIEW)
async def recon_view():
    async with pool.connection() as conn:
        s = await world.get_state(conn)
        invoices = await rows(
            conn,
            """SELECT id, provider_id, invoice_no, period_start, amount_cents, received_at,
                                              status, is_duplicate_of, recon, lines
                                       FROM ap_invoices WHERE received_at <= sim_now()
                                       ORDER BY period_start DESC, provider_id, id""",
        )
        rules = await rows(conn, "SELECT * FROM learned_rules ORDER BY id")
        return ok({"period": s["close_period"], "invoices": invoices, "rules": rules})


@app.post("/api/recon/run", dependencies=CONTROL)
async def recon_run():
    async with pool.connection() as conn:
        return ok(await recon.reconcile_pending(conn))


@app.post("/api/rules/{rule_id}/replay", dependencies=CONTROL)
async def rule_replay(rule_id: int):
    async with pool.connection() as conn:
        return ok(await recon.replay_rule(conn, rule_id))


@app.post("/api/rules/{rule_id}/activate", dependencies=CONTROL)
async def rule_activate(rule_id: int):
    async with pool.connection() as conn:
        await recon.activate_rule(conn, rule_id)
        return ok(await recon.replay_rule(conn, rule_id))


@app.post("/api/rules/{rule_id}/reject", dependencies=CONTROL)
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


@app.post("/api/demo/start", dependencies=ADMIN)
async def demo_start():
    """Start the canonical product demo from a clean, useful state."""
    async with pool.connection() as conn:
        return ok(await world.start_demo(conn))


@app.post("/api/sim/{action}", dependencies=ADMIN)
async def sim_action(action: str):
    async with pool.connection() as conn:
        if action in ("play", "pause"):
            return ok(await world.set_paused(conn, action == "pause"))
        elif action == "baseline":
            return ok(await world.reset_baseline(conn))
        elif action == "reset":
            return ok(await world.reset_world(conn))
        else:
            raise HTTPException(404)
        return ok(await world.get_state(conn))


@app.post("/api/sim-speed", dependencies=ADMIN)
async def sim_speed(s: SimSpeed):
    async with pool.connection() as conn:
        await conn.execute("UPDATE sim_state SET target_eps = %s", (max(100, min(s.eps, 20000)),))
        await conn.commit()
        return ok(await world.get_state(conn))


@app.post("/api/sim-fast-forward", dependencies=ADMIN)
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


@app.post("/api/scenario/{name}", dependencies=ADMIN)
async def scenario(name: str, on: bool = True, key: str = world.RUNAWAY_KEY):
    async with pool.connection() as conn:
        fn = {
            "runaway": lambda: world.scenario_runaway(conn, on, key=key),
            "price_change": lambda: world.scenario_price_change(conn),
            "stealth_price": lambda: world.scenario_stealth_price(conn),
            "duplicate_invoice": lambda: world.scenario_duplicate_invoice(conn),
            "late_data": lambda: world.scenario_late_data(conn),
            "stop": lambda: world.stop_scenarios(conn),
        }.get(name)
        if not fn:
            raise HTTPException(404)
        return ok(await fn())


@app.get("/api/late-data-check", dependencies=VIEW)
async def late_data_check(hour: datetime):
    async with pool.connection() as conn:
        return ok(await world.late_data_check(conn, hour))


# ------------------------------------------------------------------ under the hood


@app.get("/api/uth/stats", dependencies=VIEW)
async def uth_stats():
    async with pool.connection() as conn:
        return ok(await metrics.stats(conn))


@app.post("/api/uth/race", dependencies=ADMIN)
async def uth_race():
    async with pool.connection() as conn:
        return ok(await metrics.race(conn))


@app.post("/api/uth/freshness", dependencies=ADMIN)
async def uth_freshness():
    async with pool.connection() as conn:
        return ok(await metrics.freshness_probe(conn))


@app.get("/api/events", dependencies=VIEW)
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
