"""
CLI for the FCE pilot benchmark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from pathlib import Path
from typing import Sequence

from fiduciary.fce.adapters import (
    AnthropicBaselineAdapter,
    OpenAIBaselineAdapter,
    ReplayBaselineAdapter,
    supported_runner_arm_values,
)
from fiduciary.fce.baseline import FixtureBackedBaselineAdapter
from fiduciary.fce.evaluator_v3 import (
    SemanticJudgeConfig,
    SemanticJudgeMode,
    validate_evaluator_v3_on_audit_sample,
    write_human_evaluator_comparison_packet,
    write_human_adjudication_packet,
)
from fiduciary.fce.export import write_report_bundle, write_scenarios_jsonl
from fiduciary.fce.grading import SCORER_CHANGE_NOTE, SCORER_VERSION
from fiduciary.fce.models import EvaluationArm, FCEScenario
from fiduciary.fce.proof import COHERENT_WITNESS_SCHEMA_VERSION, PROOF_CHANGE_NOTE, supported_proof_scenario_ids
from fiduciary.fce.runner import PilotExecutionMode, parse_arms, run_pilot
from fiduciary.fce.scenarios import get_pilot_scenario, load_pilot_scenarios


REPO_ROOT = Path(__file__).resolve().parents[3]
FREEZE_FILE_PATHS: tuple[Path, ...] = (
    REPO_ROOT / "src/fiduciary/fce/models.py",
    REPO_ROOT / "src/fiduciary/fce/grading.py",
    REPO_ROOT / "src/fiduciary/fce/scenarios.py",
    REPO_ROOT / "src/fiduciary/fce/runtime.py",
    REPO_ROOT / "src/fiduciary/fce/proof.py",
    REPO_ROOT / "src/fiduciary/fce/baseline.py",
    REPO_ROOT / "src/fiduciary/fce/runner.py",
    REPO_ROOT / "src/fiduciary/fce/export.py",
    REPO_ROOT / "src/fiduciary/fce/cli.py",
    REPO_ROOT / "src/fiduciary/fce/adapters/base.py",
    REPO_ROOT / "src/fiduciary/fce/adapters/openai.py",
    REPO_ROOT / "src/fiduciary/fce/adapters/anthropic.py",
    REPO_ROOT / "src/fiduciary/fce/adapters/replay.py",
)


def _build_parser() -> argparse.ArgumentParser:
    supported_arms = ", ".join(supported_runner_arm_values())
    parser = argparse.ArgumentParser(prog="fiduciary-fce", description="Run the FCE pilot benchmark.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export-scenarios", help="Write the pilot scenario pack as JSONL.")
    export_parser.add_argument("--output", required=True, help="Path to the JSONL output file.")

    v3_parser = subparsers.add_parser(
        "evaluate-v3",
        help="Run the calibration-ready layered evaluator over an existing audit sample.",
    )
    v3_parser.add_argument(
        "--audit-sample",
        required=True,
        help="JSONL audit sample or inspection sample to evaluate.",
    )
    v3_parser.add_argument(
        "--manual-audit",
        help=(
            "Optional markdown inspection table containing provisional labels. "
            "These labels are regression/inspection artifacts, not ground truth."
        ),
    )
    v3_parser.add_argument("--output-dir", required=True, help="Directory for evaluator v3 artifacts.")
    v3_parser.add_argument(
        "--semantic-judge",
        choices=[mode.value for mode in SemanticJudgeMode],
        default=SemanticJudgeMode.OFFLINE.value,
        help="offline = built-in structured surrogate; replay = read structured judge JSONL.",
    )
    v3_parser.add_argument(
        "--semantic-judge-replay",
        help="JSONL file of structured semantic judge outputs when --semantic-judge=replay.",
    )
    v3_parser.add_argument(
        "--judge-model",
        default="offline-semantic-surrogate-v0",
        help="Judge model name recorded in semantic judge results.",
    )

    adjudication_parser = subparsers.add_parser(
        "build-adjudication-packet",
        help="Build a human-readable adjudication packet from evaluator v3 records.",
    )
    adjudication_parser.add_argument(
        "--evaluator-results",
        required=True,
        help="Path to evaluator_v3_records.jsonl.",
    )
    adjudication_parser.add_argument(
        "--raw-outputs",
        action="append",
        required=True,
        help=(
            "Raw-output JSONL path. Accepts repeated values or comma-separated paths. "
            "Audit samples and standard raw_outputs.jsonl files are both supported."
        ),
    )
    adjudication_parser.add_argument(
        "--scenario-pack",
        help="Optional scenarios.jsonl. Defaults to the built-in pilot scenario pack.",
    )
    adjudication_parser.add_argument("--output-dir", required=True, help="Directory for packet artifacts.")
    adjudication_parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include every evaluator v3 record, not just review/disagreement cases.",
    )
    adjudication_parser.add_argument(
        "--max-items",
        type=int,
        help="Optional cap on packet items for small review batches.",
    )
    adjudication_parser.add_argument(
        "--output-char-limit",
        type=int,
        default=2200,
        help="Maximum characters of model output included per item.",
    )
    adjudication_parser.add_argument(
        "--blind",
        action="store_true",
        help="Hide evaluator signals so labels can be collected before reveal/comparison.",
    )

    reveal_parser = subparsers.add_parser(
        "reveal-adjudication-comparison",
        help="Join completed human adjudication labels to evaluator v3 outputs after review.",
    )
    reveal_parser.add_argument(
        "--evaluator-results",
        required=True,
        help="Path to evaluator_v3_records.jsonl.",
    )
    reveal_parser.add_argument(
        "--human-labels",
        required=True,
        help="Completed human adjudication CSV or JSONL. Blank human_label rows are ignored.",
    )
    reveal_parser.add_argument("--output-dir", required=True, help="Directory for comparison artifacts.")

    run_parser = subparsers.add_parser("run-pilot", help="Run the pilot benchmark and emit a report directory.")
    run_parser.add_argument("--output-dir", required=True, help="Directory to populate with benchmark artifacts.")
    run_parser.add_argument(
        "--execution",
        choices=[mode.value for mode in PilotExecutionMode],
        default=PilotExecutionMode.HYBRID.value,
        help="fixtures = deterministic fixtures only; runtime = runtime-backed PrismWeft cases only; hybrid = fixtures plus runtime where available.",
    )
    run_parser.add_argument(
        "--arms",
        nargs="*",
        help=(
            "Optional runner arm list. Accepts repeated values or one comma-separated string. "
            f"Supported runner arms: {supported_arms}. "
            "Also accepts `prismweft` as shorthand for `prismweft_runtime`."
        ),
    )
    run_parser.add_argument(
        "--scenario-id",
        action="append",
        help=(
            "Optional scenario selector. Accepts repeated values or one comma-separated string. "
            "If omitted, the full pilot pack is used."
        ),
    )
    run_parser.add_argument(
        "--baseline-adapter",
        choices=["fixture", "replay", "live"],
        default="fixture",
        help="Baseline arm source: built-in fixtures, imported replay data, or live provider calls.",
    )
    run_parser.add_argument(
        "--replay-input",
        help="JSONL or CSV file containing externally captured baseline outputs.",
    )
    run_parser.add_argument(
        "--provider",
        choices=["openai", "anthropic"],
        help="Live provider to use when --baseline-adapter=live.",
    )
    run_parser.add_argument(
        "--model",
        help="Provider model name to use when --baseline-adapter=live.",
    )
    run_parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help=(
            "Provider sampling temperature for live baseline calls. "
            "Omitted from the request when unset (current frontier models reject it)."
        ),
    )
    run_parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=512,
        help="Provider output token cap for live baseline calls.",
    )
    run_parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=60.0,
        help="HTTP timeout for live provider calls.",
    )

    return parser


def _cmd_export_scenarios(output: str) -> int:
    path = write_scenarios_jsonl(Path(output), load_pilot_scenarios())
    print(f"wrote scenario pack: {path}")
    return 0


def _cmd_run_pilot(
    output_dir: str,
    execution: str,
    arms: Sequence[str] | None,
    scenario_ids: Sequence[str] | None,
    baseline_adapter: str,
    replay_input: str | None,
    provider: str | None,
    model: str | None,
    temperature: float | None,
    max_output_tokens: int,
    timeout_seconds: float,
) -> int:
    mode = PilotExecutionMode(execution)
    selected_arms = parse_arms(arms)
    selected_scenarios = _select_scenarios(scenario_ids)
    adapter = None
    if mode != PilotExecutionMode.RUNTIME:
        adapter = _build_baseline_adapter(
            baseline_adapter=baseline_adapter,
            replay_input=replay_input,
            provider=provider,
            model=model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
    manifest_metadata = _build_manifest_metadata(
        output_dir=output_dir,
        execution=mode,
        baseline_adapter=baseline_adapter,
        replay_input=replay_input,
        provider=provider,
        model=model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        selected_arms=selected_arms,
        selected_scenarios=selected_scenarios,
        adapter=adapter,
    )
    result = run_pilot(
        arms=selected_arms,
        mode=mode,
        scenarios=selected_scenarios,
        baseline_adapter=adapter,
        manifest_metadata=manifest_metadata,
    )
    paths = write_report_bundle(Path(output_dir), result, mode)

    print(f"wrote report bundle: {output_dir}")
    print(f"scenarios: {len(result.scenarios)}")
    print(f"runs: {len(result.completed_runs)}")
    print("artifacts:")
    for key, path in paths.items():
        print(f"  {key}: {path}")

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "export-scenarios":
        return _cmd_export_scenarios(args.output)

    if args.command == "evaluate-v3":
        _validate_evaluate_v3_args(parser, args)
        return _cmd_evaluate_v3(
            audit_sample=args.audit_sample,
            manual_audit=args.manual_audit,
            output_dir=args.output_dir,
            semantic_judge=args.semantic_judge,
            semantic_judge_replay=args.semantic_judge_replay,
            judge_model=args.judge_model,
        )

    if args.command == "build-adjudication-packet":
        return _cmd_build_adjudication_packet(
            evaluator_results=args.evaluator_results,
            raw_outputs=args.raw_outputs,
            scenario_pack=args.scenario_pack,
            output_dir=args.output_dir,
            include_all=args.include_all,
            max_items=args.max_items,
            output_char_limit=args.output_char_limit,
            blind=args.blind,
        )

    if args.command == "reveal-adjudication-comparison":
        return _cmd_reveal_adjudication_comparison(
            evaluator_results=args.evaluator_results,
            human_labels=args.human_labels,
            output_dir=args.output_dir,
        )

    if args.command == "run-pilot":
        _validate_run_pilot_args(parser, args)
        return _cmd_run_pilot(
            args.output_dir,
            args.execution,
            args.arms,
            args.scenario_id,
            args.baseline_adapter,
            args.replay_input,
            args.provider,
            args.model,
            args.temperature,
            args.max_output_tokens,
            args.timeout_seconds,
        )

    parser.error(f"unknown command: {args.command}")
    return 2


def _cmd_evaluate_v3(
    *,
    audit_sample: str,
    manual_audit: str | None,
    output_dir: str,
    semantic_judge: str,
    semantic_judge_replay: str | None,
    judge_model: str,
) -> int:
    config = SemanticJudgeConfig(
        mode=SemanticJudgeMode(semantic_judge),
        judge_model=judge_model,
        replay_path=semantic_judge_replay,
    )
    from fiduciary.fce.evaluator_v3 import build_semantic_judge

    paths = validate_evaluator_v3_on_audit_sample(
        audit_sample_path=Path(audit_sample),
        manual_audit_path=Path(manual_audit) if manual_audit else None,
        output_dir=Path(output_dir),
        semantic_judge=build_semantic_judge(config),
    )

    print(f"wrote evaluator v3 packet: {output_dir}")
    print("artifacts:")
    for key, path in paths.items():
        print(f"  {key}: {path}")
    return 0


def _validate_evaluate_v3_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.semantic_judge == SemanticJudgeMode.REPLAY.value and not args.semantic_judge_replay:
        parser.error("--semantic-judge-replay is required when --semantic-judge=replay")
    if args.semantic_judge != SemanticJudgeMode.REPLAY.value and args.semantic_judge_replay:
        parser.error("--semantic-judge-replay is only valid when --semantic-judge=replay")


def _cmd_build_adjudication_packet(
    *,
    evaluator_results: str,
    raw_outputs: Sequence[str],
    scenario_pack: str | None,
    output_dir: str,
    include_all: bool,
    max_items: int | None,
    output_char_limit: int,
    blind: bool,
) -> int:
    raw_output_paths = [Path(path) for path in _parse_selector_values(raw_outputs)]
    result = write_human_adjudication_packet(
        output_dir=Path(output_dir),
        evaluator_results_path=Path(evaluator_results),
        raw_output_paths=raw_output_paths,
        scenario_pack_path=Path(scenario_pack) if scenario_pack else None,
        include_all=include_all,
        max_items=max_items,
        output_char_limit=output_char_limit,
        blind=blind,
    )
    packet_type = "blinded human adjudication packet" if blind else "human adjudication packet"
    print(f"wrote {packet_type}: {output_dir}")
    print(f"items: {len(result.items)}")
    print("artifacts:")
    print(f"  markdown: {result.markdown_path}")
    print(f"  jsonl: {result.jsonl_path}")
    print(f"  csv: {result.csv_path}")
    return 0


def _cmd_reveal_adjudication_comparison(
    *,
    evaluator_results: str,
    human_labels: str,
    output_dir: str,
) -> int:
    result = write_human_evaluator_comparison_packet(
        output_dir=Path(output_dir),
        evaluator_results_path=Path(evaluator_results),
        human_labels_path=Path(human_labels),
    )
    print(f"wrote human/evaluator comparison packet: {output_dir}")
    print(f"joined labels: {len(result.records)}")
    print("artifacts:")
    print(f"  markdown: {result.markdown_path}")
    print(f"  jsonl: {result.jsonl_path}")
    print(f"  csv: {result.csv_path}")
    return 0


def _validate_run_pilot_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.execution == PilotExecutionMode.RUNTIME.value:
        return

    if args.baseline_adapter == "replay":
        if not args.replay_input:
            parser.error("--replay-input is required when --baseline-adapter=replay")
        if args.provider or args.model:
            parser.error("--provider/--model are only valid when --baseline-adapter=live")
        return

    if args.baseline_adapter == "live":
        if not args.provider:
            parser.error("--provider is required when --baseline-adapter=live")
        if not args.model:
            parser.error("--model is required when --baseline-adapter=live")
        if args.replay_input:
            parser.error("--replay-input is only valid when --baseline-adapter=replay")
        return

    if args.replay_input:
        parser.error("--replay-input is only valid when --baseline-adapter=replay")
    if args.provider or args.model:
        parser.error("--provider/--model are only valid when --baseline-adapter=live")


def _build_baseline_adapter(
    *,
    baseline_adapter: str,
    replay_input: str | None,
    provider: str | None,
    model: str | None,
    temperature: float | None,
    max_output_tokens: int,
    timeout_seconds: float,
):
    if baseline_adapter == "fixture":
        return FixtureBackedBaselineAdapter()
    if baseline_adapter == "replay":
        return ReplayBaselineAdapter(input_path=Path(replay_input or ""))
    if provider == "openai":
        return OpenAIBaselineAdapter(
            model=model or "",
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
    if provider == "anthropic":
        return AnthropicBaselineAdapter(
            model=model or "",
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
        )
    raise ValueError(f"unsupported baseline adapter selection: {baseline_adapter} / {provider}")


def _build_manifest_metadata(
    *,
    output_dir: str,
    execution: PilotExecutionMode,
    baseline_adapter: str,
    replay_input: str | None,
    provider: str | None,
    model: str | None,
    temperature: float | None,
    max_output_tokens: int,
    timeout_seconds: float,
    selected_arms: Sequence[EvaluationArm],
    selected_scenarios: Sequence[FCEScenario],
    adapter,
) -> dict[str, object]:
    return {
        "cli": {
            "command": "run-pilot",
            "output_dir": str(Path(output_dir).resolve()),
            "execution": execution.value,
            "baseline_adapter": baseline_adapter,
            "provider": provider,
            "model": model,
            "replay_input": str(Path(replay_input).resolve()) if replay_input else None,
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
            "timeout_seconds": timeout_seconds,
            "requested_arms": [arm.value for arm in selected_arms],
            "requested_scenario_ids": [scenario.scenario_id for scenario in selected_scenarios],
        },
        "adapters": {
            "baseline_adapter_class": None if adapter is None else adapter.__class__.__name__,
            "runtime_adapter_class": "PrismweftRuntimeAdapter",
        },
        "freeze": _freeze_metadata(selected_scenarios),
        "git": _git_metadata(),
        "scorer": {
            "version": SCORER_VERSION,
            "change_note": SCORER_CHANGE_NOTE,
        },
        "proof": {
            "schema_version": COHERENT_WITNESS_SCHEMA_VERSION,
            "change_note": PROOF_CHANGE_NOTE,
            "supported_scenario_ids": list(supported_proof_scenario_ids()),
        },
        "python": {
            "version": platform.python_version(),
        },
    }


def _git_metadata() -> dict[str, object]:
    status_short = _git_output("status", "--short", multiline=True)
    return {
        "branch": _git_output("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": _git_output("rev-parse", "HEAD"),
        "tags_at_head": _git_output("tag", "--points-at", "HEAD", multiline=True),
        "dirty": bool(status_short),
        "status_short": status_short,
    }


def _git_output(*args: str, multiline: bool = False):
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return [] if multiline else None
    stripped = completed.stdout.strip()
    if multiline:
        return [line for line in stripped.splitlines() if line]
    return stripped or None


def _select_scenarios(raw_items: Sequence[str] | None) -> list[FCEScenario]:
    scenario_ids = _parse_selector_values(raw_items)
    if not scenario_ids:
        return load_pilot_scenarios()

    selected: list[FCEScenario] = []
    for scenario_id in scenario_ids:
        selected.append(get_pilot_scenario(scenario_id))
    return selected


def _parse_selector_values(raw_items: Sequence[str] | None) -> list[str]:
    if not raw_items:
        return []

    parsed: list[str] = []
    for item in raw_items:
        for part in item.split(","):
            candidate = part.strip()
            if candidate and candidate not in parsed:
                parsed.append(candidate)
    return parsed


def _freeze_metadata(selected_scenarios: Sequence[FCEScenario]) -> dict[str, object]:
    return {
        "files": {
            str(path.relative_to(REPO_ROOT)): _sha256_path(path)
            for path in FREEZE_FILE_PATHS
            if path.exists()
        },
        "scenario_hashes": {
            scenario.scenario_id: _sha256_json(scenario.model_dump(mode="json"))
            for scenario in selected_scenarios
        },
    }


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(payload: object) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
