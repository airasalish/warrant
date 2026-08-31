"""
Deterministic-logic test for the adversarial suite's lock file — no API
calls, no LLM pool needed. Added after a real incident: results.csv
regressed from 33/34 genuine fixtures to 21/34 because two run_suite.py
invocations raced on the same file (see NOTES.md, Day 3). This lock is
what makes that structurally impossible now, not just "don't do that."
"""

import importlib.util
import sys
from pathlib import Path

_ADVERSARIAL_DIR = Path(__file__).parent / "adversarial_regression"
sys.path.insert(0, str(_ADVERSARIAL_DIR))  # run_suite.py does `from fixtures import ...`

_spec = importlib.util.spec_from_file_location("adversarial_run_suite", _ADVERSARIAL_DIR / "run_suite.py")
_run_suite = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_run_suite)


def test_lock_blocks_a_second_acquire():
    _run_suite.release_lock()  # start clean regardless of leftover state
    _run_suite.acquire_lock()
    try:
        try:
            _run_suite.acquire_lock()
            assert False, "acquiring an already-held lock should have raised"
        except _run_suite.AlreadyRunningError:
            pass
    finally:
        _run_suite.release_lock()


def test_release_then_acquire_works():
    _run_suite.release_lock()
    _run_suite.acquire_lock()
    _run_suite.release_lock()
    _run_suite.acquire_lock()  # should not raise - lock was properly released
    _run_suite.release_lock()


def test_release_is_safe_when_no_lock_held():
    _run_suite.release_lock()
    _run_suite.release_lock()  # calling twice should not raise
