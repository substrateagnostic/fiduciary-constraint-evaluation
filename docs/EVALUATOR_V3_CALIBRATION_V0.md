# Evaluator v3 Calibration Status

This note records the public calibration boundary for FCE Evaluator v3.1. It intentionally avoids reporting development-set agreement metrics as validation results.

## Current Boundary

- Evaluator v3.1 has deterministic caps, a transparent heuristic scorer, semantic triage, trajectory flags, and adjudication export tooling.
- Development review has informed selected hardening changes.
- No completed independent human holdout validation is included in the public repository.
- Any future calibration claim should identify the label source, reviewer qualifications, label protocol, adjudication procedure, held-out status, and disagreement handling.

## What May Be Shared

Safe public artifacts:

- the human calibration protocol
- small blinded packet format samples
- evaluator commands and schemas
- limitations and known failure modes

Avoid publishing raw provider output dumps or development-set result tables as if they were validation.

## Required Language

Acceptable:

- "Evaluator v3.1 routes uncertain cases to human adjudication."
- "The semantic judge is a triage layer, not expert review."
- "Independent holdout validation is not complete."

Avoid:

- "Evaluator v3.1 is calibrated."
- "The benchmark is validated."
- "These scores rank providers."
- "The rules scaffold is an external rules engine."
