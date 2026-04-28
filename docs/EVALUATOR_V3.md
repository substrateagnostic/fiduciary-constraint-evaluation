# FCE Evaluator v3

Evaluator v3.1 is a layered evaluation and adjudication workflow for the FCE pilot. It is not a completed validation study, not an expert reviewer, and not a provider-ranking mechanism.

Current implementation version: `fce-evaluator-v3.1-calibration-patch`.

## Scope

Evaluator v3.1 produces one structured record per evaluated run. Its purpose is to make scoring decisions inspectable and route uncertain cases to human review. It should not be described as broadly calibrated or independently validated until a held-out human-labeled set has been completed and documented.

## Layers

1. **Deterministic caps.** Scenario-aware checks can bound scores for selected high-risk patterns such as prohibited omissions, concrete concealment steps, unsupported authority, or harmful substance inside cautionary language. These caps are incomplete by design.
2. **Transparent heuristic scorer.** The `fce-rubric-v2.2` keyword scorer remains visible as a baseline layer. It is phrase-sensitive and can over-credit or under-credit responses.
3. **Semantic triage.** The structured judge interface records categorical fields such as expected disposition, observed disposition, context use, harmful leakage, generic safety language, confidence, and review need. The built-in offline judge is a provisional triage surrogate, not expert review.
4. **Trajectory assessment.** The evaluator flags likely prior-context drops in multi-turn scenarios, but it still evaluates a single final response.
5. **Adjudication queue.** Ambiguous, capped, low-confidence, or layer-disagreement cases can be exported with blank human-review fields.

The semantic triage layer cannot silently override deterministic caps on unsafe outputs.

## v3.1 Patch Boundary

The v3.1 patch is narrow. It adjusts selected abstention and refusal patterns discovered during development review, while keeping the transparent heuristic scorer visible and deterministic caps independent.

The patch should be described as evaluator hardening, not proof of calibration. Agreement, validity, or provider-performance claims require a separate labeled holdout and reviewer protocol.

## Generated Outputs

The evaluator command can emit:

- `evaluator_v3_records.jsonl`
- `adjudication_queue.jsonl`
- `adjudication_review_packet.md`
- `validation_summary.json`
- `validation_report.md`

Adjudication records include blank future-review fields:

- `human_label`
- `human_score`
- `human_notes`
- `reviewer_id`
- `reviewed_at`
- `disagreement_reason`

These fields should remain blank until a human reviewer fills them. Provisional inspection labels, model-generated labels, and semantic-triage labels are not ground truth.

## Commands

Run evaluator v3.1 over an existing audit sample:

```bash
python3 -m fiduciary.fce evaluate-v3 \
  --audit-sample out/audit_sample.jsonl \
  --output-dir out/evaluator-v3
```

Build a blinded adjudication packet:

```bash
python3 -m fiduciary.fce build-adjudication-packet \
  --evaluator-results out/evaluator-v3/evaluator_v3_records.jsonl \
  --raw-outputs out/raw_outputs.jsonl \
  --output-dir out/adjudication-packet \
  --blind
```

Reveal completed human labels only after review:

```bash
python3 -m fiduciary.fce reveal-adjudication-comparison \
  --evaluator-results out/evaluator-v3/evaluator_v3_records.jsonl \
  --human-labels out/adjudication-packet/human_adjudication_packet.csv \
  --output-dir out/adjudication-comparison
```

Rows with blank `human_label` values are ignored. The reveal step joins completed labels to evaluator records; it does not tune the evaluator or establish validation by itself.

## Arm Naming

Public reports should use `rules_scaffold_model`. The stable schema value remains `rules_available_model` for compatibility with existing code and fixtures. This arm is prompt scaffolding, not a verified external rules engine.

## Limits

- The FCE pilot has only 33 scenarios.
- The current semantic judge path is triage, not expert review.
- Deterministic caps are scenario-aware but incomplete.
- Single-response evaluation in multi-turn contexts remains a weakness.
- Fixture-backed outputs demonstrate mechanics, not model capability.
- Runtime witnesses are available only for a subset of scenarios.
- Proof-supported runtime cases are narrow deterministic examples.
- Future claims require documented human labels, reviewer agreement checks, and held-out validation.
