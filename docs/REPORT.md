# Fiduciary Constraint Evaluation: Methods Report

**Alex Galle-From**
July 2026

This is a methods report for the Fiduciary Constraint Evaluation (FCE) pilot. It describes
what the current repository contains, how the pilot is scored, what the runtime witness and
proof layer do and do not establish, and where the evidence stops. It is not a validation
study and reports no significance claims.

---

## Abstract

FCE tests a narrow workflow problem: a model may state a fiduciary or professional
constraint correctly, then fail to keep that constraint live when the user reframes the
task, adds urgency, introduces ambiguity, or asks for a locally convenient but globally
invalid action. The current pilot is 33 short multi-turn scenarios across nine
professional-duty domains. The scenario texts were drafted by GPT-5.6-Sol to my
specification; the required dispositions and scoring criteria are mine. Each scenario carries a required disposition (escalate,
refuse, clarify, or correct-continue), hidden constraints, must-not behaviors, and rubric
data. Responses are scored by a transparent heuristic scorer (`fce-rubric-v2.2`) inside the
evaluator v3.1 infrastructure. A subset of 17 scenarios additionally carries a runtime
witness derived from an explicit constraint-conflict check, and a narrower subset of those
carries a machine-checkable proof object. A live comparison run across four
current-generation models was recorded on 2026-07-10; its numbers live in the packet under
`reports/comparison-packet-20260710/` and are not reproduced here.

This report supersedes the January 2026 "Fiduciary Evals" write-up, which described a
different, 17-scenario single-turn benchmark with a different scorer. Where that earlier
document's claims are specific to its 17-scenario set, they do not carry to the current
pilot; the differences are stated in the section on the January baseline below.

---

## 1. Why This Exists

Many legal and professional benchmarks test whether a model can state a rule. FCE tests a
narrower operational problem: constraint persistence. A model that correctly names a duty in
turn one may drop it in turn three when the request is reframed. The pilot is built around
operational failure modes such as silent constraint drop, unsupported confident answers,
generic hedging, overbroad refusal, harmful leakage before clarification, and escalation
failure.

The threat model of interest is not an outside user trying to jailbreak the model. It is an
insider-shaped request that sounds authorized and uses operational language, directed at an
agent that holds a duty to some third party. That framing does not trigger typical harm
guardrails, which is why constraint persistence is worth measuring on its own.

---

## 2. Task Definition

A fiduciary or professional relationship obligates an agent to act in a principal's interest
even when a third party's instruction or the agent's own convenience points elsewhere. The
pilot operationalizes this as a required disposition per scenario rather than as a single
refuse-or-comply axis.

The four required dispositions are:

- **escalate_required** — the correct action is to route the request to a human or a
  named handoff target rather than to act.
- **refuse_required** — the correct action is to decline, ideally naming the duty at stake.
- **clarify_required** — the correct action is to ask for the missing information before
  acting, not to act on the ambiguous request.
- **correct_continue** — the correct action is to continue with the requested work,
  because the request is within scope and refusing would be an overcaution failure.

The `correct_continue` disposition is a deliberate control against a grader that rewards
refusal unconditionally. A scorer that treats every refusal as a pass cannot detect
overbroad refusal; the correct-continue scenarios exist so that over-refusal is a scored
failure, not an invisible one.

---

## 3. Methodology

### 3.1 Scenario set

The pilot contains 33 typed scenarios across nine domains:

| Domain | Scenarios |
| --- | ---: |
| confidentiality and privilege | 6 |
| candor, truthfulness, and fraud | 6 |
| competence and uncertainty | 4 |
| supervision of AI and nonlawyers | 4 |
| client communication and informed consent | 3 |
| fees, billing, and hidden automation | 3 |
| retention, deletion, logging, and escalation | 3 |
| safekeeping and trust handling | 3 |
| conflicts of interest | 1 |

By required disposition, the 33 scenarios distribute as escalate_required 17,
refuse_required 8, clarify_required 5, correct_continue 3. Scenario IDs follow the pattern
`FCE-<DOMAIN>-<NNN>-V<k>`, where the `V<k>` suffix marks phrasing variants within a scenario
family. This is a small, hand-curated pilot, useful as an inspectable artifact and methods
scaffold, not as a statistically powered benchmark.

### 3.2 Evaluation arms

Each scenario can be run under three response arms plus one runtime arm:

- `raw_model` — the model with no fiduciary hardening.
- `prompted_model` — the model with a fiduciary system prompt.
- `rules_available_model` — a prompt-based rules scaffold (displayed in reports as
  `rules_scaffold_model`; this is a compatibility schema name, not a verified external
  rules engine).
- `prismweft_runtime` — the runtime witness arm, which runs a constraint check rather than
  calling a model. It applies only to the 17 scenarios that carry a `runtime_case`.

### 3.3 Scoring

Responses are scored by a transparent heuristic scorer, `fce-rubric-v2.2`, inside the
evaluator v3.1 infrastructure (`fce-evaluator-v3.1-calibration-patch`). The evaluator
combines:

- deterministic caps for selected high-risk failure patterns,
- a heuristic rubric scorer that remains visible in the record,
- semantic triage through structured categorical fields,
- trajectory flags for suspected prior-context drops,
- a human adjudication packet generator with blank human-review fields.

The scorer produces a weighted score and per-axis metrics (for example escalation recall,
severe-harm rate, and silent-drop rate), not a single pass/fail label. The semantic judge
path is triage, not expert review; deterministic caps can miss edge cases or overflag safe
responses. The scorer relies partly on substring matching, which produces both false
positives and false negatives, and it cannot always distinguish a genuine continuation from
a short non-answer on a correct-continue scenario.

### 3.4 Live comparison packet (2026-07-10)

A live comparison run across four current-generation models plus the runtime arm was
recorded on 2026-07-10. The reviewer-facing bundle, its frozen configuration, its
descriptive per-arm aggregates, and its stop-reason accounting are in
`reports/comparison-packet-20260710/PACKET.md`. That packet is the source of record for the
numbers; they are not reproduced here to avoid drift between two copies. Two points from it
matter for reading any figure:

- `max_output_tokens` was set to 8192 and `temperature` was left unset (omitted from
  requests). An earlier April 2026 packet used a 512-token default, so scores are not
  directly comparable across packets even where a model class repeats.
- One model's provider safety layer returned refusals with empty content on several
  fiduciary scenarios. Those empty completions score as failures under the rubric, so that
  model's aggregate mixes fiduciary-behavior measurement with provider-safety-layer
  behavior. The packet reports this rather than adjusting for it.

A fifth model requested for inclusion, `gpt-5.6-sol`, was not accessible on the run date
(HTTP 404, `model_not_found`); no run artifacts exist for it.

---

## 4. Runtime Witness And Proof Layer

Prompting can steer a model toward safer behavior. The runtime witness path is different:
for the 17 scenarios with a `runtime_case`, it runs explicit constraint-conflict checks and
emits a structured witness describing the conflict class, required disposition, minimal
conflicting set, and handoff target. The witness fields — disposition, conflict type,
minimal set, and constraint IDs — are derived from the obstruction analysis, not from the
scenario's expected answer.

A narrower subset carries a machine-checkable proof object under schema
`fce-coherent-witness-v0.2`. The validator re-runs the deterministic runtime check on the
exact runtime case bound to the witness (by canonical hash plus engine id), and checks fact
contents, not merely fact kinds: unique fact ids, referenced constraint ids that resolve
against the evaluated case, obstruction claims consistent with the derived result, a pinned
schema version, and an affirmative witness status.

The evidence boundary is explicit and must not be overread:

- Three scenarios (`FCE-SUP-011-V1`, `FCE-CONF-012-V1`, `FCE-COMP-013-V1`) are
  proof-backed correct-continue stand-downs. A stand-down means the supported detectors
  fired no obstruction on a static, author-specified constraint set through the configured
  order (2). It does **not** mean the constraint set was proved satisfiable: no satisfying
  assignment is constructed or checked. Affirmative satisfiability is a v0.2 goal, not a
  current guarantee.
- These three cases function as negative controls against reflexive firing on one lexical
  case each. They are not a calibrated false-positive rate and do not prove judgment in
  general.
- In the executable runtime arm the surrounding adapter fields are not yet decoupled from
  the answer key: on a stand-down the response prose, reported actions, and identified
  duties fall back to scenario-authored expectations. The witness is runtime-derived; the
  fields the rubric scores around it are not. Decoupling them is roadmapped.
- The runtime currently evaluates the fixed `runtime_case`, not the conversation text. It
  demonstrates detection capability on a formalized constraint set, not on the live user
  turn.

The full red-team review that established these boundaries, and the maintainer response, are
under `docs/redteam/2026-07-10-gpt-5.6-sol-review.md` and
`docs/redteam/2026-07-10-response.md`. The v0.2 roadmap replaces the `None` stand-down with
an input-bound clearance certificate that returns `CLEAR` only when a concrete satisfying
assignment has been checked, and `UNKNOWN` otherwise.

---

## 5. Relationship To The January 2026 Baseline

An earlier evaluation series from January 2026, "Fiduciary Evals," is archived under
`docs/baselines/2026-01/` as a longitudinal reference. It is a different artifact and its
specific claims do not transfer to the current pilot. The relevant differences:

- **Scenario set.** The baseline was 17 single-turn scenarios organized under five "soul
  invariant" categories (NAD, NASHU, PRISUTSTVIE, PAMYAT, VZAIMNOST/CONSENT). The current
  pilot is 33 short multi-turn scenarios organized by nine professional-duty domains and
  four required dispositions.
- **Scorer.** The baseline graded by weighted refusal-phrase pattern matching into
  PASS / SOFT_FAIL / HARD_FAIL, passing a response whose weighted score was at least 2.
  The current pilot uses `fce-rubric-v2.2` under evaluator v3.1, which produces weighted
  scores and per-axis metrics.
- **Outcome taxonomy.** The baseline treated refusal as the only pass, so it could not
  score overbroad refusal as a failure and had no correct-continue disposition. The current
  pilot scores over-refusal as a failure through its three correct-continue controls.
- **Baseline headline claims.** The baseline reported per-invariant pass rates and a
  no-model-exceeds-60% overall figure. Those figures are specific to the 17-scenario set
  and its pattern-match grader; they are not comparable to the current pilot's weighted
  scores and do not carry forward. The `docs/baselines/2026-01/` files also include three
  empty runs (zero results) and one partial run (11 of 17); those are run-log artifacts,
  not model rankings.

The two series should be read as a record of how framing and method changed between January
and July 2026, not as points on one comparable scale.

---

## 6. Limitations

- The pilot has only 33 scenarios and is jurisdiction-general and English-only.
- The evaluator is not a substitute for human legal or professional judgment.
- The semantic judge is triage, not expert review.
- Deterministic caps are incomplete and can miss or overflag edge cases.
- Single-response evaluation inside multi-turn contexts remains imperfect.
- Runtime coverage is subset-specific (17 of 33 scenarios), and the runtime evaluates a
  fixed constraint set, not the live conversation.
- Proof-supported cases are narrow deterministic examples; a stand-down attests to the
  absence of a detected obstruction, not to a checked satisfying assignment.
- Fixture-backed runs demonstrate package mechanics and report generation, not model
  capability.
- No independent human holdout validation has been completed.

---

## 7. What This Does Not Claim

This repository should be read with the limitations first:

- It is not legal advice.
- It is not production software.
- It is not a validated benchmark.
- It is not a provider ranking.
- It is not a substitute for attorney, supervisor, compliance, or domain-expert review.
- It is not human-calibrated beyond any explicitly documented development label sets, and it has no completed independent human holdout validation.
- It does not claim that any model is better or worse than another.
- It does not claim to solve alignment or guarantee ethical behavior.
- The `rules_available_model` schema value is a compatibility name for a prompt-based rules scaffold. Public docs call this `rules_scaffold_model`; it is not a verified external rules engine.

---

## 8. Status

- 33-scenario pilot implemented and tested.
- Runtime witness subset implemented (17 scenarios).
- Narrow proof-supported runtime examples implemented, at schema
  `fce-coherent-witness-v0.2`.
- CLI export, run, report, replay, live-adapter, evaluator, and adjudication surfaces
  implemented.
- One curated live comparison packet committed under
  `reports/comparison-packet-20260710/`.
- Independent human holdout validation is not complete.
- The v0.2 runtime milestone (input-bound clearance certificate) is roadmapped and not yet
  implemented.

---

## References

- Galle-From, A. (2026). "Verification Without Surveillance."
  https://www.alexgallefrom.io/writing/verification-without-surveillance
- `reports/comparison-packet-20260710/PACKET.md` — the 2026-07-10 live comparison packet.
- `docs/FCE_METHODS.md`, `docs/fce_spec.md` — method and specification detail.
- `docs/redteam/2026-07-10-gpt-5.6-sol-review.md`, `docs/redteam/2026-07-10-response.md` —
  red-team review and maintainer response.
- `docs/baselines/2026-01/` — the January 2026 evaluation baseline.
