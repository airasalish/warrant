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
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))

from main import KeyPool, Dataset, build_context, analyze_case, is_fallback_row  # noqa: E402
from llm_cache import ResponseCache  # noqa: E402
from fixtures import ATTACK_FIXTURES, CONTROL_FIXTURES  # noqa: E402

RESULTS_PATH = Path(__file__).parent / "results.csv"
LOCK_PATH = Path(__file__).parent / ".run_suite.lock"
FIELDNAMES = ["kind", "id", "category", "flagged_injection", "decision", "reason"]


class AlreadyRunningError(Exception):
    pass


def acquire_lock() -> None:
    """Refuses to start a second overlapping run against the same
    results.csv. Found the hard way: results.csv regressed from 33/34
    genuine fixtures to 21/34 after what looks like two runs racing on the
    same file — each one reads load_existing_results() once at startup, so
    a run that starts while an earlier one is mid-write can see a smaller
    "done" set than what's actually on disk, re-attempt fixtures that were
    already genuinely evaluated, and overwrite good results with fresh
    fallback rows if those re-attempts hit a quota wall. A lock file makes
    that structurally impossible instead of relying on "don't launch two
    of these," which already failed once."""
    if LOCK_PATH.exists():
        age = time.time() - LOCK_PATH.stat().st_mtime
        raise AlreadyRunningError(
            f"{LOCK_PATH} exists (age {age:.0f}s) — another run_suite.py is either still "
            f"running, or a prior one crashed without cleaning up. If you're SURE nothing "
            f"else is running (check `tasklist`/`ps` for a live python process), delete "
            f"this lock file and retry."
        )
    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")


def release_lock() -> None:
    LOCK_PATH.unlink(missing_ok=True)

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


def load_existing_results() -> dict:
    """Resume support, same principle as code/main.py's process_cases():
    a prior run's genuine results are kept, and only rows that are missing
    or were the safe-fallback placeholder (is_fallback_row — e.g. from
    hitting a quota wall mid-run) get retried. Without this, a quota
    interruption would force re-spending on fixtures that already produced
    a real, cache-worthy answer."""
    if not RESULTS_PATH.exists():
        return {}
    with open(RESULTS_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for r in rows:
        if not is_fallback_row({"reason": r["reason"]}):
            r["flagged_injection"] = r["flagged_injection"] == "True"
            out[r["id"]] = r
    return out


def main() -> None:
    acquire_lock()
    try:
        _run()
    finally:
        release_lock()


def _run() -> None:
    pool = KeyPool()
    cache = ResponseCache()
    ds = Dataset(REPO_ROOT / "dataset")

    done = load_existing_results()
    if done:
        print(f"Resuming — {len(done)} fixture(s) already genuinely evaluated, skipping them.")

    all_fixtures = [("attack", fx) for fx in ATTACK_FIXTURES] + [("control", fx) for fx in CONTROL_FIXTURES]
    rows = []
    for kind, fx in all_fixtures:
        if fx["id"] in done:
            rows.append(done[fx["id"]])
            continue
        result = {"kind": kind, **run_fixture(pool, cache, ds, fx)}
        rows.append(result)
        status = "FLAGGED" if result["flagged_injection"] else "not flagged"
        print(f"  [{fx['id']}] {kind}/{fx['category']}: {status}", flush=True)
        with open(RESULTS_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)

    genuine = [r for r in rows if not is_fallback_row({"reason": r["reason"]})]
    pending = [r for r in rows if r not in genuine]

    attacks = [r for r in genuine if r["kind"] == "attack"]
    controls = [r for r in genuine if r["kind"] == "control"]

    print(f"\n{len(genuine)}/{len(rows)} fixtures genuinely evaluated"
          + (f", {len(pending)} still pending (quota-limited — re-run this script once quota recovers)" if pending else ""))
    if attacks:
        defense_rate = sum(r["flagged_injection"] for r in attacks) / len(attacks)
        print(f"Attack fixtures evaluated: {len(attacks)}/{len(ATTACK_FIXTURES)}, defense rate: {defense_rate:.0%}")
    if controls:
        control_fp_rate = sum(r["flagged_injection"] for r in controls) / len(controls)
        print(f"Control fixtures evaluated: {len(controls)}/{len(CONTROL_FIXTURES)}, false-positive rate: {control_fp_rate:.0%}")
    print(f"Results written to {RESULTS_PATH}")

    missed = [r["id"] for r in attacks if not r["flagged_injection"]]
    if missed:
        print(f"Attacks NOT flagged (genuine misses): {missed}")
    false_positives = [r["id"] for r in controls if r["flagged_injection"]]
    if false_positives:
        print(f"Controls wrongly flagged: {false_positives}")


if __name__ == "__main__":
    main()
