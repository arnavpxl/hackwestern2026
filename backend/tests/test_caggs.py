"""Continuous aggregate correctness: cagg totals == raw totals, including late data."""

from datetime import timedelta

import numpy as np

from .conftest import hour, insert_event, key_id, refresh

COLS = "sum(input_tokens)::bigint, sum(output_tokens)::bigint, sum(requests)::bigint, round(sum(cost_estimate_cents)::numeric, 6)"


async def _raw(conn, a, b):
    return await (await conn.execute(f"SELECT {COLS} FROM usage_events WHERE ts >= %s AND ts < %s", (a, b))).fetchone()


async def _cagg(conn, view, a, b):
    return await (await conn.execute(f"SELECT {COLS} FROM {view} WHERE bucket >= %s AND bucket < %s", (a, b))).fetchone()


async def _materialized(conn, view, a, b):
    """Read the materialization only (real-time union off) to prove refresh did the work."""
    await conn.execute(f"ALTER MATERIALIZED VIEW {view} SET (timescaledb.materialized_only = true)")
    try:
        return await _cagg(conn, view, a, b)
    finally:
        await conn.execute(f"ALTER MATERIALIZED VIEW {view} SET (timescaledb.materialized_only = false)")


async def _load(conn, start, n=3000, days=3, seed=1):
    rng = np.random.default_rng(seed)
    kid = await key_id(conn, "plat-gateway-prod")
    rows = []
    for _ in range(n):
        ts = start + timedelta(seconds=float(rng.uniform(0, days * 86400)))
        rows.append((ts, kid, "nimbus-llm", "nimbus-pro", int(rng.integers(1, 5000)), int(rng.integers(1, 800)),
                     0, 1, 0.0, float(rng.uniform(0, 3))))
    async with conn.cursor() as cur, cur.copy(
        "COPY usage_events (ts, api_key_id, provider, model, input_tokens, output_tokens, cached_tokens, requests,"
        " gpu_seconds, cost_estimate_cents) FROM STDIN") as cp:
        for r in rows:
            await cp.write_row(r)


async def test_hierarchy_matches_raw(conn, period):
    start, _ = period
    await _load(conn, start)
    end = start + timedelta(days=3)
    await refresh(conn, start, end)
    raw = await _raw(conn, start, end)
    for view in ("usage_1m", "usage_1h", "usage_1d"):
        assert await _cagg(conn, view, start, end) == raw, view
        assert await _materialized(conn, view, start, end) == raw, f"{view} materialized"
    # per-day equality too (hierarchical rollups preserve every bucket)
    for d in range(3):
        a, b = start + timedelta(days=d), start + timedelta(days=d + 1)
        assert await _cagg(conn, "usage_1d", a, b) == await _raw(conn, a, b)


async def test_late_data_absorbed_by_refresh(conn, period):
    start, _ = period
    await _load(conn, start, n=1000, days=2, seed=2)
    end = start + timedelta(days=2)
    await refresh(conn, start, end)
    before = await _materialized(conn, "usage_1d", start, end)
    # late-arriving metering for an hour that is already materialized (below the watermark)
    late_ts = hour(start, 0, 5)
    for i in range(10):
        await insert_event(conn, late_ts + timedelta(minutes=i), "plat-gateway-prod", "nimbus-llm", "nimbus-pro",
                           inp=1000, out=100, cost=1.5)
    await conn.commit()
    stale = await _materialized(conn, "usage_1d", start, end)
    assert stale == before, "materialization unchanged until refresh"
    assert stale != await _raw(conn, start, end)
    await refresh(conn, start, end)  # what the 7-day refresh policy does automatically
    for view in ("usage_1m", "usage_1h", "usage_1d"):
        assert await _materialized(conn, view, start, end) == await _raw(conn, start, end), view


async def test_realtime_aggregation_sees_unmaterialized(conn, period):
    start, _ = period
    await _load(conn, start, n=200, days=1, seed=3)
    await refresh(conn, start, start + timedelta(days=1))
    # brand-new rows above the watermark appear without any refresh
    t = start + timedelta(days=1, hours=2)
    await insert_event(conn, t, "plat-gateway-prod", "nimbus-llm", "nimbus-pro", inp=7777, cost=0.5)
    await conn.commit()
    row = await (await conn.execute(
        "SELECT sum(input_tokens) FROM usage_1m WHERE bucket = time_bucket('1 minute', %s::timestamptz)", (t,))
    ).fetchone()
    assert row[0] == 7777
