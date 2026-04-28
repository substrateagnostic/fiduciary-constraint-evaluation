# FCE Pilot Report Template

## Scope And Claim Boundary

This report covers the current FCE pilot only. It evaluates whether the tested system maintained fiduciary-style constraints across short, multi-turn scenarios and whether it refused, clarified, or escalated when required.

It does not show that the system is generally legally reliable, production-safe, or "aligned."

## Run Metadata

- date:
- commit:
- tags at head:
- dirty:
- environment:
- installation command:
- test command:
- benchmark command:
- models / arms evaluated:
- run sources:
- witness mode counts:

## Scenario Set

- scenario count:
- scenario ids:
- domains covered:
- which scenarios included executable runtime cases:

## Aggregate Results

| Arm | Runs | Mean Score | Escalation Precision | Escalation Recall | Severe Harm Rate | Silent Constraint Drop Rate | Witness Fidelity |
| --- | --- | --- | --- | --- | --- | --- | --- |
| raw_model |  |  |  |  |  |  | n/a |
| prompted_model |  |  |  |  |  |  | n/a |
| rules_scaffold_model |  |  |  |  |  |  | n/a |
| prismweft_runtime |  |  |  |  |  |  |  |

## Findings

### What Worked

- 

### What Failed

- 

### Failure Modes Worth Attention

- silent constraint drop:
- locally valid but globally invalid behavior:
- unsupported confident answer:
- confidentiality / fraud / billing / retention harms:

## Runtime Layer Evidence

State clearly which scenarios produced executable witnesses and whether those witnesses matched the expected disposition.

### Capability Boundary Summary

- fixture-backed runtime witnesses:
- runtime-derived annotation-heavy witnesses:
- proof-supported runtime witnesses:
- current disposition coverage (`clarify` / `refuse` / `escalate` / `continue`):

### Readable H1 Witness

- scenario:
- event:
- conflict class:
- minimal conflict set:
- handoff target:
- explanation:
- audit-safe metadata noted:

### Readable H2 Witness

- scenario:
- event:
- conflict class:
- minimal conflict set:
- handoff target:
- explanation:
- audit-safe metadata noted:

## Interpretation

Use this section for modest, defensible claims only.

- What the pilot supports:
- What the pilot does not support:
- Why this differs from static legal trivia benchmarks:

## Next Steps

- scenario expansion:
- independent human holdout validation:
- runtime coverage expansion:
- reviewer questions still open:
