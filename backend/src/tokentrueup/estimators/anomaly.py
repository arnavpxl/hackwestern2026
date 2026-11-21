"""Anomaly obligations: spend above the trailing-14-day baseline during the spike window.

Runaway usage is still real usage the provider will bill, so it is already inside the
usage estimate; this estimator quantifies the EXCESS so the owner/controller can decide
to accrue it, or exclude it if a provider credit is confirmed.
"""

from datetime import datetime

from psycopg import AsyncConnection

from .base import Estimate, run_query

ANOMALY_SQL = """
WITH spike AS (
  SELECT u.bucket, u.input_tokens, u.output_tokens, u.cached_tokens, u.requests, u.gpu_seconds, r.*
  FROM usage_1m u
  CROSS JOIN LATERAL rate_at(u.provider, u.model, u.bucket) r
  WHERE u.api_key_id = %(api_key_id)s AND u.model = %(model)s
    AND u.bucket >= time_bucket('1 minute', %(window_start)s::timestamptz)
    AND u.bucket <  %(window_end)s::timestamptz
),
cost AS (
  SELECT count(*) AS minutes,
         sum(input_tokens * input_rate / 1e6 + output_tokens * output_rate / 1e6
             + cached_tokens * cached_rate / 1e6 + requests * request_rate / 1e3
             + gpu_seconds * gpu_rate / 3600) AS spike_cents
  FROM spike
),
base AS (
  SELECT mean_cents, stddev_cents FROM baseline_as_of(%(window_start)s::timestamptz)
  WHERE api_key_id = %(api_key_id)s AND model = %(model)s
)
SELECT c.minutes::int AS minutes,
       round(c.spike_cents)::bigint AS spike_cents,
       round(b.mean_cents)::bigint AS baseline_hourly_cents,
       round(b.mean_cents * c.minutes / 60.0)::bigint AS expected_cents,
       GREATEST(0, round(c.spike_cents - b.mean_cents * c.minutes / 60.0))::bigint AS excess_cents
FROM cost c CROSS JOIN base b
"""


async def estimate_anomaly(
    conn: AsyncConnection, provider: str, api_key_id: int, model: str, window_start: datetime, window_end: datetime
) -> Estimate:
    q = await run_query(
        conn,
        ANOMALY_SQL,
        {"api_key_id": api_key_id, "model": model, "window_start": window_start, "window_end": window_end},
    )
    row = q.rows[0] if q.rows else {"excess_cents": 0}
    excess = int(row.get("excess_cents") or 0)
    return Estimate(
        kind="anomaly",
        provider_id=provider,
        amount_cents=excess,
        confidence=0.8,
        summary=f"Excess over baseline during {row.get('minutes', 0)} min spike",
        lines=q.rows,
        queries=[q],
        flags=["open_anomaly"],
    )
