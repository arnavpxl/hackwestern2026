"""Sync runner: pulls new complete hours for one connection and records each run.

- Only complete hours are fetched, and each run re-reads the last OVERLAP hours so usage the
  provider reports late is picked up. Rows are upserted, so re-reading never double counts.
- Each run is all-or-nothing: a failure rolls back its rows and is recorded with a readable error.
- The key is decrypted here only, for the duration of the fetch, and is never logged or stored.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from .. import vault
from . import anthropic, openai
from .common import ProviderError

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

log = logging.getLogger("tokentrueup.ingest")

BACKFILL = timedelta(days=14)  # first sync reaches back this far (matches the anomaly baseline window)
OVERLAP = timedelta(hours=6)  # re-read recent hours so late usage is picked up
SCHEDULE_EVERY = 300  # seconds between scheduler passes
STALE_AFTER = timedelta(hours=1)  # a connection synced within this window is not due

FetchFn = Callable[..., Awaitable[Any]]  # (key, start, end) -> async iterator of rows
PROVIDERS: dict[str, Callable[..., Any]] = {"anthropic": anthropic.fetch_usage, "openai": openai.fetch_usage}
_locks: dict[int, asyncio.Lock] = {}

UPSERT = """
INSERT INTO provider_usage_hourly (connection_id, bucket, model, workspace_id, provider_key_id,
    input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, synced_at)
VALUES (%(connection_id)s, %(bucket)s, %(model)s, %(workspace_id)s, %(provider_key_id)s,
    %(input_tokens)s, %(output_tokens)s, %(cache_read_tokens)s, %(cache_write_tokens)s, now())
ON CONFLICT (connection_id, bucket, model, workspace_id, provider_key_id) DO UPDATE SET
    input_tokens = EXCLUDED.input_tokens, output_tokens = EXCLUDED.output_tokens,
    cache_read_tokens = EXCLUDED.cache_read_tokens, cache_write_tokens = EXCLUDED.cache_write_tokens,
    synced_at = now()
"""


async def sync_connection(
    conn: AsyncConnection,
    connection_id: int,
    *,
    now: datetime | None = None,
    fetch: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Runs one sync. Returns a small summary; never includes the key."""
    lock = _locks.setdefault(connection_id, asyncio.Lock())
    if lock.locked():
        return {"status": "busy"}
    async with lock:
        return await _run(conn, connection_id, now or datetime.now(UTC), fetch)


async def sync_owned_connections(
    conn: AsyncConnection,
    user_id: int,
    *,
    now: datetime | None = None,
    fetch: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Sync all active connections owned by one user and return an aggregate summary."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, label FROM connections WHERE created_by = %s AND status = 'connected' ORDER BY id",
            (user_id,),
        )
        owned = await cur.fetchall()
    results = []
    for connection in owned:
        result = await sync_connection(conn, connection["id"], now=now, fetch=fetch)
        results.append({"id": connection["id"], "label": connection["label"], **result})
    return {
        "connections": len(results),
        "synced": sum(result["status"] == "ok" for result in results),
        "rows": sum(int(result.get("rows", 0)) for result in results),
        "errors": sum(result["status"] == "error" for result in results),
        "results": results,
    }


async def _run(
    conn: AsyncConnection, cid: int, now: datetime, fetch: Callable[..., Any] | None
) -> dict[str, Any]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, label, provider_id, encrypted_key, status FROM connections WHERE id = %s", (cid,)
        )
        c = await cur.fetchone()
    if c is None:
        raise LookupError("no such connection")
    if c["status"] != "connected":
        return {"status": "skipped", "reason": "revoked"}
    fetch = fetch or PROVIDERS.get(c["provider_id"])
    if fetch is None:
        return {"status": "skipped", "reason": "provider has no adapter yet"}

    end = now.replace(minute=0, second=0, microsecond=0)  # complete hours only
    cur = await conn.execute(
        "SELECT max(synced_through) FROM sync_runs WHERE connection_id = %s AND status = 'ok'", (cid,)
    )
    last = (await cur.fetchone())[0]
    if last and end <= last:
        return {"status": "up_to_date"}  # no complete hour is new since the last successful sync
    start = (last - OVERLAP) if last else end - BACKFILL

    cur = await conn.execute(
        "INSERT INTO sync_runs (connection_id, synced_from) VALUES (%s, %s) RETURNING id", (cid, start)
    )
    run_id = (await cur.fetchone())[0]
    await conn.commit()

    rows = 0
    try:
        key = vault.decrypt(c["encrypted_key"], f"connection:{c['label']}")
        async for row in fetch(key, start, end):
            await conn.execute(UPSERT, {**row, "connection_id": cid})
            rows += 1
        await conn.execute(
            "UPDATE sync_runs SET status = 'ok', finished_at = now(), synced_through = %s, "
            "rows_loaded = %s WHERE id = %s",
            (end, rows, run_id),
        )
        await conn.execute(
            "UPDATE connections SET last_sync_at = now(), last_error = NULL WHERE id = %s", (cid,)
        )
        await conn.commit()
        return {"status": "ok", "rows": rows, "from": start.isoformat(), "through": end.isoformat()}
    except (ProviderError, ValueError, RuntimeError) as e:
        message = str(e)[:300]
        await conn.rollback()  # discard this run's partial rows
        await conn.execute(
            "UPDATE sync_runs SET status = 'error', finished_at = now(), error = %s WHERE id = %s",
            (message, run_id),
        )
        await conn.execute("UPDATE connections SET last_error = %s WHERE id = %s", (message, cid))
        await conn.commit()
        return {"status": "error", "error": message}
    except Exception:
        await conn.rollback()
        log.exception("sync of connection %s failed unexpectedly", cid)
        message = "unexpected error during sync; see the server log"
        await conn.execute(
            "UPDATE sync_runs SET status = 'error', finished_at = now(), error = %s WHERE id = %s",
            (message, run_id),
        )
        await conn.execute("UPDATE connections SET last_error = %s WHERE id = %s", (message, cid))
        await conn.commit()
        return {"status": "error", "error": message}


async def due_connections(conn: AsyncConnection, now: datetime) -> list[int]:
    cur = await conn.execute(
        """SELECT c.id FROM connections c
           WHERE c.status = 'connected' AND NOT EXISTS (
             SELECT 1 FROM sync_runs r WHERE r.connection_id = c.id AND r.status = 'ok' AND r.finished_at > %s)
           ORDER BY c.id""",
        (now - STALE_AFTER,),
    )
    return [r[0] for r in await cur.fetchall()]


async def run_scheduler(pool: AsyncConnectionPool) -> None:
    """Hourly-by-default background loop: syncs every connection not synced within STALE_AFTER."""
    while True:
        try:
            async with pool.connection() as conn:
                ids = await due_connections(conn, datetime.now(UTC))
            for cid in ids:
                async with pool.connection() as conn:
                    result = await sync_connection(conn, cid)
                log.info("scheduled sync of connection %s: %s", cid, result.get("status"))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler pass failed; retrying")
        await asyncio.sleep(SCHEDULE_EVERY)
