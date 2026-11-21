"""Pydantic schemas every agent output is forced into (LLM structured output or fallback)."""

from typing import Literal

from pydantic import BaseModel, Field

Action = Literal[
    "ask_owner", "accrue", "accrue_with_adjustment", "exclude_from_accrual",
    "escalate_to_controller", "mark_duplicate", "propose_rule", "no_action",
]


class VolumeTier(BaseModel):
    from_tokens: float = Field(description="Monthly token volume at which this tier starts")
    discount_pct: float


class ContractTerms(BaseModel):
    """Terms extracted from unstructured contract / pricing text."""

    cached_discount_pct: float | None = Field(None, description="Extra % discount on cached input tokens, if stated")
    batch_discount_pct: float | None = Field(None, description="% discount for batch API usage, if stated")
    volume_tiers: list[VolumeTier] = []
    fixed_monthly_usd: float | None = None
    seats: int | None = None
    clause_quotes: list[str] = Field(default_factory=list, description="Verbatim quotes supporting each term")


class ReplyInterpretation(BaseModel):
    """Interpretation of a free-text owner reply in the simulated inbox."""

    intent: Literal["confirm_expected", "bug_fixed", "bug_ongoing", "assign_owner", "unclear"]
    owner_email: str | None = Field(None, description="Email of the person who owns the key, if named")
    credit_expected: bool = Field(False, description="Owner says the provider will credit the spend")
    summary: str = Field(description="One sentence, no numbers that are not in the reply")
    recommended_action: Action


class Explanation(BaseModel):
    """Plain-English explanation of an accrual. Numbers must come from the calc."""

    headline: str
    bullets: list[str]
    recommended_action: Action


class VarianceNarrative(BaseModel):
    """Narrative for a reconciliation variance. Numbers must come from the diagnosis."""

    summary: str
    bullets: list[str]
