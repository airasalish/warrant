# Labelling Rubric

This is the written rule set every case's ground-truth label is derived
from. It is applied by `scripts/generate_dataset.py::label_case()` —
**deterministic code, not the LLM under test.** That's the whole point of
committing this file: a reader can check any case's label against these
rules by hand, and the labels don't depend on the same model being
evaluated having judged them. See §1 of the brief's "held-out discipline"
requirement — an eval where the system labels its own test data is
circular and the numbers mean nothing.

Reason codes below are modeled on real, publicly known Visa/Mastercard
dispute categories, paraphrased and simplified for this synthetic dataset
— not copied from any card network's own document, and not claiming to be
authoritative merchant-guide text. The evidence-type vocabulary is this
project's own design.

---

## 1. Reason codes and their minimum evidence requirement

| Code | Network | What it disputes | Minimum evidence types required |
|---|---|---|---|
| `10.4` | Visa | Card-absent fraud — cardholder says they didn't authorize it | `avs_cvv_match`, `device_fingerprint_or_ip_log` |
| `13.1` | Visa | Merchandise/services not received | `proof_of_delivery`, `shipping_carrier_record` |
| `13.3` | Visa | Not as described / defective | `product_listing_match`, `communication_log` |
| `12.6.1` | Visa | Duplicate processing | `transaction_log_dedup` |
| `4853` | Mastercard | Defective / not as described | `product_listing_match`, `return_policy_ack` |
| `4855` | Mastercard | Goods/services not provided | `proof_of_delivery`, `service_completion_record` |
| `4837` | Mastercard | No cardholder authorization | `avs_cvv_match`, `cardholder_ip_device_match` |
| `4863` | Mastercard | Cardholder doesn't recognize transaction | `avs_cvv_match`, `prior_purchase_history` |

Each evidence item a merchant submits is tagged with one of these types
(e.g. `proof_of_delivery: signed courier receipt dated 2026-07-14`). The
tag, not the free-text description, is what the rubric and the pipeline's
deterministic signal check against — matching the "grounded citation, not
inference" principle used throughout this project.

## 2. Evidence sufficiency

- **`sufficient`** — every required evidence type for the case's reason
  code is present among the submitted evidence items.
- **`insufficient`** — at least one required type is present, but not all.
- **`not_enough_information`** — no evidence was submitted at all.

## 3. Deterministic risk signals (computed in code, not inferred by the model)

- **`amount_anomaly`** — the disputed amount doesn't match the original
  transaction amount on file, or exceeds it (a partial chargeback can
  never be larger than the original transaction).
- **`merchant_repeat_pattern`** — the merchant's chargeback rate is above
  the platform baseline (`PLATFORM_BASELINE_CHARGEBACK_RATE`, see
  `code/main.py`) **and** their prior contest win rate is low — a merchant
  who disputes a lot and rarely wins isn't automatically wrong on any one
  case, but the pattern is a real signal a human should weigh.

## 4. Ground-truth decision

Applied in this order — the first matching rule wins:

1. If `amount_anomaly` **or** `merchant_repeat_pattern` is present →
   **`manual_review`**. A risk signal outranks otherwise-clean evidence;
   the point is that "sufficient evidence" alone isn't always enough to
   auto-decide.
2. Else if evidence sufficiency is `sufficient` → **`contest`**.
3. Else (evidence is `insufficient` or `not_enough_information`) →
   **`accept_liability`** — nothing on file supports fighting the dispute,
   and no risk signal argues for sending it to a human either.

`manual_review` is an abstention, not a "hard case" bucket engineered to
be unlearnable — it exists because real risk signals sometimes outrank
clean evidence, and a system that always trusts evidence completeness
alone would miss that.

## 5. What this rubric deliberately does NOT cover

Prompt-injection / adversarial narrative content is **not** part of this
dataset or this rubric. That's tested separately, in a dedicated,
clearly-scoped, defense-only regression suite
(`tests/adversarial_regression/`, brief §6c) — kept out of the main
dataset entirely so there's no ambiguity about attack-flavored content
being scattered outside its designated, safely-named location.

## 6. Known limitation

Labels here are rubric-derived on synthetic cases, not sourced from real
dispute outcomes — stated plainly, per the brief's honesty rules. The
value of this rubric is that it's mechanical and auditable, not that it
reflects real-world card-network adjudication in full.
