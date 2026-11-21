"""Provider connections: store, rotate and revoke the API keys companies paste in.

Keys are encrypted before they reach the database and are never returned by any function here.
Every change writes an audit entry that names the actor and the action, never the key.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import vault

KEY_KINDS = ("admin", "api")
LIST_COLUMNS = """
    c.id, c.provider_id, p.name AS provider_name, c.label, c.team_id, t.name AS team,
    c.key_kind, c.key_last4, c.status, c.created_at, c.rotated_at, c.revoked_at,
    c.last_sync_at, c.last_error, u.name AS created_by
"""


async def audit(conn: AsyncConnection, actor: str, action: str, detail: dict[str, Any]) -> None:
    await conn.execute("INSERT INTO audit_log (actor, action, detail) VALUES (%s, %s, %s)",
                       (actor, action, Jsonb(detail)))


async def list_connections(conn: AsyncConnection, created_by: int | None = None) -> dict[str, Any]:
    """Everything the Connections page needs. No key material is selected."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"""SELECT {LIST_COLUMNS} FROM connections c
                              JOIN providers p ON p.id = c.provider_id JOIN teams t ON t.id = c.team_id
                              LEFT JOIN users u ON u.id = c.created_by
                              WHERE (%s::bigint IS NULL OR c.created_by = %s) ORDER BY c.id""",
                          (created_by, created_by))
        connections = await cur.fetchall()
        await cur.execute("SELECT id, name FROM providers WHERE id IN ('anthropic', 'openai') ORDER BY name")
        providers = await cur.fetchall()
        await cur.execute("SELECT id, name FROM teams ORDER BY name")
        teams = await cur.fetchall()
    return {"connections": connections, "providers": providers, "teams": teams}


async def _connected(conn: AsyncConnection, connection_id: int) -> dict[str, Any]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT id, label, provider_id, status FROM connections WHERE id = %s", (connection_id,))
        row = await cur.fetchone()
    if row is None:
        raise LookupError("no such connection")
    return row


async def add_connection(conn: AsyncConnection, actor_id: int, actor_email: str, *, provider_id: str, label: str,
                         team_id: int, key_kind: str, key: str) -> int:
    """Caller commits. Raises ValueError for bad input (messages never include the key)."""
    label = label.strip()
    if not 1 <= len(label) <= 60:
        raise ValueError("label must be 1 to 60 characters")
    if key_kind not in KEY_KINDS:
        raise ValueError(f"key type must be one of {list(KEY_KINDS)}")
    if provider_id not in ("anthropic", "openai"):
        raise ValueError("this provider is not supported yet")
    if problem := vault.check_format(provider_id, key):
        raise ValueError(problem)
    cur = await conn.execute("SELECT 1 FROM teams WHERE id = %s", (team_id,))
    if await cur.fetchone() is None:
        raise ValueError("unknown team")

    cur = await conn.execute(
        """INSERT INTO connections (provider_id, label, team_id, key_kind, encrypted_key, key_last4, created_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (provider_id, label, team_id, key_kind, vault.encrypt(key.strip(), f"connection:{label}"),
         vault.last4(key.strip()), actor_id))
    connection_id = (await cur.fetchone())[0]
    await audit(conn, f"user:{actor_email}", "connection_added",
                {"connection_id": connection_id, "provider": provider_id, "label": label, "key_kind": key_kind})
    return connection_id


async def rotate_key(conn: AsyncConnection, actor_email: str, connection_id: int, key: str) -> None:
    row = await _connected(conn, connection_id)
    if row["status"] != "connected":
        raise ValueError("this connection was revoked; add a new one instead")
    if problem := vault.check_format(row["provider_id"], key):
        raise ValueError(problem)
    await conn.execute(
        """UPDATE connections SET encrypted_key = %s, key_last4 = %s, rotated_at = now() WHERE id = %s""",
        (vault.encrypt(key.strip(), f"connection:{row['label']}"), vault.last4(key.strip()), connection_id))
    await audit(conn, f"user:{actor_email}", "connection_key_rotated",
                {"connection_id": connection_id, "label": row["label"]})


async def revoke(conn: AsyncConnection, actor_email: str, connection_id: int) -> None:
    row = await _connected(conn, connection_id)
    if row["status"] == "revoked":
        return
    await conn.execute(
        "UPDATE connections SET status = 'revoked', encrypted_key = NULL, revoked_at = now() WHERE id = %s",
        (connection_id,))
    await audit(conn, f"user:{actor_email}", "connection_revoked",
                {"connection_id": connection_id, "label": row["label"]})
