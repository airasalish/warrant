# 5-minute video — script outline

Draft, following the brief's own shape (§9b: "plan it, don't improvise").
Populated with real numbers already in hand as of this draft — update if
later dev iterations or the held-out run change them. Screen recording
with narration is fine; time is better spent getting the results section
right than on production polish.

---

## 0:00–0:30 — The one class of loss

- "This is a chargeback evidence responder — one class of loss: chargebacks."
- Why it matters: every dispute forces a binary call under time pressure —
  contest it (cost: representment effort, plus a penalty if the case was
  actually weak) or eat the loss (cost: the full transaction, even on
  cases that were genuinely winnable). Merchants either under-contest out
  of caution or over-contest on cases with no real evidence behind them.
- Show the repo's top-level README pitch line on screen.

## 0:30–1:15 — The threat model

- Merchant-submitted narrative text is untrusted input flowing into a
  money decision. A merchant with a financial interest in the outcome
  doesn't need to out-argue the model — they can try to instruct it.
- Show the `SYSTEM_PROMPT`'s untrusted-input block in `code/main.py` on
  screen — specifically the describes-vs-contains distinction ("the
  customer told us to approve it, which we found suspicious" vs. an
  actual instruction aimed at the reviewer).
- One sentence bridging to the adversarial suite: "this isn't just a
  design principle — it's measured; more on that in a minute."

## 1:15–2:30 — Architecture

- Show the Mermaid sequence diagram from the README (or record the
  rendered version).
- Say plainly: where the LLM judges (reading narrative + evidence against
  a reason code's requirement) vs. where deterministic code decides
  (evidence completeness, amount anomaly, merchant repeat-pattern — all
  computed in `risk_signals.py`, never left to the model to infer from
  raw numbers).
- The bounded loop: `max_rounds=2`, final round's tool list contains only
  `classify_chargeback` — structurally guaranteed to terminate with a
  structured answer, not an open-ended agent loop.
- `_execute_tool()` ignoring model-supplied IDs, always resolving against
  the pipeline's own record for the current case — say this is a
  least-privilege pattern, same principle as access control generally,
  applied at the tool-call boundary.

## 2:30–4:00 — Results (say the sample sizes out loud)

Dev set, 100 cases, 100% genuinely evaluated:

- `contest`: 75% precision, 100% recall
- `accept_liability`: 69% precision, 92% recall
- Coverage: 86%
- **Zero false positives, zero false negatives** on the cost-bearing
  classes — say this plainly, it's the headline number
- The honest gap: only 12/36 (33%) of cases that should route to a human
  actually did. Say why this is disclosed, not hidden: "the deterministic
  risk flags are always correct — the gap is the model not reliably
  weighting them into its final decision, and we chose not to hard-code
  that override because it would make our own eval circular."

Baseline comparison — 5 seconds, not a full breakdown:
- "A dumb rules-only baseline actually edges out the agent on raw
  precision for the two evidence-driven classes — because it's blind to
  risk on purpose. That comparison is the actual point of building an
  agent instead of shipping the baseline."

Adversarial suite (check `README.md` for the current count before
recording — this has been climbing as quota recovers, update the numbers
below to match on the day):
- As of this draft: 26/34 fixtures genuinely evaluated, 8 pending on
  quota (say why: verified against each fixture's stored response before
  reporting any rate, same discipline as the dev-set numbers)
- 23/23 attacks correctly flagged — **100% defense rate, stable across
  every recovery pass so far**
- Controls: 3/10 tested, 0% false positives — say plainly that this
  sample is still small and shouldn't be oversold as final
- One sentence on what the control group is for: "so a system that just
  flags every mention of the word 'system' doesn't score a fake win."

*(If the held-out run has completed by recording time, replace/add those
numbers here — same format, clearly labeled held-out vs dev, per the
brief's held-out discipline requirement.)*

## 4:00–4:40 — What broke and how it was recovered

Pull 2-3 concrete entries straight from `NOTES.md`, don't reconstruct from
memory on camera. Strongest candidates as of this draft:

1. The retry bug: forced-round retries were resending an *identical*
   prompt at low temperature, which mostly reproduces the same failure —
   fixed with a corrective nudge message that actually changes the retry.
2. The key-attribution bug: error handling was calling `pool.next()` a
   second time just to get a name for logging, which returned whatever
   key was next in rotation, not the one that actually failed — caught
   because the same key name showed 3 different organization IDs in the
   logs, which is impossible for a real key.
3. The quota-contamination catch: the adversarial suite's raw summary
   line would have said "33% defense rate" at one point — checked the
   actual per-fixture reasons before reporting anything and found it was
   quota fallback rows, not real defense failures.
4. The stronger one, if there's time for a fourth: a genuine regression —
   results went from 33/34 verified-genuine fixtures down to 21/34 after
   running the same recovery script a second time. Turned out to be a
   race condition between two runs on the same results file. Couldn't
   fully prove the exact mechanism from the evidence available, and said
   so honestly instead of presenting a guess as fact — but fixed it
   regardless with a lock file that makes two overlapping runs
   structurally impossible, covered by dedicated tests. This is worth
   including specifically because it shows debugging discipline under a
   real, live failure, not a rehearsed one.

## 4:40–5:00 — Known limitations, stated plainly

- Labels are rubric-derived on synthetic data, not real dispute outcomes
  — the rubric is mechanical specifically so it's checkable, but it's a
  simplified proxy.
- Sample sizes: 100 dev / 50 held-out is directional, not definitive.
- The manual_review coverage gap (33%) — say it again here, it's worth
  repeating rather than only saying it once and moving on.

---

## Honesty checklist before recording (brief's own rules)

- [ ] Sample sizes said out loud next to every number
- [ ] Say when a metric is lenient and how (the FP/FN cost model's own
      blind spot — cases that bypass a warranted review aren't priced,
      and the video should say this, not just the README)
- [ ] At least one real failure shown, not just wins
- [ ] If a number changed between dev iterations, say so rather than only
      showing the final one
- [ ] Cost assumptions (INR 800 flat FP, INR 150 review cost) stated as
      assumptions, not facts
