"""
Runner and normalization tests for FCE evaluation arms.
"""

import json

import pytest

from fiduciary.fce.cli import _select_scenarios
from fiduciary.fce import (
    AdapterExecutionSource,
    BaselineAdapterResult,
    EvaluationArm,
    FCEArmRunner,
    MiddlewareConflictType,
    ObservedAction,
    PilotExecutionMode,
    PrismweftRuntimeAdapter,
    RequiredDisposition,
    WitnessMode,
    build_baseline_request,
    get_pilot_scenario,
    normalize_baseline_result,
    parse_arms,
    run_pilot,
    write_report_bundle,
)


class TestRunnerNormalization:

    def test_baseline_normalization_dedupes_and_stays_grading_compatible(self):
        scenario = get_pilot_scenario("FCE-RET-009-V1")
        request = build_baseline_request(scenario, EvaluationArm.RAW_MODEL)
        result = BaselineAdapterResult(
            response_text="  Preserve the logs and escalate this.  ",
            actions=[ObservedAction.ESCALATE, ObservedAction.ESCALATE],
            identified_duties=["preservation", "preservation", "litigation hold"],
            adapter_name="test_baseline",
        )

        normalized = normalize_baseline_result(request, result)
        report = FCEArmRunner().run_scenario(scenario, EvaluationArm.RAW_MODEL)

        assert normalized.outcome.response_text == "Preserve the logs and escalate this."
        assert normalized.outcome.actions == [ObservedAction.ESCALATE]
        assert normalized.outcome.identified_duties == ["preservation", "litigation hold"]
        assert report.benchmark_run.score.total_score > 0.0

    def test_prismweft_runtime_uses_live_runtime_case_when_available(self):
        scenario = get_pilot_scenario("FCE-CANDOR-010-V1")

        report = FCEArmRunner().run_scenario(scenario, EvaluationArm.PRISMWEFT_RUNTIME)

        assert report.normalized_outcome.source == AdapterExecutionSource.RUNTIME
        assert report.normalized_outcome.witness_mode == WitnessMode.PROOF_SUPPORTED_RUNTIME
        assert report.normalized_outcome.outcome.witness is not None
        assert report.normalized_outcome.outcome.proof_witness is not None
        assert report.normalized_outcome.outcome.proof_verdict is not None
        assert report.normalized_outcome.outcome.witness.conflict_type is not None
        assert report.benchmark_run.score.witness_fidelity is not None

    def test_prismweft_runtime_uses_runtime_refuse_case_when_available(self):
        scenario = get_pilot_scenario("FCE-CANDOR-003-V1")

        report = FCEArmRunner().run_scenario(scenario, EvaluationArm.PRISMWEFT_RUNTIME)

        assert report.normalized_outcome.source == AdapterExecutionSource.RUNTIME
        assert report.normalized_outcome.witness_mode == WitnessMode.PROOF_SUPPORTED_RUNTIME
        assert report.normalized_outcome.proof_supported is True
        assert report.normalized_outcome.semantic_annotations_present is True
        assert report.normalized_outcome.outcome.witness is not None
        assert report.normalized_outcome.outcome.witness.event == RequiredDisposition.REFUSE_REQUIRED

    def test_prismweft_runtime_uses_runtime_clarify_case_when_available(self):
        scenario = get_pilot_scenario("FCE-COMP-004-V3")

        report = FCEArmRunner().run_scenario(scenario, EvaluationArm.PRISMWEFT_RUNTIME)

        assert report.normalized_outcome.source == AdapterExecutionSource.RUNTIME
        assert report.normalized_outcome.witness_mode == WitnessMode.RUNTIME
        assert report.normalized_outcome.proof_supported is False
        assert report.normalized_outcome.semantic_annotations_present is True
        assert report.normalized_outcome.outcome.witness is not None
        assert report.normalized_outcome.outcome.proof_witness is None
        assert report.normalized_outcome.outcome.witness.event == RequiredDisposition.CLARIFY_REQUIRED
        assert (
            report.normalized_outcome.outcome.witness.conflict_type
            == MiddlewareConflictType.WITNESS_INSUFFICIENCY
        )
        assert report.benchmark_run.score.witness_fidelity == 1.0

    def test_prismweft_runtime_falls_back_to_fixture_when_no_runtime_case_exists(self):
        scenario = get_pilot_scenario("FCE-COMP-004-V1")

        report = FCEArmRunner(
            runtime_adapter=PrismweftRuntimeAdapter(prefer_runtime=True)
        ).run_scenario(scenario, EvaluationArm.PRISMWEFT_RUNTIME)

        assert report.normalized_outcome.source == AdapterExecutionSource.FIXTURE
        assert report.normalized_outcome.witness_mode == WitnessMode.FIXTURE
        assert report.normalized_outcome.proof_supported is False
        assert report.normalized_outcome.semantic_annotations_present is False
        assert report.normalized_outcome.outcome.witness is not None
        assert report.normalized_outcome.outcome.proof_witness is None
        assert report.benchmark_run.score.witness_fidelity == 1.0

    @pytest.mark.parametrize(
        ("scenario_id", "arm", "expected_source", "expected_mode", "proof_supported", "has_annotations"),
        [
            (
                "FCE-CONF-001-V1",
                EvaluationArm.RAW_MODEL,
                AdapterExecutionSource.FIXTURE,
                WitnessMode.NONE,
                False,
                False,
            ),
            (
                "FCE-COMP-004-V1",
                EvaluationArm.PRISMWEFT_RUNTIME,
                AdapterExecutionSource.FIXTURE,
                WitnessMode.FIXTURE,
                False,
                False,
            ),
            (
                "FCE-COMP-004-V3",
                EvaluationArm.PRISMWEFT_RUNTIME,
                AdapterExecutionSource.RUNTIME,
                WitnessMode.RUNTIME,
                False,
                True,
            ),
            (
                "FCE-CANDOR-003-V1",
                EvaluationArm.PRISMWEFT_RUNTIME,
                AdapterExecutionSource.RUNTIME,
                WitnessMode.PROOF_SUPPORTED_RUNTIME,
                True,
                True,
            ),
        ],
    )
    def test_witness_capability_flags_track_execution_paths(
        self,
        scenario_id,
        arm,
        expected_source,
        expected_mode,
        proof_supported,
        has_annotations,
    ):
        scenario = get_pilot_scenario(scenario_id)

        report = FCEArmRunner().run_scenario(scenario, arm)

        assert report.normalized_outcome.source == expected_source
        assert report.normalized_outcome.witness_mode == expected_mode
        assert report.normalized_outcome.proof_supported is proof_supported
        assert report.normalized_outcome.semantic_annotations_present is has_annotations

    def test_runner_rejects_legacy_checklist_gate_arm(self):
        scenario = get_pilot_scenario("FCE-COMP-004-V1")

        with pytest.raises(ValueError, match="supported runner arms"):
            FCEArmRunner().run_scenario(scenario, EvaluationArm.CHECKLIST_GATE)

    def test_parse_arms_accepts_prismweft_alias(self):
        assert parse_arms(["prismweft"]) == (EvaluationArm.PRISMWEFT_RUNTIME,)


class TestPilotRunnerModes:

    def test_cli_scenario_selector_is_deduplicated_and_ordered(self):
        scenarios = _select_scenarios(
            [
                "FCE-COMP-004-V1,FCE-CONF-012-V1",
                "FCE-COMP-004-V1",
                "FCE-CANDOR-010-V1",
            ]
        )

        assert [scenario.scenario_id for scenario in scenarios] == [
            "FCE-COMP-004-V1",
            "FCE-CONF-012-V1",
            "FCE-CANDOR-010-V1",
        ]

    def test_runtime_mode_only_emits_runtime_backed_prismweft_runs(self):
        result = run_pilot(mode=PilotExecutionMode.RUNTIME)
        runtime_backed = [
            scenario for scenario in result.scenarios if scenario.runtime_case is not None
        ]

        assert len(result.completed_runs) == len(runtime_backed)
        assert {completed.run.arm for completed in result.completed_runs} == {
            EvaluationArm.PRISMWEFT_RUNTIME
        }
        assert all(completed.source == AdapterExecutionSource.RUNTIME for completed in result.completed_runs)

    def test_report_bundle_surfaces_capabilities_and_disposition_coverage(self, tmp_path):
        scenarios = [
            get_pilot_scenario("FCE-COMP-004-V1"),
            get_pilot_scenario("FCE-COMP-004-V3"),
            get_pilot_scenario("FCE-CANDOR-003-V1"),
            get_pilot_scenario("FCE-CANDOR-010-V1"),
            get_pilot_scenario("FCE-CONF-012-V1"),
            get_pilot_scenario("FCE-SUP-011-V1"),
            get_pilot_scenario("FCE-COMP-013-V1"),
        ]

        result = run_pilot(
            arms=[EvaluationArm.PRISMWEFT_RUNTIME],
            mode=PilotExecutionMode.HYBRID,
            scenarios=scenarios,
        )
        paths = write_report_bundle(tmp_path, result, PilotExecutionMode.HYBRID)
        manifest = json.loads(paths["manifest_json"].read_text(encoding="utf-8"))
        report_text = paths["report_md"].read_text(encoding="utf-8")

        assert manifest["capability_summary"]["witness_mode_counts"]["fixture"] == 1
        assert manifest["capability_summary"]["witness_mode_counts"]["runtime"] == 1
        # Three correct-continue stand-downs (CONF-012, SUP-011, COMP-013) join the
        # refuse and escalate proofs → five proof-supported runtime witnesses.
        assert manifest["capability_summary"]["witness_mode_counts"]["proof_supported_runtime"] == 5
        assert manifest["runtime_disposition_coverage"]["clarify_required"]["runtime"] == 1
        assert manifest["runtime_disposition_coverage"]["refuse_required"]["proof_supported_runtime"] == 1
        assert manifest["runtime_disposition_coverage"]["escalate_required"]["proof_supported_runtime"] == 1
        assert manifest["runtime_disposition_coverage"]["correct_continue"]["proof_supported_runtime"] == 3
        assert "Witness Capability Summary" in report_text
        assert "proof_supported_runtime" in report_text
        assert "Runtime Disposition Coverage" in report_text
