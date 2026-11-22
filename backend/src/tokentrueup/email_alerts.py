"""Durable SMTP delivery for signed-in users exercising the synthetic runaway demo."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any
from zoneinfo import ZoneInfo

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import settings

log = logging.getLogger("tokentrueup.email")
EASTERN = ZoneInfo("America/New_York")
MAX_ATTEMPTS = 3


def _money(cents: Any) -> str:
    try:
        return f"${float(cents) / 100:,.2f}"
    except (TypeError, ValueError):
        return "Unknown"


def build_message(row: dict[str, Any]) -> EmailMessage:
    """Build both text and HTML versions without trusting database text as HTML."""
    calc = row.get("calc") or {}
    estimate = calc.get("estimate") or calc
    projected = _money(estimate.get("projected_hourly_cents"))
    baseline = _money(estimate.get("baseline_mean_cents"))
    projected_value = float(estimate.get("projected_hourly_cents") or 0)
    baseline_value = float(estimate.get("baseline_mean_cents") or 0)
    multiple = f"{projected_value / baseline_value:.0f}×" if baseline_value > 0 else "well above normal"
    detected = row["opened_at"].astimezone(EASTERN).strftime("%b %-d, %Y at %-I:%M:%S %p %Z")
    key_label = str(row.get("key_label") or "Unknown key")
    model = str(estimate.get("model") or "Unknown model")
    case_url = f"{settings.ttu_app_url.rstrip('/')}/demo/cases/{row['case_id']}"

    subject = f"Runaway AI spend detected on {key_label}"
    text = (
        f"Hi {row['recipient_name']},\n\n"
        "Token Up detected a usage spike in the synthetic product demo.\n\n"
        f"Key: {key_label}\nModel: {model}\nDetected: {detected}\n"
        f"Projected spend: {projected}/hour\nNormal baseline: {baseline}/hour\n"
        f"Increase: {multiple}\n\nOpen anomaly case #{row['case_id']}: {case_url}\n\n"
        "This is a demonstration alert generated from synthetic data; no real provider spend occurred."
    )
    safe = {name: html.escape(str(value)) for name, value in {
        "name": row["recipient_name"], "key": key_label, "model": model, "detected": detected,
        "projected": projected, "baseline": baseline, "multiple": multiple, "url": case_url,
        "case": row["case_id"],
    }.items()}
    body = f"""\
<!doctype html><html><body style="margin:0;background:#f5f6f3;font-family:Arial,sans-serif;color:#17201b">
<div style="max-width:600px;margin:32px auto;background:#fff;border:1px solid #dde2dc;border-radius:12px;overflow:hidden">
  <div style="padding:24px 28px;background:#7f1d1d;color:#fff"><strong style="font-size:22px">Runaway AI spend detected</strong></div>
  <div style="padding:28px"><p>Hi {safe['name']},</p>
    <p>Token Up detected a usage spike in the <strong>synthetic product demo</strong>.</p>
    <table style="width:100%;border-collapse:collapse;margin:24px 0">
      <tr><td style="padding:8px;color:#667068">Key</td><td style="padding:8px"><code>{safe['key']}</code></td></tr>
      <tr><td style="padding:8px;color:#667068">Model</td><td style="padding:8px">{safe['model']}</td></tr>
      <tr><td style="padding:8px;color:#667068">Detected</td><td style="padding:8px">{safe['detected']}</td></tr>
      <tr><td style="padding:8px;color:#667068">Projected</td><td style="padding:8px"><strong>{safe['projected']}/hour</strong></td></tr>
      <tr><td style="padding:8px;color:#667068">Normal</td><td style="padding:8px">{safe['baseline']}/hour</td></tr>
      <tr><td style="padding:8px;color:#667068">Increase</td><td style="padding:8px;color:#b42318"><strong>{safe['multiple']}</strong></td></tr>
    </table>
    <p><a href="{safe['url']}" style="display:inline-block;background:#1f6338;color:#fff;text-decoration:none;padding:11px 16px;border-radius:8px">Open case #{safe['case']}</a></p>
    <p style="margin-top:26px;font-size:13px;color:#667068">This alert was generated from synthetic demo data. No real provider spend occurred.</p>
  </div>
</div></body></html>"""

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.ttu_smtp_from
    message["To"] = row["recipient"]
    if settings.ttu_smtp_message_stream:
        message["X-PM-Message-Stream"] = settings.ttu_smtp_message_stream
    message.set_content(text)
    message.add_alternative(body, subtype="html")
    return message


def _smtp_send(message: EmailMessage) -> None:
    smtp_type = smtplib.SMTP_SSL if settings.ttu_smtp_ssl else smtplib.SMTP
    kwargs = {"host": settings.ttu_smtp_host, "port": settings.ttu_smtp_port, "timeout": 10}
    if settings.ttu_smtp_ssl:
        kwargs["context"] = ssl.create_default_context()
    with smtp_type(**kwargs) as smtp:
        if settings.ttu_smtp_starttls and not settings.ttu_smtp_ssl:
            smtp.starttls(context=ssl.create_default_context())
        if settings.ttu_smtp_username:
            smtp.login(settings.ttu_smtp_username, settings.ttu_smtp_password)
        smtp.send_message(message)


async def _claim(pool: AsyncConnectionPool) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """WITH candidate AS (
                       SELECT id FROM demo_email_notifications
                       WHERE status = 'pending' AND next_attempt_at <= now()
                       ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1
                     )
                     UPDATE demo_email_notifications n
                     SET status = 'sending', attempts = attempts + 1, updated_at = now()
                     FROM candidate c WHERE n.id = c.id RETURNING n.id"""
            )
            claimed = await cur.fetchone()
            if claimed is None:
                return None
            await cur.execute(
                """SELECT n.id, n.case_id, n.user_id, n.recipient, n.recipient_name, n.attempts,
                          c.opened_at, c.calc, k.label AS key_label
                   FROM demo_email_notifications n
                   JOIN obligation_cases c ON c.id = n.case_id
                   LEFT JOIN api_keys k ON k.id = c.api_key_id
                   WHERE n.id = %s""",
                (claimed["id"],),
            )
            row = await cur.fetchone()
        await conn.commit()
        return row


async def send_one(pool: AsyncConnectionPool) -> bool:
    """Send one queued notification. Returns whether work was claimed."""
    row = await _claim(pool)
    if row is None:
        return False
    try:
        await asyncio.to_thread(_smtp_send, build_message(row))
    except Exception as exc:
        log.warning("demo email notification %s failed: %s", row["id"], type(exc).__name__)
        terminal = row["attempts"] >= MAX_ATTEMPTS
        async with pool.connection() as conn:
            await conn.execute(
                """UPDATE demo_email_notifications
                   SET status = %s, last_error = %s,
                       next_attempt_at = now() + (%s * interval '1 second'), updated_at = now()
                   WHERE id = %s""",
                ("failed" if terminal else "pending", str(exc)[:500], 5 * row["attempts"], row["id"]),
            )
            await conn.commit()
        return True

    async with pool.connection() as conn:
        await conn.execute(
            """UPDATE demo_email_notifications
               SET status = 'sent', sent_at = now(), last_error = NULL, updated_at = now()
               WHERE id = %s""",
            (row["id"],),
        )
        await conn.execute(
            "SELECT pg_notify('cases', %s)",
            (json.dumps({"event": "demo_email_sent", "case_id": row["case_id"], "user_id": row["user_id"]}),),
        )
        await conn.commit()
    return True


async def run_worker(pool: AsyncConnectionPool) -> None:
    """Continuously drain the durable queue while SMTP is configured."""
    async with pool.connection() as conn:
        await conn.execute(
            """UPDATE demo_email_notifications SET status = 'pending', updated_at = now()
               WHERE status = 'sending'"""
        )
        await conn.commit()
    while True:
        try:
            worked = await send_one(pool)
            if not worked:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("demo email worker failed; retrying")
            await asyncio.sleep(2)
