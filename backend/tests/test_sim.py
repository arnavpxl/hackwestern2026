import asyncio
from datetime import UTC, datetime

from tokentrueup.sim import world


class FakeConnection:
    def __init__(self):
        self.params = None

    async def execute(self, _sql, params):
        self.params = params

    async def commit(self):
        pass


async def test_start_demo_configures_canonical_story(monkeypatch):
    now = datetime(2026, 11, 21, tzinfo=UTC)
    configured = {}

    async def fake_reset(_conn):
        return {"sim_now": now}

    async def fake_state(conn):
        configured.update(conn.params[0].obj)
        return {"paused": False, "target_eps": 4000, "scenario": configured}

    monkeypatch.setattr(world, "reset_world", fake_reset)
    monkeypatch.setattr(world, "get_state", fake_state)
    async def fake_pause(_conn, _paused):
        return await fake_state(_conn)
    monkeypatch.setattr(world, "set_paused", fake_pause)
    result = await world.start_demo(FakeConnection())

    state = result["state"]
    scenario = state["scenario"]
    assert state["paused"] is False
    assert state["target_eps"] == 4000
    assert scenario["runaway"]["active"] is True
    assert scenario["runaway"]["key"] == "support-triage-agent"
    assert scenario["stealth_price"]["provider"] == "nimbus-llm"
    assert result["configuration"]["hero_key"] == "support-triage-agent"


async def test_pause_freezes_clock_and_records_interval(conn):
    await world.set_paused(conn, False)
    before_pause = (await world.get_state(conn))["sim_now"]
    await conn.commit()  # each simulator action is a separate API transaction
    await asyncio.sleep(0.02)

    paused = await world.set_paused(conn, True)
    frozen = paused["sim_now"]
    assert frozen > before_pause
    await conn.commit()
    await asyncio.sleep(0.03)
    assert (await world.get_state(conn))["sim_now"] == frozen
    await conn.commit()

    interval = await (await conn.execute(
        "SELECT sim_at, real_ended_at FROM sim_pause_intervals"
    )).fetchone()
    assert interval == (frozen, None)

    resumed = await world.set_paused(conn, False)
    await conn.commit()
    await asyncio.sleep(0.02)
    later = (await world.get_state(conn))["sim_now"]
    assert later > resumed["sim_now"]
    assert (await (await conn.execute(
        "SELECT real_ended_at IS NOT NULL FROM sim_pause_intervals"
    )).fetchone())[0]
