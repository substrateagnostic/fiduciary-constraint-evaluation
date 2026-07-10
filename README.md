# Fiduciary Constraint Evaluation (FCE)

FCE is an experimental Python package and benchmark scaffold for evaluating whether AI systems preserve fiduciary and professional constraints across short multi-turn interactions. It focuses on constraint persistence, escalation, refusal, clarification, and readable runtime witness generation under pressure, ambiguity, or conflicting duties.

## What This Repository Contains

- A typed FCE pilot scenario schema.
- A 33-scenario pilot covering confidentiality, candor, conflicts, competence, supervision, fees, retention, communication, and related professional-duty themes.
- CLI tooling for scenario export, fixture-backed runs, replay/live adapters, report bundles, and adjudication packet generation.
- A runtime-backed witness subset that derives selected conflict witnesses from the `fiduciary.cohomology` runtime.
- A narrow proof-supported subset for selected deterministic runtime cases.
- Evaluator v3.1 infrastructure with deterministic caps, transparent heuristic scoring, semantic triage, trajectory flags, and a human adjudication queue.
- A blinded human adjudication workflow and small curated samples for review format inspection.

## What This Does Not Claim

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

## Why This Exists

Many legal and professional benchmarks test whether a model can state a rule. FCE tests a narrower workflow problem: a model may state a fiduciary or professional constraint correctly, then fail to keep that constraint live when the user reframes the task, adds urgency, introduces ambiguity, or asks for a locally convenient but globally invalid action.

The pilot is designed around operational failure modes such as silent constraint drop, unsupported confident answers, generic hedging, overbroad refusal, harmful leakage, and escalation failure.

## Benchmark Overview

The current pilot contains 33 scenarios. Each scenario is a short multi-turn conversation with hidden constraints, an expected behavior, must-not behaviors, harm severity, rubric data, and optional middleware expectations.

The pilot covers domains such as:

- confidentiality and privilege
- candor, truthfulness, and fraud
- conflicts and former-client duties
- competence and uncertainty
- supervision of AI or nonlawyer assistants
- fees and billing transparency
- retention, preservation, and cleanup requests
- client communication and represented-party contact

This is a small, hand-curated pilot. It is useful as an inspectable artifact and methods scaffold, not as a statistically powered benchmark.

## Runtime And Witness Concept

Prompting can steer a model toward safer behavior. The runtime witness path is different: for selected scenarios, it runs explicit constraint checks and emits a structured witness describing the conflict, required disposition, conflict class, minimal conflicting set, and handoff target.

The witness path is intentionally modest. It makes certain conflicts legible and reviewable; it does not decide legal questions generally and does not prove that all scenario semantics have been formalized.

Current runtime and proof support are subset-specific. Proof-supported examples validate narrow deterministic runtime claims, not legal correctness across the whole benchmark.

## Evaluator v3.1

Evaluator v3.1 is layered evaluation infrastructure, not a completed validation study. It includes:

- deterministic caps for selected high-risk failure patterns
- a transparent heuristic scorer that remains visible
- semantic triage through structured categorical fields
- trajectory flags for suspected prior-context drops
- human adjudication packet generation with blank human-review fields

The semantic judge path is triage, not expert review. Deterministic caps can miss edge cases or overflag safe responses. Future empirical claims require independent human labels, inter-rater review, and held-out validation.

## Installation And Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
pytest -q
python3 examples/fce_demo.py
```

Export scenarios:

```bash
python3 -m fiduciary.fce export-scenarios --output out/fce-scenarios.jsonl
```

Generate a fixture/runtime smoke bundle:

```bash
python3 -m fiduciary.fce run-pilot --output-dir out/fce-smoke --execution hybrid
```

Run a replay-backed evaluation when external outputs are available:

```bash
python3 -m fiduciary.fce run-pilot \
  --output-dir out/fce-replay \
  --baseline-adapter replay \
  --replay-input out/external_outputs.jsonl \
  --arms raw_model prompted_model rules_available_model
```

The CLI uses the stable schema value `rules_available_model`; reports display this arm as `rules_scaffold_model`.

Build a blinded adjudication packet from evaluator records and raw outputs:

```bash
python3 -m fiduciary.fce build-adjudication-packet \
  --evaluator-results out/evaluator-v3/evaluator_v3_records.jsonl \
  --raw-outputs out/raw_outputs.jsonl \
  --output-dir out/adjudication-packet \
  --blind
```

## Example Outputs

Curated, sanitized examples are kept small:

- [Curated FCE smoke report](examples/curated/fce_smoke_report.md)
- [Blinded adjudication packet sample](examples/curated/blinded_packet_sample.md)

Generated raw provider outputs and full comparison packets are intentionally excluded from the public tree. Regenerate local artifacts under `out/` when needed.

## Baselines

An earlier, separate evaluation series from January 2026 (the 17-scenario Fiduciary Evals
benchmark) is archived under [`docs/baselines/2026-01/`](docs/baselines/2026-01/) as a
longitudinal reference. Those runs used a different scenario set, a different scorer
(weighted refusal-phrase matching), and a different taxonomy, so they are **not** directly
comparable to this repository's 33-scenario packet. See that directory's README for the
model list and caveats.

## Limitations

- The pilot has only 33 scenarios.
- The evaluator is not a substitute for human legal or professional judgment.
- The semantic judge is triage, not expert review.
- Deterministic caps are incomplete and can miss or overflag edge cases.
- Single-response evaluation inside multi-turn contexts remains imperfect.
- Runtime coverage is subset-specific.
- Proof-supported cases are narrow deterministic examples.
- Fixture-backed runs demonstrate package mechanics and report generation, not model capability.
- Scenario coverage is hand-authored and jurisdiction-general; it is not comprehensive.

## Status And Roadmap

Current status:

- 33-scenario pilot implemented.
- Runtime witness subset implemented.
- Narrow proof-supported runtime examples implemented.
- CLI export, run, report, replay, live-adapter, evaluator, and adjudication surfaces implemented.
- Independent human holdout validation is not complete.

Conservative next steps:

- expand and rebalance the scenario set
- complete independent human holdout validation
- improve evaluator calibration against documented labels
- add second-reviewer and inter-rater agreement workflows
- expand runtime coverage where formalization is defensible
- package a middleware demo separately from benchmark claims

## Legal And Ethical Disclaimer

This repository is for research and evaluation only. It is not legal advice, does not create an attorney-client relationship, and should not be used in production legal, fiduciary, healthcare, financial, or other high-stakes workflows without independent professional review.

## License

No open-source license has been selected yet. All rights reserved unless and until a license is added.
