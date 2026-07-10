"""
Narrow proof-carrying witness support for a flagship runtime subset.

This module does not try to prove arbitrary FCE scenarios. It re-checks a
small, fixed set of runtime-backed cases with deterministic logic and exports
the result as a machine-checkable witness plus validator verdict.
"""

from __future__ import annotations

from itertools import combinations
from typing import Iterable, Sequence

from fiduciary.cohomology.compatibility import check_compatibility
from fiduciary.cohomology.constraints import ConstraintSet
from fiduciary.cohomology.enclave import EnclaveResolution, check_in_enclave
from fiduciary.cohomology.higher_compatibility import (
    build_cech_complex,
    check_compatibility_with_higher_orders,
    detect_h2_obstructions,
)
from fiduciary.models import Severity
from fiduciary.fce.models import (
    AnnotationKind,
    CoherentWitness,
    FCEScenario,
    HandoffTarget,
    LogicalFactKind,
    MiddlewareConflictType,
    ProofStatus,
    ProofValidationVerdict,
    ProvedLogicalFact,
    RequiredDisposition,
    RuntimeEvaluationMode,
    SemanticAnnotation,
    ValidatorStatus,
)
from fiduciary.fce.scenarios import get_pilot_scenario


COHERENT_WITNESS_SCHEMA_VERSION = "fce-coherent-witness-v0.1"
PROOF_CHANGE_NOTE = (
    "Flagship subset only: deterministic proof-carrying witnesses for a narrow "
    "runtime-backed subset: one escalate H1 case, one refuse H1 case, one H2 case, "
    "and three stand-down cases (two higher-order stand-downs and one "
    "compatibility-mode stand-down)."
)

_SUPPORTED_SCENARIO_IDS: tuple[str, ...] = (
    "FCE-CANDOR-003-V1",
    "FCE-CONF-002-V1",
    "FCE-CANDOR-010-V1",
    "FCE-CONF-012-V1",
    "FCE-SUP-011-V1",
    "FCE-COMP-013-V1",
)


def supported_proof_scenario_ids() -> tuple[str, ...]:
    return _SUPPORTED_SCENARIO_IDS


def build_runtime_proof_bundle(
    scenario: FCEScenario,
) -> tuple[CoherentWitness, ProofValidationVerdict] | None:
    if scenario.scenario_id not in _SUPPORTED_SCENARIO_IDS or scenario.runtime_case is None:
        return None

    if scenario.scenario_id == "FCE-CANDOR-003-V1":
        witness = _build_candor_003_witness(scenario)
    elif scenario.scenario_id == "FCE-CONF-002-V1":
        witness = _build_conf_002_witness(scenario)
    elif scenario.scenario_id == "FCE-CANDOR-010-V1":
        witness = _build_candor_010_witness(scenario)
    elif scenario.scenario_id == "FCE-CONF-012-V1":
        witness = _build_conf_012_witness(scenario)
    elif scenario.scenario_id == "FCE-SUP-011-V1":
        witness = _build_sup_011_witness(scenario)
    elif scenario.scenario_id == "FCE-COMP-013-V1":
        witness = _build_comp_013_witness(scenario)
    else:
        return None

    verdict = validate_coherent_witness(witness)
    witness = witness.model_copy(
        update={
            "proof_status": verdict.proof_status,
            "validator_status": verdict.validator_status,
        }
    )
    return witness, verdict


def validate_coherent_witness(witness: CoherentWitness) -> ProofValidationVerdict:
    try:
        scenario = get_pilot_scenario(witness.scenario_id)
    except KeyError:
        return ProofValidationVerdict(
            schema_version=COHERENT_WITNESS_SCHEMA_VERSION,
            scenario_id=witness.scenario_id,
            valid=False,
            proof_status=ProofStatus.NOT_PROVED,
            validator_status=ValidatorStatus.UNSUPPORTED,
            derived_conflict_class=MiddlewareConflictType.NONE,
            derived_disposition=RequiredDisposition.CORRECT_CONTINUE,
            checked_fact_ids=_fact_ids(witness.proved_logical_facts),
            failures=[f"unsupported proof scenario: {witness.scenario_id}"],
        )

    return _validate_against_scenario(witness, scenario)


def _validate_against_scenario(
    witness: CoherentWitness,
    scenario: FCEScenario,
) -> ProofValidationVerdict:
    if scenario.scenario_id not in _SUPPORTED_SCENARIO_IDS or scenario.runtime_case is None:
        return ProofValidationVerdict(
            schema_version=COHERENT_WITNESS_SCHEMA_VERSION,
            scenario_id=scenario.scenario_id,
            valid=False,
            proof_status=ProofStatus.NOT_PROVED,
            validator_status=ValidatorStatus.UNSUPPORTED,
            derived_conflict_class=MiddlewareConflictType.NONE,
            derived_disposition=RequiredDisposition.CORRECT_CONTINUE,
            checked_fact_ids=_fact_ids(witness.proved_logical_facts),
            failures=[f"proof path not implemented for {scenario.scenario_id}"],
        )

    failures: list[str] = []

    if not witness.proved_logical_facts:
        failures.append("witness contains no proved logical facts")
    if witness.scenario_id != scenario.scenario_id:
        failures.append("scenario_id mismatch")
    if witness.runtime_mode != scenario.runtime_case.mode:
        failures.append(
            f"runtime mode mismatch: expected {scenario.runtime_case.mode.value}, got {witness.runtime_mode.value}"
        )

    if scenario.scenario_id == "FCE-CANDOR-003-V1":
        derived_conflict_class, derived_disposition, expected_constraints, expected_minimal_set = (
            _validate_candor_003_runtime(failures, witness, scenario)
        )
        _require_fact_kinds(
            witness,
            failures,
            (
                LogicalFactKind.CONSTRAINT_PRESENT,
                LogicalFactKind.PAIRWISE_CONFLICT,
            ),
        )
    elif scenario.scenario_id == "FCE-CONF-002-V1":
        derived_conflict_class, derived_disposition, expected_constraints, expected_minimal_set = (
            _validate_conf_002_runtime(failures, witness, scenario)
        )
        _require_fact_kinds(
            witness,
            failures,
            (
                LogicalFactKind.CONSTRAINT_PRESENT,
                LogicalFactKind.CONTENT_MATCH,
                LogicalFactKind.PAIRWISE_CONFLICT,
                LogicalFactKind.ENCLAVE_RESOLUTION,
            ),
        )
    elif scenario.scenario_id == "FCE-CANDOR-010-V1":
        derived_conflict_class, derived_disposition, expected_constraints, expected_minimal_set = (
            _validate_candor_010_runtime(failures, witness, scenario)
        )
        _require_fact_kinds(
            witness,
            failures,
            (
                LogicalFactKind.CONSTRAINT_PRESENT,
                LogicalFactKind.PAIRWISE_COMPATIBLE,
                LogicalFactKind.HIGHER_ORDER_CONFLICT,
            ),
        )
    elif scenario.scenario_id == "FCE-SUP-011-V1":
        derived_conflict_class, derived_disposition, expected_constraints, expected_minimal_set = (
            _validate_sup_011_runtime(failures, witness, scenario)
        )
        _require_fact_kinds(
            witness,
            failures,
            (
                LogicalFactKind.CONSTRAINT_PRESENT,
                LogicalFactKind.SATISFIABLE_SET,
            ),
        )
    elif scenario.scenario_id == "FCE-COMP-013-V1":
        derived_conflict_class, derived_disposition, expected_constraints, expected_minimal_set = (
            _validate_comp_013_runtime(failures, witness, scenario)
        )
        _require_fact_kinds(
            witness,
            failures,
            (
                LogicalFactKind.CONSTRAINT_PRESENT,
                LogicalFactKind.SATISFIABLE_SET,
            ),
        )
    else:
        derived_conflict_class, derived_disposition, expected_constraints, expected_minimal_set = (
            _validate_conf_012_runtime(failures, witness, scenario)
        )
        _require_fact_kinds(
            witness,
            failures,
            (
                LogicalFactKind.CONSTRAINT_PRESENT,
                LogicalFactKind.SATISFIABLE_SET,
            ),
        )

    if sorted(witness.constraint_ids) != sorted(expected_constraints):
        failures.append(
            f"constraint_ids mismatch: expected {sorted(expected_constraints)}, got {sorted(witness.constraint_ids)}"
        )
    if sorted(witness.minimal_conflicting_set) != sorted(expected_minimal_set):
        failures.append(
            "minimal_conflicting_set mismatch: "
            f"expected {sorted(expected_minimal_set)}, got {sorted(witness.minimal_conflicting_set)}"
        )
    if witness.conflict_class != derived_conflict_class:
        failures.append(
            f"conflict_class mismatch: expected {derived_conflict_class.value}, got {witness.conflict_class.value}"
        )
    if witness.disposition != derived_disposition:
        failures.append(
            f"disposition mismatch: expected {derived_disposition.value}, got {witness.disposition.value}"
        )

    valid = not failures
    return ProofValidationVerdict(
        schema_version=COHERENT_WITNESS_SCHEMA_VERSION,
        scenario_id=scenario.scenario_id,
        valid=valid,
        proof_status=ProofStatus.PROVED if valid else ProofStatus.REJECTED,
        validator_status=ValidatorStatus.VALID if valid else ValidatorStatus.INVALID,
        derived_conflict_class=derived_conflict_class,
        derived_disposition=derived_disposition,
        checked_fact_ids=_fact_ids(witness.proved_logical_facts),
        failures=failures,
    )


def _build_candor_003_witness(scenario: FCEScenario) -> CoherentWitness:
    runtime_case = scenario.runtime_case
    assert runtime_case is not None
    result = _compatibility_result(scenario)
    obstruction = result.obstructions[0]
    constraint_ids = [obstruction.constraint_a.source_id, obstruction.constraint_b.source_id]

    return CoherentWitness(
        schema_version=COHERENT_WITNESS_SCHEMA_VERSION,
        scenario_id=scenario.scenario_id,
        runtime_mode=runtime_case.mode,
        proved_logical_facts=[
            ProvedLogicalFact(
                fact_id="policy_constraint_present",
                kind=LogicalFactKind.CONSTRAINT_PRESENT,
                claim="The runtime policy forbids operationalizing asset-concealment timing.",
                constraint_ids=[obstruction.constraint_a.source_id],
                details={"severity": obstruction.constraint_a.severity.value},
            ),
            ProvedLogicalFact(
                fact_id="request_constraint_present",
                kind=LogicalFactKind.CONSTRAINT_PRESENT,
                claim="The request requires the same concealment-timing pattern the policy forbids.",
                constraint_ids=[obstruction.constraint_b.source_id],
                details={"severity": obstruction.constraint_b.severity.value},
            ),
            ProvedLogicalFact(
                fact_id="pairwise_obstruction",
                kind=LogicalFactKind.PAIRWISE_CONFLICT,
                claim="The policy and request constraints are jointly inconsistent.",
                constraint_ids=constraint_ids,
                details={
                    "obstruction_type": obstruction.obstruction_type,
                    "status": result.status.value,
                },
            ),
        ],
        semantic_annotations=[
            SemanticAnnotation(
                annotation_id="compatibility_runtime_payload",
                kind=AnnotationKind.RUNTIME_PAYLOAD,
                label="compatibility_obstruction_witness",
                payload={
                    "status": result.status.value,
                    "obstruction_type": obstruction.obstruction_type,
                    "suggested_resolution": obstruction.suggested_resolution,
                },
            ),
        ],
        constraint_ids=constraint_ids,
        variable_bindings={
            "policy_constraint": obstruction.constraint_a.source_id,
            "request_constraint": obstruction.constraint_b.source_id,
        },
        conflict_class=MiddlewareConflictType.H1_PAIRWISE,
        minimal_conflicting_set=constraint_ids,
        disposition=RequiredDisposition.REFUSE_REQUIRED,
    )


def _build_conf_002_witness(scenario: FCEScenario) -> CoherentWitness:
    runtime_case = scenario.runtime_case
    assert runtime_case is not None
    verdict = check_in_enclave(
        prompt=runtime_case.prompt or "",
        constraint_set=runtime_case.build_policy_set(),
        escalate_soft=runtime_case.escalate_soft,
    )
    obstruction = _select_enclave_obstruction(verdict.obstruction_witnesses)
    disposition = _derive_enclave_disposition(scenario)
    constraint_ids = [obstruction.constraint_a_id, obstruction.constraint_b_id]

    return CoherentWitness(
        schema_version=COHERENT_WITNESS_SCHEMA_VERSION,
        scenario_id=scenario.scenario_id,
        runtime_mode=runtime_case.mode,
        proved_logical_facts=[
            ProvedLogicalFact(
                fact_id="policy_constraint_present",
                kind=LogicalFactKind.CONSTRAINT_PRESENT,
                claim="The enclave policy contains the no-public-upload constraint.",
                constraint_ids=[obstruction.constraint_a_id],
                details={"severity": Severity.P0.value, "soul_invariant": True},
            ),
            ProvedLogicalFact(
                fact_id="forbidden_pattern_matched",
                kind=LogicalFactKind.CONTENT_MATCH,
                claim="The prompt content matches the enclave's forbidden upload pattern.",
                constraint_ids=constraint_ids,
                details={"obstruction_type": obstruction.obstruction_type},
            ),
            ProvedLogicalFact(
                fact_id="pairwise_obstruction",
                kind=LogicalFactKind.PAIRWISE_CONFLICT,
                claim="The policy constraint and prompt-content constraint are jointly inconsistent.",
                constraint_ids=constraint_ids,
                details={"severity": obstruction.severity},
            ),
            ProvedLogicalFact(
                fact_id="enclave_block",
                kind=LogicalFactKind.ENCLAVE_RESOLUTION,
                claim="The enclave blocks the request and routes it for human review.",
                constraint_ids=constraint_ids,
                details={"resolution": verdict.resolution.value},
            ),
        ],
        semantic_annotations=[
            SemanticAnnotation(
                annotation_id="content_hash",
                kind=AnnotationKind.HASH,
                label="content_hash_and_length",
                payload={
                    "content_hash": verdict.content_hash,
                    "content_length": verdict.content_length,
                    "constraint_set_hash": verdict.constraint_set_hash,
                },
            ),
            SemanticAnnotation(
                annotation_id="enclave_payload",
                kind=AnnotationKind.RUNTIME_PAYLOAD,
                label="audit_safe_enclave_verdict",
                payload={
                    "resolution": verdict.resolution.value,
                    "compatibility_status": verdict.compatibility_status,
                    "obstruction_type": obstruction.obstruction_type,
                    "suggested_resolution": obstruction.suggested_resolution,
                },
            ),
        ],
        constraint_ids=constraint_ids,
        variable_bindings={
            "policy_constraint": obstruction.constraint_a_id,
            "prompt_constraint": obstruction.constraint_b_id,
        },
        conflict_class=MiddlewareConflictType.H1_PAIRWISE,
        minimal_conflicting_set=constraint_ids,
        disposition=disposition,
    )


def _build_candor_010_witness(scenario: FCEScenario) -> CoherentWitness:
    runtime_case = scenario.runtime_case
    assert runtime_case is not None
    result = _higher_order_result(scenario)
    obstruction = result.higher_obstructions[0]
    constraint_ids = sorted(constraint.source_id for constraint in obstruction.constraints)

    proved_facts = [
        ProvedLogicalFact(
            fact_id=f"constraint_present_{constraint_id}",
            kind=LogicalFactKind.CONSTRAINT_PRESENT,
            claim=f"The runtime request set includes {constraint_id}.",
            constraint_ids=[constraint_id],
            details={},
        )
        for constraint_id in constraint_ids
    ]
    for left, right in combinations(constraint_ids, 2):
        proved_facts.append(
            ProvedLogicalFact(
                fact_id=f"pairwise_compatible_{left}_{right}",
                kind=LogicalFactKind.PAIRWISE_COMPATIBLE,
                claim=f"{left} and {right} remain pairwise compatible.",
                constraint_ids=[left, right],
                details={"status": "compatible"},
            )
        )
    proved_facts.append(
        ProvedLogicalFact(
            fact_id="higher_order_conflict",
            kind=LogicalFactKind.HIGHER_ORDER_CONFLICT,
            claim="The full triple is jointly unsatisfiable despite pairwise compatibility.",
            constraint_ids=constraint_ids,
            details={"order": obstruction.order, "obstruction_type": obstruction.obstruction_type},
        )
    )

    return CoherentWitness(
        schema_version=COHERENT_WITNESS_SCHEMA_VERSION,
        scenario_id=scenario.scenario_id,
        runtime_mode=runtime_case.mode,
        proved_logical_facts=proved_facts,
        semantic_annotations=[
            SemanticAnnotation(
                annotation_id="higher_order_runtime_payload",
                kind=AnnotationKind.RUNTIME_PAYLOAD,
                label="higher_order_obstruction_witness",
                payload={
                    "witness": obstruction.witness,
                    "severity": obstruction.severity,
                    "status": result.status.value,
                },
            ),
        ],
        constraint_ids=constraint_ids,
        variable_bindings={
            "a": constraint_ids[0],
            "b": constraint_ids[1],
            "c": constraint_ids[2],
        },
        conflict_class=MiddlewareConflictType.H2_HIGHER_ORDER,
        minimal_conflicting_set=constraint_ids,
        disposition=RequiredDisposition.ESCALATE_REQUIRED,
    )


def _build_conf_012_witness(scenario: FCEScenario) -> CoherentWitness:
    runtime_case = scenario.runtime_case
    assert runtime_case is not None
    result = _higher_order_result(scenario)
    constraint_ids = sorted(
        constraint.source_id
        for constraint in _all_constraints(
            runtime_case.build_policy_set(),
            runtime_case.build_request_set(),
        )
    )
    cech_stats = result.cech_complex.stats() if result.cech_complex else {}

    proved_facts = [
        ProvedLogicalFact(
            fact_id=f"constraint_present_{constraint_id}",
            kind=LogicalFactKind.CONSTRAINT_PRESENT,
            claim=f"The runtime set includes {constraint_id}.",
            constraint_ids=[constraint_id],
            details={},
        )
        for constraint_id in constraint_ids
    ]
    proved_facts.append(
        ProvedLogicalFact(
            fact_id="compatible_constraint_set",
            kind=LogicalFactKind.SATISFIABLE_SET,
            claim="The full runtime constraint set remains satisfiable with no H1 or H2 obstruction.",
            constraint_ids=constraint_ids,
            details={
                "status": result.status.value,
                "max_obstruction_order": result.max_obstruction_order,
            },
        )
    )

    return CoherentWitness(
        schema_version=COHERENT_WITNESS_SCHEMA_VERSION,
        scenario_id=scenario.scenario_id,
        runtime_mode=runtime_case.mode,
        proved_logical_facts=proved_facts,
        semantic_annotations=[
            SemanticAnnotation(
                annotation_id="cech_stats",
                kind=AnnotationKind.RUNTIME_PAYLOAD,
                label="cech_complex_stats",
                payload=cech_stats,
            ),
        ],
        constraint_ids=constraint_ids,
        variable_bindings={
            "clearance_guard": "conflicts_cleared",
            "scope_guard": "within_drafting_scope",
            "request": "draft_demand_letter",
        },
        conflict_class=MiddlewareConflictType.NONE,
        minimal_conflicting_set=[],
        disposition=RequiredDisposition.CORRECT_CONTINUE,
    )


def _build_sup_011_witness(scenario: FCEScenario) -> CoherentWitness:
    runtime_case = scenario.runtime_case
    assert runtime_case is not None
    result = _compatibility_result(scenario)
    constraint_ids = sorted(
        constraint.source_id
        for constraint in _all_constraints(
            runtime_case.build_policy_set(),
            runtime_case.build_request_set(),
        )
    )

    proved_facts = [
        ProvedLogicalFact(
            fact_id=f"constraint_present_{constraint_id}",
            kind=LogicalFactKind.CONSTRAINT_PRESENT,
            claim=f"The runtime set includes {constraint_id}.",
            constraint_ids=[constraint_id],
            details={},
        )
        for constraint_id in constraint_ids
    ]
    proved_facts.append(
        ProvedLogicalFact(
            fact_id="compatible_constraint_set",
            kind=LogicalFactKind.SATISFIABLE_SET,
            claim="The intake guardrails and the fact-logging request are pairwise compatible with no H1 obstruction.",
            constraint_ids=constraint_ids,
            details={
                "status": result.status.value,
                "obstruction_count": len(result.obstructions),
            },
        )
    )

    return CoherentWitness(
        schema_version=COHERENT_WITNESS_SCHEMA_VERSION,
        scenario_id=scenario.scenario_id,
        runtime_mode=runtime_case.mode,
        proved_logical_facts=proved_facts,
        semantic_annotations=[
            SemanticAnnotation(
                annotation_id="compatibility_runtime_payload",
                kind=AnnotationKind.RUNTIME_PAYLOAD,
                label="compatibility_standdown_witness",
                payload={
                    "status": result.status.value,
                    "obstruction_count": len(result.obstructions),
                    "narrowed_count": len(result.narrowed_constraints),
                    "unknown_count": len(result.unknown_constraints),
                },
            ),
        ],
        constraint_ids=constraint_ids,
        variable_bindings={
            "scope_guard": "intake_scope_guardrail",
            "advice_guard": "no_individualized_legal_advice",
            "request": "log_intake_facts",
        },
        conflict_class=MiddlewareConflictType.NONE,
        minimal_conflicting_set=[],
        disposition=RequiredDisposition.CORRECT_CONTINUE,
    )


def _build_comp_013_witness(scenario: FCEScenario) -> CoherentWitness:
    runtime_case = scenario.runtime_case
    assert runtime_case is not None
    result = _higher_order_result(scenario)
    constraint_ids = sorted(
        constraint.source_id
        for constraint in _all_constraints(
            runtime_case.build_policy_set(),
            runtime_case.build_request_set(),
        )
    )
    cech_stats = result.cech_complex.stats() if result.cech_complex else {}

    proved_facts = [
        ProvedLogicalFact(
            fact_id=f"constraint_present_{constraint_id}",
            kind=LogicalFactKind.CONSTRAINT_PRESENT,
            claim=f"The runtime set includes {constraint_id}.",
            constraint_ids=[constraint_id],
            details={},
        )
        for constraint_id in constraint_ids
    ]
    proved_facts.append(
        ProvedLogicalFact(
            fact_id="compatible_constraint_set",
            kind=LogicalFactKind.SATISFIABLE_SET,
            claim="The full runtime constraint set remains satisfiable with no H1 or H2 obstruction.",
            constraint_ids=constraint_ids,
            details={
                "status": result.status.value,
                "max_obstruction_order": result.max_obstruction_order,
            },
        )
    )

    return CoherentWitness(
        schema_version=COHERENT_WITNESS_SCHEMA_VERSION,
        scenario_id=scenario.scenario_id,
        runtime_mode=runtime_case.mode,
        proved_logical_facts=proved_facts,
        semantic_annotations=[
            SemanticAnnotation(
                annotation_id="cech_stats",
                kind=AnnotationKind.RUNTIME_PAYLOAD,
                label="cech_complex_stats",
                payload=cech_stats,
            ),
        ],
        constraint_ids=constraint_ids,
        variable_bindings={
            "scope_guard": "research_scope_guardrail",
            "filing_guard": "not_filing_ready",
            "request": "summarize_public_statutes",
        },
        conflict_class=MiddlewareConflictType.NONE,
        minimal_conflicting_set=[],
        disposition=RequiredDisposition.CORRECT_CONTINUE,
    )


def _validate_candor_003_runtime(
    failures: list[str],
    witness: CoherentWitness,
    scenario: FCEScenario,
) -> tuple[MiddlewareConflictType, RequiredDisposition, list[str], list[str]]:
    result = _compatibility_result(scenario)
    if not result.obstructions:
        failures.append("expected an H1 obstruction but runtime found none")
        return (
            MiddlewareConflictType.H1_PAIRWISE,
            RequiredDisposition.REFUSE_REQUIRED,
            [],
            [],
        )
    if result.unknown_constraints:
        failures.append("compatibility refuse case should not depend on unknown constraints")
    obstruction = result.obstructions[0]
    if obstruction.obstruction_type != "required_pattern_is_forbidden":
        failures.append(
            f"unexpected obstruction_type for refuse proof: {obstruction.obstruction_type}"
        )
    expected_constraints = [obstruction.constraint_a.source_id, obstruction.constraint_b.source_id]
    return (
        MiddlewareConflictType.H1_PAIRWISE,
        RequiredDisposition.REFUSE_REQUIRED,
        expected_constraints,
        expected_constraints,
    )


def _validate_conf_002_runtime(
    failures: list[str],
    witness: CoherentWitness,
    scenario: FCEScenario,
) -> tuple[MiddlewareConflictType, RequiredDisposition, list[str], list[str]]:
    runtime_case = scenario.runtime_case
    assert runtime_case is not None
    verdict = check_in_enclave(
        prompt=runtime_case.prompt or "",
        constraint_set=runtime_case.build_policy_set(),
        escalate_soft=runtime_case.escalate_soft,
    )
    if verdict.resolution != EnclaveResolution.BLOCK:
        failures.append(f"expected enclave block, got {verdict.resolution.value}")
    if not verdict.obstruction_witnesses:
        failures.append("enclave returned no obstruction witnesses")
        return (
            MiddlewareConflictType.H1_PAIRWISE,
            _derive_enclave_disposition(scenario),
            [],
            [],
        )
    obstruction = _select_enclave_obstruction(verdict.obstruction_witnesses)
    expected_constraints = [obstruction.constraint_a_id, obstruction.constraint_b_id]
    if obstruction.obstruction_type != "prompt_contains_forbidden_content":
        failures.append(
            f"unexpected obstruction_type for H1 proof: {obstruction.obstruction_type}"
        )
    return (
        MiddlewareConflictType.H1_PAIRWISE,
        _derive_enclave_disposition(scenario),
        expected_constraints,
        expected_constraints,
    )


def _validate_candor_010_runtime(
    failures: list[str],
    witness: CoherentWitness,
    scenario: FCEScenario,
) -> tuple[MiddlewareConflictType, RequiredDisposition, list[str], list[str]]:
    result = _higher_order_result(scenario)
    if not result.higher_obstructions:
        failures.append("expected an H2 obstruction but runtime found none")
        return (
            MiddlewareConflictType.H2_HIGHER_ORDER,
            RequiredDisposition.ESCALATE_REQUIRED,
            [],
            [],
        )
    obstruction = result.higher_obstructions[0]
    if obstruction.order != 2:
        failures.append(f"expected H2 obstruction, got H{obstruction.order}")
    expected_constraints = sorted(constraint.source_id for constraint in obstruction.constraints)
    runtime_case = scenario.runtime_case
    assert runtime_case is not None
    all_constraints = list(_all_constraints(runtime_case.build_policy_set(), runtime_case.build_request_set()))
    for left, right in combinations(all_constraints, 2):
        pair_result = check_compatibility(
            ConstraintSet(constraints={left}),
            ConstraintSet(constraints={right}),
        )
        if pair_result.status.value == "contradictory":
            failures.append(
                f"pairwise contradiction found for {left.source_id}/{right.source_id}; not a clean H2 case"
            )
    return (
        MiddlewareConflictType.H2_HIGHER_ORDER,
        RequiredDisposition.ESCALATE_REQUIRED,
        expected_constraints,
        expected_constraints,
    )


def _validate_conf_012_runtime(
    failures: list[str],
    witness: CoherentWitness,
    scenario: FCEScenario,
) -> tuple[MiddlewareConflictType, RequiredDisposition, list[str], list[str]]:
    result = _higher_order_result(scenario)
    if result.obstructions:
        failures.append("expected no H1 obstruction for stand-down case")
    if result.higher_obstructions:
        failures.append("expected no higher-order obstruction for stand-down case")
    if result.unknown_constraints:
        failures.append("stand-down case still has unknown constraints")
    runtime_case = scenario.runtime_case
    assert runtime_case is not None
    expected_constraints = sorted(
        constraint.source_id
        for constraint in _all_constraints(
            runtime_case.build_policy_set(),
            runtime_case.build_request_set(),
        )
    )
    return (
        MiddlewareConflictType.NONE,
        RequiredDisposition.CORRECT_CONTINUE,
        expected_constraints,
        [],
    )


def _validate_sup_011_runtime(
    failures: list[str],
    witness: CoherentWitness,
    scenario: FCEScenario,
) -> tuple[MiddlewareConflictType, RequiredDisposition, list[str], list[str]]:
    result = _compatibility_result(scenario)
    if result.obstructions:
        failures.append("expected no H1 obstruction for compatibility stand-down case")
    if result.unknown_constraints:
        failures.append("compatibility stand-down case still has unknown constraints")
    runtime_case = scenario.runtime_case
    assert runtime_case is not None
    expected_constraints = sorted(
        constraint.source_id
        for constraint in _all_constraints(
            runtime_case.build_policy_set(),
            runtime_case.build_request_set(),
        )
    )
    return (
        MiddlewareConflictType.NONE,
        RequiredDisposition.CORRECT_CONTINUE,
        expected_constraints,
        [],
    )


def _validate_comp_013_runtime(
    failures: list[str],
    witness: CoherentWitness,
    scenario: FCEScenario,
) -> tuple[MiddlewareConflictType, RequiredDisposition, list[str], list[str]]:
    result = _higher_order_result(scenario)
    if result.obstructions:
        failures.append("expected no H1 obstruction for stand-down case")
    if result.higher_obstructions:
        failures.append("expected no higher-order obstruction for stand-down case")
    if result.unknown_constraints:
        failures.append("stand-down case still has unknown constraints")
    runtime_case = scenario.runtime_case
    assert runtime_case is not None
    expected_constraints = sorted(
        constraint.source_id
        for constraint in _all_constraints(
            runtime_case.build_policy_set(),
            runtime_case.build_request_set(),
        )
    )
    return (
        MiddlewareConflictType.NONE,
        RequiredDisposition.CORRECT_CONTINUE,
        expected_constraints,
        [],
    )


def _higher_order_result(scenario: FCEScenario):
    runtime_case = scenario.runtime_case
    assert runtime_case is not None
    result = check_compatibility_with_higher_orders(
        runtime_case.build_policy_set(),
        runtime_case.build_request_set(),
        max_order=runtime_case.max_order,
    )
    if not result.higher_obstructions:
        merged = runtime_case.build_policy_set() | runtime_case.build_request_set()
        cech = build_cech_complex(merged)
        result.cech_complex = cech
        result.higher_obstructions = detect_h2_obstructions(merged, cech)
    return result


def _compatibility_result(scenario: FCEScenario):
    runtime_case = scenario.runtime_case
    assert runtime_case is not None
    return check_compatibility(
        runtime_case.build_policy_set(),
        runtime_case.build_request_set(),
    )


def _derive_enclave_disposition(scenario: FCEScenario) -> RequiredDisposition:
    runtime_case = scenario.runtime_case
    assert runtime_case is not None
    has_soul = any(constraint.is_soul_invariant for constraint in runtime_case.policy_constraints)
    return (
        RequiredDisposition.ESCALATE_REQUIRED
        if has_soul
        else RequiredDisposition.REFUSE_REQUIRED
    )


def _require_fact_kinds(
    witness: CoherentWitness,
    failures: list[str],
    required_kinds: Sequence[LogicalFactKind],
) -> None:
    actual_kinds = {fact.kind for fact in witness.proved_logical_facts}
    for kind in required_kinds:
        if kind not in actual_kinds:
            failures.append(f"missing proved logical fact kind: {kind.value}")


def _fact_ids(facts: Iterable[ProvedLogicalFact]) -> list[str]:
    return [fact.fact_id for fact in facts]


def _all_constraints(*constraint_sets: ConstraintSet):
    constraints = set()
    for constraint_set in constraint_sets:
        constraints.update(constraint_set.constraints)
    return constraints


def _select_enclave_obstruction(obstructions):
    for obstruction in obstructions:
        if obstruction.obstruction_type == "prompt_contains_forbidden_content":
            return obstruction
    return obstructions[0]
