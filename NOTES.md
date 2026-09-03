# Build Notes — what broke, and what I did about it

Kept live from Day 1. This feeds the README's "what broke and how I fixed it"
section and the video, per Razorpay's explicit ask. Two lines per entry:
what broke, what I did.

**Index, in true chronological order** — entries below aren't always in
this order in the file, because this is a genuinely live log (new
findings got added near related earlier context, not always appended at
the end). Not reordering the actual entries below, since a "kept live"
log that's been retroactively resequenced isn't really live anymore —
this index exists so a reader doesn't have to reconstruct the timeline
themselves.

1. [Day 1](#2026-08-30-day-1) — repo up, architecture ported
2. [Day 2, continued](#2026-08-30-day-2-continued-same-session) — dataset, rubric, split committed
3. [Day 3, first live API run](#2026-08-30-day-3-first-live-api-run) — retry bug, key-attribution bug found and fixed
4. [Day 2, reproducibility check](#2026-08-31-day-2-continued--reproducibility-check) — clone/install/run verified end to end
5. [Day 2, full dev run](#2026-08-31-day-2-full-dev-run) — 100/100 genuine, real precision/recall/cost numbers
6. [Adversarial suite complete](#2026-09-02--adversarial-suite-complete) — 34/34, race-condition regression found and fixed with a lock file
7. [Third prompt attempt confirmed ineffective](#2026-09-03--third-prompt-attempt-confirmed-not-just-hoped-ineffective) — controlled before/after, no improvement

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

## 2026-08-31 (Day 2, continued — reproducibility check)

- **Verified "clone → install → run" for real**, not just assumed: cloned
  the repo fresh into an isolated temp directory (from local git, so this
  checks what's actually committed, not the working directory's state),
  created a brand-new venv, `pip install -r requirements.txt`, and ran the
  full test suite — 30/30 passed with zero dependency on anything outside
  the clone. Confirmed `.env` correctly does not exist in the clone
  (git-ignored, never committed). Also ran `code/main.py` with no API key
  configured, to see what a judge's very first run would actually look
  like: clean `Error: no GROQ_API_KEY* found. Get a free key at
  https://console.groq.com`, exit code 1 — no stack trace, no confusion.
  Closes the brief's pre-flight checklist item on this.

## 2026-08-31 (Day 2, full dev run)

- **Corrected a wrong assumption within the same hour I made it.** Added
  3 more Groq keys pulled from the August build's `.env`
  (`GROQ_API_KEY_2/3/4`), expecting ~4x the daily token headroom since
  that's what multi-key rotation is *for*. Kicked off the full 100-case
  dev run; it hit the exact same 200,000-tokens/day cap again at case 21,
  this time reported against `GROQ_API_KEY_2` — and the error's
  organization ID (`org_01ktx4r9g2fpt839w0rypds62t`) is identical to
  yesterday's error under the original key. All 4 keys belong to the same
  Groq account, not 4 separate accounts, so they share one daily pool —
  rotating across them helps spread per-minute rate limits, not the daily
  cap. Told the user the wrong thing in the moment ("4x headroom now") and
  am correcting it here rather than letting the wrong claim stand
  uncorrected once the real behavior showed up.
- **Full 100-case dev run completed, genuinely (0 fallback rows).** Real
  numbers: `contest` precision 75% / recall 100%, `accept_liability`
  precision 69% / recall 92%, coverage 86%, **zero false positives and
  zero false negatives** — every automated decision the agent actually
  committed to was directionally correct against ground truth. The real,
  disclosed weakness: only 12 of 36 actual `manual_review` cases (33%)
  got routed there — the other 24 were auto-decided anyway, the exact
  "bypassed review" risk `code/evaluation/main.py` was built to surface
  rather than hide. Matches the smaller-sample pattern seen earlier
  (`cb_0072`) at full scale, now quantified instead of anecdotal.
- **Found the same path bug twice in one session** — passed
  `--output ../dataset/dev/output.csv` while running from `code/`, which
  resolves against `REPO_ROOT` (the project root), not the shell's cwd, so
  it silently wrote to `D:\downloads2\dataset\dev\output.csv` — one level
  above the actual project — and, worse, resume detection then found
  nothing there and re-ran **all 100 cases from scratch** to retry what
  should have been 1 fallback case. Caught it from the "Processing 100/100"
  line (should have said "Processing 1/100" for a single retry) before it
  got far, stopped it, verified the real `dataset/dev/output.csv` was
  untouched, and re-ran with the correct relative path. Wasted some
  quota, not any data. Worth remembering: this CLI's paths are always
  relative to the repo root, never to the invoking shell's cwd.
- **Adversarial suite finished a first pass (33/34 genuine, 1 still an
  honest fallback, not swept under the rug).** Real result at that point:
  **100% defense rate (23/23 genuinely-evaluated attacks correctly
  flagged), 0% control false-positive rate (10/10 clean).** Zero genuine
  misses among anything actually evaluated — the one pending fixture
  (`inj_10`, fake_prior_approval) failed on quota/auth errors both times
  it was attempted, not on a real model judgment, verified directly
  against `results.csv`'s `reason` field before reporting anything.
- **Then a real regression, caught and only partially explained.** Ran
  `run_suite.py` again to retry that last pending fixture; the result
  came back *worse* — 21/34 genuine instead of the 33/34 just confirmed
  above. 12 previously-genuine fixtures (3 attacks, 9 controls) had been
  silently overwritten with fresh fallback rows. Cache timestamps
  confirmed real API calls were made for those 12 during this run —
  proving they were genuinely re-attempted, not just corrupted on disk —
  which means `load_existing_results()` read a much smaller "done" set
  than what was actually on disk at that moment. Couldn't fully
  reconstruct why from the available evidence (the two runs I can account
  for were sequential, not obviously overlapping) — stating that honestly
  rather than presenting a root cause I'm not certain of. What IS fixed
  regardless of the exact mechanism: added a lock file
  (`acquire_lock()`/`release_lock()` in `run_suite.py`) that makes two
  overlapping runs against the same `results.csv` structurally
  impossible, with 3 new unit tests (`tests/test_adversarial_lock.py`)
  covering it. Re-ran cleanly afterward under the lock — it correctly
  resumed from the true 21 (no further regression, proving the fix
  works), but recovered none of the 13 lost fixtures: every one of the 7
  keys is now near its own daily cap from today's total testing volume,
  so all 13 retries hit quota/auth errors and fell back again. Current
  honest state: **21/34 genuine (20/20 attacks, 1/10 controls)** — the
  attack-side defense rate is still solid evidence, but the control
  false-positive rate is down to n=1 and shouldn't be quoted as a real
  number until it's rebuilt. README corrected to match — the earlier
  33/34 numbers were still sitting there stale before this update, which
  would have been reporting a number that was no longer true.
- **Recovery, in progress, tracked honestly at each step rather than only
  at the end.** Checked quota with a single cheap call per key before
  committing to a full run (found `GROQ_API_KEY_2` is genuinely invalid —
  consistent 401s, not quota — worth writing off rather than continuing
  to burn a retry slot on it every time). Ran the suite under the lock:
  recovered from 21/34 to **25/34 genuine (22/22 attacks, still 100%
  defense; 3/10 controls, still 0% false positives but the sample is
  still small)**. All 6 working keys hit their caps again within this one
  run. README updated to match this improved-but-still-partial number
  rather than either the stale 33/34 or leaving the regressed 21/34
  standing after real progress was made.
- **One more recovery pass: 25 → 26/34 genuine** (23/23 attacks, still
  100%; 3/3 controls tested, still 0% FP). Diminishing returns now — each
  pass nets roughly 1 fixture as all 6 working keys tighten toward their
  caps together from today's total volume. 8 still pending
  (`inj_24` + 7 controls). Pausing longer between recovery attempts from
  here rather than grinding for marginal gains — the attack-side number
  is solid and stable; only the control sample size still needs building
  back up before quoting it with confidence.
- **Attack side now complete: 24/24 genuine, 100% defense, final.**
  Another recovery pass brought the total to 28/34 (controls at 4/10).
  Also fixed a real design inconsistency while reviewing the README for
  staleness: `code/main.py`'s `--input` flag was resolved against the
  shell's cwd while `--output` was resolved against the repo root — in
  the SAME command. That inconsistency is the actual root cause behind
  every path mistake tonight (the smoke-test file landing outside the
  project, the fallback retry redoing all 100 cases). Made both flags
  resolve against `REPO_ROOT` consistently, verified the fix directly
  without wasting any API calls (just checked the resolved paths), and
  corrected the README's setup commands and Data Model section, both of
  which had drifted from what the code actually does since Day 1
  drafting — the setup section literally referenced a `dataset/cases.csv`
  file that has never existed in this project.

## 2026-09-02 — Adversarial suite complete

- **34/34 genuine, 0 fallback rows. 100% defense rate (24/24), 0% control
  false-positive rate (10/10).** After a full day's rolling-window quota
  recovery plus the day boundary passing, all 6 working keys had enough
  headroom to clear the remaining fixtures in one clean pass — no errors
  visible in the run at all, a real contrast to every earlier recovery
  attempt tonight. Verified directly against `results.csv` before calling
  this final, same discipline as every number before it in this file.
  README updated to drop the "still building" caveats now that both
  sides of the suite are genuinely complete, not partial.
- **Added `ARCHITECTURE.md`** as a standalone architecture document,
  separate from the README, since the brief lists it as its own required
  submission (#3) distinct from the repo itself. Pulls together the
  component list, request-flow diagram, the judgment-vs-arithmetic
  design line, and the non-circularity argument (§5 of the brief) into
  one file a reviewer can point to directly, rather than assuming the
  README serves double duty.
- **Actual fix for the daily cap specifically:** a key from a genuinely
  different Groq account (different email signup) — the friend's key
  offered earlier would actually help here, these four didn't. The cap
  also appears to be a rolling 24h window, not a fixed midnight reset
  (error messages give a countdown like "try again in 13m", not "resets at
  midnight") — so capacity trickles back gradually rather than resetting
  cleanly once a day.

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

## 2026-09-03 — Third prompt attempt: confirmed, not just hoped, ineffective

- Ran a genuinely fresh full dev pass under the updated prompt (inline
  risk-flag reminders + worked example, see the 2026-09-02 entry) to a
  separate file so resume logic couldn't silently skip it and produce a
  false "no change" reading. 94/100 genuine after two rounds (6 fallback
  on the first pass, all 6 still fallback on retry — quota fully spent
  across all 7 keys by that point, not pursued further).
- **The real comparison, on the exact same 32 risk-flagged cases in both
  runs: 12/32 caught under the OLD prompt, 12/32 caught under the NEW
  prompt. Identical.** Not a rounding difference — the same 12 case_ids,
  confirmed by direct comparison, not inferred from the aggregate rate.
  The earlier 15-case smoke test's 6/15 (40%) reading was a real number
  on a real subset, but not representative of the full, controlled
  comparison — worth remembering that a promising small sample doesn't
  guarantee the full-sample result, and this is exactly why the fuller
  check was worth doing before updating any claim in the README.
- One good outcome from an otherwise flat result: only 1 of 62 non-risk
  cases was affected by the prompt change, so the fix that didn't help
  also didn't measurably hurt anything else.
- This is the honest, now-confirmed version of what was already
  disclosed as a real possibility: *"I can't promise a third attempt
  would fix it."* It didn't. Reporting that directly rather than
  quietly keeping the more hopeful, earlier-stage framing in the README.
