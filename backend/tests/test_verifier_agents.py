"""Verifier + rule-based fallback agents (no DB, no API key)."""

from tokentrueup.agents import fallback
from tokentrueup.agents.schemas import Explanation
from tokentrueup.agents.verifier import extract_numbers, texts_of, verify
from tokentrueup.sim.catalog import CONTRACTS

ALLOWED = ["ask_owner", "accrue", "escalate_to_controller"]


def test_traceable_numbers_pass():
    facts = {123456.0, 1234.56, 10.0}
    r = verify(["Accrue $1,234.56 (10% tier) across 3 keys"], facts)
    assert r.ok, r.reason


def test_invented_number_rejected():
    r = verify(["Accrue $1,250.00 to be safe"], {123456.0, 1234.56})
    assert not r.ok and r.unverified_numbers == ["$1,250.00"]


def test_rounded_dollars_within_tolerance():
    assert verify(["about $1,235"], {1234.56}).ok


def test_model_names_and_small_counts_ignored():
    assert verify(["h100 and cx-large over 14 days, 3 keys"], set()).ok


def test_dollar_small_ints_still_checked():
    assert not verify(["costs $5"], set()).ok


def test_context_strings_allow_dates():
    r = verify(["since 2026-11-03"], set(), context_strings=["window from 2026-11-03T04:00"])
    assert r.ok, r.reason


def test_action_outside_policy_rejected():
    out = Explanation(headline="x", bullets=[], recommended_action="propose_rule")
    r = verify(texts_of(out), set(), actions=[out.recommended_action], allowed_actions=ALLOWED)
    assert not r.ok and r.disallowed_actions == ["propose_rule"]


def test_extract_numbers_formats():
    vals = [v for _, v in extract_numbers("$1,234.56 and 12.5% and −40 and v4")]
    assert vals == [1234.56, 12.5, -40.0]


def _contract(provider, kind="usage"):
    return next(c for c in CONTRACTS if c["provider_id"] == provider and c["kind"] == kind)["source_text"]


def test_contract_parser_cached_discount():
    t = fallback.parse_contract(_contract("cortexa"))
    assert t.cached_discount_pct == 50
    assert t.clause_quotes and "cached" in t.clause_quotes[0].lower()


def test_contract_parser_tiers_and_batch():
    t = fallback.parse_contract(_contract("nimbus-llm"))
    assert [(x.from_tokens, x.discount_pct) for x in t.volume_tiers] == [(0, 0), (15e9, 5), (30e9, 8)]
    assert t.batch_discount_pct == 50


def test_contract_parser_seats():
    t = fallback.parse_contract(_contract("vectorhaus", "committed"))
    assert t.seats == 25 and t.fixed_monthly_usd == 1000


def test_reply_interpreter_intents():
    assert fallback.interpret_reply("Agent got stuck in a loop, I killed it", "anomaly").intent == "bug_fixed"
    assert fallback.interpret_reply("Yes this is the planned load test", "anomaly").intent == "confirm_expected"
    assert fallback.interpret_reply("it's still going, can't stop it", "anomaly").intent == "bug_ongoing"
    r = fallback.interpret_reply("That's tomas.i@example.test's scraper", "usage")
    assert r.intent == "assign_owner" and r.owner_email == "tomas.i@example.test"
    assert fallback.interpret_reply("hmm?", "anomaly").intent == "unclear"


def test_fallback_explanation_passes_verifier():
    est = {"kind": "usage", "amount_cents": 4169345, "summary": "MTD 28,301.09 + projected 13,392.36",
           "flags": ["orphan_key_excluded"],
           "lines": [{"key_label": "growth-search", "line_total_cents": 4169345, "mtd_cents": 2830109,
                      "projected_cents": 1339236}]}
    exp = fallback.explain({"title": "Quill usage"}, est)
    facts = {4169345.0, 41693.45, 2830109.0, 28301.09, 1339236.0, 13392.36}
    assert verify(texts_of(exp), facts, actions=[exp.recommended_action], allowed_actions=ALLOWED).ok
