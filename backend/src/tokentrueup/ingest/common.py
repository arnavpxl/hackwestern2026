"""Shared HTTP handling for provider usage APIs: retries, rate limits, and readable errors.

Error messages name the provider and the reason, never the key or the request headers.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

RETRIES = 3


class ProviderError(Exception):
    """A failure reported by a provider. The message is safe to show and store."""


async def get_json(client: httpx.AsyncClient, provider: str, url: str, params: list[tuple[str, str]],
                   headers: dict[str, str]) -> dict[str, Any]:
    for attempt in range(RETRIES):
        try:
            r = await client.get(url, params=params, headers=headers)
        except httpx.HTTPError:
            if attempt == RETRIES - 1:
                raise ProviderError(f"could not reach {provider}") from None
            await asyncio.sleep(2**attempt)
            continue
        if r.status_code in (401, 403):
            raise ProviderError(f"{provider} rejected this key ({r.status_code}); check it is an admin key")
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == RETRIES - 1:
                raise ProviderError(f"{provider} is busy or failing ({r.status_code}); will retry next sync")
            await asyncio.sleep(2**attempt)
            continue
        if r.status_code != 200:
            raise ProviderError(f"unexpected response from {provider} ({r.status_code})")
        return r.json()
    raise ProviderError(f"{provider} did not answer")  # unreachable: the loop always returns or raises


def client_or_new(client: httpx.AsyncClient | None) -> tuple[httpx.AsyncClient, bool]:
    return (client, False) if client is not None else (httpx.AsyncClient(timeout=30), True)
