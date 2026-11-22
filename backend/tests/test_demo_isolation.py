"""The public synthetic dashboard must never expose connected-workspace key metadata."""

from tokentrueup.api.main import SYNTHETIC_PROVIDER_IDS, synthetic_key_rows


async def test_demo_keys_exclude_connected_providers_and_key_labels(conn, period):
    start, end = period
    team_id = (await (await conn.execute("SELECT id FROM teams ORDER BY id LIMIT 1")).fetchone())[0]
    await conn.execute(
        """INSERT INTO api_keys (label, provider_id, team_id)
           VALUES ('private-anthropic-mapping', 'anthropic', %s),
                  ('private-openai-mapping', 'openai', %s)""",
        (team_id, team_id),
    )

    result = await synthetic_key_rows(conn, start, end)

    assert result
    assert all(row["provider_id"] in SYNTHETIC_PROVIDER_IDS for row in result)
    assert all("label" not in row for row in result)
    assert not {"anthropic", "openai"} & {row["provider_id"] for row in result}
