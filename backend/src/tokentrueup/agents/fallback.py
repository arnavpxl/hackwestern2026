"""Rule-based fallback agents: same schemas as the LLM agents, no API key needed."""

from __future__ import annotations

import re

from .schemas import ContractTerms, Explanation, ReplyInterpretation, VarianceNarrative, VolumeTier

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def parse_contract(text: str) -> ContractTerms:
    t = ContractTerms()
    low = text.lower()
    if m := re.search(r"cached[^.]*?(\d+(?:\.\d+)?)%\s*discount", low) or re.search(
        r"(\d+(?:\.\d+)?)%\s*discount[^.]*cached", low
    ):
        t.cached_discount_pct = float(m.group(1))
        t.clause_quotes.append(_sentence(text, m.start()))
    if m := re.search(r"batch[^.]*?(\d+(?:\.\d+)?)%\s*of list", low):
        t.batch_discount_pct = 100 - float(m.group(1))
        t.clause_quotes.append(_sentence(text, m.start()))
    for m in re.finditer(r"(\d+(?:\.\d+)?)%[^.,]*?above (\d+(?:\.\d+)?) billion", low):
        t.volume_tiers.append(VolumeTier(from_tokens=float(m.group(2)) * 1e9, discount_pct=float(m.group(1))))
    if t.volume_tiers:
        t.volume_tiers.insert(0, VolumeTier(from_tokens=0, discount_pct=0))
    if m := re.search(r"(\d+) seats at \$([\d,.]+)", low):
        t.seats = int(m.group(1))
        t.fixed_monthly_usd = t.seats * float(m.group(2).replace(",", ""))
    elif m := re.search(r"\$([\d,]+\.\d{2}) per month", low):
        t.fixed_monthly_usd = float(m.group(1).replace(",", ""))
    return t


def _sentence(text: str, pos: int) -> str:
    start = text.rfind(".", 0, pos) + 1
    end = text.find(".", pos)
    return text[start : end + 1 if end != -1 else len(text)].strip()


def interpret_reply(body: str, case_type: str) -> ReplyInterpretation:
    low = body.lower()
    email = EMAIL_RE.search(body)
    credit = "credit" in low or "refund" in low
    if case_type != "anomaly" and email:
        return ReplyInterpretation(intent="assign_owner", owner_email=email.group(0), credit_expected=False,
                                   summary="Owner identified for the key; accrue under their team.",
                                   recommended_action="accrue")
    if re.search(r"\b(still|ongoing|can't stop|cannot stop|not sure how)\b", low):
        return ReplyInterpretation(intent="bug_ongoing", credit_expected=credit,
                                   summary="Owner reports the runaway usage is still happening.",
                                   recommended_action="escalate_to_controller")
    if re.search(r"\b(killed|stopped|fixed|bug|loop|runaway|shut)\b", low):
        return ReplyInterpretation(intent="bug_fixed", credit_expected=credit,
                                   summary="Owner confirms a bug caused the spike and it has been stopped.",
                                   recommended_action="accrue_with_adjustment")
    if re.search(r"\b(expected|intentional|planned|load test|launch|backfill)\b", low):
        return ReplyInterpretation(intent="confirm_expected", credit_expected=False,
                                   summary="Owner confirms the usage was expected.", recommended_action="accrue")
    if email:
        return ReplyInterpretation(intent="assign_owner", owner_email=email.group(0), credit_expected=False,
                                   summary="Reply names an owner for the key.", recommended_action="accrue")
    return ReplyInterpretation(intent="unclear", summary="Reply could not be interpreted; ask again.",
                               recommended_action="ask_owner")


def explain(case: dict, est: dict) -> Explanation:
    amt = est["amount_cents"] / 100
    bullets = [est["summary"]]
    for line in est.get("lines", [])[:4]:
        label = line.get("key_label") or line.get("name") or line.get("description") or line.get("po_number")
        val = line.get("line_total_cents", line.get("amount_cents", line.get("excess_cents")))
        if label is not None and val is not None:
            bullets.append(f"{label}: ${val / 100:,.2f}")
    for flag in est.get("flags", []):
        bullets.append({"orphan_key_excluded": "A key with no owner was excluded until someone claims it.",
                        "open_anomaly": "An open spend anomaly must be explained before approval."}.get(flag, flag))
    action = "ask_owner" if est.get("flags") else "accrue"
    return Explanation(headline=f"Accrue ${amt:,.2f} for {case['title']}", bullets=bullets,
                       recommended_action=action)


def narrate_variance(diag: dict) -> VarianceNarrative:
    v = diag["variance_cents"] / 100
    bullets = [f"{c['cause']}: ${c['amount_cents'] / 100:,.2f}" for c in diag.get("causes", [])]
    direction = "above" if v > 0 else "below"
    return VarianceNarrative(
        summary=f"Invoice is ${abs(v):,.2f} {direction} the accrual ({diag['variance_pct']:.2f}%).",
        bullets=bullets or ["No specific cause identified."],
    )
