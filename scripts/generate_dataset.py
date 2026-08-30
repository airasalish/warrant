"""
Generates the synthetic chargeback dataset per dataset/LABELLING_RUBRIC.md.

Deterministic given SEED — re-running this script reproduces byte-identical
output, which is what makes "the labels are rubric-derived, not
model-derived" a checkable claim rather than an assertion.

IMPORTANT — label_case() lives ONLY in this file, not in code/risk_signals.py
or anywhere code/main.py can import from. That's deliberate: code/main.py
uses risk_signals.py's FEATURE functions (evidence_sufficiency,
is_amount_anomaly, is_merchant_repeat_pattern) to hand the model computed
facts, but the runtime pipeline has no code path to the DECISION rule that
turns those features into a ground-truth label. If it did, "the pipeline
predicts its own eval labels" would be a fair circularity objection. It
doesn't, so it isn't.

Usage:
    python scripts/generate_dataset.py
"""

import csv
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))
import risk_signals  # noqa: E402

SEED = 42
N_DEV = 100
N_HELD_OUT = 50
N_TOTAL = N_DEV + N_HELD_OUT

DATASET_DIR = REPO_ROOT / "dataset"

# ── Reason codes ──────────────────────────────────────────────────────────
REASON_CODES = {
    "10.4": {
        "network": "Visa", "description": "Card-absent fraud (cardholder says they didn't authorize it)",
        "required_evidence_types": ["avs_cvv_match", "device_fingerprint_or_ip_log"],
    },
    "13.1": {
        "network": "Visa", "description": "Merchandise/services not received",
        "required_evidence_types": ["proof_of_delivery", "shipping_carrier_record"],
    },
    "13.3": {
        "network": "Visa", "description": "Not as described / defective",
        "required_evidence_types": ["product_listing_match", "communication_log"],
    },
    "12.6.1": {
        "network": "Visa", "description": "Duplicate processing",
        "required_evidence_types": ["transaction_log_dedup"],
    },
    "4853": {
        "network": "Mastercard", "description": "Defective / not as described",
        "required_evidence_types": ["product_listing_match", "return_policy_ack"],
    },
    "4855": {
        "network": "Mastercard", "description": "Goods/services not provided",
        "required_evidence_types": ["proof_of_delivery", "service_completion_record"],
    },
    "4837": {
        "network": "Mastercard", "description": "No cardholder authorization",
        "required_evidence_types": ["avs_cvv_match", "cardholder_ip_device_match"],
    },
    "4863": {
        "network": "Mastercard", "description": "Cardholder doesn't recognize transaction",
        "required_evidence_types": ["avs_cvv_match", "prior_purchase_history"],
    },
}

EVIDENCE_DESCRIPTIONS = {
    "avs_cvv_match": [
        "AVS match report showing billing address and CVV matched at authorization",
        "Payment gateway log confirming AVS full-match and CVV verified",
    ],
    "device_fingerprint_or_ip_log": [
        "Device fingerprint log showing this device on 3 prior successful orders",
        "IP geolocation log placing the order in the cardholder's registered city",
    ],
    "proof_of_delivery": [
        "Signed delivery confirmation dated within the expected window",
        "Courier proof-of-delivery photo with GPS-tagged drop location",
    ],
    "shipping_carrier_record": [
        "Carrier tracking record showing package scanned delivered",
        "Shipping manifest with carrier tracking number matching the order",
    ],
    "product_listing_match": [
        "Product listing screenshot matching the SKU shipped",
        "Order confirmation showing the exact item and specification ordered",
    ],
    "communication_log": [
        "Support ticket thread with the customer discussing the item received",
        "Email thread with the customer prior to the dispute being filed",
    ],
    "transaction_log_dedup": [
        "Payment processor log showing only one settled charge for this order",
        "Ledger export confirming no duplicate authorization for this order ID",
    ],
    "return_policy_ack": [
        "Checkout screenshot showing the customer accepted the return policy",
        "Order confirmation email including the stated return policy terms",
    ],
    "service_completion_record": [
        "Service completion log timestamped and matching the booking",
        "Technician check-in/check-out record for the scheduled service",
    ],
    "cardholder_ip_device_match": [
        "Login history showing this device used the cardholder's account before",
        "Session log matching the order's IP to the cardholder's usual login IP",
    ],
    "prior_purchase_history": [
        "Account history showing 5 prior orders paid with the same card",
        "Purchase history showing a consistent buying pattern on this account",
    ],
}

NARRATIVE_TEMPLATES = [
    "We fulfilled this order as described and have the records to support it.",
    "Our records show this transaction was processed normally; we're contesting.",
    "We believe this chargeback was filed in error and are submitting what we have on file.",
    "The customer's order was handled per our standard process; details attached.",
    "We don't have complete records for this one but are submitting what's available.",
    "This customer has disputed before; we're submitting our side regardless.",
    "Order went out on schedule per our fulfillment log for this period.",
    "We're short on documentation for this case but wanted to respond regardless.",
]

random.seed(SEED)


def make_merchants() -> list:
    """20 synthetic merchants. 4 are deliberately 'risky' (chargeback rate
    above baseline AND poor contest win rate) so merchant_repeat_pattern
    has real positive cases to be evaluated against, not just theory."""
    merchants = []
    for i in range(1, 21):
        merchant_id = f"mch_{i:03d}"
        risky = i <= 4
        if risky:
            rate = round(random.uniform(0.8, 2.5), 2)
            win_rate = round(random.uniform(0.05, 0.35), 2)
        else:
            rate = round(random.uniform(0.05, 0.55), 2)
            win_rate = round(random.uniform(0.45, 0.9), 2)
        merchants.append({
            "merchant_id": merchant_id,
            "chargeback_rate_30d": rate,
            "chargeback_rate_90d": rate,
            "total_transactions_30d": random.randint(200, 5000),
            "prior_contest_win_rate": win_rate,
            "history_flags": "repeat_dispute_pattern" if risky else "none",
        })
    return merchants


def make_evidence_items_string(required_types: list, bucket: str) -> str:
    """bucket: 'full' (all required + maybe 1 extra), 'partial' (missing
    exactly one required type), 'none' (nothing submitted)."""
    if bucket == "none":
        return ""
    types_to_include = list(required_types)
    if bucket == "partial" and len(types_to_include) > 1:
        types_to_include.pop(random.randrange(len(types_to_include)))
    elif bucket == "partial" and len(types_to_include) == 1:
        return ""  # single-requirement codes: "partial" degrades to nothing submitted
    items = []
    for t in types_to_include:
        desc = random.choice(EVIDENCE_DESCRIPTIONS[t])
        items.append(f"{t}: {desc}")
    if bucket == "full" and random.random() < 0.3:
        extra_type = random.choice(list(EVIDENCE_DESCRIPTIONS.keys()))
        items.append(f"{extra_type}: {random.choice(EVIDENCE_DESCRIPTIONS[extra_type])}")
    return " | ".join(items)


def label_case(case: dict, req: dict, merchant: dict) -> tuple:
    """THE ground-truth decision rule — dataset/LABELLING_RUBRIC.md §4,
    applied here in code, never by the LLM under test. First matching rule
    wins:
      1. amount_anomaly or merchant_repeat_pattern -> manual_review
      2. evidence sufficient -> contest
      3. else -> accept_liability
    """
    evidence_items = risk_signals.parse_evidence_items(case)
    required_types = set(req["required_evidence_types"])
    sufficiency, _missing = risk_signals.evidence_sufficiency(evidence_items, required_types)

    amount_anomaly = risk_signals.is_amount_anomaly(case)
    repeat_pattern = risk_signals.is_merchant_repeat_pattern(merchant)

    if amount_anomaly or repeat_pattern:
        decision = "manual_review"
    elif sufficiency == "sufficient":
        decision = "contest"
    else:
        decision = "accept_liability"

    return decision, sufficiency


def generate_cases(merchants: list) -> list:
    codes = list(REASON_CODES.keys())
    bucket_choices = (["full"] * 4) + (["partial"] * 3) + (["none"] * 1) + (["full"] * 2)  # ~40/30/10/20 full-heavy

    cases = []
    for i in range(1, N_TOTAL + 1):
        case_id = f"cb_{i:04d}"
        reason_code = codes[(i - 1) % len(codes)]
        req = REASON_CODES[reason_code]
        merchant = merchants[random.randrange(len(merchants))]

        bucket = random.choice(bucket_choices)
        evidence_items_str = make_evidence_items_string(req["required_evidence_types"], bucket)

        original_amount = round(random.uniform(300, 15000), 2)
        if random.random() < 0.12:
            amount = round(original_amount + random.uniform(50, 2000), 2)  # anomaly: exceeds original
        else:
            amount = original_amount

        case = {
            "case_id": case_id,
            "merchant_id": merchant["merchant_id"],
            "amount": amount,
            "original_amount": original_amount,
            "currency": "INR",
            "transaction_date": f"2026-{random.randint(1,7):02d}-{random.randint(1,28):02d}",
            "payment_method": random.choice(["card", "upi", "netbanking"]),
            "reason_code": reason_code,
            "evidence_items": evidence_items_str,
            "merchant_narrative": random.choice(NARRATIVE_TEMPLATES),
        }

        decision, sufficiency = label_case(case, req, merchant)
        cases.append({
            "case": case,
            "label": {
                "case_id": case_id,
                "ground_truth_decision": decision,
                "ground_truth_evidence_sufficiency": sufficiency,
            },
        })
    return cases


def write_csv(path: Path, rows: list, fieldnames: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    merchants = make_merchants()
    write_csv(
        DATASET_DIR / "merchant_history.csv", merchants,
        ["merchant_id", "chargeback_rate_30d", "chargeback_rate_90d",
         "total_transactions_30d", "prior_contest_win_rate", "history_flags"],
    )

    req_rows = [
        {
            "reason_code": code, "network": r["network"], "description": r["description"],
            "minimum_evidence_required": " and ".join(r["required_evidence_types"]),
            "required_evidence_types": "|".join(r["required_evidence_types"]),
        }
        for code, r in REASON_CODES.items()
    ]
    write_csv(
        DATASET_DIR / "reason_code_requirements.csv", req_rows,
        ["reason_code", "network", "description", "minimum_evidence_required", "required_evidence_types"],
    )

    generated = generate_cases(merchants)
    random.shuffle(generated)  # seeded — reproducible shuffle, not a fresh draw each run
    dev, held_out = generated[:N_DEV], generated[N_DEV:N_DEV + N_HELD_OUT]

    case_fields = ["case_id", "merchant_id", "amount", "original_amount", "currency",
                   "transaction_date", "payment_method", "reason_code", "evidence_items", "merchant_narrative"]
    label_fields = ["case_id", "ground_truth_decision", "ground_truth_evidence_sufficiency"]

    write_csv(DATASET_DIR / "dev" / "cases.csv", [c["case"] for c in dev], case_fields)
    write_csv(DATASET_DIR / "dev" / "labels.csv", [c["label"] for c in dev], label_fields)
    write_csv(DATASET_DIR / "held_out" / "cases.csv", [c["case"] for c in held_out], case_fields)
    write_csv(DATASET_DIR / "held_out" / "labels.csv", [c["label"] for c in held_out], label_fields)

    dev_decisions = [c["label"]["ground_truth_decision"] for c in dev]
    ho_decisions = [c["label"]["ground_truth_decision"] for c in held_out]
    print(f"Generated {len(dev)} dev cases, {len(held_out)} held-out cases (seed={SEED}).")
    for name, decisions in [("dev", dev_decisions), ("held_out", ho_decisions)]:
        counts = {d: decisions.count(d) for d in sorted(set(decisions))}
        print(f"  {name} class balance: {counts}")


if __name__ == "__main__":
    main()
