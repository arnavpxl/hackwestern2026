"""Agent runner: LLM (Anthropic structured outputs) when ANTHROPIC_API_KEY is set, else the
rule-based fallback. Every output is a Pydantic model and passes the verifier; a rejected
LLM output is retried once with the verifier's feedback, then replaced by the fallback."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from ..config import settings
from . import fallback
from .schemas import ContractTerms, Explanation, ReplyInterpretation, VarianceNarrative
from .verifier import VerifyResult, texts_of, verify

log = logging.getLogger("tokentrueup.agents")

SYSTEM = (
    "You are a finance operations assistant for month-end accruals of AI/cloud API spend. "
    "Deterministic SQL has already computed every dollar figure. You ONLY interpret text and explain. "
    "Never invent, round differently, or derive new numbers: any number you write must appear verbatim in the "
    "FACTS provided. Prefer fewer numbers. Recommended actions must be one of the allowed actions."
)


@dataclass
class AgentRun:
    agent: str
    mode: str  # 'llm' | 'fallback' | 'fallback_after_reject'
    output: BaseModel
    verification: VerifyResult
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def audit(self) -> dict[str, Any]:
        return {"agent": self.agent, "mode": self.mode, "verified": self.verification.ok,
                "verifier": self.verification.model_dump(), "attempts": self.attempts}


_client = None


def _anthropic():
    global _client
    if _client is None:
        from anthropic import AsyncAnthropic

        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def _llm(schema: type[BaseModel], prompt: str) -> BaseModel | None:
    resp = await _anthropic().messages.parse(
        model=settings.anthropic_model,
        max_tokens=4000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=schema,
    )
    if resp.stop_reason == "refusal":
        return None
    return resp.parsed_output


async def run_agent(
    name: str,
    schema: type[BaseModel],
    prompt: str,
    fallback_fn,
    *,
    facts: set[float],
    allowed_actions: list[str],
    context_strings: list[str] = (),
    action_field: str | None = "recommended_action",
) -> AgentRun:
    def check(out: BaseModel) -> VerifyResult:
        actions = [getattr(out, action_field)] if action_field and hasattr(out, action_field) else []
        return verify(texts_of(out), facts, actions=actions, allowed_actions=allowed_actions,
                      context_strings=context_strings)

    attempts: list[dict[str, Any]] = []
    if settings.llm_enabled:
        p = prompt
        for attempt in range(2):
            try:
                out = await _llm(schema, p)
            except Exception as e:  # network / API errors fall back, never block close
                log.warning("LLM agent %s failed: %s", name, e)
                attempts.append({"attempt": attempt + 1, "error": str(e)[:300]})
                break
            if out is None:
                attempts.append({"attempt": attempt + 1, "error": "refusal"})
                break
            vr = check(out)
            attempts.append({"attempt": attempt + 1, "output": out.model_dump(), "verifier": vr.model_dump()})
            if vr.ok:
                return AgentRun(name, "llm", out, vr, attempts)
            p = (f"{prompt}\n\nYour previous answer was REJECTED by the verifier: {vr.reason}. "
                 "Rewrite it using only numbers from FACTS, or no numbers at all.")
    out = fallback_fn()
    vr = check(out)
    return AgentRun(name, "fallback_after_reject" if attempts else "fallback", out, vr, attempts)


# ------------------------------------------------------------------ agents

async def contract_parser(text: str) -> AgentRun:
    prompt = f"Extract the commercial terms from this contract text.\n\nCONTRACT:\n{text}\n\nFACTS: the contract text."
    return await run_agent("contract_parser", ContractTerms, prompt, lambda: fallback.parse_contract(text),
                           facts=set(), allowed_actions=[], context_strings=[text], action_field=None)


async def reply_interpreter(body: str, case: dict, allowed_actions: list[str]) -> AgentRun:
    prompt = (f"A key owner replied to our question about case '{case['title']}' (type {case['type']}).\n"
              f"OUR QUESTION:\n{case.get('question', '')}\n\nOWNER REPLY:\n{body}\n\n"
              f"Allowed actions: {allowed_actions}. FACTS: only the text above.")
    return await run_agent("reply_interpreter", ReplyInterpretation, prompt,
                           lambda: fallback.interpret_reply(body, case["type"]),
                           facts=set(), allowed_actions=allowed_actions,
                           context_strings=[body, case["title"], case.get("question", "")])


async def explainer(case: dict, est: dict, facts: set[float], allowed_actions: list[str]) -> AgentRun:
    compact = {k: est[k] for k in ("kind", "amount_cents", "summary", "flags") if k in est}
    compact["lines"] = est.get("lines", [])[:8]
    prompt = (f"Explain this accrual to a controller in a headline and up to 5 bullets.\nCASE: {case['title']}\n"
              f"FACTS (JSON; cents fields may be shown as dollars = cents/100):\n{json.dumps(compact, default=str)}\n"
              f"Allowed actions: {allowed_actions}")
    return await run_agent("explainer", Explanation, prompt, lambda: fallback.explain(case, est),
                           facts=facts, allowed_actions=allowed_actions, context_strings=[case["title"]])


async def variance_narrator(diag: dict, facts: set[float]) -> AgentRun:
    prompt = ("Write a short variance narrative (summary + bullets) for this reconciliation diagnosis.\n"
              f"FACTS (JSON; cents may be shown as dollars):\n{json.dumps(diag, default=str)}")
    return await run_agent("variance_narrator", VarianceNarrative, prompt, lambda: fallback.narrate_variance(diag),
                           facts=facts, allowed_actions=[], action_field=None)


__all__ = ["AgentRun", "Explanation", "contract_parser", "explainer", "reply_interpreter", "variance_narrator"]
