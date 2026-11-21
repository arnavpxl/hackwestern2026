"""Measure the Tiger Data features TokenTrueUp leans on and write BENCHMARKS.md + bench_results.

    PYTHONPATH=src .venv/bin/ttu-bench [--live-api http://localhost:8000] [--out ../BENCHMARKS.md]

Everything here is measured on this run, against the database in DATABASE_URL. The bulk-ingest
test COPYs into the real hypertable inside a transaction that is rolled back, so it leaves no
data behind. --live-api triggers one runaway through the running API to time detection, then
switches it off again.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from ..config import settings
from ..orchestrator.recon import accrual_at_close
from ..orchestrator.rules import params_for
from ..sim import world
from ..sim.profiles import backfill_start, month_start
from . import metrics


def _med(xs: list[float]) -> float:
    return round(statistics.median(xs), 2)


async def bulk_ingest(conn: AsyncConnection, seconds: float = 100, eps: float = 5000) -> dict[str, Any]:
    """COPY ~seconds*eps realistic rows into usage_events (a fresh chunk), then roll back."""
    ids = await world.key_ids(conn)
    tables = await world.load_rate_tables(conn)
    state = await world.get_state(conn)
    origin = backfill_start(state["real_now"]).timestamp()
    t0 = (state["real_now"] + timedelta(days=400)).timestamp()
    rng = np.random.default_rng(1)
    batches = world.live_window(t0, t0 + seconds, eps, ids, origin, tables, rng, {})
    await conn.commit()
    t = time.perf_counter()
    async with conn.transaction(force_rollback=True):
        rows = await world.copy_batches(conn, batches)
    s = time.perf_counter() - t
    return {"rows": rows, "seconds": round(s, 3), "rows_per_s": round(rows / s)}


async def timed(conn: AsyncConnection, sql: str, runs: int = 10) -> dict[str, Any]:
    times = []
    for _ in range(runs):
        t = time.perf_counter()
        await (await conn.execute(sql)).fetchall()
        times.append((time.perf_counter() - t) * 1000)
    return {"median_ms": _med(times), "p_max_ms": round(max(times), 2), "runs": runs}


async def replay_all(conn: AsyncConnection) -> dict[str, Any]:
    """Close-time accrual for every provider x every invoiced month, straight off the caggs."""
    cur = await conn.execute("SELECT DISTINCT provider_id, period_start FROM ap_invoices ORDER BY 1, 2")
    pairs = await cur.fetchall()
    t = time.perf_counter()
    for provider, period in pairs:
        start = datetime.combine(period, datetime.min.time(), UTC)
        await accrual_at_close(conn, provider, start, month_start(start, 1), await params_for(conn, provider, start))
    ms = (time.perf_counter() - t) * 1000
    return {"provider_months": len(pairs), "ms": round(ms, 1),
            "ms_per_provider_month": round(ms / max(1, len(pairs)), 1)}


RUNAWAY_CANDIDATES = ["support-triage-agent", "plat-gateway-prod", "support-copilot", "growth-personalize"]


def _api(base: str, method: str, path: str) -> dict:
    req = urllib.request.Request(base + path, method=method, data=b"" if method == "POST" else None)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read()).get("data", {})


async def live_detection(conn: AsyncConnection, base: str, wait_s: float = 30) -> dict[str, Any]:
    st = _api(base, "GET", "/api/state")
    if st.get("paused"):
        _api(base, "POST", "/api/sim/play")
        await asyncio.sleep(3)
    cur = await conn.execute("SELECT coalesce(max(id), 0) FROM obligation_cases WHERE type = 'anomaly'")
    last = (await cur.fetchone())[0]
    # the detector opens at most one case per key per 6 h, so use a key without a recent one
    cur = await conn.execute(
        """SELECT k.label FROM unnest(%s::text[]) WITH ORDINALITY AS c(label, n) JOIN api_keys k USING (label)
           WHERE NOT EXISTS (SELECT 1 FROM obligation_cases o WHERE o.type = 'anomaly' AND o.api_key_id = k.id
                               AND o.opened_at > sim_now() - interval '6 hours')
           ORDER BY n LIMIT 1""", (RUNAWAY_CANDIDATES,))
    row = await cur.fetchone()
    await conn.commit()
    if not row:
        return {"error": "every candidate key already has an anomaly case in the last 6 h (reset the sim)"}
    key = row[0]
    t = time.perf_counter()
    _api(base, "POST", f"/api/scenario/runaway?on=true&key={key}")
    try:
        while time.perf_counter() - t < wait_s:
            cur = await conn.execute(
                "SELECT id, detection_latency_ms, spike_started_at FROM obligation_cases"
                " WHERE type = 'anomaly' AND id > %s ORDER BY id LIMIT 1", (last,))
            row = await cur.fetchone()
            await conn.commit()
            if row:
                return {"case_id": row[0], "key": key, "wall_ms": round((time.perf_counter() - t) * 1000),
                        "detection_latency_ms": row[1], "spike_start_found": row[2] is not None}
            await asyncio.sleep(0.2)
        return {"error": f"not detected within {wait_s}s"}
    finally:
        _api(base, "POST", f"/api/scenario/runaway?on=false&key={key}")


async def run(out_path: Path, live_api: str | None) -> dict[str, Any]:
    conn = await AsyncConnection.connect(settings.database_url)
    r: dict[str, Any] = {"ts": datetime.now(UTC).isoformat(timespec="seconds")}
    ver = await (await conn.execute(
        "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")).fetchone()
    pgv = await (await conn.execute("SHOW server_version")).fetchone()
    r["env"] = {"timescaledb": ver[0], "postgres": pgv[0].split()[0], "client": platform.platform(),
                "db_host": settings.database_url.split("@")[-1].split("/")[0]}
    print("stats ...")
    r["stats"] = await metrics.stats(conn)
    await conn.commit()
    print("query race ...")
    r["race"] = await metrics.race(conn, runs=5)
    await conn.commit()
    print("freshness ...")
    probes = [await metrics.freshness_probe(conn) for _ in range(5)]
    r["freshness"] = {"visible_after_ms": [p["visible_after_ms"] for p in probes],
                      "median_ms": _med([p["visible_after_ms"] or 0 for p in probes])}
    print("anomaly scan ...")
    r["scan"] = await timed(conn, "SELECT * FROM scan_anomalies(sim_now())")
    await conn.commit()
    print("bulk ingest ...")
    r["ingest"] = await bulk_ingest(conn)
    print("replay ...")
    r["replay"] = await replay_all(conn)
    await conn.commit()
    if live_api:
        print("live detection ...")
        r["detection"] = await live_detection(conn, live_api)

    rows = [("usage_events_rows", r["stats"]["usage_rows"], "rows", {}),
            ("race_raw_ms", r["race"]["raw"]["ms"], "ms", {}),
            ("race_cagg_ms", r["race"]["cagg"]["ms"], "ms", {}),
            ("race_speedup", r["race"]["speedup"], "x", {"totals_match": r["race"]["totals_match"]}),
            ("freshness_ms", r["freshness"]["median_ms"], "ms", {}),
            ("scan_anomalies_ms", r["scan"]["median_ms"], "ms", {}),
            ("copy_rows_per_s", r["ingest"]["rows_per_s"], "rows/s", r["ingest"]),
            ("replay_ms", r["replay"]["ms"], "ms", r["replay"])]
    for c in r["stats"]["columnstore"]:
        if c.get("ratio_pct") is not None:
            rows.append((f"columnstore_{c['name']}_pct", c["ratio_pct"], "%", {"x": c["x"]}))
    if (d := r.get("detection")) and "detection_latency_ms" in d:
        rows.append(("detection_latency_ms", d["detection_latency_ms"], "ms", d))
    for metric, value, unit, detail in rows:
        await conn.execute("INSERT INTO bench_results (metric, value, unit, detail) VALUES (%s, %s, %s, %s)",
                           (metric, float(value), unit, Jsonb(detail)))
    await conn.commit()
    await conn.close()
    r["markdown"] = render(r)
    return r


def _mb(b) -> str:
    return f"{(b or 0) / 1e6:,.1f} MB"


def render(r: dict[str, Any]) -> str:
    s, race = r["stats"], r["race"]
    ev = next(c for c in s["columnstore"] if c["name"] == "usage_events")
    lines = [
        "# Benchmarks",
        "",
        f"Measured {r['ts']} by `ttu-bench` (`backend/src/tokentrueup/bench/run_benchmarks.py`) against "
        f"TimescaleDB {r['env']['timescaledb']} on PostgreSQL {r['env']['postgres']} at `{r['env']['db_host']}` "
        f"(client: {r['env']['client']}). All data is synthetic. The live event generator "
        f"was {'paused' if s['paused'] else 'running'} during the run.",
        "",
        "| What | Result |",
        "|---|---|",
        f"| Raw usage events (hypertable, 1-day chunks) | {s['usage_rows']:,} rows in {s['chunks']} chunks "
        f"({s['compressed_chunks']} in columnstore) |",
        f"| Columnstore compression, `usage_events` | {_mb(ev.get('before'))} to {_mb(ev.get('after'))} "
        f"({ev.get('ratio_pct')}% smaller, {ev.get('x')}x) |",
        f"| 30-day spend by team, raw hypertable | {race['raw']['ms']} ms (median of 5) |",
        f"| Same query on the `usage_1d` continuous aggregate | {race['cagg']['ms']} ms "
        f"({race['speedup']}x faster; totals match: {race['totals_match']}) |",
        f"| New event visible in `usage_1m` (real-time aggregation) | {r['freshness']['median_ms']} ms median "
        f"(runs: {r['freshness']['visible_after_ms']}) |",
        f"| `scan_anomalies()` (detector run by the in-DB job every 5 s) | {r['scan']['median_ms']} ms median |",
        f"| Bulk COPY into the hypertable | {r['ingest']['rows_per_s']:,} rows/s "
        f"({r['ingest']['rows']:,} rows, rolled back) |",
        f"| Re-accrue every invoiced provider-month from the caggs (rule replay) | "
        f"{r['replay']['provider_months']} provider-months in {r['replay']['ms']} ms |",
    ]
    if d := r.get("detection"):
        if "detection_latency_ms" in d:
            lines.append(f"| Runaway key: first spike event to case opened (in-DB job) | "
                         f"{d['detection_latency_ms']:,} ms (key `{d['key']}`; wall clock from trigger: {d['wall_ms']:,} ms) |")
        else:
            lines.append(f"| Runaway detection | {d.get('error')} |")
    lines += ["", "## Columnstore by table", "", "| Table | Before | After | Smaller | Chunks compressed |",
              "|---|---|---|---|---|"]
    for c in s["columnstore"]:
        lines.append(f"| `{c['name']}` | {_mb(c.get('before'))} | {_mb(c.get('after'))} | "
                     f"{c.get('ratio_pct', '-')}% | {c.get('number_compressed_chunks', 0)}/{c.get('total_chunks', 0)} |")
    lines += ["", "## Background jobs", "", "| Job | Target | Every | Last run | Runs | Failures |",
              "|---|---|---|---|---|---|"]
    for j in s["jobs"]:
        lines.append(f"| {j['proc_name']} | {j['target'] or '-'} | {j['every']} | {j['last_run_status']} "
                     f"({j['last_ms']} ms) | {j['total_runs']} | {j['total_failures']} |")
    lines += ["", "## The query race", "", "Raw hypertable:", "", "```sql", race["raw"]["sql"], "```", "",
              "Continuous aggregate:", "", "```sql", race["cagg"]["sql"], "```", "",
              "Each is timed with `EXPLAIN (ANALYZE, BUFFERS)`. Both return the same per-team totals "
              f"(${race['raw_total']:,.2f} vs ${race['cagg_total']:,.2f}).", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live-api", default=None, help="base URL of a running API, to time runaway detection")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[4] / "BENCHMARKS.md"))
    args = ap.parse_args()
    r = asyncio.run(run(Path(args.out), args.live_api))
    Path(args.out).write_text(r.pop("markdown"))
    print(json.dumps({k: r[k] for k in ("race", "freshness", "scan", "ingest", "replay")}, default=str)[:1500])
    print("wrote", args.out)


if __name__ == "__main__":
    main()
