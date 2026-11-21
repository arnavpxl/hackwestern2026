"""OpenAI usage adapter: pulls hourly completions usage from the organization usage API.

Uses GET /v1/organization/usage/completions with an admin key. Buckets are unix seconds. Cached
input tokens are not confirmed in the API reference, so cache_read_tokens is 0 until verified against
a real admin key, and input_tokens is stored as the API reports it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx

from .common import ProviderError, client_or_new, get_json

BASE_URL = "https://api.openai.com"
PAGE_LIMIT = 168  # hourly buckets per page (one week)
PROVIDER = "OpenAI"

__all__ = ["ProviderError", "fetch_usage", "normalize"]


def normalize(bucket: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    return {
        "bucket": datetime.fromtimestamp(int(bucket["start_time"]), UTC),
        "model": row.get("model") or "unknown",
        "workspace_id": row.get("project_id") or "",
        "provider_key_id": row.get("api_key_id") or "",
        "input_tokens": int(row.get("input_tokens") or 0),
        "output_tokens": int(row.get("output_tokens") or 0),
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }


async def fetch_usage(key: str, start: datetime, end: datetime, *,
                      client: httpx.AsyncClient | None = None) -> AsyncIterator[dict[str, Any]]:
    """Yields normalized hourly rows for [start, end). Follows the provider's paging."""
    client, owns = client_or_new(client)
    headers = {"Authorization": f"Bearer {key}"}
    try:
        page: str | None = None
        while True:
            params = [("start_time", str(int(start.timestamp()))), ("end_time", str(int(end.timestamp()))),
                      ("bucket_width", "1h"), ("limit", str(PAGE_LIMIT)),
                      ("group_by", "model"), ("group_by", "project_id"), ("group_by", "api_key_id")]
            if page:
                params.append(("page", page))
            body = await get_json(client, PROVIDER, f"{BASE_URL}/v1/organization/usage/completions", params, headers)
            for bucket in body.get("data", []):
                for row in bucket.get("results", []):
                    yield normalize(bucket, row)
            if not body.get("has_more") or not body.get("next_page"):
                return
            page = body["next_page"]
    finally:
        if owns:
            await client.aclose()
