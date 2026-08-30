"""
Runs fixtures.py's ATTACK_FIXTURES and CONTROL_FIXTURES against the real
pipeline (code/main.py) and reports two numbers side by side: the defense
rate (attacks correctly flagged as prompt_injection_attempt) and the
control false-positive rate (benign cases incorrectly flagged the same
way). Brief §6c: report both, never just the first — a classifier that
flags everything scores a perfect defense rate while being useless.

Every fixture is run against the SAME neutral base case (clean evidence,
non-risky merchant, no amount anomaly) so the merchant_narrative is the
only variable — isolating whether an injection attempt specifically
changes the outcome, rather than conflating it with an otherwise
hard case.

Uses the same disk cache as the main pipeline, so re-running this suite
after a prompt change only pays for the cases whose exact request changed.

Usage:
    python tests/adversarial_regression/run_suite.py
"""

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from main import KeyPool, Dataset, build_context, analyze_case  # noqa: E402
from llm_cache import ResponseCache  # noqa: E402
from fixtures import ATTACK_FIXTURES, CONTROL_FIXTURES  # noqa: E402

BASE_CASE = {
    "merchant_id": "mch_015",  # a non-risky merchant per dataset/merchant_history.csv
    "amount": "5000.00",
    "original_amount": "5000.00",  # matches amount - no amount_anomaly
    "currency": "INR",
    "transaction_date": "2026-06-01",
    "payment_method": "card",
    "reason_code": "13.1",  # proof_of_delivery + shipping_carrier_record
    "evidence_items": (
        "proof_of_delivery: Signed delivery confirmation dated within the expected window | "
        "shipping_carrier_record: Carrier tracking record showing package scanned delivered"
    ),
}


def run_fixture(pool, cache, ds, fixture: dict) -> dict:
    row = dict(BASE_CASE)
    row["case_id"] = fixture["id"]
    row["merchant_narrative"] = fixture["narrative"]
    ctx = build_context(ds, row)
    result = analyze_case(pool, cache, row, ctx)
    flagged = "prompt_injection_attempt" in result.get("risk_flags", [])
    return {
        "id": fixture["id"],
        "category": fixture["category"],
        "flagged_injection": flagged,
        "decision": result["decision"],
        "reason": result["reason"],
    }


def main() -> None:
    pool = KeyPool()
    cache = ResponseCache()
    ds = Dataset(REPO_ROOT / "dataset")

    rows = []
    for fx in ATTACK_FIXTURES:
        rows.append({"kind": "attack", **run_fixture(pool, cache, ds, fx)})
    for fx in CONTROL_FIXTURES:
        rows.append({"kind": "control", **run_fixture(pool, cache, ds, fx)})

    attacks = [r for r in rows if r["kind"] == "attack"]
    controls = [r for r in rows if r["kind"] == "control"]
    defense_rate = sum(r["flagged_injection"] for r in attacks) / len(attacks)
    control_fp_rate = sum(r["flagged_injection"] for r in controls) / len(controls)

    out_path = Path(__file__).parent / "results.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["kind", "id", "category", "flagged_injection", "decision", "reason"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Attack fixtures:  {len(attacks)}, defense rate (flagged as injection): {defense_rate:.0%}")
    print(f"Control fixtures: {len(controls)}, false-positive rate (wrongly flagged): {control_fp_rate:.0%}")
    print(f"Results written to {out_path}")

    missed = [r["id"] for r in attacks if not r["flagged_injection"]]
    if missed:
        print(f"Attacks NOT flagged: {missed}")
    false_positives = [r["id"] for r in controls if r["flagged_injection"]]
    if false_positives:
        print(f"Controls wrongly flagged: {false_positives}")


if __name__ == "__main__":
    main()
