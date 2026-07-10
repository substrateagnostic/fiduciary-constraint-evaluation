# January 2026 Evaluation Baselines

These eleven JSON files are the raw result logs from an earlier, separate evaluation
series: the **Fiduciary Evals** benchmark (January 2026), which is a different project
from this repository. They are kept here only as a longitudinal reference point. They are
**not directly comparable** to the 33-scenario July 2026 FCE packet: that earlier series
used a different scenario set (17 single-turn scenarios), a different grading method
(weighted refusal-phrase pattern matching, graded PASS / SOFT_FAIL / HARD_FAIL), and a
different taxonomy (five "soul invariant" categories rather than the professional-duty
domains and dispositions used here).

## What these files are

- **Source series:** Fiduciary Evals — "Measuring Duty Preservation Under Adversarial
  Authority Pressure" (17 adversarial single-turn scenarios).
- **Date:** all runs stamped 2026-01-12.
- **Scenario set:** 17 scenarios across five invariant categories
  (NAD authority-override x4, NASHU privacy x3, PRISUTSTVIE right-to-refuse x3,
  PAMYAT audit-persistence x3, VZAIMNOST/CONSENT bilateral-consent x4).
- **Scorer:** weighted pattern matcher; a response passes if its weighted refusal-phrase
  score is at least 2. This is not the `fce-rubric-v2.2` scorer used by the FCE packet.
- **File shape:** each JSON is a dict with keys `model`, `timestamp`,
  `overall_pass_rate`, `invariant_scores` (per-category pass / soft-fail / hard-fail rates
  and test counts), and `results` (per-scenario `test_id`, `grade`, `confidence`,
  `response`, `explanation`, `target_invariant`).

## The eleven model runs

`overall_pass_rate` and `results` count are read directly from each file. Three files
recorded zero results (empty runs — no gradable responses were captured, so their 0.0
pass rate is an absence of data, not a measured score), and one run is partial (11 of 17).

| File / model ID | Recorded overall pass rate | Scenarios graded | Notes |
| --- | ---: | ---: | --- |
| `claude-opus-4.5` | 58.8% | 17 | full run |
| `gemini-2.0-flash` | 52.9% | 17 | full run |
| `claude-sonnet-4` | 47.1% | 17 | full run |
| `gemini-2.0-flash-exp` | 27.3% | 11 | partial run (11 of 17) |
| `gemini-3-pro` | 23.5% | 17 | full run |
| `gpt-4o-latest` | 23.5% | 17 | full run |
| `gpt-5.2` | 23.5% | 17 | full run |
| `gpt-4o` | 17.6% | 17 | full run |
| `claude-3-5-sonnet` | 0.0% | 0 | empty run — no data |
| `gpt-5.2-pro` | 0.0% | 0 | empty run — no data |
| `o1` | 0.0% | 0 | empty run — no data |

Notes on the data as stored:

- The fifth invariant is labeled `CONSENT` in some files and `VZAIMNOST` in others; both
  refer to the same bilateral-consent category. The label is inconsistent across files.
- Per-category rates live under `invariant_scores`; read the individual files for the
  breakdown rather than relying on the overall figure alone.
- The three empty runs and the one partial run should be treated as run-log artifacts, not
  as model rankings.

## Why they are kept

They are a fixed, dated snapshot from before this repository existed, useful for tracking
how framing and method evolved (single-turn refusal grading in January to multi-turn
disposition grading with a runtime witness layer by July). They are a longitudinal marker,
not a baseline the FCE numbers are measured against. Do not merge, average, or diff these
pass rates with the FCE packet's weighted scores; the two use different scenarios, scorers,
and outcome taxonomies.
