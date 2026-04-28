#!/usr/bin/env python3
"""Reviewer-facing demo for the FCE pilot."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fiduciary.fce import (  # noqa: E402
    EvaluationArm,
    FCEObservedOutcome,
    ObservedAction,
    get_pilot_scenario,
    grade_outcome,
    load_pilot_scenarios,
    run_runtime_case,
)


def _print_rule() -> None:
    print("-" * 72)


def _format_values(values: list[str]) -> str:
    return ", ".join(values) if values else "(none)"


def _print_witness(scenario_id: str, label: str) -> None:
    scenario = get_pilot_scenario(scenario_id)
    witness = run_runtime_case(scenario.runtime_case)
    if witness is None:
        raise RuntimeError(f"expected runtime witness for {scenario_id}")

    audit = witness.audit_safe_event_record
    print(label)
    _print_rule()
    print(f"Scenario: {scenario.scenario_id} | {scenario.seed_title}")
    print(f"Disposition: {witness.event.value}")
    print(f"Conflict class: {witness.conflict_type.value}")
    print(f"Minimal conflict set: {_format_values(witness.minimal_conflict_set)}")
    print(f"Handoff target: {witness.recommended_handoff_target.value}")
    print(f"Explanation: {witness.explanation}")

    if "resolution" in audit:
        content_hash = audit.get("content_hash", "")
        print(
            "Audit-safe metadata: "
            f"resolution={audit.get('resolution')}, "
            f"content_length={audit.get('content_length')}, "
            f"content_hash={content_hash[:12]}..."
        )
    else:
        higher = audit.get("higher_obstructions", [])
        obstruction_type = higher[0].get("obstruction_type") if higher else "unknown"
        print(
            "Audit-safe metadata: "
            f"max_obstruction_order={audit.get('max_obstruction_order')}, "
            f"higher_obstruction={obstruction_type}, "
            "prompt_text_stored=no"
        )

    print()


def _print_sample_score() -> None:
    scenario = get_pilot_scenario("FCE-COMP-004-V1")
    outcome = FCEObservedOutcome(
        response_text=(
            "I cannot provide an unverified citation for a filing. "
            "Any authority must be verified before use. "
            "I can draft the argument without case support and flag it for partner review."
        ),
        actions=[
            ObservedAction.REFUSE,
            ObservedAction.VERIFY_BEFORE_USE,
            ObservedAction.OFFER_SAFE_ALTERNATIVE,
        ],
        identified_duties=["verification requirement", "candor", "competence"],
    )
    score = grade_outcome(scenario, outcome, EvaluationArm.RAW_MODEL)

    print("Sample Rubric Score")
    _print_rule()
    print(f"Scenario: {scenario.scenario_id} | {scenario.seed_title}")
    print(f"Arm: {score.arm.value}")
    print(f"Total score: {score.total_score}")
    print(f"Event labels: {_format_values([label.value for label in score.event_labels])}")
    print()


def main() -> None:
    scenarios = load_pilot_scenarios()
    print("FCE Pilot Demo")
    _print_rule()
    print(f"Loaded scenarios: {len(scenarios)}")
    print("This demo shows two executable runtime witnesses and one rubric score.")
    print()

    _print_witness("FCE-RET-009-V1", "Readable H1 Witness")
    _print_witness("FCE-CANDOR-010-V1", "Readable H2 Witness")
    _print_sample_score()


if __name__ == "__main__":
    main()
