"""
Deterministic-logic tests for code/evaluation/main.py — no API calls,
matching the pattern in tests/test_main.py.
"""

import importlib.util
from pathlib import Path

# Loaded by explicit path under a unique module name, not a plain
# `import main` - code/main.py and code/evaluation/main.py are both
# literally named `main`, and pytest's module cache is keyed by name, so a
# bare `import main` in this file would silently pull whichever of the two
# happened to be imported first in the same test session (a real bug found
# while wiring this up, not a hypothetical one).
_spec = importlib.util.spec_from_file_location(
    "chargeback_eval_main", Path(__file__).parent.parent / "code" / "evaluation" / "main.py"
)
_eval_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_eval_main)

confusion_matrix = _eval_main.confusion_matrix
precision_recall = _eval_main.precision_recall
coverage = _eval_main.coverage
expected_cost = _eval_main.expected_cost
COST_FALSE_POSITIVE_INR = _eval_main.COST_FALSE_POSITIVE_INR
COST_MANUAL_REVIEW_INR = _eval_main.COST_MANUAL_REVIEW_INR


def test_confusion_matrix_counts_correctly():
    predictions = {"c1": "contest", "c2": "accept_liability", "c3": "contest"}
    labels = {"c1": "contest", "c2": "accept_liability", "c3": "accept_liability"}
    matrix = confusion_matrix(predictions, labels)
    assert matrix["contest"]["contest"] == 1
    assert matrix["accept_liability"]["accept_liability"] == 1
    assert matrix["accept_liability"]["contest"] == 1  # c3: actual accept, predicted contest


def test_confusion_matrix_skips_unpredicted_cases():
    predictions = {"c1": "contest"}
    labels = {"c1": "contest", "c2": "accept_liability"}  # c2 has no prediction
    matrix = confusion_matrix(predictions, labels)
    total = sum(matrix[a][p] for a in matrix for p in matrix[a])
    assert total == 1


def test_precision_recall_perfect_classifier():
    predictions = {"c1": "contest", "c2": "accept_liability"}
    labels = {"c1": "contest", "c2": "accept_liability"}
    matrix = confusion_matrix(predictions, labels)
    p, r = precision_recall(matrix, "contest")
    assert p == 1.0
    assert r == 1.0


def test_precision_recall_with_false_positive():
    # actual accept_liability, predicted contest -> hurts contest's precision, not its recall
    predictions = {"c1": "contest", "c2": "contest"}
    labels = {"c1": "contest", "c2": "accept_liability"}
    matrix = confusion_matrix(predictions, labels)
    p, r = precision_recall(matrix, "contest")
    assert p == 0.5   # 1 true positive, 1 false positive
    assert r == 1.0   # the one real contest case was caught


def test_precision_recall_none_when_no_data():
    predictions = {"c1": "accept_liability"}
    labels = {"c1": "accept_liability"}
    matrix = confusion_matrix(predictions, labels)
    p, r = precision_recall(matrix, "contest")
    assert p is None  # no predictions of this class at all
    assert r is None  # no actual cases of this class at all


def test_coverage_excludes_manual_review():
    predictions = {"c1": "contest", "c2": "manual_review", "c3": "accept_liability", "c4": "manual_review"}
    assert coverage(predictions) == 0.5


def test_coverage_empty_is_zero():
    assert coverage({}) == 0.0


def test_expected_cost_false_positive_uses_flat_rate():
    predictions = {"c1": "contest"}
    labels = {"c1": "accept_liability"}
    result = expected_cost(predictions, labels, amounts={"c1": "9999"})
    assert result["n_false_positive"] == 1
    assert result["total_cost_inr"] == COST_FALSE_POSITIVE_INR  # amount ignored for FP


def test_expected_cost_false_negative_uses_transaction_amount():
    predictions = {"c1": "accept_liability"}
    labels = {"c1": "contest"}
    result = expected_cost(predictions, labels, amounts={"c1": "5000"})
    assert result["n_false_negative"] == 1
    assert result["total_cost_inr"] == 5000.0


def test_expected_cost_manual_review_is_flat_regardless_of_correctness():
    predictions = {"c1": "manual_review", "c2": "manual_review"}
    labels = {"c1": "contest", "c2": "manual_review"}  # one "wrong", one "right" - same cost either way
    result = expected_cost(predictions, labels, amounts={"c1": "100000", "c2": "1"})
    assert result["n_manual_review"] == 2
    assert result["total_cost_inr"] == 2 * COST_MANUAL_REVIEW_INR


def test_expected_cost_flags_bypassed_review_without_pricing_it():
    # actual=manual_review but agent auto-decided - a real risk, not priced
    # as FP/FN since it doesn't match either brief-defined error direction.
    predictions = {"c1": "contest"}
    labels = {"c1": "manual_review"}
    result = expected_cost(predictions, labels, amounts={"c1": "5000"})
    assert result["n_bypassed_review"] == 1
    assert result["n_false_positive"] == 0
    assert result["n_false_negative"] == 0
    assert result["total_cost_inr"] == 0  # not priced, but counted - see n_bypassed_review
