# FCE Review Pack Issues

Derived from the local `integrate/fce-review-pack` branch without merging its raw critique files onto `main`.

Sources reviewed:

- `integrate/fce-review-pack:CRITIQUE.md`
- `integrate/fce-review-pack:REDTEAM.md`

## Tracked Follow-Ups

| ID | Source | Status | Summary | Next step |
| --- | --- | --- | --- | --- |
| RP-001 | REDTEAM P0-3, CRITIQUE O4 | Addressed on `main` | Add a first-class path for scoring externally captured outputs instead of only fixture-backed structured outcomes. | Land replay/import adapter, CLI mode, and tests. |
| RP-002 | REDTEAM P0-3, P1-7 | Open | Free-text scoring still relies on keyword inference plus explicitly supplied persistence/global-validity fields when those are available. | Add an optional structured extractor or judge pass for raw outputs. |
| RP-003 | CRITIQUE O5, REDTEAM P2-9 | Open | The benchmark still evaluates a single response point inside a multi-turn context rather than repeated model turns. | Add multi-response scenario variants when the pilot surface stabilizes. |
| RP-004 | REDTEAM P2-8, P3-18 | Open | Runtime cases are still skewed toward positive detections and lexicalizable conflicts. | Add more negative runtime cases and synonym-heavy enclave prompts. |
| RP-005 | REDTEAM P1-10 | Open | Response-explanation and witness-fidelity axes remain arm-specific and should not be overcompared. | Keep report language bounded and avoid claiming cross-arm equivalence for that axis. |
| RP-006 | REDTEAM P2-12 | Open | Coverage remains ABA-model-rules-centric. | Add explicit cross-jurisdiction variants after replay/live ingestion is stable. |

## Notes

- The review-pack branch intentionally removes the current FCE implementation from the tree, so it is a review source, not a merge candidate.
- This doc is the merge-safe synthesis. The raw critique files remain isolated on `integrate/fce-review-pack`.
