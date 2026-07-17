# FCE Human-Validation Study — Reviewer Brief

**DRAFT — HUMAN GATE. Not final until approved by the study owner.**

*Prepared for: independent reviewers being recruited by Alex Galle-From (study owner).
This is a recruiting and scoping brief, not the rating instrument. The frozen protocol
lives in `PREREGISTRATION-draft.md`; what a rater actually sees lives in
`RATING_PACKET_TEMPLATE.md`.*

---

## 1. What FCE measures

Fiduciary Constraint Evaluation (FCE) is a small research benchmark. It tests one narrow
thing: when an AI system has already been told about a professional or fiduciary duty
earlier in a conversation, does it keep acting on that duty when the user then pushes back —
through urgency, euphemistic reframing, role confusion, or instructions that cannot all be
satisfied at once?

Each scenario is a short multi-turn conversation ending in one model response. The response
is expected to do one of four things ("required disposition"): **continue** the in-scope
work, **clarify** before acting, **refuse**, or **escalate** to a human. A response is
scored against that scenario's expected behavior by an automated, keyword-based rubric
(the "scorer," version `fce-rubric-v2.2`) on a 100-point scale across five axes: duty
recognition, constraint persistence, action correctness, harm avoidance, and explanation
quality.

FCE is a jurisdiction-general, ABA-Model-Rules-style pilot of 33 hand-authored scenarios. It
is explicitly **not** a validated benchmark, not legal advice, not a provider ranking, and
not a claim that any model is "aligned." The scope of this study is equally narrow.

## 2. Why independent validation is needed (stated plainly)

The automated scorer is a transparent keyword/rubric heuristic, not a legal expert. The
project ran an internal manual check of the scorer against a fresh set of model responses
and the scorer **failed**: on a 24-item audit it was directionally correct on only **14 of
24** items (58%), and it did not clear the project's own pre-set "stop gate" for treating
the scores as usable. As a result the project has **closed its empirical lane**: it
currently publishes all FCE scores as "unvalidated instrument readings" and makes no
accuracy or ranking claims from them. (Source: `reports/comparison-packet-20260710/PACKET.md`.)

The study owner has commissioned this independent human-validation study to answer one
question honestly: **does the automated scorer agree with qualified attorney judgment on a
genuinely held-out set of scenarios — well enough to make any empirical claim at all?** The
answer may be "no." A clean, preregistered "no" is a valid and useful result here; this
study is designed so that failing is as publishable as passing.

Two facts make independence essential:
- The scorer's matching logic is **scenario-specific** — it grades each response against that
  scenario's own authored answer key, so all 13 existing scenario families are built into the
  scorer by construction (and its phrase lists were additionally tuned on earlier model outputs
  from the same pilot lineage). A fair test therefore requires **new scenario families the
  scorer has never seen** (see `PREREGISTRATION-draft.md`, "Sampling").
- Prior review of this project was done by its maintainer and by AI red-teamers. Neither is a
  substitute for independent, qualified human raters who are blind to the scorer's output.

## 3. Reviewer roles

Three independent reviewers, no prior involvement with FCE, blinded to scorer outputs and to
model identities (see Section 5).

**Rater A — Professional-responsibility attorney.** Licensed attorney with substantive legal-
ethics / professional-responsibility experience (e.g. ethics counsel, bar-discipline, or a
PR practice/teaching background). Independently judges each blinded response: what disposition
it actually takes, whether it is materially safe, and which (if any) failure pattern it shows.

**Rater B — Fiduciary / trust or compliance attorney.** Licensed attorney with fiduciary-duty,
trust-and-estates, or regulatory-compliance experience (e.g. trust administration, fiduciary
litigation, or in-house compliance). Rates the **same** items independently, giving a second
qualified judgment and enabling inter-rater agreement.

**Reviewer C — Measurement-methods reviewer.** A methods/measurement specialist (quant social
scientist, psychometrician, ML-evaluation methodologist, or statistician). Does **not** rate
items. Reviews the preregistration before data collection, checks that blinding and
randomization were executed as written, computes/audits the agreement statistics, and reviews
the honesty of the final claims. Legal expertise not required; measurement rigor is.

## 4. Time commitment (estimates, to be confirmed at contracting)

| Reviewer | Onboarding + calibration | Rating | Adjudication | Estimated total |
|---|---|---|---|---|
| Rater A (attorney) | 2–3 hrs | ~15–21 hrs (100–150 items @ 7–12 min) | ~1–2 hrs | **~18–26 hrs** |
| Rater B (attorney) | 2–3 hrs | ~15–21 hrs | ~1–2 hrs | **~18–26 hrs** |
| Reviewer C (methods) | design review 4–6 hrs | — | analysis + write-up review 6–10 hrs | **~10–16 hrs** |

Estimated attorney-rater hours combined: **~36–52 hrs**. See `LOGISTICS.md` for the budget
worksheet. Work is asynchronous and can be spread across ~2–4 weeks.

## 5. Independence and blinding requirements

Every reviewer must attest, in writing, that they:
- have **no prior involvement** with FCE, its code, its scenarios, or its scoring, and no
  financial or personal stake in a particular outcome (a genuine "the scorer fails" finding is
  an acceptable and compensated result);
- will rate/review **only** from the materials provided, and will **not** consult the FCE
  repository, its scorer, its documentation, or any FCE-related model output during rating.

Raters are **blinded to**: the automated scorer's score and per-axis output; any deterministic-
cap, semantic-triage, or trajectory label; the evaluator's recommendation and confidence;
and **the identity of the model** that produced each response. Items are presented in a single
randomized order per rater (procedure in `RATING_PACKET_TEMPLATE.md`). The methods reviewer
holds the blind key and does not rate.

Compensation is a **placeholder** pending the owner's decision: a flat honorarium or an hourly
rate per reviewer. Indicative envelope for the full study is **$3,000–$8,000** total across all
three reviewers; the itemized worksheet and rate scenarios are in `LOGISTICS.md`. Compensation
is **not** contingent on the study reaching any particular conclusion.
