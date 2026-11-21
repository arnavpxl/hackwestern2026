"""Live Tiger Data metrics for the 'Under the Hood' page and BENCHMARKS.md."""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from ..estimators.base import jsonable

WINDOW = ("e.ts >= time_bucket('1 day', sim_now()) - interval '30 days' "
          "AND e.ts < time_bucket('1 day', sim_now())")

RACE_RAW = f"""
SELECT t.name AS team, round(sum(e.cost_estimate_cents)::numeric / 100, 2) AS dollars, count(*) AS rows_scanned
FROM usage_events e JOIN api_keys k ON k.id = e.api_key_id JOIN teams t ON t.id = k.team_id
WHERE {WINDOW}
GROUP BY 1 ORDER BY 1
"""

RACE_CAGG = f"""
SELECT t.name AS team, round(sum(e.cost_estimate_cents)::numeric / 100, 2) AS dollars, sum(e.events) AS rows_scanned
FROM usage_1d e JOIN api_keys k ON k.id = e.api_key_id JOIN teams t ON t.id = k.team_id
WHERE {WINDOW.replace('e.ts', 'e.bucket')}
GROUP BY 1 ORDER BY 1
"""


async def _rows(conn: AsyncConnection, sql: str, params: Any = None) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        return [jsonable(r) for r in await cur.fetchall()]


async def stats(conn: AsyncConnection) -> dict[str, Any]:
    out: dict[str, Any] = {}
    r = await _rows(conn, """
      SELECT approximate_row_count('usage_events') AS usage_rows,
             (SELECT count(*) FROM timescaledb_information.chunks WHERE hypertable_name = 'usage_events') AS chunks,
             (SELECT count(*) FROM timescaledb_information.chunks WHERE hypertable_name = 'usage_events'
                AND is_compressed) AS compressed_chunks,
             (SELECT ingest_eps FROM sim_state) AS ingest_eps,
             (SELECT paused FROM sim_state) AS paused,
             (SELECT min(ts) FROM usage_events) AS oldest, sim_now() AS sim_now""")
    out.update(r[0])
    comp = []
    for name in ("usage_events", "usage_1m", "usage_1h", "usage_1d"):
        rel = name
        if name != "usage_events":
            m = await _rows(conn, """SELECT format('%%I.%%I', materialization_hypertable_schema,
                                       materialization_hypertable_name) AS mat
                                     FROM timescaledb_information.continuous_aggregates WHERE view_name = %s""", (name,))
            rel = m[0]["mat"]
        s = await _rows(conn, f"""SELECT before_compression_total_bytes AS before, after_compression_total_bytes AS after,
                                         number_compressed_chunks, total_chunks
                                  FROM hypertable_columnstore_stats('{rel}')""")
        size = await _rows(conn, f"SELECT hypertable_size('{rel}') AS bytes")
        row = {"name": name, **(s[0] if s else {}), "total_bytes": size[0]["bytes"]}
        if row.get("before"):
            row["ratio_pct"] = round(100 * (1 - row["after"] / row["before"]), 1)
            row["x"] = round(row["before"] / row["after"], 1)
        comp.append(row)
    out["columnstore"] = comp
    out["caggs"] = await _rows(conn, """
      SELECT ca.view_name, ca.materialized_only,
             _timescaledb_functions.to_timestamp(_timescaledb_functions.cagg_watermark(h.id)) AS watermark,
             js.last_successful_finish AS last_refresh, j.schedule_interval::text AS every,
             j.config->>'start_offset' AS start_offset, j.config->>'end_offset' AS end_offset
      FROM timescaledb_information.continuous_aggregates ca
      JOIN _timescaledb_catalog.hypertable h ON h.table_name = ca.materialization_hypertable_name
      LEFT JOIN timescaledb_information.jobs j ON j.hypertable_name = ca.view_name
           AND j.proc_name = 'policy_refresh_continuous_aggregate'
      LEFT JOIN timescaledb_information.job_stats js ON js.job_id = j.job_id
      ORDER BY ca.view_name""")
    out["jobs"] = await _rows(conn, """
      SELECT j.job_id, j.proc_name, coalesce(j.hypertable_name, '') AS target, j.schedule_interval::text AS every,
             js.last_run_status, js.last_successful_finish, js.total_runs, js.total_failures,
             round(extract(epoch FROM js.last_run_duration) * 1000)::int AS last_ms
      FROM timescaledb_information.jobs j LEFT JOIN timescaledb_information.job_stats js USING (job_id)
      WHERE j.job_id >= 1000 ORDER BY j.job_id""")
    out["anomaly_latency"] = await _rows(conn, """
      SELECT id, title, spike_started_at, opened_at, detection_latency_ms FROM obligation_cases
      WHERE type = 'anomaly' ORDER BY id DESC LIMIT 5""")
    return out


async def _explain_ms(conn: AsyncConnection, sql: str) -> tuple[float, dict]:
    rows = await (await conn.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql)).fetchone()
    plan = rows[0] if isinstance(rows[0], list) else json.loads(rows[0])
    return float(plan[0]["Execution Time"]), plan[0]


def _plan_summary(plan: dict) -> dict[str, Any]:
    nodes: list[str] = []

    def walk(n):
        rel = n.get("Relation Name", "")
        if n["Node Type"] in ("Custom Scan", "Seq Scan", "Index Scan", "Index Only Scan", "Bitmap Heap Scan") and rel:
            nodes.append(rel)
        elif n["Node Type"] == "Custom Scan":
            nodes.append(n.get("Custom Plan Provider", "custom"))
        for c in n.get("Plans", []):
            walk(c)
    walk(plan["Plan"])
    return {"relations_touched": len(nodes), "sample": sorted(set(nodes))[:6],
            "shared_hit_blocks": plan["Plan"].get("Shared Hit Blocks"),
            "shared_read_blocks": plan["Plan"].get("Shared Read Blocks")}


async def race(conn: AsyncConnection, runs: int = 3) -> dict[str, Any]:
    """Same 30-day spend-by-team question on raw hypertable vs usage_1d cagg."""
    out = {}
    for name, sql in (("raw", RACE_RAW), ("cagg", RACE_CAGG)):
        times, plan = [], {}
        for _ in range(runs):
            ms, plan = await _explain_ms(conn, sql)
            times.append(ms)
        result = await _rows(conn, sql)
        out[name] = {"ms": round(statistics.median(times), 2), "all_ms": [round(t, 2) for t in times],
                     "sql": sql.strip(), "result": result, "plan": _plan_summary(plan)}
    raw_tot = sum(r["dollars"] for r in out["raw"]["result"])
    cagg_tot = sum(r["dollars"] for r in out["cagg"]["result"])
    out["speedup"] = round(out["raw"]["ms"] / max(out["cagg"]["ms"], 0.01), 1)
    out["totals_match"] = abs(raw_tot - cagg_tot) < 0.05
    out["raw_total"], out["cagg_total"] = raw_tot, cagg_tot
    return out


async def freshness_probe(conn: AsyncConnection) -> dict[str, Any]:
    """Insert one event at sim_now and time how long until usage_1m (real-time cagg) shows it."""
    marker = f"probe-{int(time.time() * 1000)}"
    t0 = time.perf_counter()
    await conn.execute(
        "INSERT INTO usage_events (ts, api_key_id, provider, model, requests, cost_estimate_cents)"
        " SELECT sim_now(), min(id), 'probe', %s, 1, 0 FROM api_keys", (marker,))
    await conn.commit()
    t_insert = time.perf_counter()
    visible_ms = None
    for _ in range(200):
        r = await (await conn.execute(
            "SELECT count(*) FROM usage_1m WHERE model = %s AND bucket >= time_bucket('1 minute', sim_now()) - interval '1 minute'",
            (marker,))).fetchone()
        if r[0]:
            visible_ms = (time.perf_counter() - t_insert) * 1000
            break
        await asyncio.sleep(0.05)
    await conn.execute("DELETE FROM usage_events WHERE provider = 'probe' AND model = %s", (marker,))
    await conn.commit()
    return {"insert_ms": round((t_insert - t0) * 1000, 2),
            "visible_after_ms": round(visible_ms, 2) if visible_ms is not None else None,
            "via": "real-time aggregation (materialized_only = false): un-materialized rows above the watermark "
                   "are unioned in at query time"}
