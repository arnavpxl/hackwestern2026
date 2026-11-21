"""Every estimator against hand-computed expectations."""

from datetime import timedelta

from psycopg.types.json import Jsonb

from tokentrueup.estimators.anomaly import estimate_anomaly
from tokentrueup.estimators.fixed import estimate_fixed
from tokentrueup.estimators.one_time import estimate_one_time
from tokentrueup.estimators.usage import UsageParams, estimate_usage

from .conftest import hour, insert_event, key_id, refresh

# nimbus-pro list rates (cents / 1M): input 300, output 1500, cached 30
M = 1_000_000


async def _three_hours(conn, start, label="plat-gateway-prod"):
    for h in (1, 2, 3):
        await insert_event(conn, hour(start, 1, h), label, "nimbus-llm", "nimbus-pro", inp=800 * M)
    await refresh(conn, start, start + timedelta(days=3))


async def test_usage_list_price(conn, period):
    start, end = period
    await _three_hours(conn, start)
    est = await estimate_usage(conn, "nimbus-llm", start, end, end, UsageParams())
    assert est.amount_cents == 3 * 800 * 300  # 720,000 cents
    assert est.queries[0].rows[0]["projected_cents"] == 0


async def test_usage_volume_tier_crossing(conn, period):
    start, end = period
    await _three_hours(conn, start)
    p = UsageParams(tiers=[{"from_tokens": 0, "discount_pct": 0}, {"from_tokens": 1e9, "discount_pct": 10}])
    est = await estimate_usage(conn, "nimbus-llm", start, end, end, p)
    # hour 1: cum 0, hour 2: cum 800M (<1B) -> list; hour 3: cum 1.6B -> 10% off
    assert est.amount_cents == 240_000 + 240_000 + 216_000


async def test_usage_mid_month_price_change(conn, period):
    start, end = period
    await conn.execute(
        """INSERT INTO price_changes (ts, provider, model, input_rate, output_rate, cached_rate)
           VALUES (%s, 'nimbus-llm', 'nimbus-pro', 600, 1500, 30)""", (hour(start, 1, 3),))
    await _three_hours(conn, start)
    est = await estimate_usage(conn, "nimbus-llm", start, end, end, UsageParams())
    assert est.amount_cents == 240_000 * 2 + 800 * 600  # rate in effect at each hour


async def test_usage_batch_and_cached_discounts(conn, period):
    start, end = period
    await insert_event(conn, hour(start, 1, 1), "research-batch-labeling", "nimbus-llm", "nimbus-pro", inp=100 * M)
    await insert_event(conn, hour(start, 1, 1), "plat-gateway-prod", "nimbus-llm", "nimbus-pro", cached=100 * M)
    await refresh(conn, start, start + timedelta(days=2))
    base = await estimate_usage(conn, "nimbus-llm", start, end, end, UsageParams())
    assert base.amount_cents == 30_000 + 3_000
    disc = await estimate_usage(conn, "nimbus-llm", start, end, end,
                                UsageParams(batch_discount_pct=50, cached_discount_pct=50))
    assert disc.amount_cents == 15_000 + 1_500


async def test_usage_orphan_key_excluded_and_flagged(conn, period):
    start, end = period
    await insert_event(conn, hour(start, 1, 1), "growth-scraper-legacy", "quillsearch", "quill-rerank", requests=10_000)
    await insert_event(conn, hour(start, 1, 1), "growth-search", "quillsearch", "quill-rerank", requests=20_000)
    await refresh(conn, start, start + timedelta(days=2))
    est = await estimate_usage(conn, "quillsearch", start, end, end, UsageParams())
    assert est.amount_cents == 2_000  # 20k requests x 100 cents / 1k
    assert "orphan_key_excluded" in est.flags
    incl = await estimate_usage(conn, "quillsearch", start, end, end, UsageParams(include_orphans=True))
    assert incl.amount_cents == 3_000 and not incl.flags


async def test_usage_projection_and_uplift(conn, period):
    start, end = period
    # 24 hours x 1,000 cents/hour on day 1 -> trailing mean over hours with data = 1,000/h
    for h in range(24):
        await insert_event(conn, hour(start, 1, h), "plat-vision-ocr", "stratus-cloud", "vision-api", requests=6_667)
    await refresh(conn, start, start + timedelta(days=3))
    as_of = start + timedelta(days=2)
    est = await estimate_usage(conn, "stratus-cloud", start, end, as_of, UsageParams())
    line = est.queries[0].rows[0]
    remaining = (end - as_of).total_seconds() / 3600
    assert line["mtd_cents"] == round(24 * 6_667 * 150 / 1000)
    assert abs(line["projected_cents"] - round(6_667 * 150 / 1000 * remaining)) <= 1
    up = await estimate_usage(conn, "stratus-cloud", start, end, as_of, UsageParams(uplift_pct=10))
    assert abs(up.amount_cents - round(est.amount_cents * 1.1)) <= 1


async def test_usage_exclude_window_removes_spike_from_projection(conn, period):
    start, end = period
    kid = await key_id(conn, "plat-vision-ocr")
    for h in range(24):
        await insert_event(conn, hour(start, 1, h), "plat-vision-ocr", "stratus-cloud", "vision-api",
                           requests=100_000 if h == 5 else 1_000)
    await refresh(conn, start, start + timedelta(days=3))
    as_of = start + timedelta(days=2)
    win = [{"api_key_id": kid, "start_ts": hour(start, 1, 5).isoformat(), "end_ts": hour(start, 1, 6).isoformat()}]
    with_spike = await estimate_usage(conn, "stratus-cloud", start, end, as_of, UsageParams())
    without = await estimate_usage(conn, "stratus-cloud", start, end, as_of, UsageParams(exclude_windows=win))
    assert with_spike.queries[0].rows[0]["mtd_cents"] == without.queries[0].rows[0]["mtd_cents"]  # still billed
    remaining = (end - as_of).total_seconds() / 3600
    assert abs(without.queries[0].rows[0]["projected_cents"] - round(150 * remaining)) <= 1


async def test_fixed_prorated(conn, period):
    start, end = period
    mid = start + timedelta(days=10)
    cur = await conn.execute(
        """INSERT INTO contracts (provider_id, name, kind, fixed_monthly_cents, effective_from, tiers)
           VALUES ('vectorhaus', 'Test seats', 'fixed', 300000, %s, %s) RETURNING id""",
        (mid.date(), Jsonb([])))
    cid = (await cur.fetchone())[0]
    est = await estimate_fixed(conn, "vectorhaus", cid, start, end)
    days = (end - start).days
    assert est.amount_cents == round(300_000 * (days - 10) / days)


async def test_one_time_po(conn, period):
    start, end = period
    cur = await conn.execute(
        """INSERT INTO purchase_orders (po_number, provider_id, team_id, kind, description, amount_cents, service_date)
           VALUES ('PO-T1', 'helio-gpu', 1, 'fine_tune', 'test job', 123456, %s) RETURNING id""",
        ((start + timedelta(days=5)).date(),))
    po = (await cur.fetchone())[0]
    assert (await estimate_one_time(conn, "helio-gpu", po, start, end, end)).amount_cents == 123_456
    # not yet delivered as of day 2 -> nothing to accrue
    assert (await estimate_one_time(conn, "helio-gpu", po, start, end, start + timedelta(days=2))).amount_cents == 0


async def _baseline_and_spike(conn, start):
    """14 days at 01:00 UTC with 100 cents/hour, then a 10-minute spike of 300 cents/minute."""
    spike_day = 15
    for d in range(1, spike_day):
        await insert_event(conn, hour(start, d, 1), "support-triage-agent", "nimbus-llm", "nimbus-pro",
                           inp=333_333, cost=100.0)
    spike = hour(start, spike_day, 1) + timedelta(minutes=20)
    for m in range(10):
        await insert_event(conn, spike + timedelta(minutes=m), "support-triage-agent", "nimbus-llm", "nimbus-pro",
                           inp=1 * M, cost=300.0)
    await refresh(conn, start, start + timedelta(days=spike_day + 1))
    return spike


async def test_anomaly_excess_over_baseline(conn, period):
    start, _ = period
    spike = await _baseline_and_spike(conn, start)
    kid = await key_id(conn, "support-triage-agent")
    est = await estimate_anomaly(conn, "nimbus-llm", kid, "nimbus-pro", spike, spike + timedelta(minutes=10))
    row = est.queries[0].rows[0]
    assert row["minutes"] == 10 and row["spike_cents"] == 3_000 and row["baseline_hourly_cents"] == 100
    assert est.amount_cents == round(3_000 - 100 * 10 / 60)


async def test_sql_detector_flags_spike(conn, period):
    start, _ = period
    spike = await _baseline_and_spike(conn, start)
    hits = await (await conn.execute(
        "SELECT api_key_id, projected_hourly_cents, threshold_cents FROM scan_anomalies(%s)",
        (spike + timedelta(minutes=9, seconds=30),))).fetchall()
    assert len(hits) == 1
    assert hits[0][0] == await key_id(conn, "support-triage-agent")
    assert hits[0][1] > hits[0][2]
    quiet = await (await conn.execute("SELECT count(*) FROM scan_anomalies(%s)",
                                      (spike - timedelta(minutes=5),))).fetchone()
    assert quiet[0] == 0
