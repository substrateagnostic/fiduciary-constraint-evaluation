# Escalation recall — chart data (audit sheet)

Data behind `escalation-recall.svg`. Neutral extraction; numbers are copied from
the committed packet, not computed here.

- **Source (authoritative):** each bundle's
  `reports/comparison-packet-20260710/<bundle>/summary.csv`, field `escalation_recall`.
- **Cross-check:** `reports/comparison-packet-20260710/PACKET.md` summary table
  (lines 80–92). All values agree between `summary.csv` and `PACKET.md`.
- **Arm-name note:** the third arm is `rules_available_model` in the `summary.csv`
  files and `rules_scaffold_model` in `PACKET.md`'s table and in this chart — same
  arm, two labels.
- **Scope note:** live-model arms are over n=33 scenarios each; the
  `prismweft-runtime` value is over the n=17 scenario subset and is drawn as a
  separate reference, not a fourth arm.

| Model | raw_model | prompted_model | rules_scaffold_model |
| --- | ---: | ---: | ---: |
| `claude-fable-5` | 0.5882 | 0.7647 | 0.8824 |
| `claude-opus-4-8` | 0.3529 | 0.5294 | 0.9412 |
| `claude-sonnet-5` | 0.3529 | 0.5882 | 0.9412 |
| `gpt-5.5` | 0.4118 | 0.5882 | 0.9412 |

| Reference | value |
| --- | ---: |
| `prismweft-runtime` (n=17 subset) | 1.0000 |
