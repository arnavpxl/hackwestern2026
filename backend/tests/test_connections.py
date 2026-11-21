"""Provider keys: encryption, format checks, and the connection lifecycle with its audit trail."""

import json
import uuid

import pytest

from tokentrueup import auth, connections, vault

ADMIN_KEY = "sk-ant-admin01-" + "x" * 40


@pytest.fixture(autouse=True)
def master_key(monkeypatch):
    monkeypatch.setattr(vault.settings, "ttu_encryption_key", vault.generate_master_key())


def test_encrypt_roundtrip_and_context_binding():
    token = vault.encrypt(ADMIN_KEY, "connection:one")
    assert token.startswith("v1:") and ADMIN_KEY not in token
    assert vault.decrypt(token, "connection:one") == ADMIN_KEY
    with pytest.raises(ValueError):
        vault.decrypt(token, "connection:two")  # a ciphertext moved to another row must not decrypt


def test_tampered_ciphertext_is_rejected():
    token = vault.encrypt(ADMIN_KEY, "connection:one")
    flipped = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]
    with pytest.raises(ValueError):
        vault.decrypt(flipped, "connection:one")


def test_missing_master_key_refuses_to_store(monkeypatch):
    monkeypatch.setattr(vault.settings, "ttu_encryption_key", "")
    with pytest.raises(RuntimeError):
        vault.encrypt(ADMIN_KEY, "connection:one")


def test_format_checks():
    assert vault.check_format("anthropic", ADMIN_KEY) is None
    assert vault.check_format("anthropic", "sk-ant-api03-" + "x" * 40) is not None  # not an admin key
    assert vault.check_format("openai", "short") is not None
    assert vault.check_format("openai", "sk-" + "x" * 30 + " with space") is not None
    assert vault.last4(ADMIN_KEY) == ADMIN_KEY[-4:]


async def _provider_and_user(conn) -> tuple[int, str]:
    await conn.execute("INSERT INTO providers (id, name, kind) VALUES ('anthropic', 'Anthropic', 'llm') "
                       "ON CONFLICT (id) DO NOTHING")
    email = f"{uuid.uuid4().hex[:10]}@example.test"
    uid = await auth.create_user(conn, email, "Admin Tester", "a-long-test-password", "admin")
    return uid, email


async def test_add_list_rotate_revoke(conn):
    uid, email = await _provider_and_user(conn)
    team_id = (await (await conn.execute("SELECT id FROM teams ORDER BY id LIMIT 1")).fetchone())[0]
    label = f"prod-{uuid.uuid4().hex[:6]}"

    cid = await connections.add_connection(conn, uid, email, provider_id="anthropic", label=label,
                                           team_id=team_id, key_kind="admin", key=ADMIN_KEY)
    listing = await connections.list_connections(conn)
    row = next(c for c in listing["connections"] if c["id"] == cid)
    assert row["key_last4"] == ADMIN_KEY[-4:] and row["status"] == "connected"
    assert "encrypted_key" not in row and ADMIN_KEY not in json.dumps(listing, default=str)

    new_key = "sk-ant-admin02-" + "y" * 40
    await connections.rotate_key(conn, email, cid, new_key)
    stored = await (await conn.execute("SELECT encrypted_key, key_last4 FROM connections WHERE id = %s", (cid,))).fetchone()
    assert vault.decrypt(stored[0], f"connection:{label}") == new_key
    assert stored[1] == new_key[-4:]

    await connections.revoke(conn, email, cid)
    revoked = await (await conn.execute("SELECT status, encrypted_key FROM connections WHERE id = %s", (cid,))).fetchone()
    assert revoked == ("revoked", None)
    with pytest.raises(ValueError):
        await connections.rotate_key(conn, email, cid, new_key)


async def test_audit_records_actions_without_the_key(conn):
    uid, email = await _provider_and_user(conn)
    team_id = (await (await conn.execute("SELECT id FROM teams ORDER BY id LIMIT 1")).fetchone())[0]
    label = f"audit-{uuid.uuid4().hex[:6]}"
    cid = await connections.add_connection(conn, uid, email, provider_id="anthropic", label=label,
                                           team_id=team_id, key_kind="admin", key=ADMIN_KEY)
    await connections.revoke(conn, email, cid)
    rows = await (await conn.execute(
        "SELECT action, actor, detail::text FROM audit_log WHERE detail->>'connection_id' = %s ORDER BY id",
        (str(cid),))).fetchall()
    assert [r[0] for r in rows] == ["connection_added", "connection_revoked"]
    assert all(r[1] == f"user:{email}" for r in rows)
    assert all(ADMIN_KEY not in r[2] for r in rows)


async def test_bad_input_is_refused(conn):
    uid, email = await _provider_and_user(conn)
    team_id = (await (await conn.execute("SELECT id FROM teams ORDER BY id LIMIT 1")).fetchone())[0]
    with pytest.raises(ValueError):  # wrong key type for Anthropic usage data
        await connections.add_connection(conn, uid, email, provider_id="anthropic", label="x",
                                         team_id=team_id, key_kind="admin", key="sk-ant-api03-" + "x" * 40)
    with pytest.raises(ValueError):  # provider not supported yet
        await connections.add_connection(conn, uid, email, provider_id="nimbus-llm", label="y",
                                         team_id=team_id, key_kind="admin", key=ADMIN_KEY)
    with pytest.raises(ValueError):  # unknown team
        await connections.add_connection(conn, uid, email, provider_id="anthropic", label="z",
                                         team_id=999999, key_kind="admin", key=ADMIN_KEY)
