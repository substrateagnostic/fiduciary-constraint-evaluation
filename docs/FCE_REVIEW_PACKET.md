# FCE Review Surface

This note describes the public review surface for the current FCE pilot. It replaces generated packet references with commands that can be run locally.

## Scope

The reviewable artifact is the package, schema, tests, CLI, methods docs, and small curated examples. Generated raw provider outputs and full comparison packets are intentionally excluded from the public tree.

## Generate A Local Smoke Bundle

```bash
python3 -m fiduciary.fce run-pilot --output-dir out/fce-smoke --execution hybrid
```

The generated bundle includes:

- `scenarios.jsonl`
- `runs.jsonl`
- `runs.csv`
- `summary.csv`
- `report.md`
- `manifest.json`
- `manifest.jsonl`
- `proof_artifacts.jsonl` when proof-supported runtime cases are present

Fixture-backed baseline arms demonstrate the scorer and reporting mechanics. They are not evidence of live model performance.

## Runtime Witness Examples

Representative pairwise witness:

- scenario: `FCE-RET-009-V1`
- conflict type: `H1`
- minimal conflict set: `preserve_records`, `prompt_content`
- expected handoff: `compliance`

Representative higher-order witness:

- scenario: `FCE-CANDOR-010-V1`
- conflict type: `H2`
- minimal conflict set: `candor_to_tribunal`, `omit_required_fact`, `maximize_client_advantage`
- expected handoff: `lawyer`

## Review Boundaries

What the public artifact supports:

- the CLI can emit machine-readable scenarios, runs, summaries, reports, and manifests
- runtime witnesses are inspectable for the supported subset
- proof-supported runtime examples are narrow and deterministic
- evaluator v3.1 can produce review queues and blinded packet formats

What it does not support:

- real-model provider rankings
- production-readiness claims
- validated benchmark claims
- legal reliability claims
- completed independent human holdout validation

## Curated Samples

- `examples/curated/fce_smoke_report.md`
- `examples/curated/blinded_packet_sample.md`
