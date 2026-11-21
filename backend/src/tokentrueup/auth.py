"""Local accounts, password hashing and server-side sessions (standard library only).

Roles are ordered: viewer < controller < admin. A role satisfies a requirement when it is
at least as high. Passwords use scrypt; session tokens are random and stored only as hashes.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import hashlib
import hmac
import re
import secrets
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from .config import settings

ROLES = {"viewer": 0, "controller": 1, "admin": 2}
COOKIE = "ttu_session"
SESSION_TTL = timedelta(hours=12)
MIN_PASSWORD = 12
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def has_role(role: str, required: str) -> bool:
    return ROLES.get(role, -1) >= ROLES[required]


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r),
                                p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Used when the email is unknown, so a failed login costs the same time either way.
_DUMMY_HASH = hash_password("not-a-real-password-used-for-timing")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_user(conn: AsyncConnection, email: str, name: str, password: str, role: str) -> int:
    """Caller commits. Raises ValueError for bad input."""
    email = email.strip().lower()
    if not _EMAIL.match(email):
        raise ValueError("email looks invalid")
    if role not in ROLES:
        raise ValueError(f"role must be one of {sorted(ROLES)}")
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    cur = await conn.execute(
        "INSERT INTO users (email, name, role, password_hash) VALUES (%s, %s, %s, %s) RETURNING id",
        (email, name.strip(), role, hash_password(password)),
    )
    return (await cur.fetchone())[0]


async def authenticate(conn: AsyncConnection, email: str, password: str) -> dict[str, Any] | None:
    """Returns the user's public fields on success, else None. Caller commits."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT id, email, name, role, password_hash, disabled FROM users WHERE email = %s",
                          (email.strip().lower(),))
        row = await cur.fetchone()
    if row is None:
        verify_password(password, _DUMMY_HASH)
        return None
    ok = verify_password(password, row["password_hash"]) and not row["disabled"]
    if not ok:
        return None
    await conn.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (row["id"],))
    return {k: row[k] for k in ("id", "email", "name", "role")}


async def create_session(conn: AsyncConnection, user_id: int) -> str:
    """Returns the raw token for the cookie; only its hash is stored. Caller commits."""
    token = secrets.token_urlsafe(32)
    await conn.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
        (_token_hash(token), user_id, datetime.now(UTC) + SESSION_TTL),
    )
    return token


async def user_from_session(conn: AsyncConnection, token: str) -> dict[str, Any] | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """SELECT u.id, u.email, u.name, u.role FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = %s AND s.expires_at > now() AND NOT u.disabled""",
            (_token_hash(token),))
        return await cur.fetchone()


async def delete_session(conn: AsyncConnection, token: str) -> None:
    await conn.execute("DELETE FROM sessions WHERE token_hash = %s", (_token_hash(token),))


async def list_users(conn: AsyncConnection) -> list[dict[str, Any]]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT id, email, name, role, disabled, created_at, last_login_at FROM users ORDER BY id")
        return await cur.fetchall()


class LoginGuard:
    """Blocks an email after repeated failures for a while. In-memory, so it resets on restart."""

    def __init__(self, limit: int = 10, window: timedelta = timedelta(minutes=15)) -> None:
        self.limit = limit
        self.window = window
        self.failures: dict[str, list[datetime]] = {}

    def blocked(self, email: str) -> bool:
        cutoff = datetime.now(UTC) - self.window
        recent = [t for t in self.failures.get(email, []) if t > cutoff]
        self.failures[email] = recent
        return len(recent) >= self.limit

    def fail(self, email: str) -> None:
        self.failures.setdefault(email, []).append(datetime.now(UTC))

    def clear(self, email: str) -> None:
        self.failures.pop(email, None)


async def _create_user_cli(email: str, name: str, role: str, password: str) -> None:
    async with await AsyncConnection.connect(settings.database_url) as conn:
        uid = await create_user(conn, email, name, password, role)
        await conn.commit()
    print(f"created user {email.strip().lower()} ({role}), id {uid}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m tokentrueup.auth")
    sub = ap.add_subparsers(dest="cmd", required=True)
    create = sub.add_parser("create-user", help="create a local account")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", required=True, choices=sorted(ROLES))
    args = ap.parse_args(argv)

    password = getpass.getpass(f"Password (at least {MIN_PASSWORD} characters): ")
    if getpass.getpass("Repeat password: ") != password:
        sys.exit("passwords do not match")
    if sys.platform == "win32":  # psycopg async needs the selector event loop on Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(_create_user_cli(args.email, args.name, args.role, password))
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
