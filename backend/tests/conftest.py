"""Test DB: a separate database on the same server, migrated from db/migrations, seeded
with the synthetic catalog, background jobs removed so every test is deterministic."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
import pytest_asyncio
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from tokentrueup import migrate
from tokentrueup.config import settings
from tokentrueup.sim.profiles import month_start
from tokentrueup.sim.seed import seed


def _test_url() -> str:
    if url := os.environ.get("TEST_DATABASE_URL"):
        return url
    info = conninfo_to_dict(settings.database_url)
    info["dbname"] = "tokentrueup_test"
    return make_conninfo(**info)


TEST_URL = _test_url()


@pytest.fixture(scope="session")
def db_url() -> str:
    admin = conninfo_to_dict(TEST_URL)
    name = admin.pop("dbname")
    admin["dbname"] = "postgres"
    with psycopg.connect(make_conninfo(**admin), autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {name}")
    migrate.apply(TEST_URL, verbose=False)
    with psycopg.connect(TEST_URL, autocommit=True) as c:
        # deterministic: no background refresh / compression / anomaly jobs
        c.execute("SELECT delete_job(job_id) FROM timescaledb_information.jobs WHERE job_id >= 1000")
    return TEST_URL


@pytest.fixture
def fresh(db_url):
    """Seed the catalog (truncates everything) before each test."""
    with psycopg.connect(db_url) as c:
        seed(c)
    return db_url


@pytest_asyncio.fixture
async def conn(fresh):
    async with await psycopg.AsyncConnection.connect(fresh) as c:
        yield c


@pytest.fixture
def period() -> tuple[datetime, datetime]:
    start = month_start(datetime.now(UTC))
    return start, month_start(start, 1)


def hour(start: datetime, day: int, h: int) -> datetime:
    return start + timedelta(days=day, hours=h)


async def key_id(conn, label: str) -> int:
    return (await (await conn.execute("SELECT id FROM api_keys WHERE label = %s", (label,))).fetchone())[0]


async def insert_event(conn, ts, label, provider, model, *, inp=0, out=0, cached=0, requests=1, gpu_s=0.0,
                       cost=0.0) -> None:
    kid = await key_id(conn, label)
    await conn.execute(
        """INSERT INTO usage_events (ts, api_key_id, provider, model, input_tokens, output_tokens, cached_tokens,
               requests, gpu_seconds, cost_estimate_cents) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (ts, kid, provider, model, inp, out, cached, requests, gpu_s, cost))


async def refresh(conn, start: datetime, end: datetime) -> None:
    await conn.commit()
    await conn.set_autocommit(True)
    for v in ("usage_1m", "usage_1h", "usage_1d", "spend_baseline"):
        await conn.execute("CALL refresh_continuous_aggregate(%s, %s, %s)", (v, start, end))
    await conn.set_autocommit(False)
