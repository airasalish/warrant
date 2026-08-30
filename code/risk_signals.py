"""
Deterministic risk signals — shared between the runtime pipeline
(code/main.py) and the dataset label generator (scripts/generate_dataset.py).

Sharing this module between the two is intentional, not circular: it
computes FEATURES (evidence sufficiency, amount anomaly, merchant repeat
pattern), never the final decision. The runtime pipeline hands these
features to the LLM as pre-computed facts (so the model isn't reinventing
evidence-matching from raw text — see the brief's "deterministic signals
computed in code, not in the prompt" principle); the label generator uses
the same features as inputs to its own separate decision rule.

The decision rule itself (which combines these features into a ground-truth
contest/accept_liability/manual_review label) lives ONLY in
scripts/generate_dataset.py — deliberately not importable from here, so
code/main.py has no code path that could ever consult it. That's what
keeps this non-circular: the model never sees the answer, only the
features a human-written rubric also happens to use.
"""

PLATFORM_BASELINE_CHARGEBACK_RATE = 0.6  # percent; synthetic assumption, stated here so it's auditable

AMOUNT_ANOMALY_TOLERANCE = 0.01  # currency units; rounding slack only


def parse_evidence_items(row: dict) -> list:
    """Parses a case's pipe-separated evidence_items field into structured
    items: [{"evidence_id", "type", "description"}, ...]. Each item is
    expected as "type_tag: free text description". Deterministic ID
    assignment in file order — the model may only cite these IDs, never
    invent one."""
    raw = (row.get("evidence_items") or "").strip()
    if not raw:
        return []
    items = []
    for i, chunk in enumerate([c.strip() for c in raw.split("|") if c.strip()], 1):
        if ":" in chunk:
            tag, desc = chunk.split(":", 1)
            tag, desc = tag.strip(), desc.strip()
        else:
            tag, desc = "unknown", chunk
        items.append({"evidence_id": f"ev_{i}", "type": tag, "description": desc})
    return items


def required_evidence_types(req_row: dict) -> set:
    """Parses reason_code_requirements.csv's pipe-separated required-types column."""
    raw = (req_row.get("required_evidence_types") or "").strip()
    return {t.strip() for t in raw.split("|") if t.strip()}


def evidence_sufficiency(evidence_items: list, required_types: set) -> tuple:
    """Returns (sufficiency_label, missing_types) per the rubric's §2:
    - not_enough_information: nothing submitted at all.
    - insufficient: some but not all required types present.
    - sufficient: every required type present."""
    if not evidence_items:
        return "not_enough_information", sorted(required_types)
    present = {item["type"] for item in evidence_items}
    missing = required_types - present
    if missing:
        return "insufficient", sorted(missing)
    return "sufficient", []


def is_amount_anomaly(row: dict) -> bool:
    """True if the disputed amount doesn't match the original transaction
    amount on file, or exceeds it — a partial chargeback can never be
    larger than the original transaction. Rubric §3."""
    try:
        amount = float(row.get("amount", 0))
        original = float(row.get("original_amount", amount))
    except (TypeError, ValueError):
        return False
    if amount > original + AMOUNT_ANOMALY_TOLERANCE:
        return True
    return abs(amount - original) > AMOUNT_ANOMALY_TOLERANCE and amount != original


def is_merchant_repeat_pattern(merchant_row: dict, baseline: float = PLATFORM_BASELINE_CHARGEBACK_RATE) -> bool:
    """True if the merchant's chargeback rate is above the platform
    baseline AND their prior contest win rate is low. Rubric §3 — a single
    number alone (high chargeback rate) isn't the flag; it's the
    combination with a poor contest track record."""
    try:
        rate = float(merchant_row.get("chargeback_rate_90d", 0))
        win_rate = float(merchant_row.get("prior_contest_win_rate", 1))
    except (TypeError, ValueError):
        return False
    return rate > baseline and win_rate < 0.4
