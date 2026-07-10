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

    def test_sup_011_compatibility_standdown_witness_validates(self):
        scenario = get_pilot_scenario("FCE-SUP-011-V1")

        proof_bundle = build_runtime_proof_bundle(scenario)

        assert proof_bundle is not None
        witness, verdict = proof_bundle
        assert witness.conflict_class == MiddlewareConflictType.NONE
        assert witness.disposition == RequiredDisposition.CORRECT_CONTINUE
        assert witness.minimal_conflicting_set == []
        assert sorted(witness.constraint_ids) == [
            "intake_scope_guardrail",
            "log_intake_facts",
            "no_individualized_legal_advice",
        ]
        assert any(
            fact.kind == LogicalFactKind.SATISFIABLE_SET
            for fact in witness.proved_logical_facts
        )
        assert verdict.valid
        assert verdict.validator_status == ValidatorStatus.VALID

    def test_comp_013_higher_order_standdown_witness_validates(self):
        scenario = get_pilot_scenario("FCE-COMP-013-V1")

        proof_bundle = build_runtime_proof_bundle(scenario)

        assert proof_bundle is not None
        witness, verdict = proof_bundle
        assert witness.conflict_class == MiddlewareConflictType.NONE
        assert witness.disposition == RequiredDisposition.CORRECT_CONTINUE
        assert witness.minimal_conflicting_set == []
        assert sorted(witness.constraint_ids) == [
            "not_filing_ready",
            "research_scope_guardrail",
            "summarize_public_statutes",
        ]
        assert any(
            fact.kind == LogicalFactKind.SATISFIABLE_SET
            for fact in witness.proved_logical_facts
        )
        assert verdict.valid
        assert verdict.validator_status == ValidatorStatus.VALID

    def test_tampered_standdown_witness_rejected(self):
        """A stand-down witness whose disposition is flipped to refuse must be
        rejected — the validator re-derives from the engine rather than echoing
        the asserted fields."""
        scenario = get_pilot_scenario("FCE-SUP-011-V1")
        proof_bundle = build_runtime_proof_bundle(scenario)
        assert proof_bundle is not None
        witness, _ = proof_bundle

        tampered = witness.model_copy(
            update={
                "conflict_class": MiddlewareConflictType.H1_PAIRWISE,
                "disposition": RequiredDisposition.REFUSE_REQUIRED,
                "proof_status": ProofStatus.PROVED,
            }
        )
        verdict = validate_coherent_witness(tampered)

        assert not verdict.valid
        assert verdict.validator_status == ValidatorStatus.INVALID
        assert any("disposition mismatch" in failure for failure in verdict.failures)

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

    def test_witness_from_mutated_runtime_case_is_rejected(self):
        """Finding 4 (gpt-5.6-sol) counterexample: SUP-011 with log_intake_facts
        rewritten to the exact forbidden expression. The runtime now derives an
        H1 escalate, so the stand-down witness the builder emits must NOT validate
        — validation runs against the supplied (mutated) artifact, not a fresh
        catalog lookup that would still look clean."""
        scenario = get_pilot_scenario("FCE-SUP-011-V1")
        base = scenario.runtime_case
        assert base is not None
        forbidden = r"individualized legal advice|legal opinion|recommend a litigation strategy"
        mutated_reqs = [
            c.model_copy(update={"target": forbidden}) if c.id == "log_intake_facts" else c
            for c in base.request_constraints
        ]
        mutated_case = base.model_copy(update={"request_constraints": mutated_reqs})
        mutated_scenario = scenario.model_copy(update={"runtime_case": mutated_case})

        bundle = build_runtime_proof_bundle(mutated_scenario)
        assert bundle is not None
        _witness, verdict = bundle

        assert not verdict.valid
        assert verdict.validator_status == ValidatorStatus.INVALID
        # The engine actually finds an obstruction on the mutated case.
        assert any("obstruction" in failure.lower() for failure in verdict.failures)

    def test_genuine_witness_rejected_against_a_different_artifact(self):
        """The canonical hash binds a witness to one runtime case. A genuine
        witness cannot be validated against a different runtime case that merely
        reuses the same scenario_id."""
        scenario = get_pilot_scenario("FCE-SUP-011-V1")
        bundle = build_runtime_proof_bundle(scenario)
        assert bundle is not None
        witness, verdict = bundle
        assert verdict.valid  # genuine witness validates against its own artifact

        base = scenario.runtime_case
        assert base is not None
        mutated_case = base.model_copy(
            update={
                "policy_constraints": [
                    c.model_copy(update={"target": c.target + "|extra_scope"})
                    if c.id == "intake_scope_guardrail"
                    else c
                    for c in base.policy_constraints
                ]
            }
        )
        mutated_scenario = scenario.model_copy(update={"runtime_case": mutated_case})

        reverdict = validate_coherent_witness(witness, mutated_scenario)

        assert not reverdict.valid
        assert any("runtime_case_hash mismatch" in failure for failure in reverdict.failures)

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
