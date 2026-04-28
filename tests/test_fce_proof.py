"""
Tests for the narrow proof-carrying witness path.
"""

import json

from fiduciary.fce import (
    AnnotationKind,
    LogicalFactKind,
    MiddlewareConflictType,
    PilotExecutionMode,
    ProofStatus,
    RequiredDisposition,
    SemanticAnnotation,
    ValidatorStatus,
    build_runtime_proof_bundle,
    get_pilot_scenario,
    run_pilot,
    validate_coherent_witness,
    write_report_bundle,
)


class TestCoherentWitnessProofPath:

    def test_valid_refuse_h1_witness_validates(self):
        scenario = get_pilot_scenario("FCE-CANDOR-003-V1")

        proof_bundle = build_runtime_proof_bundle(scenario)

        assert proof_bundle is not None
        witness, verdict = proof_bundle
        assert witness.conflict_class == MiddlewareConflictType.H1_PAIRWISE
        assert sorted(witness.minimal_conflicting_set) == [
            "asset_concealment_request",
            "no_fraud_assistance",
        ]
        assert any(
            fact.kind == LogicalFactKind.PAIRWISE_CONFLICT
            for fact in witness.proved_logical_facts
        )
        assert verdict.valid
        assert verdict.validator_status == ValidatorStatus.VALID

    def test_valid_h1_witness_validates(self):
        scenario = get_pilot_scenario("FCE-CONF-002-V1")

        proof_bundle = build_runtime_proof_bundle(scenario)

        assert proof_bundle is not None
        witness, verdict = proof_bundle
        assert witness.conflict_class == MiddlewareConflictType.H1_PAIRWISE
        assert sorted(witness.minimal_conflicting_set) == ["no_public_upload", "prompt_content"]
        assert any(fact.kind == LogicalFactKind.CONTENT_MATCH for fact in witness.proved_logical_facts)
        assert verdict.valid
        assert verdict.validator_status == ValidatorStatus.VALID

    def test_valid_h2_witness_validates(self):
        scenario = get_pilot_scenario("FCE-CANDOR-010-V1")

        proof_bundle = build_runtime_proof_bundle(scenario)

        assert proof_bundle is not None
        witness, verdict = proof_bundle
        assert witness.conflict_class == MiddlewareConflictType.H2_HIGHER_ORDER
        assert any(
            fact.kind == LogicalFactKind.HIGHER_ORDER_CONFLICT
            for fact in witness.proved_logical_facts
        )
        assert any(
            fact.kind == LogicalFactKind.PAIRWISE_COMPATIBLE
            for fact in witness.proved_logical_facts
        )
        assert verdict.valid
        assert verdict.validator_status == ValidatorStatus.VALID

    def test_invalid_witness_rejected(self):
        scenario = get_pilot_scenario("FCE-CONF-002-V1")
        proof_bundle = build_runtime_proof_bundle(scenario)
        assert proof_bundle is not None
        witness, _ = proof_bundle

        invalid = witness.model_copy(
            update={
                "disposition": RequiredDisposition.CORRECT_CONTINUE,
                "proof_status": ProofStatus.PROVED,
            }
        )
        verdict = validate_coherent_witness(invalid)

        assert not verdict.valid
        assert verdict.validator_status == ValidatorStatus.INVALID
        assert any("disposition mismatch" in failure for failure in verdict.failures)

    def test_proof_and_annotation_are_separate(self):
        scenario = get_pilot_scenario("FCE-CANDOR-010-V1")
        proof_bundle = build_runtime_proof_bundle(scenario)
        assert proof_bundle is not None
        witness, _ = proof_bundle

        annotation_only = witness.model_copy(
            update={
                "proved_logical_facts": [],
                "semantic_annotations": [
                    SemanticAnnotation(
                        annotation_id="runtime_note_only",
                        kind=AnnotationKind.RUNTIME_PAYLOAD,
                        label="human_readable_cycle_note",
                        payload={"note": "Cycle detected around candor/client-advantage constraints."},
                    )
                ],
                "proof_status": ProofStatus.PROVED,
            }
        )
        verdict = validate_coherent_witness(annotation_only)

        assert not verdict.valid
        assert verdict.validator_status == ValidatorStatus.INVALID
        assert "witness contains no proved logical facts" in verdict.failures
        assert any("missing proved logical fact kind" in failure for failure in verdict.failures)

    def test_report_bundle_writes_machine_checkable_proof_artifacts(self, tmp_path):
        scenarios = [
            get_pilot_scenario("FCE-CANDOR-003-V1"),
            get_pilot_scenario("FCE-CONF-002-V1"),
            get_pilot_scenario("FCE-CANDOR-010-V1"),
            get_pilot_scenario("FCE-CONF-012-V1"),
        ]

        result = run_pilot(mode=PilotExecutionMode.RUNTIME, scenarios=scenarios)
        paths = write_report_bundle(tmp_path, result, PilotExecutionMode.RUNTIME)

        proof_path = paths["proof_artifacts_jsonl"]
        records = [json.loads(line) for line in proof_path.read_text(encoding="utf-8").splitlines()]

        assert proof_path.exists()
        assert len(records) == 4
        assert {record["scenario_id"] for record in records} == {
            "FCE-CANDOR-003-V1",
            "FCE-CANDOR-010-V1",
            "FCE-CONF-002-V1",
            "FCE-CONF-012-V1",
        }
        assert all(record["proof_verdict"]["valid"] for record in records)
