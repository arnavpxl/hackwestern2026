"""Verifier: rejects agent output containing numbers that are not traceable to a query
result / evidence row, or actions outside policy. Deterministic, no LLM."""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel

# A number not glued to letters (so 'h100', 'v4', 'cx-large' are ignored).
NUM_RE = re.compile(r"(?<![A-Za-z0-9_.])[-−]?\$?\d[\d,]*(?:\.\d+)?\s?%?(?![A-Za-z0-9_])")
SMALL_INT_LIMIT = 31  # counts, days, minutes ("3 keys", "14-day", "day 30") are not money claims


class VerifyResult(BaseModel):
    ok: bool
    unverified_numbers: list[str] = []
    disallowed_actions: list[str] = []

    @property
    def reason(self) -> str:
        parts = []
        if self.unverified_numbers:
            parts.append(f"untraceable numbers: {', '.join(self.unverified_numbers)}")
        if self.disallowed_actions:
            parts.append(f"actions outside policy: {', '.join(self.disallowed_actions)}")
        return "; ".join(parts) or "ok"


def parse_number(tok: str) -> float | None:
    s = tok.replace("−", "-").replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def extract_numbers(text: str) -> list[tuple[str, float]]:
    out = []
    for m in NUM_RE.finditer(text):
        v = parse_number(m.group(0))
        if v is not None:
            out.append((m.group(0).strip(), v))
    return out


def matches(v: float, facts: Iterable[float]) -> bool:
    for f in facts:
        tol = max(0.006 * abs(f), 0.01)
        if abs(abs(v) - abs(f)) <= tol:
            return True
    return False


def facts_from_strings(strings: Iterable[str]) -> set[float]:
    """Numbers inside context strings (dates, labels) may be repeated verbatim."""
    out: set[float] = set()
    for s in strings:
        for _, v in extract_numbers(str(s)):
            out.add(v)
        for m in re.finditer(r"\d+(?:\.\d+)?", str(s)):
            out.add(float(m.group(0)))
    return out


def verify(
    texts: Iterable[str],
    facts: set[float],
    *,
    actions: Iterable[str] = (),
    allowed_actions: Iterable[str] = (),
    context_strings: Iterable[str] = (),
) -> VerifyResult:
    allowed_facts = set(facts) | facts_from_strings(context_strings)
    bad: list[str] = []
    for text in texts:
        for tok, v in extract_numbers(text):
            if float(v).is_integer() and 0 <= v <= SMALL_INT_LIMIT and "$" not in tok and "%" not in tok:
                continue
            if not matches(v, allowed_facts):
                bad.append(tok)
    allowed = set(allowed_actions)
    disallowed = [a for a in actions if allowed and a not in allowed]
    return VerifyResult(ok=not bad and not disallowed, unverified_numbers=bad, disallowed_actions=disallowed)


def texts_of(model: BaseModel) -> list[str]:
    """All free-text fields of a schema instance."""
    out: list[str] = []
    for v in model.model_dump().values():
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            out.extend(x for x in v if isinstance(x, str))
    return out
