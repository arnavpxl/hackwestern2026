"""Provider usage: the Anthropic adapter (paging, errors) and the sync runner (cursor, upsert, failure)."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from tokentrueup import auth, connections, vault
from tokentrueup.ingest import anthropic, sync
from tokentrueup.ingest.common import ProviderError

ADMIN_KEY = "sk-ant-admin-ingest-" + "x" * 30
NOW = datetime(2026, 11, 21, 10, 30, tzinfo=UTC)  # sync end will be 10:00 (complete hours only)


@pytest.fixture(autouse=True)
def master_key(monkeypatch):
    monkeypatch.setattr(vault.settings, "ttu_encryption_key", vault.generate_master_key())


def bucket(hour: int, day: int = 21, rows=None) -> dict:
    return {"starting_at": f"2026-11-{day:02d}T{hour:02d}:00:00Z", "ending_at": "x",
            "results": rows or []}


def row(model="claude-x", workspace="ws_1", key="apikey_1", inp=100, out=50, cache=10):
    return {"model": model, "workspace_id": workspace, "api_key_id": key, "uncached_input_tokens": inp,
            "output_tokens": out, "cache_read_input_tokens": cache,
            "cache_creation": {"ephemeral_5m_input_tokens": 5, "ephemeral_1h_input_tokens": 0}}


async def test_adapter_follows_paging_and_normalizes():
    pages = {
        None: {"data": [bucket(9, rows=[row(inp=100)])], "has_more": True, "next_page": "p2"},
        "p2": {"data": [bucket(10, rows=[row(inp=200)])], "has_more": False, "next_page": None},
    }
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["x-api-key"] == ADMIN_KEY
        return httpx.Response(200, json=pages[request.url.params.get("page")])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = [r async for r in anthropic.fetch_usage(ADMIN_KEY, NOW - timedelta(hours=2), NOW, client=client)]
    assert [r["input_tokens"] for r in rows] == [100, 200]
    assert rows[0]["bucket"] == datetime(2026, 11, 21, 9, tzinfo=UTC)
    assert rows[0]["cache_write_tokens"] == 5 and rows[0]["cache_read_tokens"] == 10
    assert "group_by%5B%5D=model" in str(seen[0].url) and "bucket_width=1h" in str(seen[0].url)


async def test_rejected_key_error_never_contains_the_key():
    def handler(request):
        return httpx.Response(401, json={"error": "invalid"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(anthropic.ProviderError) as info:
            [r async for r in anthropic.fetch_usage(ADMIN_KEY, NOW - timedelta(hours=1), NOW, client=client)]
    assert "rejected" in str(info.value) and ADMIN_KEY not in str(info.value)


async def test_openai_adapter_follows_paging_and_normalizes():
    from tokentrueup.ingest import openai as openai_adapter

    start = datetime(2026, 11, 21, 8, tzinfo=UTC)
    end = datetime(2026, 11, 21, 10, tzinfo=UTC)
    pages = {
        None: {"data": [{"start_time": int(start.timestamp()), "results": [
            {"model": "gpt-x", "project_id": "proj_1", "api_key_id": "key_1", "input_tokens": 300, "output_tokens": 20}]}],
            "has_more": True, "next_page": "p2"},
        "p2": {"data": [{"start_time": int((start + timedelta(hours=1)).timestamp()), "results": [
            {"model": "gpt-x", "project_id": "proj_1", "api_key_id": "key_1", "input_tokens": 400, "output_tokens": 5}]}],
            "has_more": False, "next_page": None},
    }
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["authorization"] == f"Bearer {ADMIN_KEY}"
        return httpx.Response(200, json=pages[request.url.params.get("page")])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = [r async for r in openai_adapter.fetch_usage(ADMIN_KEY, start, end, client=client)]
    assert [r["input_tokens"] for r in rows] == [300, 400]
    assert rows[0]["bucket"] == start and rows[0]["workspace_id"] == "proj_1" and rows[0]["provider_key_id"] == "key_1"
    assert "bucket_width=1h" in str(seen[0].url) and "start_time" in str(seen[0].url)


async def test_openai_rejected_key_message_is_readable_and_keyless():
    from tokentrueup.ingest import openai as openai_adapter

    def handler(request):
        return httpx.Response(401, json={"error": "invalid"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError) as info:
            [r async for r in openai_adapter.fetch_usage(ADMIN_KEY, NOW - timedelta(hours=1), NOW, client=client)]
    assert "OpenAI rejected" in str(info.value) and ADMIN_KEY not in str(info.value)


async def _connection(conn) -> int:
    await conn.execute("INSERT INTO providers (id, name, kind) VALUES ('anthropic', 'Anthropic', 'llm') "
                       "ON CONFLICT (id) DO NOTHING")
    email = f"{uuid.uuid4().hex[:10]}@example.test"
    uid = await auth.create_user(conn, email, "Sync Tester", "a-long-test-password", "admin")
    team_id = (await (await conn.execute("SELECT id FROM teams ORDER BY id LIMIT 1")).fetchone())[0]
    return await connections.add_connection(conn, uid, email, provider_id="anthropic",
                                            label=f"sync-{uuid.uuid4().hex[:6]}", team_id=team_id,
                                            key_kind="admin", key=ADMIN_KEY)


def fake_fetch(rows, fail_after=None, error=None):
    async def fetch(key, start, end):
        assert key == ADMIN_KEY  # the runner decrypts the stored key and passes it through
        for i, r in enumerate(rows):
            if fail_after is not None and i == fail_after:
                raise error or anthropic.ProviderError("the provider is busy")
            yield r
    return fetch


async def test_first_sync_backfills_then_is_idempotent(conn):
    cid = await _connection(conn)
    rows = [{"bucket": NOW - timedelta(hours=h), "model": "m", "workspace_id": "w", "provider_key_id": "k",
             "input_tokens": 10, "output_tokens": 1, "cache_read_tokens": 0, "cache_write_tokens": 0}
            for h in (3, 2)]
    first = await sync.sync_connection(conn, cid, now=NOW, fetch=fake_fetch(rows))
    assert first["status"] == "ok" and first["rows"] == 2
    assert first["from"] == (NOW.replace(minute=0) - timedelta(days=14)).isoformat()

    again = await sync.sync_connection(conn, cid, now=NOW, fetch=fake_fetch(rows))
    assert again["status"] == "up_to_date"

    later = NOW + timedelta(hours=2)
    rerun = await sync.sync_connection(conn, cid, now=later, fetch=fake_fetch(rows))
    assert rerun["status"] == "ok" and rerun["from"] == (NOW.replace(minute=0) - timedelta(hours=6)).isoformat()
    count = (await (await conn.execute("SELECT count(*) FROM provider_usage_hourly WHERE connection_id = %s",
                                       (cid,))).fetchone())[0]
    assert count == 2  # overlapping hours were overwritten, not duplicated
    status = (await (await conn.execute("SELECT last_sync_at IS NOT NULL, last_error FROM connections WHERE id = %s",
                                        (cid,))).fetchone())
    assert status == (True, None)


async def test_failed_sync_rolls_back_and_records_error(conn):
    cid = await _connection(conn)
    rows = [{"bucket": NOW - timedelta(hours=h), "model": "m", "workspace_id": "w", "provider_key_id": "k",
             "input_tokens": 10, "output_tokens": 1, "cache_read_tokens": 0, "cache_write_tokens": 0}
            for h in (3, 2)]
    result = await sync.sync_connection(conn, cid, now=NOW, fetch=fake_fetch(rows, fail_after=1))
    assert result["status"] == "error" and "busy" in result["error"]
    partial = (await (await conn.execute("SELECT count(*) FROM provider_usage_hourly WHERE connection_id = %s",
                                         (cid,))).fetchone())[0]
    assert partial == 0, "a failed run must not leave partial rows"
    run = (await (await conn.execute("SELECT status, error FROM sync_runs WHERE connection_id = %s",
                                     (cid,))).fetchone())
    assert run[0] == "error" and "busy" in run[1]
    listed = json.dumps(await connections.list_connections(conn), default=str)
    assert ADMIN_KEY not in listed


async def test_revoked_connection_is_not_synced(conn):
    cid = await _connection(conn)
    await connections.revoke(conn, "tester@example.test", cid)
    result = await sync.sync_connection(conn, cid, now=NOW, fetch=fake_fetch([]))
    assert result == {"status": "skipped", "reason": "revoked"}
