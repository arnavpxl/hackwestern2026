"""Backfill ~3 months of synthetic usage_events (default 20M rows).

Per day: generate events with numpy, binary COPY into the day's chunk, then convert
that chunk to the columnstore immediately so peak storage stays small (matters on
the Tiger Cloud free tier). Afterwards refresh the cagg hierarchy bottom-up.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import numpy as np
import psycopg

from ..config import settings
from .catalog import KEYS
from .profiles import backfill_start, build_events, lognormal_split, rate_tables, units_per_hour

COPY_SQL = (
    "COPY usage_events (ts, api_key_id, provider, model, input_tokens, output_tokens, cached_tokens,"
    " requests, gpu_seconds, cost_estimate_cents) FROM STDIN (FORMAT BINARY)"
)
COPY_TYPES = ["timestamptz", "int4", "text", "text", "int8", "int8", "int8", "int4", "float8", "float8"]

# Relative event density per key (keeps row counts realistic: chatty keys emit more).
EVENT_WEIGHT = np.array([3.0, 1.0, 2.0, 2.5, 1.5, 1.0, 0.8, 1.5, 0.6, 0.4, 1.2, 1.5, 0.7, 2.0, 0.6])


def key_ids(conn: psycopg.Connection) -> list[int]:
    by_label = dict(conn.execute("SELECT label, id FROM api_keys").fetchall())
    return [by_label[k.label] for k in KEYS]


def gen_window(
    t0: float, t1: float, n_events: int, ids: list[int], origin: float, tables: dict, rng: np.random.Generator,
    multipliers: dict[int, float] | None = None,
) -> list[dict]:
    """Events over [t0, t1): per key, event times are drawn proportionally to the
    profile so per-hour spend follows units_per_hour regardless of event count."""
    out = []
    weights = EVENT_WEIGHT / EVENT_WEIGHT.sum()
    grid = np.arange(t0, t1, 300.0)  # 5-minute grid for density sampling
    if len(grid) == 0:
        return out
    for i, spec in enumerate(KEYS):
        n = max(1, int(round(n_events * weights[i])))
        dens = units_per_hour(spec, grid + 150, origin)
        p = dens / dens.sum()
        cells = rng.choice(len(grid), size=n, p=p)
        ts = grid[cells] + rng.uniform(0, 300, size=n)
        ts = ts[ts < t1]
        if len(ts) == 0:
            continue
        total_units = float((dens * (min(300.0, t1 - t0) / 3600)).sum())
        mult = (multipliers or {}).get(i, 1.0)
        units = lognormal_split(np.full(len(ts), total_units / len(ts)), rng) * mult
        out.append(build_events(i, ids[i], ts, units, tables, rng))
    return out


def copy_events(conn: psycopg.Connection, batches: list[dict]) -> int:
    rows = 0
    with conn.cursor() as cur, cur.copy(COPY_SQL) as cp:
        cp.set_types(COPY_TYPES)
        for b in batches:
            models = b["models"]
            ts = [datetime.fromtimestamp(x, UTC) for x in b["epoch"].tolist()]
            for t, mi, inp, out, cached, req, gpu, cost in zip(
                ts, b["model_idx"].tolist(), b["input_tokens"].tolist(), b["output_tokens"].tolist(),
                b["cached_tokens"].tolist(), b["requests"].tolist(), b["gpu_seconds"].tolist(),
                b["cost"].tolist(), strict=True,
            ):
                cp.write_row((t, int(b["api_key_id"][0]), b["provider"], models[mi], inp, out, cached, req, gpu, cost))
            rows += len(ts)
    return rows


def load_day(day_start: datetime, end: datetime, per_day: int, ids, origin, tables, seed: int) -> int:
    rng = np.random.default_rng(seed)
    t0 = day_start.timestamp()
    t1 = min(end.timestamp(), t0 + 86400)
    n = int(per_day * (t1 - t0) / 86400)
    batches = gen_window(t0, t1, n, ids, origin, tables, rng)
    with psycopg.connect(settings.database_url) as conn:
        rows = copy_events(conn, batches)
        conn.commit()
        if t1 < (end - timedelta(days=1)).timestamp():
            # Convert this day's chunk to columnstore right away.
            for (chunk,) in conn.execute(
                """SELECT format('%%I.%%I', chunk_schema, chunk_name) FROM timescaledb_information.chunks
                   WHERE hypertable_name = 'usage_events' AND range_start >= %s AND range_end <= %s""",
                (day_start, day_start + timedelta(days=1)),
            ).fetchall():
                conn.execute("CALL convert_to_columnstore(%s, if_not_columnstore => true)", (chunk,))
            conn.commit()
    return rows


def refresh_all(conn: psycopg.Connection, start: datetime, end: datetime) -> dict[str, float]:
    timings = {}
    conn.autocommit = True
    for view in ("usage_1m", "usage_1h", "usage_1d", "spend_baseline"):
        t = time.perf_counter()
        conn.execute("CALL refresh_continuous_aggregate(%s, %s, %s)", (view, start, end))
        timings[view] = time.perf_counter() - t
        print(f"  refreshed {view} in {timings[view]:.1f}s")
    return timings


def run(rows: int, workers: int = 4, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    start = backfill_start(now)
    days = []
    d = start
    while d < now:
        days.append(d)
        d += timedelta(days=1)
    per_day = rows / ((now - start).total_seconds() / 86400)
    tables = rate_tables(start)
    with psycopg.connect(settings.database_url) as conn:
        ids = key_ids(conn)
    origin = start.timestamp()
    t = time.perf_counter()
    total = 0
    with ThreadPoolExecutor(workers) as pool:
        futs = [pool.submit(load_day, day, now, per_day, ids, origin, tables, 1000 + i) for i, day in enumerate(days)]
        for i, f in enumerate(futs):
            total += f.result()
            if i % 10 == 0 or i == len(futs) - 1:
                el = time.perf_counter() - t
                print(f"  day {i + 1}/{len(days)}  rows={total:,}  {total / el:,.0f} rows/s")
    load_s = time.perf_counter() - t
    with psycopg.connect(settings.database_url) as conn:
        refresh = refresh_all(conn, start, now)
    invoices = asyncio.run(_history(now))
    print(f"  generated {invoices} historical AP invoices")
    return {"rows": total, "load_seconds": load_s, "rows_per_sec": total / load_s, "refresh_seconds": refresh}


async def _history(now: datetime) -> int:
    from .invoices import generate_history

    async with await psycopg.AsyncConnection.connect(settings.database_url) as conn:
        await conn.execute("DELETE FROM ap_invoices")
        return await generate_history(conn, now)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=settings.backfill_rows)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    stats = run(args.rows, args.workers)
    print(stats)
