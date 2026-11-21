"""Accounts, sessions and roles. Each test uses its own email, since users are not truncated by seeding."""

import uuid

import pytest

from tokentrueup import auth

PASSWORD = "a-long-test-password"


def fresh_email() -> str:
    return f"{uuid.uuid4().hex[:10]}@example.test"


def test_password_roundtrip():
    stored = auth.hash_password(PASSWORD)
    assert stored.startswith("scrypt$")
    assert auth.verify_password(PASSWORD, stored)
    assert not auth.verify_password("a-different-password", stored)


def test_malformed_stored_hash_is_rejected():
    assert not auth.verify_password(PASSWORD, "not-a-hash")
    assert not auth.verify_password(PASSWORD, "bcrypt$1$2$3$aa$bb")


def test_roles_are_ordered():
    assert auth.has_role("admin", "controller")
    assert auth.has_role("controller", "viewer")
    assert auth.has_role("viewer", "viewer")
    assert not auth.has_role("viewer", "controller")
    assert not auth.has_role("controller", "admin")
    assert not auth.has_role("unknown", "viewer")


def test_login_guard_blocks_after_limit_and_clears():
    guard = auth.LoginGuard(limit=3)
    for _ in range(3):
        guard.fail("someone@example.test")
    assert guard.blocked("someone@example.test")
    assert not guard.blocked("other@example.test")
    guard.clear("someone@example.test")
    assert not guard.blocked("someone@example.test")


async def test_create_and_authenticate(conn):
    email = fresh_email()
    await auth.create_user(conn, email, "Test User", PASSWORD, "controller")
    await conn.commit()
    user = await auth.authenticate(conn, email.upper(), PASSWORD)  # emails are case-insensitive
    assert user is not None and user["role"] == "controller"
    assert await auth.authenticate(conn, email, "wrong-password-here") is None
    assert await auth.authenticate(conn, "nobody@example.test", PASSWORD) is None


async def test_disabled_user_cannot_sign_in(conn):
    email = fresh_email()
    await auth.create_user(conn, email, "Test User", PASSWORD, "admin")
    await conn.execute("UPDATE users SET disabled = true WHERE email = %s", (email,))
    await conn.commit()
    assert await auth.authenticate(conn, email, PASSWORD) is None


async def test_session_lifecycle_stores_only_a_hash(conn):
    email = fresh_email()
    uid = await auth.create_user(conn, email, "Test User", PASSWORD, "viewer")
    await conn.commit()
    token = await auth.create_session(conn, uid)
    await conn.commit()

    user = await auth.user_from_session(conn, token)
    assert user is not None and user["email"] == email

    plain_rows = await (await conn.execute("SELECT count(*) FROM sessions WHERE token_hash = %s", (token,))).fetchone()
    assert plain_rows[0] == 0, "the raw token must never be stored"

    await auth.delete_session(conn, token)
    await conn.commit()
    assert await auth.user_from_session(conn, token) is None


async def test_expired_session_is_rejected(conn):
    email = fresh_email()
    uid = await auth.create_user(conn, email, "Test User", PASSWORD, "viewer")
    await conn.commit()
    token = await auth.create_session(conn, uid)
    await conn.execute("UPDATE sessions SET expires_at = now() - interval '1 minute' WHERE user_id = %s", (uid,))
    await conn.commit()
    assert await auth.user_from_session(conn, token) is None


async def test_disabling_a_user_ends_their_sessions(conn):
    email = fresh_email()
    uid = await auth.create_user(conn, email, "Test User", PASSWORD, "controller")
    await conn.commit()
    token = await auth.create_session(conn, uid)
    await conn.execute("UPDATE users SET disabled = true WHERE id = %s", (uid,))
    await conn.commit()
    assert await auth.user_from_session(conn, token) is None


async def test_user_input_is_validated(conn):
    with pytest.raises(ValueError):
        await auth.create_user(conn, "not-an-email", "Test", PASSWORD, "viewer")
    with pytest.raises(ValueError):
        await auth.create_user(conn, fresh_email(), "Test", "short", "viewer")
    with pytest.raises(ValueError):
        await auth.create_user(conn, fresh_email(), "Test", PASSWORD, "superuser")
