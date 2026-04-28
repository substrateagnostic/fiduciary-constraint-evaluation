"""
Runner surface for executing FCE benchmark arms through baseline or runtime adapters.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Iterable, List, Sequence

from pydantic import BaseModel, ConfigDict, Field

from fiduciary.fce.adapters import (
    AdapterExecutionSource,
    BASELINE_EVALUATION_ARMS,
    RUNNER_EVALUATION_ARMS,
    FCEExecutionReport,
    FCENormalizedObservedOutcome,
    BaselineArmAdapter,
    RuntimeArmAdapter,
    RuntimeArmRequest,
    normalize_baseline_result,
    normalize_runtime_result,
    supported_runner_arm_values,
    supports_runner_arm,
)
from fiduciary.fce.baseline import FixtureBackedBaselineAdapter, build_baseline_request
from fiduciary.fce.grading import build_run, summarize_runs
from fiduciary.fce.models import EvaluationArm, FCEBenchmarkRun, FCESummary, FCEScenario
from fiduciary.fce.runtime import PrismweftRuntimeAdapter
from fiduciary.fce.scenarios import load_pilot_scenarios


class PilotExecutionMode(str, Enum):
    FIXTURES = "fixtures"
    RUNTIME = "runtime"
    HYBRID = "hybrid"


class CompletedRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: FCEBenchmarkRun
    source: AdapterExecutionSource
    normalized_outcome: FCENormalizedObservedOutcome


class PilotRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenarios: List[FCEScenario]
    completed_runs: List[CompletedRun]
    summaries: List[FCESummary]
    manifest_metadata: Dict[str, Any] = Field(default_factory=dict)


DEFAULT_ARMS: tuple[EvaluationArm, ...] = (
    EvaluationArm.RAW_MODEL,
    EvaluationArm.PROMPTED_MODEL,
    EvaluationArm.RULES_AVAILABLE_MODEL,
    EvaluationArm.PRISMWEFT_RUNTIME,
)


class FCEArmRunner:
    def __init__(
        self,
        baseline_adapter: BaselineArmAdapter | None = None,
        runtime_adapter: RuntimeArmAdapter | None = None,
    ) -> None:
        self._baseline_adapter = baseline_adapter or FixtureBackedBaselineAdapter()
        self._runtime_adapter = runtime_adapter or PrismweftRuntimeAdapter()

    def run_scenario(self, scenario: FCEScenario, arm: EvaluationArm) -> FCEExecutionReport:
        if not supports_runner_arm(arm):
            supported = ", ".join(supported_runner_arm_values())
            raise ValueError(
                f"unsupported runner arm: {arm.value}. supported runner arms: {supported}"
            )

        normalized = self.normalize_scenario(scenario, arm)
        benchmark_run = build_run(scenario, normalized.outcome, arm)
        return FCEExecutionReport(
            scenario_id=scenario.scenario_id,
            arm=arm,
            normalized_outcome=normalized,
            benchmark_run=benchmark_run,
        )

    def normalize_scenario(
        self,
        scenario: FCEScenario,
        arm: EvaluationArm,
    ) -> FCENormalizedObservedOutcome:
        if arm in BASELINE_EVALUATION_ARMS:
            request = build_baseline_request(scenario, arm)
            result = self._baseline_adapter.invoke(request)
            return normalize_baseline_result(request, result)

        request = RuntimeArmRequest(scenario=scenario, arm=arm)
        result = self._runtime_adapter.invoke(request)
        return normalize_runtime_result(request, result)

    def run_suite(
        self,
        scenarios: Iterable[FCEScenario],
        arms: Sequence[EvaluationArm] | None = None,
    ) -> List[FCEExecutionReport]:
        selected_arms = tuple(arms or DEFAULT_ARMS)
        reports: List[FCEExecutionReport] = []
        for scenario in scenarios:
            for arm in selected_arms:
                reports.append(self.run_scenario(scenario, arm))
        return reports

    def summarize_reports(
        self,
        scenarios: Sequence[FCEScenario],
        reports: Sequence[FCEExecutionReport],
    ) -> List[FCESummary]:
        return summarize_runs(scenarios, [report.benchmark_run for report in reports])


def default_runner_arms() -> tuple[EvaluationArm, ...]:
    return DEFAULT_ARMS


def parse_arms(arms: Sequence[str] | None) -> tuple[EvaluationArm, ...]:
    if not arms:
        return DEFAULT_ARMS

    parsed: List[EvaluationArm] = []
    for item in arms:
        for part in item.split(","):
            candidate = part.strip()
            if not candidate:
                continue
            if candidate == "prismweft":
                candidate = EvaluationArm.PRISMWEFT_RUNTIME.value
            parsed.append(EvaluationArm(candidate))
    deduped: List[EvaluationArm] = []
    for arm in parsed:
        if arm not in deduped:
            deduped.append(arm)
    return tuple(deduped)


def run_pilot(
    *,
    arms: Sequence[EvaluationArm] | None = None,
    mode: PilotExecutionMode = PilotExecutionMode.HYBRID,
    scenarios: Sequence[FCEScenario] | None = None,
    baseline_adapter: BaselineArmAdapter | None = None,
    runtime_adapter: RuntimeArmAdapter | None = None,
    manifest_metadata: Dict[str, Any] | None = None,
) -> PilotRunResult:
    selected_scenarios = list(scenarios or load_pilot_scenarios())
    selected_arms = _arms_for_mode(arms, mode)
    runner = _runner_for_mode(
        mode,
        baseline_adapter=baseline_adapter,
        runtime_adapter=runtime_adapter,
    )
    reports = _reports_for_mode(runner, selected_scenarios, selected_arms, mode)

    completed_runs = [
        CompletedRun(
            run=report.benchmark_run,
            source=report.normalized_outcome.source,
            normalized_outcome=report.normalized_outcome,
        )
        for report in reports
    ]

    return PilotRunResult(
        scenarios=selected_scenarios,
        completed_runs=completed_runs,
        summaries=runner.summarize_reports(selected_scenarios, reports),
        manifest_metadata=dict(manifest_metadata or {}),
    )


def _arms_for_mode(
    arms: Sequence[EvaluationArm] | None,
    mode: PilotExecutionMode,
) -> tuple[EvaluationArm, ...]:
    if mode == PilotExecutionMode.RUNTIME:
        return (EvaluationArm.PRISMWEFT_RUNTIME,)

    selected_arms = tuple(arms or DEFAULT_ARMS)
    unsupported = [arm.value for arm in selected_arms if not supports_runner_arm(arm)]
    if unsupported:
        supported = ", ".join(supported_runner_arm_values())
        raise ValueError(
            f"unsupported runner arms: {', '.join(unsupported)}. supported runner arms: {supported}"
        )
    if mode == PilotExecutionMode.FIXTURES:
        return tuple(arm for arm in selected_arms if arm in RUNNER_EVALUATION_ARMS)
    return selected_arms


def _runner_for_mode(
    mode: PilotExecutionMode,
    *,
    baseline_adapter: BaselineArmAdapter | None = None,
    runtime_adapter: RuntimeArmAdapter | None = None,
) -> FCEArmRunner:
    selected_runtime_adapter = runtime_adapter
    if selected_runtime_adapter is None:
        selected_runtime_adapter = PrismweftRuntimeAdapter(
            prefer_runtime=mode != PilotExecutionMode.FIXTURES
        )
    return FCEArmRunner(
        baseline_adapter=baseline_adapter,
        runtime_adapter=selected_runtime_adapter,
    )


def _reports_for_mode(
    runner: FCEArmRunner,
    scenarios: Sequence[FCEScenario],
    arms: Sequence[EvaluationArm],
    mode: PilotExecutionMode,
) -> List[FCEExecutionReport]:
    if mode == PilotExecutionMode.RUNTIME:
        runtime_scenarios = [scenario for scenario in scenarios if scenario.runtime_case is not None]
        return runner.run_suite(runtime_scenarios, arms=arms)
    return runner.run_suite(scenarios, arms=arms)
