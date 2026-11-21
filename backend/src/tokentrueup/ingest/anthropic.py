"""Anthropic usage adapter: pulls hourly token usage from the Admin API and normalizes it.

Uses the usage report endpoint (GET /v1/organizations/usage_report/messages), which Anthropic
marks as legacy. The field names below follow that report; they must be checked against a real
admin key before this is relied on (see the step 2 notes). All Anthropic-specific code is here.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx

BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"
PAGE_LIMIT = 168  # hourly buckets per page (one week)
RETRIES = 3


class ProviderError(Exception):
    """A failure reported by the provider. Messages never contain the key."""


def normalize(bucket: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    cache_write = row.get("cache_creation") or {}
    return {
        "bucket": datetime.fromisoformat(bucket["starting_at"].replace("Z", "+00:00")),
        "model": row.get("model") or "unknown",
        "workspace_id": row.get("workspace_id") or "",
        "provider_key_id": row.get("api_key_id") or "",
        "input_tokens": int(row.get("uncached_input_tokens") or 0),
        "output_tokens": int(row.get("output_tokens") or 0),
        "cache_read_tokens": int(row.get("cache_read_input_tokens") or 0),
        "cache_write_tokens": int(cache_write.get("ephemeral_5m_input_tokens") or 0)
        + int(cache_write.get("ephemeral_1h_input_tokens") or 0),
    }


async def _get(client: httpx.AsyncClient, key: str, params: list[tuple[str, str]]) -> dict[str, Any]:
    headers = {"x-api-key": key, "anthropic-version": API_VERSION}
    for attempt in range(RETRIES):
        try:
            r = await client.get(f"{BASE_URL}/v1/organizations/usage_report/messages", params=params, headers=headers)
        except httpx.HTTPError:
            if attempt == RETRIES - 1:
                raise ProviderError("could not reach the provider") from None
            await asyncio.sleep(2**attempt)
            continue
        if r.status_code in (401, 403):
            raise ProviderError(f"the provider rejected this key ({r.status_code}); check it is an Admin API key")
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == RETRIES - 1:
                raise ProviderError(f"the provider is busy or failing ({r.status_code}); will retry next sync")
            await asyncio.sleep(2**attempt)
            continue
        if r.status_code != 200:
            raise ProviderError(f"unexpected response from the provider ({r.status_code})")
        return r.json()
    raise ProviderError("the provider did not answer")  # unreachable, keeps type checkers calm


async def fetch_usage(key: str, start: datetime, end: datetime, *,
                      client: httpx.AsyncClient | None = None) -> AsyncIterator[dict[str, Any]]:
    """Yields normalized hourly rows for [start, end). Follows the provider's paging."""
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        page: str | None = None
        while True:
            params = [("starting_at", start.isoformat()), ("ending_at", end.isoformat()),
                      ("bucket_width", "1h"), ("limit", str(PAGE_LIMIT)),
                      ("group_by[]", "model"), ("group_by[]", "workspace_id"), ("group_by[]", "api_key_id")]
            if page:
                params.append(("page", page))
            body = await _get(client, key, params)
            for bucket in body.get("data", []):
                for row in bucket.get("results", []):
                    yield normalize(bucket, row)
            if not body.get("has_more") or not body.get("next_page"):
                return
            page = body["next_page"]
    finally:
        if owns:
            await client.aclose()
