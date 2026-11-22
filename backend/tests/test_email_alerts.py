from datetime import UTC, datetime, timedelta

from psycopg_pool import AsyncConnectionPool

from tokentrueup import auth, email_alerts
from tokentrueup.config import settings


async def _insert_anomaly(conn, key_id: int) -> int:
    return (
        await (
            await conn.execute(
                """INSERT INTO obligation_cases
                       (period, type, provider_id, api_key_id, title, opened_at, calc)
                   SELECT date_trunc('month', sim_now())::date, 'anomaly', provider_id, id,
                          'Runaway test', sim_now(),
                          '{"model":"nimbus-pro","projected_hourly_cents":4200,"baseline_mean_cents":200}'::jsonb
                   FROM api_keys WHERE id = %s RETURNING id""",
                (key_id,),
            )
        ).fetchone()
    )[0]


async def test_anomaly_enqueues_and_sends_one_email(conn, db_url, monkeypatch):
    email = "pitch-alert@example.test"
    user_id = await auth.create_user(conn, email, "Pitch User", "a-long-test-password", "admin")
    key_id = (
        await (await conn.execute("SELECT id FROM api_keys WHERE label = 'support-triage-agent'")).fetchone()
    )[0]
    await conn.execute(
        """INSERT INTO demo_email_enrollments (user_id, api_key_id, expires_at)
           VALUES (%s, %s, %s)""",
        (user_id, key_id, datetime.now(UTC) + timedelta(minutes=10)),
    )
    case_id = await _insert_anomaly(conn, key_id)
    queued = await (
        await conn.execute(
            """SELECT recipient, status,
                      next_attempt_at >= created_at + interval '4.5 seconds'
               FROM demo_email_notifications WHERE case_id = %s""",
            (case_id,),
        )
    ).fetchall()
    assert queued == [(email, "pending", True)]
    await conn.execute(
        "UPDATE demo_email_notifications SET next_attempt_at = now() WHERE case_id = %s", (case_id,)
    )
    await conn.commit()

    sent = []
    monkeypatch.setattr(settings, "ttu_smtp_from", "alerts@example.test")
    monkeypatch.setattr(settings, "ttu_smtp_message_stream", "outbound")
    monkeypatch.setattr(email_alerts, "_smtp_send", lambda message: sent.append(message))
    pool = AsyncConnectionPool(db_url, min_size=1, max_size=1, open=False)
    await pool.open()
    try:
        assert await email_alerts.send_one(pool) is True
        assert await email_alerts.send_one(pool) is False
    finally:
        await pool.close()

    assert len(sent) == 1
    assert sent[0]["To"] == email
    assert sent[0]["X-PM-Message-Stream"] == "outbound"
    assert "Runaway AI spend detected" in sent[0]["Subject"]
    row = await (
        await conn.execute(
            "SELECT status, attempts, sent_at IS NOT NULL FROM demo_email_notifications WHERE case_id = %s",
            (case_id,),
        )
    ).fetchone()
    assert row == ("sent", 1, True)


async def test_public_demo_user_is_never_queued(conn):
    demo_id = await auth.create_user(
        conn, "demo@tokentrueup.local", "Demo visitor", "a-long-test-password", "admin"
    )
    key_id = (
        await (await conn.execute("SELECT id FROM api_keys WHERE label = 'support-triage-agent'")).fetchone()
    )[0]
    await conn.execute(
        """INSERT INTO demo_email_enrollments (user_id, api_key_id, expires_at)
           VALUES (%s, %s, now() + interval '10 minutes')""",
        (demo_id, key_id),
    )
    case_id = await _insert_anomaly(conn, key_id)
    count = (
        await (
            await conn.execute("SELECT count(*) FROM demo_email_notifications WHERE case_id = %s", (case_id,))
        ).fetchone()
    )[0]
    assert count == 0
