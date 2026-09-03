"""
Deterministic-logic tests only — no API calls. Mirrors the August build's
test_main.py pattern (brief §4: "Deterministic-logic tests, no API calls").

Covers the pieces that must never depend on model output being well-formed:
sanitize()'s fallback-to-safe-default behavior, enumerate_evidence()'s
deterministic ID assignment, _execute_tool()'s refusal to trust
model-supplied identifiers, and is_fallback_row()'s resume detection.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "code"))

from main import (  # noqa: E402
    sanitize, enumerate_evidence, _execute_tool, is_fallback_row,
    apply_deterministic_overrides,
    SAFE_FALLBACK, DECISION_VALUES, RISK_FLAG_VALUES,
)
import risk_signals  # noqa: E402


def test_sanitize_rejects_invalid_decision():
    result = sanitize({
        "decision": "definitely_contest_this",  # not a real enum value
        "evidence_sufficiency": "sufficient",
        "risk_flags": ["none"],
        "reason": "test",
        "confidence": 0.9,
        "cited_evidence_ids": "ev_1",
    })
    assert result["decision"] == "manual_review"
    assert "manual_review_required" in result["risk_flags"]


def test_sanitize_clamps_confidence():
    result = sanitize({
        "decision": "contest",
        "evidence_sufficiency": "sufficient",
        "risk_flags": ["none"],
        "reason": "test",
        "confidence": 1.7,
        "cited_evidence_ids": "ev_1",
    })
    assert result["confidence"] == 1.0

    result2 = sanitize({
        "decision": "contest",
        "evidence_sufficiency": "sufficient",
        "risk_flags": ["none"],
        "reason": "test",
        "confidence": "not_a_number",
        "cited_evidence_ids": "ev_1",
    })
    assert result2["confidence"] == 0.5


def test_sanitize_filters_unknown_risk_flags():
    result = sanitize({
        "decision": "accept_liability",
        "evidence_sufficiency": "insufficient",
        "risk_flags": ["amount_anomaly", "made_up_flag", "none"],
        "reason": "test",
        "confidence": 0.6,
        "cited_evidence_ids": "none",
    })
    assert result["risk_flags"] == ["amount_anomaly"]
    assert all(f in RISK_FLAG_VALUES for f in result["risk_flags"])


def test_sanitize_normalizes_evidence_id_list_to_string():
    result = sanitize({
        "decision": "contest",
        "evidence_sufficiency": "sufficient",
        "risk_flags": ["none"],
        "reason": "test",
        "confidence": 0.8,
        "cited_evidence_ids": ["ev_1", "ev_3"],
    })
    assert result["cited_evidence_ids"] == "ev_1;ev_3"


def test_sanitize_manual_review_always_carries_the_flag():
    result = sanitize({
        "decision": "manual_review",
        "evidence_sufficiency": "not_enough_information",
        "risk_flags": ["none"],  # model forgot to add the flag itself
        "reason": "ambiguous",
        "confidence": 0.4,
        "cited_evidence_ids": "none",
    })
    assert "manual_review_required" in result["risk_flags"]


def test_enumerate_evidence_assigns_deterministic_ids_and_parses_type():
    row = {"evidence_items": "proof_of_delivery: signed delivery slip | shipping_carrier_record: courier tracking screenshot"}
    out = enumerate_evidence(row)
    assert [e["evidence_id"] for e in out] == ["ev_1", "ev_2"]
    assert out[0]["type"] == "proof_of_delivery"
    assert out[0]["description"] == "signed delivery slip"
    assert out[1]["type"] == "shipping_carrier_record"


def test_enumerate_evidence_handles_empty():
    assert enumerate_evidence({"evidence_items": ""}) == []
    assert enumerate_evidence({}) == []


def test_execute_tool_ignores_model_supplied_args_and_uses_ctx():
    ctx = {
        "transaction_summary": "amount=500 INR",
        "minimum_evidence_required": "delivery proof",
        "merchant_narrative": "we shipped it",
        "evidence_candidates": [{"evidence_id": "ev_1", "type": "proof_of_delivery", "description": "tracking"}],
        "evidence_sufficiency_precomputed": "sufficient",
        "missing_evidence_types": [],
        "amount_anomaly_flag": False,
        "merchant_history_summary": "chargeback_rate_30d=1.2%",
        "merchant_repeat_pattern_flag": False,
    }
    # A model could pass a completely different / hallucinated case_id here —
    # _execute_tool must not care, since it never reads its own arguments.
    result = _execute_tool("lookup_case_evidence", ctx)
    assert result["transaction_summary"] == "amount=500 INR"
    assert result["evidence_candidates"] == ctx["evidence_candidates"]
    assert result["evidence_sufficiency_precomputed"] == "sufficient"

    result2 = _execute_tool("lookup_merchant_history", ctx)
    assert result2["merchant_history_summary"] == "chargeback_rate_30d=1.2%"
    assert result2["merchant_repeat_pattern_flag"] is False

    result3 = _execute_tool("nonexistent_tool", ctx)
    assert "error" in result3


def test_execute_tool_adds_inline_reminder_only_when_flag_is_true():
    base_ctx = {
        "transaction_summary": "amount=500 INR",
        "minimum_evidence_required": "delivery proof",
        "merchant_narrative": "we shipped it",
        "evidence_candidates": [],
        "evidence_sufficiency_precomputed": "sufficient",
        "missing_evidence_types": [],
        "merchant_history_summary": "chargeback_rate_30d=1.2%",
    }
    # Flag false - no reminder field at all, not even an empty one.
    no_flag_ctx = {**base_ctx, "amount_anomaly_flag": False, "merchant_repeat_pattern_flag": False}
    assert "amount_anomaly_flag_reminder" not in _execute_tool("lookup_case_evidence", no_flag_ctx)
    assert "merchant_repeat_pattern_flag_reminder" not in _execute_tool("lookup_merchant_history", no_flag_ctx)

    # Flag true - reminder present, and it says the flag is true.
    flagged_ctx = {**base_ctx, "amount_anomaly_flag": True, "merchant_repeat_pattern_flag": True}
    r1 = _execute_tool("lookup_case_evidence", flagged_ctx)
    assert "TRUE" in r1["amount_anomaly_flag_reminder"]
    r2 = _execute_tool("lookup_merchant_history", flagged_ctx)
    assert "TRUE" in r2["merchant_repeat_pattern_flag_reminder"]


def test_apply_deterministic_overrides_pins_evidence_sufficiency():
    ctx = {
        "evidence_sufficiency_precomputed": "insufficient",
        "amount_anomaly_flag": False,
        "merchant_repeat_pattern_flag": False,
    }
    # Model guessed wrong (said sufficient) — override must correct it.
    result = {"decision": "contest", "evidence_sufficiency": "sufficient", "risk_flags": ["none"]}
    out = apply_deterministic_overrides(result, ctx)
    assert out["evidence_sufficiency"] == "insufficient"
    assert "evidence_incomplete_for_reason_code" in out["risk_flags"]


def test_apply_deterministic_overrides_adds_amount_anomaly_and_repeat_pattern():
    ctx = {
        "evidence_sufficiency_precomputed": "sufficient",
        "amount_anomaly_flag": True,
        "merchant_repeat_pattern_flag": True,
    }
    result = {"decision": "contest", "evidence_sufficiency": "sufficient", "risk_flags": ["none"]}
    out = apply_deterministic_overrides(result, ctx)
    assert "amount_anomaly" in out["risk_flags"]
    assert "merchant_repeat_pattern" in out["risk_flags"]
    assert "none" not in out["risk_flags"]


def test_apply_deterministic_overrides_removes_incorrectly_claimed_flags():
    ctx = {
        "evidence_sufficiency_precomputed": "sufficient",
        "amount_anomaly_flag": False,
        "merchant_repeat_pattern_flag": False,
    }
    # Model incorrectly claimed amount_anomaly when the computed flag says False.
    result = {"decision": "contest", "evidence_sufficiency": "sufficient", "risk_flags": ["amount_anomaly"]}
    out = apply_deterministic_overrides(result, ctx)
    assert out["risk_flags"] == ["none"]


def test_risk_signals_evidence_sufficiency_three_states():
    required = {"proof_of_delivery", "shipping_carrier_record"}
    assert risk_signals.evidence_sufficiency([], required)[0] == "not_enough_information"
    partial = [{"evidence_id": "ev_1", "type": "proof_of_delivery", "description": "x"}]
    label, missing = risk_signals.evidence_sufficiency(partial, required)
    assert label == "insufficient"
    assert missing == ["shipping_carrier_record"]
    full = partial + [{"evidence_id": "ev_2", "type": "shipping_carrier_record", "description": "y"}]
    assert risk_signals.evidence_sufficiency(full, required) == ("sufficient", [])


def test_risk_signals_amount_anomaly():
    assert risk_signals.is_amount_anomaly({"amount": "500", "original_amount": "500"}) is False
    assert risk_signals.is_amount_anomaly({"amount": "600", "original_amount": "500"}) is True  # exceeds original
    assert risk_signals.is_amount_anomaly({"amount": "400", "original_amount": "500"}) is True  # partial mismatch flagged


def test_risk_signals_merchant_repeat_pattern_needs_both_conditions():
    # High rate but good win record — not a repeat-pattern flag on its own.
    assert risk_signals.is_merchant_repeat_pattern({"chargeback_rate_90d": "2.0", "prior_contest_win_rate": "0.8"}) is False
    # High rate AND poor win record — flagged.
    assert risk_signals.is_merchant_repeat_pattern({"chargeback_rate_90d": "2.0", "prior_contest_win_rate": "0.1"}) is True
    # Low rate, poor win record — not flagged, rate alone doesn't trigger it.
    assert risk_signals.is_merchant_repeat_pattern({"chargeback_rate_90d": "0.1", "prior_contest_win_rate": "0.1"}) is False


def test_is_fallback_row_detects_the_safe_placeholder():
    fallback_row = {"reason": SAFE_FALLBACK["reason"]}
    real_row = {"reason": "ev_2 is a signed delivery confirmation matching the transaction date."}
    assert is_fallback_row(fallback_row) is True
    assert is_fallback_row(real_row) is False


def test_decision_values_match_the_brief_schema():
    assert DECISION_VALUES == {"contest", "accept_liability", "manual_review"}


if __name__ == "__main__":
    import subprocess
    subprocess.run([sys.executable, "-m", "pytest", str(Path(__file__)), "-v"])
