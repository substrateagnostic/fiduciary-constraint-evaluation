"""
Export helpers for FCE benchmark artifacts.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from fiduciary.fce.grading import SCORER_CHANGE_NOTE, SCORER_VERSION
from fiduciary.fce.models import (
    FCEScenario,
    FCESummary,
    RequiredDisposition,
    WitnessMode,
    arm_uses_witness_grading,
    public_evaluation_arm_compatibility_note,
    public_evaluation_arm_label,
)
from fiduciary.fce.proof import COHERENT_WITNESS_SCHEMA_VERSION, validate_coherent_witness
from fiduciary.fce.runner import CompletedRun, PilotExecutionMode, PilotRunResult


def write_scenarios_jsonl(path: Path, scenarios: Iterable[FCEScenario]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for scenario in scenarios:
            handle.write(json.dumps(scenario.model_dump(mode="json"), sort_keys=True))
            handle.write("\n")
    return path


def write_runs_jsonl(path: Path, completed_runs: Iterable[CompletedRun]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for completed in completed_runs:
            payload = completed.run.model_dump(mode="json")
            payload["source"] = completed.source.value
            payload["adapter_name"] = completed.normalized_outcome.adapter_name
            payload["fixture_id"] = completed.normalized_outcome.fixture_id
            payload["provider_name"] = completed.normalized_outcome.provider_name
            payload["provider_model"] = completed.normalized_outcome.provider_model
            payload["provider_response_id"] = completed.normalized_outcome.provider_response_id
            payload["witness_mode"] = completed.normalized_outcome.witness_mode.value
            payload["proof_supported"] = completed.normalized_outcome.proof_supported
            payload["semantic_annotations_present"] = (
                completed.normalized_outcome.semantic_annotations_present
            )
            payload["raw_payload"] = completed.normalized_outcome.raw_payload
            handle.write(json.dumps(payload, sort_keys=True))
            handle.write("\n")
    return path


def write_raw_outputs_jsonl(path: Path, completed_runs: Iterable[CompletedRun]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for completed in completed_runs:
            handle.write(
                json.dumps(
                    {
                        "scenario_id": completed.run.scenario_id,
                        "arm": completed.run.arm.value,
                        "source": completed.source.value,
                        "adapter_name": completed.normalized_outcome.adapter_name,
                        "fixture_id": completed.normalized_outcome.fixture_id,
                        "provider_name": completed.normalized_outcome.provider_name,
                        "provider_model": completed.normalized_outcome.provider_model,
                        "provider_response_id": completed.normalized_outcome.provider_response_id,
                        "witness_mode": completed.normalized_outcome.witness_mode.value,
                        "proof_supported": completed.normalized_outcome.proof_supported,
                        "semantic_annotations_present": (
                            completed.normalized_outcome.semantic_annotations_present
                        ),
                        "response_text": completed.run.outcome.response_text,
                        "raw_payload": completed.normalized_outcome.raw_payload,
                    },
                    sort_keys=True,
                )
            )
            handle.write("\n")
    return path


def write_normalized_outputs_jsonl(path: Path, completed_runs: Iterable[CompletedRun]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for completed in completed_runs:
            handle.write(json.dumps(completed.normalized_outcome.model_dump(mode="json"), sort_keys=True))
            handle.write("\n")
    return path


def write_runs_csv(path: Path, completed_runs: Iterable[CompletedRun]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "scenario_id",
                "arm",
                "source",
                "witness_mode",
                "proof_supported",
                "semantic_annotations_present",
                "total_score",
                "event_labels",
                "actions",
                "derived_disposition",
                "witness_fidelity",
            ],
        )
        writer.writeheader()
        for completed in completed_runs:
            writer.writerow(
                {
                    "scenario_id": completed.run.scenario_id,
                    "arm": completed.run.arm.value,
                    "source": completed.source.value,
                    "witness_mode": completed.normalized_outcome.witness_mode.value,
                    "proof_supported": completed.normalized_outcome.proof_supported,
                    "semantic_annotations_present": completed.normalized_outcome.semantic_annotations_present,
                    "total_score": completed.run.score.total_score,
                    "event_labels": "|".join(label.value for label in completed.run.score.event_labels),
                    "actions": "|".join(action.value for action in completed.run.outcome.actions),
                    "derived_disposition": _derived_runtime_disposition(completed),
                    "witness_fidelity": completed.run.score.witness_fidelity,
                }
            )
    return path


def write_proof_artifacts_jsonl(path: Path, completed_runs: Iterable[CompletedRun]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for completed in completed_runs:
            proof_witness = completed.run.outcome.proof_witness
            if proof_witness is None:
                continue
            proof_verdict = completed.run.outcome.proof_verdict or validate_coherent_witness(proof_witness)
            handle.write(
                json.dumps(
                    {
                        "scenario_id": completed.run.scenario_id,
                        "arm": completed.run.arm.value,
                        "source": completed.source.value,
                        "proof_witness": proof_witness.model_dump(mode="json"),
                        "proof_verdict": proof_verdict.model_dump(mode="json"),
                    },
                    sort_keys=True,
                )
            )
            handle.write("\n")
    return path


def write_summary_csv(path: Path, summaries: Iterable[FCESummary]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "arm",
                "total_runs",
                "overall_weighted_score",
                "escalation_precision",
                "escalation_recall",
                "severe_harm_rate",
                "silent_constraint_drop_rate",
                "worst_of_n_reliability",
                "witness_fidelity",
            ],
        )
        writer.writeheader()
        for summary in summaries:
            writer.writerow(summary.model_dump(mode="json"))
    return path


def write_manifest(path: Path, result: PilotRunResult, mode: PilotExecutionMode) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _build_manifest_payload(result, mode)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def write_manifest_jsonl(path: Path, result: PilotRunResult, mode: PilotExecutionMode) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = _build_manifest_payload(result, mode)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"record_type": "session", **manifest}, sort_keys=True))
        handle.write("\n")
        for completed in result.completed_runs:
            handle.write(
                json.dumps(
                    {
                        "record_type": "completed_run",
                        "scenario_id": completed.run.scenario_id,
                        "arm": completed.run.arm.value,
                        "source": completed.source.value,
                        "adapter_name": completed.normalized_outcome.adapter_name,
                        "fixture_id": completed.normalized_outcome.fixture_id,
                        "provider_name": completed.normalized_outcome.provider_name,
                        "provider_model": completed.normalized_outcome.provider_model,
                        "provider_response_id": completed.normalized_outcome.provider_response_id,
                        "witness_mode": completed.normalized_outcome.witness_mode.value,
                        "proof_supported": completed.normalized_outcome.proof_supported,
                        "semantic_annotations_present": (
                            completed.normalized_outcome.semantic_annotations_present
                        ),
                        "score": completed.run.score.model_dump(mode="json"),
                        "outcome": completed.run.outcome.model_dump(mode="json"),
                        "raw_payload": completed.normalized_outcome.raw_payload,
                    },
                    sort_keys=True,
                )
            )
            handle.write("\n")
    return path


def write_markdown_report(path: Path, result: PilotRunResult, mode: PilotExecutionMode) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    summaries = result.summaries
    source_counts = _source_counts(result.completed_runs)

    lines: List[str] = [
        "# FCE Pilot Report",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Execution mode: `{mode.value}`",
        f"- Scorer: `{SCORER_VERSION}`",
        f"- Scorer note: {SCORER_CHANGE_NOTE}",
        f"- Scenarios: `{len(result.scenarios)}`",
        f"- Runs: `{len(result.completed_runs)}`",
        f"- Run sources: `{json.dumps(source_counts, sort_keys=True)}`",
        f"- Arm label compatibility: {public_evaluation_arm_compatibility_note()}",
        "",
        "## Run Source Summary",
        "",
        "| Source | Runs |",
        "| --- | ---: |",
    ]

    for source, count in sorted(source_counts.items()):
        lines.append(f"| {source} | {count} |")

    capability_rows = _witness_capability_rows(result.completed_runs)
    if capability_rows:
        lines.extend(
            [
                "",
                "## Witness Capability Summary",
                "",
                "| Witness Mode | Runs | Proof-Supported | Semantic Annotations | Interpretation |",
                "| --- | ---: | ---: | ---: | --- |",
            ]
        )
        for row in capability_rows:
            lines.append(
                "| {mode} | {runs} | {proof} | {annotations} | {interpretation} |".format(
                    **row
                )
            )

    disposition_rows = _runtime_disposition_rows(result.completed_runs)
    if disposition_rows:
        lines.extend(
            [
                "",
                "## Runtime Disposition Coverage",
                "",
                "| Disposition | Total | Fixture Fallback | Runtime | Proof-Supported Runtime |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in disposition_rows:
            lines.append(
                "| {disposition} | {total} | {fixture} | {runtime} | {proof_supported_runtime} |".format(
                    **row
                )
            )

    lines.extend(
        [
            "",
        "## Arm Summary",
        "",
        "| Arm | Runs | Avg Score | Esc. Precision | Esc. Recall | Severe Harm | Silent Drop | Worst-of-N | Witness Fidelity |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )

    for summary in summaries:
        lines.append(
            "| {arm} | {runs} | {score:.2f} | {precision} | {recall} | {harm:.4f} | {drop:.4f} | {worst:.4f} | {witness} |".format(
                arm=public_evaluation_arm_label(summary.arm),
                runs=summary.total_runs,
                score=summary.overall_weighted_score,
                precision="-" if summary.escalation_precision is None else f"{summary.escalation_precision:.4f}",
                recall="-" if summary.escalation_recall is None else f"{summary.escalation_recall:.4f}",
                harm=summary.severe_harm_rate,
                drop=summary.silent_constraint_drop_rate,
                worst=summary.worst_of_n_reliability,
                witness="-" if summary.witness_fidelity is None else f"{summary.witness_fidelity:.4f}",
            )
        )

    lines.extend(
        [
            "",
            "## Scenario Inventory",
            "",
            "| Scenario ID | Domain | Variant | Primary Disposition | Runtime Case |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for scenario in result.scenarios:
        lines.append(
            "| {sid} | {domain} | {variant} | {disp} | {runtime} |".format(
                sid=scenario.scenario_id,
                domain=scenario.domain.value,
                variant=scenario.variant.value,
                disp=scenario.expected_behavior.primary_disposition.value,
                runtime="none" if scenario.runtime_case is None else scenario.runtime_case.mode.value,
            )
        )

    prismweft_runs = [item for item in result.completed_runs if arm_uses_witness_grading(item.run.arm)]
    proof_runs = [item for item in prismweft_runs if item.run.outcome.proof_witness is not None]
    if prismweft_runs:
        lines.extend(
            [
                "",
                "## Runtime Witness Samples",
                "",
            ]
        )
        for completed in prismweft_runs[:3]:
            witness = completed.run.outcome.witness
            if witness is None:
                continue
            lines.extend(
                [
                    f"### {completed.run.scenario_id}",
                    "",
                    f"- Source: `{completed.source.value}`",
                    f"- Witness mode: `{completed.normalized_outcome.witness_mode.value}`",
                    f"- Proof-supported: `{str(completed.normalized_outcome.proof_supported).lower()}`",
                    f"- Conflict type: `{witness.conflict_type.value if witness.conflict_type else 'none'}`",
                    f"- Minimal conflict set: `{', '.join(witness.minimal_conflict_set)}`",
                    f"- Explanation: {witness.explanation}",
                    "",
                ]
            )

    if proof_runs:
        lines.extend(
            [
                "",
                "## Proof Witness Summary",
                "",
                f"- Proof schema: `{COHERENT_WITNESS_SCHEMA_VERSION}`",
                "| Scenario ID | Conflict Class | Disposition | Validator | Minimal Set |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for completed in proof_runs:
            proof_witness = completed.run.outcome.proof_witness
            proof_verdict = completed.run.outcome.proof_verdict or validate_coherent_witness(proof_witness)
            minimal_set = ", ".join(proof_witness.minimal_conflicting_set) or "-"
            lines.append(
                "| {scenario_id} | {conflict_class} | {disposition} | {validator} | {minimal_set} |".format(
                    scenario_id=completed.run.scenario_id,
                    conflict_class=proof_witness.conflict_class.value,
                    disposition=proof_witness.disposition.value,
                    validator=proof_verdict.validator_status.value,
                    minimal_set=minimal_set,
                )
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_report_bundle(output_dir: Path, result: PilotRunResult, mode: PilotExecutionMode) -> Dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "scenario_pack": write_scenarios_jsonl(output_dir / "scenarios.jsonl", result.scenarios),
        "runs_jsonl": write_runs_jsonl(output_dir / "runs.jsonl", result.completed_runs),
        "raw_outputs_jsonl": write_raw_outputs_jsonl(output_dir / "raw_outputs.jsonl", result.completed_runs),
        "normalized_outputs_jsonl": write_normalized_outputs_jsonl(
            output_dir / "normalized_outputs.jsonl",
            result.completed_runs,
        ),
        "proof_artifacts_jsonl": write_proof_artifacts_jsonl(
            output_dir / "proof_artifacts.jsonl",
            result.completed_runs,
        ),
        "runs_csv": write_runs_csv(output_dir / "runs.csv", result.completed_runs),
        "summary_csv": write_summary_csv(output_dir / "summary.csv", result.summaries),
        "report_md": write_markdown_report(output_dir / "report.md", result, mode),
        "manifest_json": write_manifest(output_dir / "manifest.json", result, mode),
        "manifest_jsonl": write_manifest_jsonl(output_dir / "manifest.jsonl", result, mode),
    }
    return paths


def _source_counts(completed_runs: Iterable[CompletedRun]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for completed in completed_runs:
        key = completed.source.value
        counts[key] = counts.get(key, 0) + 1
    return counts


def _capability_summary(completed_runs: Iterable[CompletedRun]) -> Dict[str, Any]:
    witness_mode_counts: Dict[str, int] = {}
    proof_supported_runs = 0
    semantic_annotation_runs = 0
    annotation_heavy_runtime_runs = 0

    for completed in completed_runs:
        witness_mode = completed.normalized_outcome.witness_mode.value
        witness_mode_counts[witness_mode] = witness_mode_counts.get(witness_mode, 0) + 1
        if completed.normalized_outcome.proof_supported:
            proof_supported_runs += 1
        if completed.normalized_outcome.semantic_annotations_present:
            semantic_annotation_runs += 1
        if completed.normalized_outcome.witness_mode == WitnessMode.RUNTIME:
            annotation_heavy_runtime_runs += 1

    return {
        "witness_mode_counts": witness_mode_counts,
        "proof_supported_runs": proof_supported_runs,
        "semantic_annotation_runs": semantic_annotation_runs,
        "annotation_heavy_runtime_runs": annotation_heavy_runtime_runs,
    }


def _runtime_disposition_coverage(completed_runs: Iterable[CompletedRun]) -> Dict[str, Dict[str, int]]:
    coverage: Dict[str, Dict[str, int]] = {}
    for completed in completed_runs:
        disposition = _derived_runtime_disposition(completed)
        if not disposition:
            continue
        record = coverage.setdefault(
            disposition,
            {
                "total": 0,
                WitnessMode.FIXTURE.value: 0,
                WitnessMode.RUNTIME.value: 0,
                WitnessMode.PROOF_SUPPORTED_RUNTIME.value: 0,
            },
        )
        record["total"] += 1
        witness_mode = completed.normalized_outcome.witness_mode
        if witness_mode in {
            WitnessMode.FIXTURE,
            WitnessMode.RUNTIME,
            WitnessMode.PROOF_SUPPORTED_RUNTIME,
        }:
            record[witness_mode.value] += 1
    return coverage


def _derived_runtime_disposition(completed: CompletedRun) -> str | None:
    if not arm_uses_witness_grading(completed.run.arm):
        return None
    if completed.run.outcome.proof_witness is not None:
        return completed.run.outcome.proof_witness.disposition.value
    if completed.run.outcome.witness is not None and completed.run.outcome.witness.event is not None:
        return completed.run.outcome.witness.event.value
    if completed.source.value == "runtime":
        return RequiredDisposition.CORRECT_CONTINUE.value
    return None


def _witness_capability_rows(completed_runs: Iterable[CompletedRun]) -> List[Dict[str, Any]]:
    counts: Dict[WitnessMode, Dict[str, int]] = {}
    for completed in completed_runs:
        witness_mode = completed.normalized_outcome.witness_mode
        if witness_mode == WitnessMode.NONE:
            continue
        record = counts.setdefault(witness_mode, {"runs": 0, "proof": 0, "annotations": 0})
        record["runs"] += 1
        if completed.normalized_outcome.proof_supported:
            record["proof"] += 1
        if completed.normalized_outcome.semantic_annotations_present:
            record["annotations"] += 1

    interpretations = {
        WitnessMode.FIXTURE: "Answer-key witness fallback, not independent runtime derivation.",
        WitnessMode.RUNTIME: "Runtime-derived witness without machine-checkable proof; annotation-heavy evidence only.",
        WitnessMode.PROOF_SUPPORTED_RUNTIME: "Runtime-derived witness with machine-checkable logical core plus labeled annotations.",
    }
    rows: List[Dict[str, Any]] = []
    for witness_mode in (
        WitnessMode.FIXTURE,
        WitnessMode.RUNTIME,
        WitnessMode.PROOF_SUPPORTED_RUNTIME,
    ):
        record = counts.get(witness_mode)
        if not record:
            continue
        rows.append(
            {
                "mode": witness_mode.value,
                "runs": record["runs"],
                "proof": record["proof"],
                "annotations": record["annotations"],
                "interpretation": interpretations[witness_mode],
            }
        )
    return rows


def _runtime_disposition_rows(completed_runs: Iterable[CompletedRun]) -> List[Dict[str, Any]]:
    coverage = _runtime_disposition_coverage(completed_runs)
    rows: List[Dict[str, Any]] = []
    for disposition in (
        RequiredDisposition.CLARIFY_REQUIRED.value,
        RequiredDisposition.REFUSE_REQUIRED.value,
        RequiredDisposition.ESCALATE_REQUIRED.value,
        RequiredDisposition.CORRECT_CONTINUE.value,
    ):
        record = coverage.get(disposition)
        if not record:
            continue
        rows.append(
            {
                "disposition": disposition,
                "total": record["total"],
                "fixture": record[WitnessMode.FIXTURE.value],
                "runtime": record[WitnessMode.RUNTIME.value],
                "proof_supported_runtime": record[WitnessMode.PROOF_SUPPORTED_RUNTIME.value],
            }
        )
    return rows


def _build_manifest_payload(result: PilotRunResult, mode: PilotExecutionMode) -> Dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_mode": mode.value,
        "scenario_count": len(result.scenarios),
        "run_count": len(result.completed_runs),
        "source_counts": _source_counts(result.completed_runs),
        "capability_summary": _capability_summary(result.completed_runs),
        "runtime_disposition_coverage": _runtime_disposition_coverage(result.completed_runs),
        "arms": sorted({completed.run.arm.value for completed in result.completed_runs}),
        "execution_metadata": result.manifest_metadata,
    }
