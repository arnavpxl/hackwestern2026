"""Simulator world: sim clock, live event stream, fast-forward, scenarios, invoice delivery.

Time model: sim_now() = now() + sim_offset. Live events are written at sim_now so they
always land above the cagg watermark (real-time aggregation shows them instantly).
Fast-forward synthesizes the skipped interval at 1-minute density and bumps the offset.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from .backfill import COPY_SQL, EVENT_WEIGHT
from .catalog import KEYS, MODELS, RUNAWAY_KEY
from .invoices import build_invoice, insert_invoice
from .profiles import backfill_start, build_events, lognormal_split, month_start, units_per_hour

log = logging.getLogger("tokentrueup.sim")
KEY_INDEX = {k.label: i for i, k in enumerate(KEYS)}


async def get_state(conn: AsyncConnection) -> dict[str, Any]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT *, sim_now() AS sim_now, now() AS real_now FROM sim_state WHERE id = 1")
        return await cur.fetchone()


async def load_rate_tables(conn: AsyncConnection) -> dict:
    tables: dict[tuple[str, str], list] = {}
    cur = await conn.execute(
        "SELECT provider, model, extract(epoch FROM ts), input_rate, output_rate, cached_rate, request_rate, gpu_rate"
        " FROM price_changes ORDER BY provider, model, ts"
    )
    for prov, model, eff, *rates in await cur.fetchall():
        tables.setdefault((prov, model), []).append((float(eff), tuple(float(r) for r in rates)))
    return tables


async def key_ids(conn: AsyncConnection) -> list[int]:
    rows = await (await conn.execute("SELECT label, id FROM api_keys")).fetchall()
    by_label = dict(rows)
    return [by_label[k.label] for k in KEYS]


COPY_CSV_SQL = COPY_SQL.replace("(FORMAT BINARY)", "(FORMAT CSV)")


def _csv(batches: list[dict]) -> tuple[str, int]:
    parts, n = [], 0
    for b in batches:
        kid = int(b["api_key_id"][0])
        prov = b["provider"]
        models = b["models"]
        parts.extend(
            f"{datetime.fromtimestamp(t, UTC).isoformat()},{kid},{prov},{models[mi]},{i},{o},{c},{r},{g!r},{cost!r}"
            for t, mi, i, o, c, r, g, cost in zip(
                b["epoch"].tolist(), b["model_idx"].tolist(), b["input_tokens"].tolist(),
                b["output_tokens"].tolist(), b["cached_tokens"].tolist(), b["requests"].tolist(),
                b["gpu_seconds"].tolist(), b["cost"].tolist(), strict=True,
            )
        )
        n += len(b["epoch"])
    return "\n".join(parts) + "\n", n


async def copy_batches(conn: AsyncConnection, batches: list[dict]) -> int:
    """One bulk COPY write per batch set (a per-row await caps throughput at ~3k rows/s)."""
    data, n = _csv(batches)
    if n:
        async with conn.cursor() as cur, cur.copy(COPY_CSV_SQL) as cp:
            await cp.write(data)
    return n


def multipliers(scenario: dict) -> dict[int, float]:
    out = {}
    run = scenario.get("runaway")
    if run and run.get("active"):
        out[KEY_INDEX[run["key"]]] = float(run.get("mult", 80))
    return out


def live_window(t0: float, t1: float, eps: float, ids: list[int], origin: float, tables: dict,
                rng: np.random.Generator, mult: dict[int, float]) -> list[dict]:
    """Events in a short live window: spend follows the profile; eps only sets granularity."""
    dt = t1 - t0
    weights = EVENT_WEIGHT / EVENT_WEIGHT.sum()
    mid = np.array([(t0 + t1) / 2])
    out = []
    for i, spec in enumerate(KEYS):
        m = mult.get(i, 1.0)
        lam = eps * dt * weights[i] * (min(m, 8.0) if m > 1 else 1.0)  # loops are chattier too
        total_units = float(units_per_hour(spec, mid, origin)[0]) * dt / 3600 * m
        n = int(rng.poisson(lam))
        if MODELS[(spec.provider, spec.models[0][0])][0] == "requests":
            n = min(n, max(1, int(total_units)))  # an event carries >= 1 request on average
        if n == 0:
            continue
        ts = np.sort(rng.uniform(t0, t1, size=n))
        units = lognormal_split(np.full(n, total_units / n), rng)
        out.append(build_events(i, ids[i], ts, units, tables, rng))
    return out


class LiveGenerator:
    """Writes usage_events continuously with batched COPY. Runs inside the API process."""

    def __init__(self, pool: AsyncConnectionPool, tick: float = 0.2):
        self.pool = pool
        self.tick = tick
        self.running = False
        self.events_total = 0
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if not self._task:
            self.running = True
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        rng = np.random.default_rng()
        async with self.pool.connection() as conn:
            ids = await key_ids(conn)
            state = await get_state(conn)
            tables = await load_rate_tables(conn)
        origin = backfill_start(state["real_now"]).timestamp()
        last_t = None
        window_count, window_start = 0, time.monotonic()
        last_refresh = 0.0
        last_future_refresh = 0.0
        while self.running:
            loop_start = time.monotonic()
            try:
                async with self.pool.connection() as conn:
                    if loop_start - last_refresh > 1.0:
                        state = await get_state(conn)
                        tables = await load_rate_tables(conn)
                        last_refresh = loop_start
                        await deliver_due_invoices(conn, state)
                    sim_now = (state["real_now"] + state["sim_offset"]).timestamp() + (
                        time.time() - state["real_now"].timestamp())
                    if state["paused"]:
                        last_t = None
                    else:
                        # never back-fill a big gap (e.g. right after fast-forward): fast_forward
                        # synthesizes skipped time itself; the live stream only covers ~1 tick
                        t0 = max(last_t or 0.0, sim_now - 2 * self.tick)
                        batches = live_window(t0, sim_now, state["target_eps"], ids, origin, tables, rng,
                                              multipliers(state["scenario"]))
                        n = await copy_batches(conn, batches)
                        await conn.commit()
                        last_t = sim_now
                        window_count += n
                        self.events_total += n
                    if state["sim_offset"].total_seconds() > 60 and loop_start - last_future_refresh > 10:
                        await refresh_ahead(conn, datetime.fromtimestamp(sim_now, UTC))
                        last_future_refresh = loop_start
                    el = time.monotonic() - window_start
                    if el >= 1.0:
                        await conn.execute(
                            "UPDATE sim_state SET ingest_eps = %s, eps_updated_at = now() WHERE id = 1",
                            (round(window_count / el, 1),),
                        )
                        await conn.commit()
                        window_count, window_start = 0, time.monotonic()
            except asyncio.CancelledError:
                raise
            except Exception:  # keep the stream alive through transient errors
                log.exception("generator tick failed")
                await asyncio.sleep(1)
            await asyncio.sleep(max(0.0, self.tick - (time.monotonic() - loop_start)))


async def refresh_ahead(conn: AsyncConnection, sim_now: datetime, start: datetime | None = None) -> None:
    """When the sim clock runs ahead of real time, refresh policies (relative to real now())
    never reach the simulated data; materialize it explicitly, bottom-up."""
    start = start or sim_now - timedelta(hours=2)
    await conn.commit()
    await conn.set_autocommit(True)
    try:
        for view, end in (("usage_1m", sim_now - timedelta(minutes=1)),
                          ("usage_1h", sim_now.replace(minute=0, second=0, microsecond=0)),
                          ("usage_1d", sim_now.replace(hour=0, minute=0, second=0, microsecond=0))):
            if end > start:
                await conn.execute("CALL refresh_continuous_aggregate(%s, %s, %s)", (view, start, end))
    finally:
        await conn.set_autocommit(False)


async def fast_forward(conn: AsyncConnection, to: datetime) -> dict[str, Any]:
    """Synthesize [sim_now, to) at 5-minute density per key (no runaway), move the clock,
    then materialize the skipped range in the cagg hierarchy."""
    state = await get_state(conn)
    start = state["sim_now"]
    if to <= start:
        return {"rows": 0, "sim_now": start.isoformat()}
    ids = await key_ids(conn)
    tables = await load_rate_tables(conn)
    origin = backfill_start(state["real_now"]).timestamp()
    rng = np.random.default_rng(int(to.timestamp()))
    t0, t1 = start.timestamp(), to.timestamp()
    minutes = np.arange(np.ceil(t0 / 300) * 300, t1, 300.0)
    t = time.perf_counter()
    rows = 0
    batches = []
    for i, spec in enumerate(KEYS):
        units = lognormal_split(units_per_hour(spec, minutes, origin) / 12, rng, sigma=0.2)
        batches.append(build_events(i, ids[i], minutes + rng.uniform(0, 299, len(minutes)), units, tables, rng))
    rows = await copy_batches(conn, batches)
    scenario = dict(state["scenario"])
    if scenario.get("runaway"):
        scenario["runaway"]["active"] = False
    await conn.execute(
        "UPDATE sim_state SET sim_offset = %s::timestamptz - now(), scenario = %s WHERE id = 1",
        (to, Jsonb(scenario)),
    )
    await conn.commit()
    t_ref = time.perf_counter()
    await refresh_ahead(conn, to, start=start.replace(minute=0, second=0, microsecond=0))
    refresh_s = time.perf_counter() - t_ref
    state = await get_state(conn)
    delivered = await deliver_due_invoices(conn, state)
    return {"rows": rows, "refresh_seconds": round(refresh_s, 2), "seconds": round(time.perf_counter() - t, 2), "from": start.isoformat(),
            "sim_now": state["sim_now"].isoformat(), "invoices_delivered": delivered}


async def deliver_due_invoices(conn: AsyncConnection, state: dict) -> list[int]:
    """Providers invoice the close period N days after it ends (plus any scenario duplicates)."""
    period = datetime.combine(state["close_period"], datetime.min.time(), UTC)
    end = month_start(period, 1)
    sim_now = state["sim_now"]
    if sim_now < end:
        return []
    scenario = state["scenario"] or {}
    delivered = []
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """SELECT p.id, p.invoice_lag_days FROM providers p
               WHERE NOT EXISTS (SELECT 1 FROM ap_invoices i WHERE i.provider_id = p.id AND i.period_start = %s)
                 AND %s::timestamptz + make_interval(days => p.invoice_lag_days) <= %s""",
            (period.date(), end, sim_now),
        )
        due = await cur.fetchall()
    for p in due:
        amount, lines = await build_invoice(conn, p["id"], period, end, scenario.get("stealth_price"))
        received = end + timedelta(days=p["invoice_lag_days"])
        inv = await insert_invoice(conn, p["id"], period, received, amount, lines)
        delivered.append(inv)
        if scenario.get("duplicate_invoice") == p["id"]:
            delivered.append(await insert_invoice(conn, p["id"], period, received + timedelta(hours=20), amount,
                                                  lines, suffix="-RESUBMIT"))
        await conn.execute(
            "INSERT INTO audit_log (actor, action, detail) VALUES ('sim:ap_inbox', 'invoice_received', %s)",
            (Jsonb({"provider": p["id"], "invoice_id": inv, "amount_cents": amount}),),
        )
    await conn.commit()
    if delivered:
        await conn.execute("SELECT pg_notify('cases', %s)", ('{"event":"invoices_received"}',))
        await conn.commit()
    return delivered


# ---------------------------------------------------------------- scenarios

async def set_scenario(conn: AsyncConnection, patch: dict) -> dict:
    cur = await conn.execute(
        "UPDATE sim_state SET scenario = scenario || %s, updated_at = now() WHERE id = 1 RETURNING scenario",
        (Jsonb(patch),),
    )
    row = await cur.fetchone()
    await conn.commit()
    return row[0]


async def scenario_runaway(conn: AsyncConnection, on: bool = True, key: str = RUNAWAY_KEY, mult: float = 80) -> dict:
    state = await get_state(conn)
    return await set_scenario(conn, {"runaway": {"key": key, "mult": mult, "active": on,
                                                 "since": state["sim_now"].isoformat()}})


async def scenario_price_change(conn: AsyncConnection, provider: str = "cortexa", model: str = "cx-large",
                                pct: float = 10.0) -> dict:
    """Announced mid-month price change: a new price_changes row effective now."""
    state = await get_state(conn)
    cur = await conn.execute(
        """INSERT INTO price_changes (ts, provider, model, input_rate, output_rate, cached_rate, request_rate,
               gpu_rate, note)
           SELECT %s, provider, model, input_rate * %s, output_rate * %s, cached_rate * %s, request_rate * %s,
                  gpu_rate * %s, 'announced price change (scenario)'
           FROM price_changes WHERE provider = %s AND model = %s ORDER BY ts DESC LIMIT 1
           RETURNING ts, input_rate, output_rate""",
        (state["sim_now"], *(1 + pct / 100,) * 5, provider, model),
    )
    row = await cur.fetchone()
    await conn.commit()
    return {"provider": provider, "model": model, "effective": row[0].isoformat(),
            "input_rate": float(row[1]), "output_rate": float(row[2])}


async def scenario_stealth_price(conn: AsyncConnection, provider: str = "nimbus-llm", model: str = "nimbus-pro",
                                 component: str = "output_tokens", new_rate: float = 1800, days_ago: float = 6) -> dict:
    """Unannounced price change: only the provider's invoice knows. Recon must find it."""
    state = await get_state(conn)
    since = state["sim_now"] - timedelta(days=days_ago)
    return await set_scenario(conn, {"stealth_price": {"provider": provider, "model": model, "component": component,
                                                       "rate": new_rate, "from": since.isoformat()}})


async def scenario_duplicate_invoice(conn: AsyncConnection, provider: str = "stratus-cloud") -> dict:
    return await set_scenario(conn, {"duplicate_invoice": provider})


async def scenario_late_data(conn: AsyncConnection, key: str = "research-train-h100", days_ago: float = 2,
                             gpu_hours: float = 40) -> dict[str, Any]:
    """Provider re-sends 2-day-old metering. The rows land BELOW the cagg watermark, so
    they invalidate a materialized range; the 1m refresh policy (7-day window) re-materializes it."""
    state = await get_state(conn)
    ids = await key_ids(conn)
    tables = await load_rate_tables(conn)
    i = KEY_INDEX[key]
    start = (state["sim_now"] - timedelta(days=days_ago)).replace(minute=0, second=0, microsecond=0)
    rng = np.random.default_rng(7)
    ts = np.sort(rng.uniform(start.timestamp(), start.timestamp() + 3600, 120))
    units = np.full(120, gpu_hours / 120)
    rows = await copy_batches(conn, [build_events(i, ids[i], ts, units, tables, rng)])
    await conn.commit()
    return {"rows": rows, "key": key, "hour": start.isoformat(), "gpu_hours": gpu_hours,
            "provider": KEYS[i].provider, "model": KEYS[i].models[0][0]}


async def late_data_check(conn: AsyncConnection, hour: datetime, key: str = "research-train-h100") -> dict:
    """Raw vs materialized-only cagg for the late hour: proves refresh absorbed it."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """SELECT
                 (SELECT coalesce(sum(e.gpu_seconds), 0) / 3600 FROM usage_events e JOIN api_keys k ON k.id = e.api_key_id
                  WHERE k.label = %(k)s AND e.ts >= %(h)s AND e.ts < %(h)s::timestamptz + interval '1 hour') AS raw_gpu_hours,
                 (SELECT coalesce(sum(u.gpu_seconds), 0) / 3600 FROM usage_1m u JOIN api_keys k ON k.id = u.api_key_id
                  WHERE k.label = %(k)s AND u.bucket >= %(h)s AND u.bucket < %(h)s::timestamptz + interval '1 hour')
                   AS cagg_gpu_hours,
                 (SELECT js.last_successful_finish FROM timescaledb_information.job_stats js
                  JOIN timescaledb_information.jobs j USING (job_id)
                  WHERE j.proc_name = 'policy_refresh_continuous_aggregate'
                    AND j.hypertable_name = 'usage_1m') AS last_refresh""",
            {"k": key, "h": hour},
        )
        row = await cur.fetchone()
    row["in_sync"] = abs(float(row["raw_gpu_hours"]) - float(row["cagg_gpu_hours"])) < 1e-6
    return row


async def reset_world(conn: AsyncConnection) -> dict:
    """Drop fast-forwarded future data, clear close-period workflow state, rewind clock."""
    state = await get_state(conn)
    await conn.execute("UPDATE sim_state SET sim_offset = '0', paused = true, scenario = '{}' WHERE id = 1")
    await conn.execute("DELETE FROM usage_events WHERE ts > now()")
    await conn.execute("DELETE FROM price_changes WHERE note LIKE '%%scenario%%' OR note LIKE '%%learned rule%%'")
    await conn.execute("DELETE FROM ap_invoices WHERE period_start >= %s", (state["close_period"],))
    await conn.execute("DELETE FROM obligation_cases")
    await conn.execute("DELETE FROM learned_rules")
    await conn.execute("DELETE FROM audit_log")
    await conn.execute("DELETE FROM accrual_snapshots")
    await conn.execute("UPDATE api_keys SET owner_id = NULL WHERE label = 'growth-scraper-legacy'")
    await conn.commit()
    return await get_state(conn)


__all__ = ["MODELS", "month_start"]
