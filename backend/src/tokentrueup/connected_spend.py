"""Estimated spend analytics for provider data owned by one signed-in user.

This module never reads simulator tables. Provider APIs report tokens rather than invoice totals,
so amounts are explicitly estimates based on the effective public list price catalog.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

USAGE_SQL = """
SELECT u.connection_id, u.bucket, u.model, u.workspace_id, u.provider_key_id,
       u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens,
       c.provider_id, p.name AS provider_name, c.label AS connection_label,
       k.id AS api_key_id, t.name AS team, o.name AS owner,
       price.input_per_million, price.output_per_million,
       price.cache_read_per_million, price.cache_write_per_million
FROM provider_usage_hourly u
JOIN connections c ON c.id = u.connection_id
JOIN providers p ON p.id = c.provider_id
LEFT JOIN key_mappings m ON m.connection_id = u.connection_id
  AND m.provider_key_id = u.provider_key_id AND m.workspace_id = u.workspace_id
LEFT JOIN api_keys k ON k.id = m.api_key_id
LEFT JOIN teams t ON t.id = k.team_id
LEFT JOIN owners o ON o.id = k.owner_id
LEFT JOIN LATERAL (
  SELECT input_per_million, output_per_million, cache_read_per_million, cache_write_per_million
  FROM provider_model_prices mp
  WHERE mp.provider_id = c.provider_id AND u.model LIKE mp.model_pattern
    AND mp.effective_from <= u.bucket::date
    AND (mp.effective_to IS NULL OR u.bucket::date < mp.effective_to)
  ORDER BY mp.priority DESC, length(mp.model_pattern) DESC, mp.effective_from DESC
  LIMIT 1
) price ON true
WHERE c.created_by = %(user_id)s AND u.bucket >= %(start)s AND u.bucket < %(end)s
ORDER BY u.bucket
"""


def _money(row: dict[str, Any]) -> Decimal | None:
    if row["input_per_million"] is None:
        return None
    return (
        Decimal(row["input_tokens"]) * row["input_per_million"]
        + Decimal(row["output_tokens"]) * row["output_per_million"]
        + Decimal(row["cache_read_tokens"]) * row["cache_read_per_million"]
        + Decimal(row["cache_write_tokens"]) * row["cache_write_per_million"]
    ) / Decimal(1_000_000)


def _rounded(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.0001")))


def _identity(row: dict[str, Any]) -> str:
    if row["api_key_id"] is not None:
        return f"key:{row['api_key_id']}"
    # Stable enough for React row identity without returning the provider's key/workspace identifiers.
    raw = f"{row['connection_id']}\0{row['workspace_id']}\0{row['provider_key_id']}".encode()
    return f"unmapped:{hashlib.sha256(raw).hexdigest()[:12]}"


async def dashboard(
    conn: AsyncConnection, user_id: int, *, hours: int = 168, now: datetime | None = None
) -> dict[str, Any]:
    """Return chart-ready connected analytics. All connection access is user-scoped."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    hours = min(max(hours, 24), 24 * 31)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    chart_start = now - timedelta(hours=hours)
    query_start = min(month_start, chart_start, now - timedelta(hours=24))

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """SELECT c.id, c.label, c.provider_id, p.name AS provider_name, c.status,
                      c.last_sync_at, c.last_error
               FROM connections c JOIN providers p ON p.id = c.provider_id
               WHERE c.created_by = %s ORDER BY c.id""",
            (user_id,),
        )
        connections = await cur.fetchall()
        await cur.execute(USAGE_SQL, {"user_id": user_id, "start": query_start, "end": now})
        usage = await cur.fetchall()

    hourly: dict[tuple[datetime, str], Decimal] = defaultdict(Decimal)
    daily: dict[tuple[Any, str], Decimal] = defaultdict(Decimal)
    keys: dict[str, dict[str, Any]] = {}
    unpriced: dict[tuple[str, str], int] = defaultdict(int)
    priced_tokens = 0
    total_tokens = 0
    priced_mtd = Decimal(0)
    priced_24h = Decimal(0)
    latest_bucket: datetime | None = None

    for row in usage:
        tokens = sum(
            int(row[name])
            for name in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
        )
        total_tokens += tokens
        team = row["team"] or "Unmapped"
        bucket = row["bucket"].astimezone(UTC)
        identity = _identity(row)
        item = keys.setdefault(
            identity,
            {
                "id": identity,
                "provider": row["provider_name"],
                "team": team,
                "owner": row["owner"],
                "mtd": Decimal(0),
                "last_24h": Decimal(0),
                "latest": Decimal(0),
                "mapped": row["api_key_id"] is not None,
            },
        )
        cost = _money(row)
        if cost is None:
            unpriced[(row["provider_name"], row["model"])] += tokens
            continue
        priced_tokens += tokens
        if bucket >= chart_start:
            hourly[(bucket, team)] += cost
        if bucket >= month_start:
            daily[(bucket.date(), team)] += cost
            priced_mtd += cost
        if bucket >= now - timedelta(hours=24):
            priced_24h += cost
        latest_bucket = max(latest_bucket, bucket) if latest_bucket else bucket

        if bucket >= month_start:
            item["mtd"] += cost
        if bucket >= now - timedelta(hours=24):
            item["last_24h"] += cost

    if latest_bucket is not None:
        for row in usage:
            if row["bucket"].astimezone(UTC) != latest_bucket:
                continue
            cost = _money(row)
            if cost is None:
                continue
            identity = _identity(row)
            keys[identity]["latest"] += cost

    avg_hourly = priced_24h / Decimal(24)
    period_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    remaining_hours = Decimal(str(max((period_end - now).total_seconds() / 3600, 0)))
    projected = priced_mtd + avg_hourly * remaining_hours
    key_rows = []
    for item in keys.values():
        key_avg = item.pop("last_24h") / Decimal(24)
        latest = item.pop("latest")
        key_rows.append(
            {
                **item,
                "mtd": _rounded(item["mtd"]),
                "avg_hourly_24h": _rounded(key_avg),
                "current_hour": _rounded(latest),
                "projected": _rounded(item["mtd"] + key_avg * remaining_hours),
            }
        )
    key_rows.sort(key=lambda item: item["mtd"], reverse=True)

    return {
        "generated_at": now,
        "period_start": month_start,
        "period_end": period_end,
        "resolution": "hour",
        "hours": hours,
        "summary": {
            "mtd": _rounded(priced_mtd),
            "projected": _rounded(projected),
            "burn_rate_hourly": _rounded(avg_hourly),
        },
        "series": [
            {"bucket": bucket, "team": team, "dollars": _rounded(cost)}
            for (bucket, team), cost in sorted(hourly.items())
        ],
        "daily": [
            {"day": day, "team": team, "dollars": _rounded(cost)}
            for (day, team), cost in sorted(daily.items())
        ],
        "keys": key_rows,
        "connections": connections,
        "quality": {
            "estimated": True,
            "priced_token_percent": round(priced_tokens / total_tokens * 100, 1) if total_tokens else None,
            "unpriced_models": [
                {"provider": provider, "model": model, "tokens": tokens}
                for (provider, model), tokens in sorted(unpriced.items())
            ],
            "unmapped_key_count": sum(1 for item in key_rows if not item["mapped"]),
            "first_bucket": usage[0]["bucket"] if usage else None,
            "last_bucket": usage[-1]["bucket"] if usage else None,
        },
    }
