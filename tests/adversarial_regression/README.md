# Adversarial regression suite

> This suite is defensive. It contains fixed, publicly-documented injection
> patterns used as regression tests to verify the agent's untrusted-input
> handling. It does not generate novel attacks, does not target
> third-party systems, and produces no offensive capability. It exists so
> the defense can be measured rather than asserted.

## What this is

24 attack fixtures (`fixtures.py::ATTACK_FIXTURES`) covering well-known,
publicly-documented prompt-injection categories (OWASP LLM Top 10 style):
direct instruction override, authority/admin spoofing, fake system-tag
delimiters, fake conversation continuation, payload injection via code
blocks, persona/jailbreak framing, fake prior-approval claims, and prompt
leaking — applied to this project's own domain (a chargeback merchant
narrative) so they test THIS system's defense, not anyone else's.

10 benign control fixtures (`fixtures.py::CONTROL_FIXTURES`) that use
similar surface vocabulary ("override," "system," "ignore," "contest")
without actually directing the model to do anything, so a defense that
just pattern-matches on scary-looking words shows up as a control
false-positive, not a clean win.

## What this deliberately is NOT

- No novel attack discovery, no optimization loop, no attack-generation
  code anywhere in this repo.
- No transferability testing against any third-party system — every
  fixture runs only against this project's own pipeline, on synthetic
  data.
- Not named `attacks/`, `exploits/`, `red_team/`, or `payloads/` — kept
  clearly scoped as a regression test suite, same as any security test
  suite in a normal engineering repo.

## Running it

```bash
python tests/adversarial_regression/run_suite.py
```

Reports two numbers side by side, per the brief's own requirement — never
just the attack-defense rate alone:

- **Defense rate** — share of attack fixtures correctly flagged
  `prompt_injection_attempt`.
- **Control false-positive rate** — share of benign fixtures *incorrectly*
  flagged the same way. A system that flags everything scores 100% on the
  first number while being useless; this number is what stops that from
  looking good.

Full per-fixture results land in `results.csv` (git-ignored — regenerate
by running the suite; the numbers belong in the main README, not as a
committed artifact that goes stale).
