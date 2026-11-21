# Benchmarks

Measured 2026-11-21T06:38:56+00:00 by `ttu-bench` (`backend/src/tokentrueup/bench/run_benchmarks.py`) against TimescaleDB 2.32.1 on PostgreSQL 17.12 at `localhost:5433` (client: macOS-26.6.2-arm64-arm-64bit). All data is synthetic. The live event generator was running during the run.

| What | Result |
|---|---|
| Raw usage events (hypertable, 1-day chunks) | 28,878,574 rows in 129 chunks (111 in columnstore) |
| Columnstore compression, `usage_events` | 3,668.9 MB to 343.3 MB (90.6% smaller, 10.7x) |
| 30-day spend by team, raw hypertable | 1786.98 ms (median of 5) |
| Same query on the `usage_1d` continuous aggregate | 1.77 ms (1009.6x faster; totals match: True) |
| New event visible in `usage_1m` (real-time aggregation) | 5.04 ms median (runs: [6.09, 5.04, 4.41, 4.74, 5.11]) |
| `scan_anomalies()` (detector run by the in-DB job every 5 s) | 24.22 ms median |
| Bulk COPY into the hypertable | 264,712 rows/s (344,195 rows, rolled back) |
| Re-accrue every invoiced provider-month from the caggs (rule replay) | 18 provider-months in 360.1 ms |
| Runaway key: first spike event to case opened (in-DB job) | 8,104 ms (key `plat-gateway-prod`; wall clock from trigger: 8,184 ms) |

## Columnstore by table

| Table | Before | After | Smaller | Chunks compressed |
|---|---|---|---|---|
| `usage_events` | 3,668.9 MB | 343.3 MB | 90.6% | 111/129 |
| `usage_1m` | 584.8 MB | 48.6 MB | 91.7% | 11/14 |
| `usage_1h` | 11.1 MB | 2.0 MB | 81.7% | 11/14 |
| `usage_1d` | 1.2 MB | 0.7 MB | 37.9% | 10/14 |

## Background jobs

| Job | Target | Every | Last run | Runs | Failures |
|---|---|---|---|---|---|
| policy_compression | price_changes | 1 day | None (None ms) | 0 | 0 |
| policy_compression | usage_events | 12:00:00 | Success (19 ms) | 1 | 0 |
| policy_retention | usage_events | 1 day | Success (9 ms) | 1 | 0 |
| policy_compression | usage_1m | 12:00:00 | Success (10 ms) | 1 | 0 |
| policy_retention | usage_1m | 1 day | Success (7 ms) | 1 | 0 |
| policy_refresh_continuous_aggregate | usage_1h | 00:05:00 | Success (21 ms) | 22 | 0 |
| policy_compression | usage_1h | 12:00:00 | Success (6 ms) | 1 | 0 |
| policy_refresh_continuous_aggregate | usage_1d | 01:00:00 | Success (8 ms) | 3 | 0 |
| policy_compression | usage_1d | 12:00:00 | Success (21 ms) | 1 | 0 |
| policy_compression | accrual_snapshots | 12:00:00 | Success (19 ms) | 1 | 0 |
| detect_anomalies | - | 00:00:05 | Success (151 ms) | 635 | 0 |
| policy_refresh_continuous_aggregate | spend_baseline | 01:00:00 | Success (15 ms) | 3 | 0 |
| policy_refresh_continuous_aggregate | usage_1m | 00:00:10 | Success (7 ms) | 332 | 0 |

## The query race

Raw hypertable:

```sql
SELECT t.name AS team, round(sum(e.cost_estimate_cents)::numeric / 100, 2) AS dollars, count(*) AS rows_scanned
FROM usage_events e JOIN api_keys k ON k.id = e.api_key_id JOIN teams t ON t.id = k.team_id
WHERE e.ts >= time_bucket('1 day', sim_now()) - interval '30 days' AND e.ts < time_bucket('1 day', sim_now())
GROUP BY 1 ORDER BY 1
```

Continuous aggregate:

```sql
SELECT t.name AS team, round(sum(e.cost_estimate_cents)::numeric / 100, 2) AS dollars, sum(e.events) AS rows_scanned
FROM usage_1d e JOIN api_keys k ON k.id = e.api_key_id JOIN teams t ON t.id = k.team_id
WHERE e.bucket >= time_bucket('1 day', sim_now()) - interval '30 days' AND e.bucket < time_bucket('1 day', sim_now())
GROUP BY 1 ORDER BY 1
```

Each is timed with `EXPLAIN (ANALYZE, BUFFERS)`. Both return the same per-team totals ($397,340.84 vs $397,340.84).
