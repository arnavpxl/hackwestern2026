"""Connected analytics stay user-scoped and surface incomplete pricing/mapping honestly."""

from datetime import UTC, datetime, timedelta

from tokentrueup import auth, connected_spend

NOW = datetime(2026, 11, 21, 12, 30, tzinfo=UTC)


async def _user(conn, suffix: str) -> int:
    return await auth.create_user(
        conn, f"analytics-{suffix}@example.test", "Analytics User", "a-long-test-password", "admin"
    )


async def _connection(conn, user_id: int, label: str, provider: str = "anthropic") -> int:
    team_id = (await (await conn.execute("SELECT id FROM teams ORDER BY id LIMIT 1")).fetchone())[0]
    row = await (
        await conn.execute(
            """INSERT INTO connections
             (provider_id, label, team_id, key_kind, encrypted_key, key_last4, created_by, last_sync_at)
           VALUES (%s, %s, %s, 'admin', 'test-ciphertext', '1234', %s, %s) RETURNING id""",
            (provider, label, team_id, user_id, NOW),
        )
    ).fetchone()
    return row[0]


async def _usage(
    conn,
    connection_id: int,
    bucket: datetime,
    model: str,
    *,
    key: str = "provider-key",
    inp: int = 1_000_000,
    out: int = 0,
) -> None:
    await conn.execute(
        """INSERT INTO provider_usage_hourly
             (connection_id, bucket, model, workspace_id, provider_key_id, input_tokens, output_tokens)
           VALUES (%s, %s, %s, 'workspace', %s, %s, %s)""",
        (connection_id, bucket, model, key, inp, out),
    )


async def test_dashboard_is_scoped_and_prices_known_models(conn):
    ours = await _user(conn, "ours")
    other = await _user(conn, "other")
    ours_connection = await _connection(conn, ours, "our-anthropic")
    other_connection = await _connection(conn, other, "their-anthropic")
    await _usage(
        conn,
        ours_connection,
        NOW - timedelta(hours=2),
        "claude-sonnet-4-5-20250929",
        inp=1_000_000,
        out=1_000_000,
    )
    await _usage(
        conn,
        other_connection,
        NOW - timedelta(hours=2),
        "claude-sonnet-4-5-20250929",
        inp=9_000_000,
        out=9_000_000,
    )

    result = await connected_spend.dashboard(conn, ours, now=NOW)

    assert len(result["connections"]) == 1
    assert result["connections"][0]["label"] == "our-anthropic"
    assert result["summary"]["mtd"] == 18.0  # $3 input + $15 output
    assert result["quality"]["priced_token_percent"] == 100.0
    assert result["quality"]["default_team_source_count"] == 1
    assert result["keys"][0]["team"] == "Platform"
    assert "provider-key" not in str(result)


async def test_unpriced_usage_is_reported_and_excluded(conn):
    user_id = await _user(conn, "unpriced")
    connection_id = await _connection(conn, user_id, "our-openai", provider="openai")
    await _usage(conn, connection_id, NOW - timedelta(hours=1), "future-model-without-a-price")

    result = await connected_spend.dashboard(conn, user_id, now=NOW)

    assert result["summary"]["mtd"] == 0
    assert result["quality"]["priced_token_percent"] == 0.0
    assert result["quality"]["unpriced_models"] == [
        {"provider": "OpenAI", "model": "future-model-without-a-price", "tokens": 1_000_000}
    ]
    assert len(result["keys"]) == 1
    assert result["keys"][0]["mtd"] == 0
    assert result["quality"]["default_team_source_count"] == 1


async def test_mapped_usage_uses_owner_and_team_without_showing_key_identifier(conn):
    user_id = await _user(conn, "mapped")
    connection_id = await _connection(conn, user_id, "mapped-anthropic")
    team_id = (await (await conn.execute("SELECT id FROM teams WHERE name = 'Research'")).fetchone())[0]
    owner_id = (
        await (await conn.execute("SELECT id FROM owners WHERE team_id = %s LIMIT 1", (team_id,))).fetchone()
    )[0]
    api_key_id = (
        await (
            await conn.execute(
                """INSERT INTO api_keys (label, provider_id, team_id, owner_id)
           VALUES ('connected-test-key', 'anthropic', %s, %s) RETURNING id""",
                (team_id, owner_id),
            )
        ).fetchone()
    )[0]
    await conn.execute(
        """INSERT INTO key_mappings (connection_id, provider_key_id, workspace_id, api_key_id, mapped_by)
           VALUES (%s, 'secret-provider-id', 'workspace', %s, 'test')""",
        (connection_id, api_key_id),
    )
    await _usage(
        conn, connection_id, NOW - timedelta(hours=1), "claude-haiku-4-5-20251001", key="secret-provider-id"
    )

    result = await connected_spend.dashboard(conn, user_id, now=NOW)

    assert result["keys"][0]["mapped"] is True
    assert result["keys"][0]["team"] == "Research"
    assert result["keys"][0]["owner"]
    assert "secret-provider-id" not in str(result)
