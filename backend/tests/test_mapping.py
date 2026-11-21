"""Key mapping: provider keys attach to our keys, provider rules are enforced, unmapped usage is listed."""

import uuid
from datetime import UTC, datetime

import pytest

from tokentrueup import auth, connections, vault
from tokentrueup.ingest import mapping

ADMIN_KEY = "sk-ant-admin-mapping-" + "x" * 30
HOUR = datetime(2026, 11, 21, 9, tzinfo=UTC)


@pytest.fixture(autouse=True)
def master_key(monkeypatch):
    monkeypatch.setattr(vault.settings, "ttu_encryption_key", vault.generate_master_key())


async def _setup(conn):
    await conn.execute("INSERT INTO providers (id, name, kind) VALUES ('anthropic', 'Anthropic', 'llm') "
                       "ON CONFLICT (id) DO NOTHING")
    email = f"{uuid.uuid4().hex[:10]}@example.test"
    uid = await auth.create_user(conn, email, "Mapper", "a-long-test-password", "admin")
    team_id = (await (await conn.execute("SELECT id FROM teams ORDER BY id LIMIT 1")).fetchone())[0]
    cid = await connections.add_connection(conn, uid, email, provider_id="anthropic",
                                           label=f"map-{uuid.uuid4().hex[:6]}", team_id=team_id,
                                           key_kind="admin", key=ADMIN_KEY)
    await conn.execute(
        """INSERT INTO provider_usage_hourly (connection_id, bucket, model, workspace_id, provider_key_id,
               input_tokens, output_tokens) VALUES (%s, %s, 'claude-x', 'ws_1', 'apikey_1', 100, 50)""",
        (cid, HOUR))
    return cid, email, team_id


async def test_map_to_existing_key_and_unmapped_list(conn):
    cid, email, team_id = await _setup(conn)
    label = f"ours-{uuid.uuid4().hex[:6]}"
    our_key = (await (await conn.execute(
        "INSERT INTO api_keys (label, provider_id, team_id) VALUES (%s, 'anthropic', %s) RETURNING id",
        (label, team_id))).fetchone())[0]

    detail = await mapping.connection_detail(conn, cid)
    assert [u["provider_key_id"] for u in detail["unmapped"]] == ["apikey_1"]

    await mapping.map_key(conn, email, cid, provider_key_id="apikey_1", workspace_id="ws_1", api_key_id=our_key)
    detail = await mapping.connection_detail(conn, cid)
    assert detail["unmapped"] == []
    assert detail["mappings"][0]["label"] == label

    await mapping.unmap_key(conn, email, cid, provider_key_id="apikey_1", workspace_id="ws_1")
    assert [u["provider_key_id"] for u in (await mapping.connection_detail(conn, cid))["unmapped"]] == ["apikey_1"]


async def test_new_key_is_created_with_the_connection_provider(conn):
    cid, email, team_id = await _setup(conn)
    label = f"new-{uuid.uuid4().hex[:6]}"
    api_key_id = await mapping.map_key(conn, email, cid, provider_key_id="apikey_1", workspace_id="ws_1",
                                       new_key={"label": label, "team_id": team_id, "owner_id": None})
    provider, owner = await (await conn.execute("SELECT provider_id, owner_id FROM api_keys WHERE id = %s",
                                                (api_key_id,))).fetchone()
    assert provider == "anthropic" and owner is None  # no owner means an orphan, as elsewhere in the app


async def test_provider_mismatch_and_bad_input_are_refused(conn):
    cid, email, team_id = await _setup(conn)
    other = (await (await conn.execute(
        "INSERT INTO api_keys (label, provider_id, team_id) VALUES (%s, 'nimbus-llm', %s) RETURNING id",
        (f"other-{uuid.uuid4().hex[:6]}", team_id))).fetchone())[0]
    with pytest.raises(ValueError):
        await mapping.map_key(conn, email, cid, provider_key_id="apikey_1", workspace_id="ws_1", api_key_id=other)
    with pytest.raises(ValueError):  # neither choice given
        await mapping.map_key(conn, email, cid, provider_key_id="apikey_1", workspace_id="ws_1")
    with pytest.raises(ValueError):  # new key without a team
        await mapping.map_key(conn, email, cid, provider_key_id="apikey_1", workspace_id="ws_1",
                              new_key={"label": "no-team", "team_id": None})
    with pytest.raises(LookupError):
        await mapping.connection_detail(conn, 999999)
