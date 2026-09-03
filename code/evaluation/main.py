"""
Evaluation harness — dev split only. held_out stays refused until code
freeze (brief §6a: opened once, on freeze day, never touched for tuning).

Reports, per brief §6a/§6b/§6d:
- Confusion matrix over {contest, accept_liability, manual_review}.
- Precision/recall for `contest` and `accept_liability` specifically -
  NOT overall accuracy, and NOT for manual_review (an abstention, not a
  class with its own precision/recall target).
- Coverage: share of cases decided automatically (not manual_review) -
  reported so a system that abstains on everything can't look artificially
  good on precision alone.
- Expected cost per 100 cases, from an explicit false-positive/
  false-negative cost model, with the cost assumptions stated in the
  output itself, not just in a README someone might not read.
- A rules-only baseline (§6d): always predict per evidence_sufficiency
  alone (sufficient -> contest, else -> accept_liability, never
  manual_review), scored the same way, so precision/recall have a
  reference point.

Usage:
    python code/evaluation/main.py --split dev --predictions dataset/dev/output.csv
"""

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "code"))
import risk_signals  # noqa: E402

# ── Cost model (brief §6b) — assumptions stated here, not hidden ──────────
# False positive: contest a chargeback that should have been accepted.
# Cost = wasted representment effort + dispute filing fee. Flat, because
# this cost doesn't scale with transaction size - filing evidence takes
# roughly the same analyst effort regardless of the amount in dispute.
COST_FALSE_POSITIVE_INR = 800

# False negative: accept liability on a case that should have been
# contested (winnable). Cost = the transaction amount itself, straight
# loss - this DOES scale with the case, so it's read per-case from
# dataset/dev/cases.csv rather than assumed flat.

# Secondary, non-mandatory metric: routing to manual_review always costs
# analyst time regardless of whether it was the "right" call - included
# for completeness, kept clearly separate from the mandatory FP/FN metric
# above so it's not confused with an error cost.
COST_MANUAL_REVIEW_INR = 150

# Third, bonus/exploratory metric — NOT part of the brief's mandatory
# cost model (§6b prices exactly two error directions). Models the
# unpriced exposure from a case that had a real risk signal but got
# auto-decided anyway (a "bypassed review") as a fraction of the
# transaction amount, since that exposure scales with what's at stake,
# unlike the flat manual_review labor cost above. A stated assumption,
# not a measured one.
BYPASSED_REVIEW_EXPOSURE_RATE = 0.10

DECISION_VALUES = ["contest", "accept_liability", "manual_review"]
POSITIVE_CLASSES = ["contest", "accept_liability"]  # manual_review excluded - see module docstring


def load_csv(path: Path) -> list:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def confusion_matrix(predictions: dict, labels: dict) -> dict:
    """predictions, labels: case_id -> decision. Returns {actual: {predicted: count}}."""
    matrix = {a: {p: 0 for p in DECISION_VALUES} for a in DECISION_VALUES}
    for case_id, actual in labels.items():
        predicted = predictions.get(case_id)
        if predicted is None:
            continue
        matrix[actual][predicted] += 1
    return matrix


def precision_recall(matrix: dict, positive_class: str) -> tuple:
    tp = matrix[positive_class][positive_class]
    fp = sum(matrix[a][positive_class] for a in DECISION_VALUES if a != positive_class)
    fn = sum(matrix[positive_class][p] for p in DECISION_VALUES if p != positive_class)
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return precision, recall


def coverage(predictions: dict) -> float:
    if not predictions:
        return 0.0
    decided = sum(1 for d in predictions.values() if d != "manual_review")
    return decided / len(predictions)


def expected_cost(predictions: dict, labels: dict, amounts: dict) -> dict:
    """Returns total cost, per-100-cases cost, and the count of each error
    type, over exactly the cases that have both a prediction and a label."""
    total_cost = 0.0
    n_fp = n_fn = n_review = n_scored = 0
    for case_id, actual in labels.items():
        predicted = predictions.get(case_id)
        if predicted is None:
            continue
        n_scored += 1
        if predicted == "contest" and actual == "accept_liability":
            total_cost += COST_FALSE_POSITIVE_INR
            n_fp += 1
        elif predicted == "accept_liability" and actual == "contest":
            total_cost += float(amounts.get(case_id, 0))
            n_fn += 1
        elif predicted == "manual_review":
            total_cost += COST_MANUAL_REVIEW_INR
            n_review += 1
    per_100 = (total_cost / n_scored * 100) if n_scored else 0.0

    # Not priced above, on purpose: the brief defines cost for exactly two
    # error directions (contest-should-be-accept, accept-should-be-contest).
    # A third real category exists but has no brief-specified price - cases
    # where a human review was actually warranted (actual=manual_review)
    # but the agent auto-decided anyway, bypassing the review entirely.
    # That's arguably worse than either named error (an unreviewed
    # high-risk case), so it's counted and surfaced rather than silently
    # folded into "correct" just because it doesn't match either FP/FN
    # definition.
    bypassed_ids = [
        case_id for case_id, actual in labels.items()
        if actual == "manual_review" and predictions.get(case_id) in ("contest", "accept_liability")
    ]
    # Bonus/exploratory metric, NOT part of the brief's mandatory cost
    # model (§6b defines exactly two error directions) and deliberately
    # kept out of total_cost_inr/cost_per_100_inr above, so the required
    # number stays exactly what the brief asked for. Modeled as a fraction
    # of the transaction amount rather than a flat fee, because unlike the
    # manual_review labor cost (a known, fixed analyst-time cost), the
    # exposure from skipping a warranted review scales with what's at
    # stake in the case - a stated assumption, not a measured one, since
    # real-world outcomes for bypassed reviews aren't observable in this
    # dataset.
    bypassed_review_exposure_inr = sum(
        float(amounts.get(case_id, 0)) * BYPASSED_REVIEW_EXPOSURE_RATE for case_id in bypassed_ids
    )
    return {
        "n_scored": n_scored, "total_cost_inr": total_cost, "cost_per_100_inr": per_100,
        "n_false_positive": n_fp, "n_false_negative": n_fn, "n_manual_review": n_review,
        "n_bypassed_review": len(bypassed_ids),
        "bypassed_review_exposure_inr": bypassed_review_exposure_inr,
        "bypassed_review_exposure_per_100_inr": (bypassed_review_exposure_inr / n_scored * 100) if n_scored else 0.0,
    }


def baseline_predictions(cases: list, ds_requirements: dict) -> dict:
    """Rules-only baseline (brief §6d): contest if evidence is sufficient
    per the reason code's requirement, accept_liability otherwise. Never
    predicts manual_review - it has no concept of risk signals, only
    evidence completeness. Deliberately dumb, for comparison only."""
    preds = {}
    for row in cases:
        req = ds_requirements.get(row["reason_code"], {})
        required_types = risk_signals.required_evidence_types(req)
        evidence_items = risk_signals.parse_evidence_items(row)
        sufficiency, _ = risk_signals.evidence_sufficiency(evidence_items, required_types)
        preds[row["case_id"]] = "contest" if sufficiency == "sufficient" else "accept_liability"
    return preds


def always_manual_review_predictions(cases: list) -> dict:
    """Second baseline (brief §6d): route every case to a human. Perfect
    'precision' on nothing (no automated decisions), zero coverage."""
    return {row["case_id"]: "manual_review" for row in cases}


def report(name: str, predictions: dict, labels: dict, amounts: dict) -> None:
    matrix = confusion_matrix(predictions, labels)
    n = sum(matrix[a][p] for a in DECISION_VALUES for p in DECISION_VALUES)
    print(f"\n=== {name} (n={n} scored) ===")
    if n == 0:
        print("  No predictions available to score yet.")
        return
    print("  Confusion matrix (rows=actual, cols=predicted):")
    col_w = max(len(p) for p in DECISION_VALUES) + 4
    header = " " * 20 + "".join(f"{p:>{col_w}}" for p in DECISION_VALUES)
    print(header)
    for a in DECISION_VALUES:
        print(f"  {a:<18}" + "".join(f"{matrix[a][p]:>{col_w}}" for p in DECISION_VALUES))

    for cls in POSITIVE_CLASSES:
        p, r = precision_recall(matrix, cls)
        p_str = f"{p:.0%}" if p is not None else "n/a (no predictions of this class)"
        r_str = f"{r:.0%}" if r is not None else "n/a (no actual cases of this class)"
        print(f"  {cls}: precision={p_str}, recall={r_str}")

    cov = coverage(predictions)
    print(f"  coverage (share not routed to manual_review): {cov:.0%}")

    cost = expected_cost(predictions, labels, amounts)
    print(f"  expected cost: INR {cost['cost_per_100_inr']:.0f} per 100 cases "
          f"(FP={cost['n_false_positive']} x INR{COST_FALSE_POSITIVE_INR}, "
          f"FN={cost['n_false_negative']} x transaction amount, "
          f"manual_review={cost['n_manual_review']} x INR{COST_MANUAL_REVIEW_INR})")
    if cost["n_bypassed_review"]:
        print(f"  WARNING: {cost['n_bypassed_review']} case(s) had actual=manual_review but were "
              f"auto-decided anyway - not priced in the required cost above (brief only prices "
              f"the contest/accept_liability error directions).")
        print(f"  BONUS (not part of the brief's cost model, exploratory only): modeling that "
              f"exposure at {BYPASSED_REVIEW_EXPOSURE_RATE:.0%} of transaction amount gives "
              f"INR {cost['bypassed_review_exposure_per_100_inr']:.0f} per 100 cases in unpriced risk "
              f"- reported separately so it's never confused with the required, brief-defined number.")
    if n < 30:
        print(f"  NOTE: small sample (n={n}) - treat these rates as directional, not final.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--split", choices=["dev", "held_out"], required=True,
        help="Which split to evaluate against. No default on purpose.",
    )
    parser.add_argument("--dataset-dir", default="dataset")
    parser.add_argument("--predictions", default=None, help="Path to the pipeline's output CSV")
    parser.add_argument(
        "--i-am-opening-held-out-for-real", action="store_true",
        help="Required to run --split held_out. Forces a deliberate choice, not a "
             "flag flipped absent-mindedly on data that's supposed to be opened once.",
    )
    args = parser.parse_args()

    dataset_dir = REPO_ROOT / args.dataset_dir
    marker_path = dataset_dir / "held_out" / ".opened_at_commit"

    if args.split == "held_out":
        if not args.i_am_opening_held_out_for_real:
            print(
                "Refusing to run: pass --i-am-opening-held-out-for-real to confirm this "
                "is the genuine, one-time open - not something to pass casually."
            )
            raise SystemExit(1)
        if marker_path.exists():
            print(f"NOTE: held_out was already opened once - see {marker_path}")
            print(marker_path.read_text(encoding="utf-8"))
            print("Re-running is for display purposes only; the brief's discipline is "
                  "about not TUNING after seeing this, not about a technical rerun block.")

    split_dir = dataset_dir / args.split
    cases = load_csv(split_dir / "cases.csv")
    labels_rows = load_csv(split_dir / "labels.csv")
    labels = {r["case_id"]: r["ground_truth_decision"] for r in labels_rows}
    amounts = {r["case_id"]: r["amount"] for r in cases}
    req_rows = load_csv(dataset_dir / "reason_code_requirements.csv")
    ds_requirements = {r["reason_code"]: r for r in req_rows}

    if args.predictions:
        pred_rows = load_csv(REPO_ROOT / args.predictions)
        predictions = {r["case_id"]: r["decision"] for r in pred_rows}
        report(f"Agent ({args.split})", predictions, labels, amounts)
    else:
        print(f"No --predictions given - run code/main.py against {args.split}/cases.csv first, "
              "or pass --predictions explicitly. Showing baselines only.")

    report("Baseline: rules-only", baseline_predictions(cases, ds_requirements), labels, amounts)
    report("Baseline: always manual_review", always_manual_review_predictions(cases), labels, amounts)

    if args.split == "held_out" and not marker_path.exists():
        import datetime
        import subprocess
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
            ).stdout.strip()
        except Exception:
            commit = "unknown"
        marker_path.write_text(
            f"held_out opened for the first time at {datetime.datetime.now().isoformat()}\n"
            f"git commit at open time: {commit}\n"
            f"This file is proof of when held_out was first opened - committing it to the "
            f"repo makes the open time verifiable in git log, not just claimed in prose.\n",
            encoding="utf-8",
        )
        print(f"\nWrote {marker_path} - commit this file to make the open time verifiable.")


if __name__ == "__main__":
    main()
