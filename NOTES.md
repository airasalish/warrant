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
