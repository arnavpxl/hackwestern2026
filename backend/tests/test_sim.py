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
    result = await world.start_demo(FakeConnection())

    state = result["state"]
    scenario = state["scenario"]
    assert state["paused"] is False
    assert state["target_eps"] == 4000
    assert scenario["runaway"]["active"] is True
    assert scenario["runaway"]["key"] == "support-triage-agent"
    assert scenario["stealth_price"]["provider"] == "nimbus-llm"
    assert result["configuration"]["hero_key"] == "support-triage-agent"
