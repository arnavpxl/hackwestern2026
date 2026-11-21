"""Shared estimator plumbing. Every dollar figure is the output of a SQL statement that
is stored verbatim (text + params + result rows) so the UI can show and re-run it."""

from __future__ import annotations

import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from pydantic import BaseModel, Field


def jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [jsonable(x) for x in v]
    return v


class QueryRun(BaseModel):
    sql: str
    params: dict[str, Any]
    rows: list[dict[str, Any]]
    ms: float


class Estimate(BaseModel):
    kind: str
    provider_id: str
    amount_cents: int
    confidence: float = Field(ge=0, le=1)
    summary: str
    lines: list[dict[str, Any]] = []
    queries: list[QueryRun] = []
    flags: list[str] = []  # e.g. 'orphan_key_excluded', 'open_anomaly'

    def facts(self) -> set[float]:
        """Every number the verifier will accept in an explanation of this estimate."""
        out: set[float] = {float(self.amount_cents), self.amount_cents / 100}
        for q in self.queries:
            for r in q.rows:
                for v in r.values():
                    if isinstance(v, int | float) and not isinstance(v, bool):
                        out.add(float(v))
                        out.add(float(v) / 100)
        for line in self.lines:
            for v in line.values():
                if isinstance(v, int | float) and not isinstance(v, bool):
                    out.add(float(v))
                    out.add(float(v) / 100)
        return out


async def run_query(conn: AsyncConnection, sql: str, params: dict[str, Any]) -> QueryRun:
    t = time.perf_counter()
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        rows = await cur.fetchall()
    return QueryRun(
        sql=sql.strip(), params=jsonable(params), rows=[jsonable(r) for r in rows], ms=(time.perf_counter() - t) * 1000
    )
