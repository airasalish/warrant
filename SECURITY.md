# Security posture

## Scope, stated honestly

This project never touches real cardholder data, real merchant
credentials, or Razorpay's own payment APIs — it's a hackathon prototype
running against a synthetic, rubric-labelled dataset (`dataset/`). That
means PCI-DSS scope doesn't technically apply here; there's no cardholder
data to protect because none exists in this repo. What follows isn't a
compliance claim — it's this project voluntarily following the same
operating discipline Razorpay's own published security practices describe
([razorpay.com/docs/security](https://razorpay.com/docs/security/)),
because the whole point of a Track 2 (AI Risk Manager) submission is
handling money-adjacent decisions the way a real risk team would.

## Secrets

- The only credential this project uses is a `GROQ_API_KEY` (this is an
  LLM-inference key, not a payment credential). It is read from the
  environment only — `code/main.py`'s `KeyPool` never accepts a key as a
  literal, hardcoded value.
- `.env` is git-ignored. `.env.example` ships with a placeholder only.
- `scripts/check_no_secrets.py` scans staged files for key-shaped strings
  (Groq, and — defensively — Razorpay's own `rzp_live_`/`rzp_test_` format,
  AWS keys, private-key blocks, and any `*_API_KEY`/`*_SECRET`/`*_TOKEN`
  assignment that isn't an obvious placeholder) before a commit is allowed
  through. Install it once per clone:

  ```bash
  cp scripts/pre-commit .git/hooks/pre-commit
  chmod +x .git/hooks/pre-commit   # not needed on Windows
  ```

  This exists as a script, not just a README promise, because Razorpay's
  own docs state the same rule — secret keys must never be committed, env
  vars only — and a script that structurally blocks the commit is
  evidence that rule is followed, not just asserted.
- Verified directly (not assumed): `git log --all -p | grep gsk_` across
  every commit in this repo's history returns only the placeholder in
  `.env.example`, never a real key. Log output (`KeyPool`'s prints, error
  messages) references key **names** (`GROQ_API_KEY`, `GROQ_API_KEY_2`,
  ...) only — never key values, anywhere in the codebase.

## Least-privilege data access

`code/main.py`'s `_execute_tool()` deliberately ignores whatever
arguments the model supplies (`case_id`, `merchant_id`, etc.) and always
resolves against the pipeline's own pre-computed context for the *current*
case — a wrong or hallucinated identifier can never leak another case's or
merchant's data, because the tool's authority is the pipeline's own ground
truth, not the model's claim about which record it wants. This is the same
need-to-know principle access-control systems use generally, applied at
the tool-call boundary of an LLM agent rather than at a database or API
layer.

## Untrusted input

Merchant-submitted narrative text and evidence descriptions are treated as
**data, not instructions** — see the `SYSTEM_PROMPT` untrusted-input block
in `code/main.py` and the adversarial regression suite (in progress,
`tests/adversarial_regression/`, see the main README's defense-only
posture statement). The threat model: a party with a direct financial
interest in the model's decision can write arbitrary text into a field the
model reads, so that field cannot be trusted as authoritative about what
the model itself should do.

## Known limitation, disclosed rather than hidden

The local LLM response cache (`.cache/llm_responses/*.json`, git-ignored)
stores request/response pairs in plaintext on disk. That's an acceptable
tradeoff here because the dataset is synthetic with no real PII — but if
this pipeline were ever pointed at real chargeback evidence (which can
contain customer names, addresses, and order details), the cache would
need encryption at rest before that was acceptable. Flagging this now
rather than waiting to be asked, per the project's own honesty rules.
