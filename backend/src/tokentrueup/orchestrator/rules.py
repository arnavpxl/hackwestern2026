"""Learned rules -> explicit estimator parameters. Deterministic; no LLM involvement."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from ..estimators.usage import UsageParams, contract_params


def apply_rule(p: UsageParams, rule: dict[str, Any]) -> UsageParams:
    kind, params = rule["kind"], rule["params"]
    if kind == "cached_discount":
        p.cached_discount_pct = float(params["pct"])
    elif kind == "late_data_buffer":
        p.uplift_pct = float(params["pct"])
    elif kind == "include_orphan_keys":
        p.include_orphans = True
    # rate_effective_dating is a data fix (backdated price_changes row), not a parameter.
    if rule.get("id") is not None:
        p.applied_rules.append(rule["id"])
    return p


async def active_rules(conn: AsyncConnection, provider: str) -> list[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, kind, params FROM learned_rules WHERE status = 'active' AND provider_id = %s ORDER BY id",
            (provider,),
        )
        return await cur.fetchall()


async def params_for(
    conn: AsyncConnection,
    provider: str,
    at: datetime,
    *,
    extra_rules: list[dict] | None = None,
    exclude_rule_ids: set[int] | None = None,
    use_active: bool = True,
) -> UsageParams:
    p = await contract_params(conn, provider, at)
    rules = await active_rules(conn, provider) if use_active else []
    for r in rules:
        if exclude_rule_ids and r["id"] in exclude_rule_ids:
            continue
        apply_rule(p, r)
    for r in extra_rules or []:
        apply_rule(p, r)
    return p
