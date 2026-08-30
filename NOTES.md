# Build Notes — what broke, and what I did about it

Kept live from Day 1. This feeds the README's "what broke and how I fixed it"
section and the video, per Razorpay's explicit ask. Two lines per entry:
what broke, what I did.

---

## 2026-08-30 (Day 1)

- **Repo scaffolded.** New repo, separate from both Orchestrate reference
  repos — this is Track 2 (AI Risk Manager), not a continuation of either.
- **Ported `KeyPool`, `sanitize()`, `_execute_tool()`, `_run_agent_turn()`,
  bounded-loop pattern, and resume/`is_fallback_row()` from the August
  Orchestrate build** (`hackerrank-orchestrate-august26/code/main.py`),
  domain-adapted from WhatsApp message routing to chargeback decisions.
  Ported the claim-status three-way schema shape (`supported` /
  `contradicted` / `not_enough_information`) from the June build, renamed to
  the chargeback domain (`contest` / `accept_liability` / `manual_review`).
- **Added response caching before the first real API call**, not after
  hitting the quota wall — the August build lost hours to Groq's free-tier
  daily cap after ~19 calls, discovered mid-round instead of on Day 1. This
  time: `code/llm_cache.py` hashes the exact request (model + messages +
  tools + tool_choice + temperature) and persists the normalized response to
  `.cache/llm_responses/<hash>.json`. Re-running the same case is now a
  cache hit, not a fresh call — this is the single highest-leverage
  mitigation from §6c-2 of the brief, so it went in before any dataset work.
- **Dataset not built yet** (Day 2 per the plan) — `code/main.py` assumes a
  `dataset/cases.csv` / `dataset/merchant_history.csv` /
  `dataset/reason_code_requirements.csv` shape documented in the README and
  in `code/main.py`'s `Dataset` loader, but those files don't exist yet, so
  the CLI can't run end-to-end tonight. That's expected — architecture
  first, so Day 2's dataset work has something real to run against
  immediately instead of being blocked on plumbing.

## 2026-08-30 (Day 2, continued same session)

- **Label-provenance risk, addressed structurally, not just by disclaimer.**
  If the same code path computed both the ground-truth label and the
  feature shown to the agent, an outside reader could reasonably ask "isn't
  this circular?" Fixed by splitting the logic: `code/risk_signals.py`
  computes FEATURES only (evidence sufficiency, amount anomaly, merchant
  repeat pattern) and is imported by both the runtime pipeline and the
  dataset generator — sharing feature code is fine, it's just arithmetic.
  The actual DECISION rule that turns those features into a ground-truth
  label lives only inside `scripts/generate_dataset.py`, with nothing in
  `code/main.py` importing from it. `dataset/LABELLING_RUBRIC.md` documents
  the rule in full so it's checkable by hand, independent of this claim.
- **Verified the wiring, not just the units.** Unit tests covered
  `sanitize()`, `enumerate_evidence()`, and the new override logic in
  isolation, but that doesn't catch a column-name mismatch between the
  generator's CSV output and `Dataset`'s loader. Ran `build_context()`
  against all 100 real generated dev cases and diffed its computed
  `evidence_sufficiency_precomputed` against the generator's own ground
  truth for the same field — 0 mismatches across all 100. Cheap check,
  would have caught a real class of bug that only shows up at integration
  time, not in a unit test with hand-built fixtures.
- **Generated dataset:** 150 synthetic cases across 8 real Visa/Mastercard
  reason codes (paraphrased, not copied — see the rubric), split 100 dev /
  50 held-out, seeded (`SEED=42` in `generate_dataset.py`) so it's
  byte-reproducible. Class balance came out reasonably even on both splits
  without having to force it (dev: 38 contest / 36 manual_review / 26
  accept_liability; held-out: 16/17/17) — worth stating since a lopsided
  split would need disclosing as a limitation, and this one doesn't.
- **Committing the dev/held-out split now**, before `code/evaluation/main.py`
  has any real logic in it (it's currently a stub that refuses to run
  against held_out at all) — so the git history itself is the evidence that
  the split predates any tuning, per the brief's operational rule.

## 2026-08-30 (Day 3, first live API run)

- **Real bug, found on a 5-case smoke test before it could waste the full
  dev set:** every single case exhausted all 6 retries and fell back to the
  safe default. Root cause — the forced final round (`tool_choice` locked
  to `classify_chargeback`) would fail with a 400 (`tool_use_failed`, or
  the model attempting a tool that wasn't in that round's tool list), and
  the outer retry loop responded by resending the *exact same prompt*
  again. At temperature 0.1, an identical prompt mostly reproduces the
  identical failure — literally watched it retry the same wrong tool call
  3 times in a row against an unchanged message list. Fixed by giving the
  forced round its own local retry (`_run_agent_turn`'s
  `force_local_retries`) that appends a corrective nudge message before
  retrying, so the retry actually changes something instead of repeating
  itself, plus more `max_tokens` headroom since this is a reasoning model
  (hidden reasoning tokens can eat the whole budget before the visible
  answer gets written). Re-ran the same 5 cases after the fix: 5/5 real
  decisions, zero fallbacks, one transient error that self-corrected via
  the new local retry instead of burning all 6 outer attempts.
- **Real gap, found in the actual model output, not a hypothetical:** case
  `cb_0072` had `merchant_repeat_pattern` correctly flagged (via the
  deterministic override — that part worked exactly as designed) but the
  model still recommended `contest` instead of routing to a human, which
  defeats the point of computing that signal at all. The prompt described
  the flag but never told the model it should change the *decision*, not
  just get logged. Added one explicit paragraph: a true risk flag should
  make `manual_review` the default lean, and if the model overrides that
  anyway, `reason` must say why. Not yet re-verified against a fresh run —
  next smoke test should confirm this actually changes behavior rather
  than just reads well.
- **Security pass, prompted by a direct ask to be careful given who's
  judging this.** Verified (not assumed) that the real Groq key never
  touched any tracked file or git history:
  `git log --all -p | grep gsk_` across every commit returns only the
  `.env.example` placeholder. Added `scripts/check_no_secrets.py` (scans
  staged files for Groq/Razorpay/AWS/private-key-shaped strings and any
  non-placeholder `*_API_KEY`/`*_SECRET` assignment) plus a
  `scripts/pre-commit` hook, and `SECURITY.md` documenting the actual
  practices — explicitly scoped honestly (no real cardholder data here,
  PCI-DSS doesn't apply, but the same discipline is followed anyway,
  referencing Razorpay's own published security docs).
- **One real thing worth doing, not yet done:** the reused Groq key's raw
  value appeared in this session's tool output when it was read from the
  old Orchestrate repo to copy into `.env` — meaning it exists in this
  chat's transcript, not just in `.env`. Recommended rotating it at
  console.groq.com once convenient. Low actual stakes (it's an inference
  key, not a payment credential, and was already a shared-across-projects
  key rather than newly generated for this submission) but worth doing on
  general hygiene grounds rather than leaving it be.
- **Hit the exact failure mode the caching architecture was built to
  prevent — just on a different workload than expected.** Ran the
  adversarial regression suite (34 fixtures) on the same single
  `GROQ_API_KEY` already used for two dev-set smoke tests earlier the same
  day, and hit Groq's 200,000 tokens/day free-tier cap partway through
  (`Used 198553, Requested 3807`). Every fixture after that point silently
  became the safe-fallback row instead of a genuine model response — which
  matters a lot here specifically, because the fallback's risk_flags never
  include `prompt_injection_attempt`, so a quota-starved run would have
  looked like a *defense failure* (fixture "not flagged") if reported at
  face value. Caught by checking `results.csv` before reporting any number:
  every fixture from `inj_09` onward, and all 10 controls, carried the
  literal fallback reason text. **Real result: 8/8 genuinely-evaluated
  attacks correctly flagged (100%), 16 attacks and all 10 controls not yet
  genuinely tested — not "33% defense rate," which is what a naive read of
  the summary line would have said.**
- Fixed `run_suite.py` to resume properly (mirrors `process_cases()`'s
  existing resume pattern) — a rerun now skips fixtures that already got a
  genuine answer and retries only the fallback/missing ones, so the 8 good
  results from this run aren't wasted. Root cause isn't really a bug
  though — it's that this project only has ONE Groq key configured, so the
  dev-set testing and the adversarial suite compete for the same daily
  cap. §6c-2 of the brief's own mitigation list says to add more keys for
  exactly this reason; that's next, not yet done.
