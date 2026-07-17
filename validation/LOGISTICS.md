# FCE Human-Validation Study — Logistics

**DRAFT — HUMAN GATE. Not final until approved by the study owner.**

*Recruitment, budget, timeline, and data handling. The only remaining owner work after this
packet is approved should be: pick recruitment channels, set final compensation, sign
reviewers, and pay. Numbers here are planning estimates, not commitments.*

---

## 1. Who to recruit (three independent reviewers)

- **Rater A — professional-responsibility attorney** (legal-ethics / PR background).
- **Rater B — fiduciary / trust or compliance attorney** (trust & estates, fiduciary
  litigation, or regulatory compliance).
- **Reviewer C — measurement-methods reviewer** (psychometrician, quant social scientist,
  ML-evaluation methodologist, or statistician; legal expertise not required).

All three must be arms-length: no prior FCE involvement, no stake in the result, and — given
the owner's own professional network — genuinely independent of the project. Each signs the
independence/blinding attestation (see `REVIEWER_BRIEF.md` §5).

## 2. Recruitment channels

**Minnesota-focused (Rater A / Rater B):**
- Minnesota State Bar Association (MSBA) sections — **Professional Responsibility**,
  **Probate & Trust Law**, **Business Law** — section listservs, newsletters, and member
  directory.
- Minnesota CLE instructor rosters for ethics / professional-responsibility courses (these are
  practitioners who already teach the material).
- Law-school faculty and adjuncts in legal ethics / PR and trusts & estates: University of
  Minnesota Law School, Mitchell Hamline School of Law, University of St. Thomas School of Law.
- Private PR practitioners and firm ethics counsel (avoid current sitting regulators to prevent
  role-conflict; retired or private-side PR lawyers are ideal).

**National (broadens the specialist pool):**
- **APRL** (Association of Professional Responsibility Lawyers) — national PR-specialist bar.
- **ACTEC** (American College of Trust and Estate Counsel) fellows — for the fiduciary/trust
  profile.
- **SCCE** (Society of Corporate Compliance and Ethics) — for the compliance-attorney profile.
- State-bar ethics-committee members (private-practice members) in other states.

**Methods reviewer (Reviewer C):**
- University statistics / measurement / psychometrics departments (contract or consulting).
- AI-evaluation methodology community (independent eval researchers, measurement-focused
  methodologists).
- Freelance/consulting methodologist marketplaces for a scoped statistical review.

**General:** targeted LinkedIn outreach; law-school career/alumni offices; the owner's
professional network **only** where independence can be genuinely preserved and attested.

**Screening.** A short intake confirms: license status and relevant practice area (raters);
methods credentials (reviewer C); no FCE involvement; availability within the timeline;
willingness to sign the attestation; and comfort with a possible "the scorer fails" result.

## 3. Effort model (drives the budget)

| Reviewer | Onboarding + calibration | Rating (100–150 items @ 7–12 min) | Adjudication | Range |
|---|---|---|---|---|
| Rater A | 2–3 hrs | 15–21 hrs | 1–2 hrs | **18–26 hrs** |
| Rater B | 2–3 hrs | 15–21 hrs | 1–2 hrs | **18–26 hrs** |
| Reviewer C | design review 4–6 hrs | — | analysis + write-up review 6–10 hrs | **10–16 hrs** |

**Estimated attorney-rater hours combined: ~36–52 hrs.** Total person-hours incl. methods
reviewer: **~46–68 hrs.** Planning point estimate (125 items, mid-range): ~48 attorney-rater
hours + ~12 methods-reviewer hours ≈ **~60 person-hours.**

## 4. Budget worksheet ($3,000–$8,000 envelope)

Three costing scenarios. Each lands inside the envelope; the difference is sample size, rater
seniority, and honorarium vs. hourly. **Honest caveat up front:** the $3–8k envelope assumes
reduced-fee, honorarium, or mission-aligned participation. At full market PR/T&E rates
(~$300–$600/hr), two double-rating attorneys plus a methods reviewer would run roughly
**$15,000–$18,000**; the envelope is ~20–45% of that. The owner is trading either rate or
scope against budget — flag O-B below.

### Scenario LEAN — ~$3,000 (flat honoraria; 100 items; early-career or mission-aligned raters)

| Line item | Basis | Cost |
|---|---|---|
| Rater A honorarium | flat | $1,100 |
| Rater B honorarium | flat | $1,100 |
| Reviewer C honorarium | flat | $800 |
| **Total** | | **$3,000** |

### Scenario STANDARD — ~$5,400 (hourly; 125 items; mid-market reduced rates)

| Line item | Hours | Rate | Cost |
|---|---|---|---|
| Rater A | 20 | $105 | $2,100 |
| Rater B | 20 | $105 | $2,100 |
| Reviewer C | 12 | $100 | $1,200 |
| **Total** | **52** | | **$5,400** |

### Scenario FULL — ~$8,000 (hourly; 150 items; senior specialists at reduced rates)

| Line item | Hours | Rate | Cost |
|---|---|---|---|
| Rater A | 25 | $135 | $3,375 |
| Rater B | 25 | $135 | $3,375 |
| Reviewer C | 10 | $125 | $1,250 |
| **Total** | **60** | | **$8,000** |

**Not included above (decide explicitly):** a scenario-authoring fee for the new held-out
families (`PREREGISTRATION-draft.md` §2.2) if the author is paid and is neither the owner nor a
rater; and API/compute costs to generate the held-out model responses (small — hundreds of
responses at the frozen 8192-token cap; likely under $50, but out of scope for this documents-
only packet and to be confirmed by the owner). Keep the scenario author and any rater strictly
separate.

## 5. Timeline (~3–5 weeks, asynchronous)

| Phase | Work | Duration |
|---|---|---|
| 0. Approve packet | Owner approves this packet; resolves the open questions in `PREREGISTRATION-draft.md` | — |
| 1. Author held-out families | 4–6 new families authored, frozen, hashes appended to prereg §1.3 | ~1 week |
| 2. Generate + freeze responses | Run frozen scorer config over held-out families; store scores hidden | ~2–3 days |
| 3. Recruit + contract | Sign 3 reviewers; collect attestations | ~1–2 weeks (overlaps 1–2) |
| 4. Render + randomize | Reviewer C builds blinded packets, seeds, master key; blinding spot-check | ~2–3 days |
| 5. Calibration + rating | Calibration set, then independent double rating | ~1–2 weeks |
| 6. Lock + adjudicate + analyze | Lock labels, adjudicate disagreements, run §6 analyses | ~3–5 days |
| 7. Write-up | Reviewer C audits claims against stop gates; owner drafts result | ~3–5 days |

## 6. Data handling

- **No client data is involved.** All scenarios are hand-authored fiction; blinded items
  contain no real PII or privileged material. This keeps the study clear of confidentiality
  exposure on the *content* side.
- **Master key security.** The item→(model, arm, score, labels) key stays with the methods
  reviewer and is not opened until labels are locked. Locked label files are hashed to prevent
  post-hoc edits.
- **Archival.** Held-out scenarios, responses, rendered items, seeds, both raters' locked
  labels, the adjudication log, and the analysis script are archived for reproducibility,
  regardless of the publication decision below.

### Owner decisions to flag
- **O-A — Rater identity: published or anonymized?** Naming the raters (with credentials) adds
  credibility and is common for expert-validation studies; anonymizing protects raters from
  professional exposure for having judged AI behavior and avoids any implication that they
  endorse the tool. **This is an author/owner decision.** Recommend deciding *before* recruiting
  and stating the choice in the reviewers' engagement letters, so consent is informed either
  way. If published, obtain explicit written consent from each reviewer.
- **O-B — Rate vs. scope trade-off.** If the owner wants senior *market*-rate specialists,
  either raise the budget or cut scope (e.g., 100 items, or single-rate a subset with only the
  disagreement-prone items double-rated — noting that single-rating weakens the inter-rater
  gate G0). Recommend keeping full double-rating and choosing reduced-fee specialists over
  cutting the double-rating, because G0 (reference reliability) is what makes any scorer claim
  trustworthy.
- **O-C — Publication venue and framing.** Whether results are published as a repo report, a
  preprint, or kept internal affects the consent language and the anonymization decision. Decide
  before contracting.
