"""Key mapping and connection health.

A provider key is mapped to one of our api_keys. If none fits, the admin can create one on the spot;
it takes the connection's provider, and the team and owner they choose. Mapping a provider key to a
key from a different provider is refused.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from ..connections import audit


async def connection_detail(conn: AsyncConnection, connection_id: int) -> dict[str, Any]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """SELECT c.id, c.label, c.provider_id, p.name AS provider_name, c.team_id, t.name AS team,
                      c.key_kind, c.key_last4, c.status, c.last_sync_at, c.last_error
               FROM connections c JOIN providers p ON p.id = c.provider_id JOIN teams t ON t.id = c.team_id
               WHERE c.id = %s""", (connection_id,))
        connection = await cur.fetchone()
        if connection is None:
            raise LookupError("no such connection")
        await cur.execute(
            """SELECT started_at, finished_at, status, synced_from, synced_through, rows_loaded, error
               FROM sync_runs WHERE connection_id = %s ORDER BY id DESC LIMIT 10""", (connection_id,))
        runs = await cur.fetchall()
        await cur.execute(
            """SELECT count(*) AS rows, min(bucket) AS first_bucket, max(bucket) AS last_bucket
               FROM provider_usage_hourly WHERE connection_id = %s""", (connection_id,))
        coverage = await cur.fetchone()
        await cur.execute(
            """SELECT u.provider_key_id, u.workspace_id, sum(u.input_tokens + u.output_tokens + u.cache_read_tokens
                      + u.cache_write_tokens)::bigint AS tokens, min(u.bucket) AS first_seen, max(u.bucket) AS last_seen
               FROM provider_usage_hourly u
               LEFT JOIN key_mappings m ON m.connection_id = u.connection_id
                    AND m.provider_key_id = u.provider_key_id AND m.workspace_id = u.workspace_id
               WHERE u.connection_id = %s AND m.api_key_id IS NULL
               GROUP BY 1, 2 ORDER BY tokens DESC""", (connection_id,))
        unmapped = await cur.fetchall()
        await cur.execute(
            """SELECT m.provider_key_id, m.workspace_id, m.api_key_id, k.label, k.team_id, t.name AS team,
                      k.owner_id, o.name AS owner
               FROM key_mappings m JOIN api_keys k ON k.id = m.api_key_id JOIN teams t ON t.id = k.team_id
               LEFT JOIN owners o ON o.id = k.owner_id
               WHERE m.connection_id = %s ORDER BY k.label""", (connection_id,))
        mappings = await cur.fetchall()
        await cur.execute("SELECT id, label, team_id, owner_id FROM api_keys WHERE provider_id = %s ORDER BY label",
                          (connection["provider_id"],))
        our_keys = await cur.fetchall()
        await cur.execute("SELECT id, name FROM owners ORDER BY name")
        owners = await cur.fetchall()
    return {"connection": connection, "runs": runs, "coverage": coverage, "unmapped": unmapped,
            "mappings": mappings, "our_keys": our_keys, "owners": owners}


async def map_key(conn: AsyncConnection, actor_email: str, connection_id: int, *, provider_key_id: str,
                  workspace_id: str, api_key_id: int | None = None, new_key: dict[str, Any] | None = None) -> int:
    """Caller commits. Returns the api_key id the provider key now maps to."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT id, provider_id, label FROM connections WHERE id = %s", (connection_id,))
        c = await cur.fetchone()
    if c is None:
        raise LookupError("no such connection")
    if (api_key_id is None) == (new_key is None):
        raise ValueError("choose an existing key or describe a new one, not both")
    if new_key is not None:
        label = str(new_key.get("label", "")).strip()
        if not 1 <= len(label) <= 80:
            raise ValueError("key name must be 1 to 80 characters")
        if not isinstance(new_key.get("team_id"), int):
            raise ValueError("choose a team for the new key")
        cur = await conn.execute(
            """INSERT INTO api_keys (label, provider_id, team_id, owner_id) VALUES (%s, %s, %s, %s) RETURNING id""",
            (label, c["provider_id"], new_key["team_id"], new_key.get("owner_id")))
        api_key_id = (await cur.fetchone())[0]
        await audit(conn, f"user:{actor_email}", "api_key_created_from_mapping",
                    {"api_key_id": api_key_id, "label": label, "connection_id": connection_id})
    else:
        cur = await conn.execute("SELECT provider_id FROM api_keys WHERE id = %s", (api_key_id,))
        row = await cur.fetchone()
        if row is None:
            raise ValueError("unknown key")
        if row[0] != c["provider_id"]:
            raise ValueError("that key belongs to a different provider than this connection")
    await conn.execute(
        """INSERT INTO key_mappings (connection_id, provider_key_id, workspace_id, api_key_id, mapped_by)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (connection_id, provider_key_id, workspace_id) DO UPDATE
           SET api_key_id = EXCLUDED.api_key_id, mapped_by = EXCLUDED.mapped_by, mapped_at = now()""",
        (connection_id, provider_key_id, workspace_id, api_key_id, actor_email))
    await audit(conn, f"user:{actor_email}", "key_mapped",
                {"connection_id": connection_id, "provider_key_id": provider_key_id, "workspace_id": workspace_id,
                 "api_key_id": api_key_id})
    return api_key_id


async def unmap_key(conn: AsyncConnection, actor_email: str, connection_id: int, *, provider_key_id: str,
                    workspace_id: str) -> None:
    cur = await conn.execute(
        """DELETE FROM key_mappings WHERE connection_id = %s AND provider_key_id = %s AND workspace_id = %s""",
        (connection_id, provider_key_id, workspace_id))
    if cur.rowcount:
        await audit(conn, f"user:{actor_email}", "key_unmapped",
                    {"connection_id": connection_id, "provider_key_id": provider_key_id, "workspace_id": workspace_id})
