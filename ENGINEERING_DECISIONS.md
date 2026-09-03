# Engineering decisions

Razorpay's own framing for this track: *"verification capacity, not
generation speed, is the bottleneck."* That's a statement about how this
gets judged, not just what gets built — so this file exists to make
verification cheap. Every decision below is a place where the easy version
and the correct version diverged, with the reasoning for picking the
harder one, a pointer to where it lives, and — where relevant — what would
have happened if the easy version had shipped instead. Chronological build
log with real failures is in [NOTES.md](NOTES.md); this file is the
distilled "why," organized by concern instead of by day.

## Measurement integrity (the part this track actually scores)

- **The ground-truth decision rule is structurally unreachable from the
  runtime pipeline.** `risk_signals.py` computes shared FEATURES (evidence
  sufficiency, amount anomaly, merchant repeat-pattern) used by both
  `code/main.py` and `scripts/generate_dataset.py` — sharing feature code
  is fine, it's arithmetic. But `generate_dataset.py::label_case()`, the
  rule that turns those features into a ground-truth label, lives *only*
  in that file. Nothing in `code/main.py` imports it. This isn't a promise
  in a README — it's checkable by reading the import graph.
- **Deliberately did NOT hard-code that rule into the agent, even after
  watching it hurt a live result.** The first real run showed the model
  detecting `merchant_repeat_pattern` correctly but still deciding
  `contest` — exactly what the rubric says should route to
  `manual_review`. The fast fix is one `if` statement in
  `apply_deterministic_overrides()` forcing that outcome in code. That was
  rejected: it would make the pipeline mechanically agree with its own
  eval's answer key on that decision boundary, which turns "precision/
  recall on this class" into a tautology instead of a measurement. Pushed
  the prompt harder instead — three separate attempts total (see
  NOTES.md) — and the third was tested with a controlled before/after on
  the identical risk-flagged cases rather than just eyeballed: it made
  **zero measurable difference**, the exact same case IDs caught both
  times. That's now a confirmed result, not a hoped-for one, and it's
  reported as such rather than left at "still improving it." The decision
  not to hard-code the override stands regardless of that outcome — a
  fix that happens to raise the number isn't the same thing as a fix
  that's actually true.
- **What IS pinned in code, and why that's different:** `evidence_
  sufficiency` and the three mechanically-derivable risk flags
  (`evidence_incomplete_for_reason_code`, `amount_anomaly`,
  `merchant_repeat_pattern`) get overridden to the code-computed value
  regardless of model output (`apply_deterministic_overrides`). These are
  objective facts checkable against the reason code's requirement table —
  there's no judgment call being short-circuited, only arithmetic the
  model would otherwise have a chance to get wrong for no reason. The line
  is: pin what's actually deterministic, never pin what requires reading
  the narrative.
- **Held-out split committed in its own commit, before any evaluation
  logic exists in the repo** — `git log` order is the evidence, not a
  claim (see the commit history; `code/evaluation/main.py` still refuses
  `--split held_out` outright as of this writing).

## Reliability under real quota constraints

- **Disk cache keyed by exact request hash, built before the first real
  API call** (`code/llm_cache.py`) — not added after hitting a wall, which
  is what actually happened on the prior Orchestrate build (~19 calls
  before the daily cap). Re-running this pipeline over cases already seen
  costs zero additional calls.
- **A retry that doesn't just resend the same failing prompt.** The first
  live smoke test found every case exhausting all retries because the
  outer retry loop resent an *identical* request at temperature 0.1 —
  which mostly reproduces the identical failure. Fixed with a local retry
  inside the forced-decision round that appends a corrective message
  before retrying, so the retry is actually a different request (`code/
  main.py::_run_agent_turn`, `FORCE_CLASSIFY_NUDGE`). Full story in
  NOTES.md — this is exactly the kind of thing Razorpay's brief explicitly
  asks to see disclosed, not smoothed over.
- **`_recover_failed_generation`**: Groq's forced-`tool_choice` path
  sometimes rejects a call with a 400 even when the model produced a
  complete, correct JSON answer as plain text instead of a structured tool
  call. Recovering that instead of discarding a real result and burning a
  retry.

## Least-privilege by construction

`_execute_tool()` ignores every argument the model supplies (`case_id`,
`merchant_id`) and always resolves against the pipeline's own pre-computed
context for the *current* case. A hallucinated or manipulated identifier
can't leak another case's data, because the tool's authority is the
pipeline's ground truth, never the model's claim about which record it
wants. Same principle real access-control systems use for least-privilege
data access, applied at the tool-call boundary instead of a database layer
— see [SECURITY.md](SECURITY.md) for the fuller writeup, including how
this project's secret-handling aligns with Razorpay's own published
security practices.

## Defense-only robustness testing, scoped to survive the disqualification bar

The brief is explicit that anything offense-capable is disqualifying for
this track. The adversarial regression suite
(`tests/adversarial_regression/`) is named and scoped specifically to stay
on the right side of that line: fixed, publicly-documented injection
patterns only, no attack generation, no third-party targeting, and a
required posture statement at the top of that directory's own README —
see it for the full defense-rate / control-false-positive-rate results
methodology.

## Honesty as infrastructure, not just a section in the README

- `NOTES.md` has been live since hour one — every entry above about a bug
  was written when it happened, not reconstructed afterward for this
  document. That's the difference between a real "what broke" section and
  a plausible-sounding one.
- `dataset/LABELLING_RUBRIC.md` commits the ground-truth logic in the
  open, in prose a reviewer can check by hand against `generate_dataset.py`
  without running any code.
- Known limitations are stated where they're found, not collected at the
  end: `SECURITY.md` discloses that the local LLM cache is unencrypted
  plaintext (fine for synthetic data, would need fixing for real PII)
  before anyone asks.
