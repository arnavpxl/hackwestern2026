"""Anthropic usage adapter: pulls hourly token usage from the Admin API and normalizes it.

Uses the usage report endpoint (GET /v1/organizations/usage_report/messages), which Anthropic
marks as legacy. The field names below follow that report; they must be checked against a real
admin key before this is relied on.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx

from .common import ProviderError, client_or_new, get_json

BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"
PAGE_LIMIT = 168  # hourly buckets per page (one week)
PROVIDER = "Anthropic"

__all__ = ["ProviderError", "fetch_usage", "normalize"]


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


async def fetch_usage(key: str, start: datetime, end: datetime, *,
                      client: httpx.AsyncClient | None = None) -> AsyncIterator[dict[str, Any]]:
    """Yields normalized hourly rows for [start, end). Follows the provider's paging."""
    client, owns = client_or_new(client)
    headers = {"x-api-key": key, "anthropic-version": API_VERSION}
    try:
        page: str | None = None
        while True:
            params = [("starting_at", start.isoformat()), ("ending_at", end.isoformat()),
                      ("bucket_width", "1h"), ("limit", str(PAGE_LIMIT)),
                      ("group_by[]", "model"), ("group_by[]", "workspace_id"), ("group_by[]", "api_key_id")]
            if page:
                params.append(("page", page))
            body = await get_json(client, PROVIDER, f"{BASE_URL}/v1/organizations/usage_report/messages",
                                  params, headers)
            for bucket in body.get("data", []):
                for row in bucket.get("results", []):
                    yield normalize(bucket, row)
            if not body.get("has_more") or not body.get("next_page"):
                return
            page = body["next_page"]
    finally:
        if owns:
            await client.aclose()
