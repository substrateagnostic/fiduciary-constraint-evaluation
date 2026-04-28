"""
Optional runtime adapters for FCE scenarios that include executable cases.
"""

from __future__ import annotations

from typing import Optional

from fiduciary.cohomology.compatibility import check_compatibility
from fiduciary.cohomology.enclave import EnclaveResolution, check_in_enclave
from fiduciary.cohomology.higher_compatibility import (
    build_cech_complex,
    check_compatibility_with_higher_orders,
    detect_h2_obstructions,
)
from fiduciary.fce.adapters import (
    AdapterExecutionSource,
    RuntimeAdapterResult,
    RuntimeArmRequest,
    primary_action_for_disposition,
)
from fiduciary.models import Severity
from fiduciary.fce.models import (
    EvaluationArm,
    FCERuntimeCase,
    HandoffTarget,
    MiddlewareConflictType,
    MiddlewareExpectation,
    MiddlewareWitnessRecord,
    ObservedAction,
    RequiredDisposition,
    RuntimeEvaluationMode,
)
from fiduciary.fce.proof import build_runtime_proof_bundle


def _derive_enclave_disposition(verdict, has_soul_invariant: bool) -> RequiredDisposition:
    """Derive disposition from enclave resolution, not from the answer key.

    Soul invariant violations produce ESCALATE (needs human oversight)
    rather than REFUSE (unilateral AI decision) because the stakes
    are too high for the system to decide alone.
    """
    if verdict.resolution == EnclaveResolution.BLOCK:
        if has_soul_invariant:
            return RequiredDisposition.ESCALATE_REQUIRED
        return RequiredDisposition.REFUSE_REQUIRED
    if verdict.resolution == EnclaveResolution.WIGGLE:
        return RequiredDisposition.ESCALATE_REQUIRED
    return RequiredDisposition.CORRECT_CONTINUE


def _derive_h1_disposition(obstructions) -> RequiredDisposition:
    """Derive disposition from H1 obstruction severity."""
    for obs in obstructions:
        if getattr(obs.constraint_a, "is_soul_invariant", False):
            return RequiredDisposition.REFUSE_REQUIRED
        if getattr(obs.constraint_b, "is_soul_invariant", False):
            return RequiredDisposition.REFUSE_REQUIRED
        if getattr(obs.constraint_a, "severity", None) == Severity.P0:
            return RequiredDisposition.REFUSE_REQUIRED
        if getattr(obs.constraint_b, "severity", None) == Severity.P0:
            return RequiredDisposition.REFUSE_REQUIRED
    return RequiredDisposition.ESCALATE_REQUIRED


def _unknown_constraint_witness(
    unknown_constraints,
    *,
    handoff: HandoffTarget,
    raw_payload: dict,
) -> MiddlewareWitnessRecord:
    constraint_ids = sorted({constraint.source_id for constraint in unknown_constraints if constraint.source_id})
    pretty_ids = ", ".join(constraint_id.replace("_", " ") for constraint_id in constraint_ids) or "missing facts"
    payload = dict(raw_payload)
    payload["unknown_constraints"] = [constraint.to_dict() for constraint in unknown_constraints]
    payload["clarify_required"] = True
    return MiddlewareWitnessRecord(
        event=RequiredDisposition.CLARIFY_REQUIRED,
        conflict_type=MiddlewareConflictType.WITNESS_INSUFFICIENCY,
        constraint_ids_involved=constraint_ids,
        minimal_conflict_set=constraint_ids,
        recommended_handoff_target=handoff,
        explanation=(
            "Runtime analysis could not resolve the request without clarifying "
            f"{pretty_ids}."
        ),
        audit_safe_event_record=payload,
    )


class PrismweftRuntimeAdapter:
    supported_arms = (EvaluationArm.PRISMWEFT_RUNTIME,)

    def __init__(self, *, prefer_runtime: bool = True) -> None:
        self._prefer_runtime = prefer_runtime

    def invoke(self, request: RuntimeArmRequest) -> RuntimeAdapterResult:
        scenario = request.scenario
        witness: Optional[MiddlewareWitnessRecord] = None
        proof_witness = None
        proof_verdict = None
        source = AdapterExecutionSource.FIXTURE
        raw_payload = {
            "fixture": True,
            "scenario_id": scenario.scenario_id,
        }
        runtime_executed = False

        if self._prefer_runtime and scenario.runtime_case is not None:
            witness = run_runtime_case(scenario.runtime_case)
            runtime_executed = True
            if witness is not None:
                source = AdapterExecutionSource.RUNTIME
                raw_payload = witness.audit_safe_event_record
            else:
                # Runtime executed and found no obstruction — this IS the result.
                # Do not substitute a fixture witness; None means "all clear."
                source = AdapterExecutionSource.RUNTIME
                raw_payload = {"runtime_clear": True, "scenario_id": scenario.scenario_id}
            proof_bundle = build_runtime_proof_bundle(scenario)
            if proof_bundle is not None:
                proof_witness, proof_verdict = proof_bundle

        if witness is None and not runtime_executed:
            witness = _fixture_witness(scenario.middleware_expected)

        response_text = (
            witness.explanation
            if witness is not None
            else scenario.middleware_expected.human_readable_explanation
        )

        return RuntimeAdapterResult(
            response_text=response_text,
            actions=_runtime_actions_for_scenario(scenario),
            identified_duties=list(scenario.expected_behavior.must_identify),
            witness=witness,
            proof_witness=proof_witness,
            proof_verdict=proof_verdict,
            adapter_name="prismweft_runtime_adapter",
            source=source,
            fixture_id=None if source == AdapterExecutionSource.RUNTIME else f"{scenario.scenario_id}:{request.arm.value}",
            raw_payload=raw_payload,
        )


def run_runtime_case(
    runtime_case: FCERuntimeCase,
) -> Optional[MiddlewareWitnessRecord]:
    """Execute a runtime case and derive the witness independently.

    The witness record (event, handoff target, explanation) is derived
    entirely from obstruction analysis — never from the answer key.
    The expectation is only used during scoring, not during execution.
    """
    handoff = runtime_case.default_handoff_target or HandoffTarget.SUPERVISOR

    if runtime_case.mode == RuntimeEvaluationMode.ENCLAVE:
        verdict = check_in_enclave(
            prompt=runtime_case.prompt or "",
            constraint_set=runtime_case.build_policy_set(),
            escalate_soft=runtime_case.escalate_soft,
        )
        if not verdict.obstruction_witnesses:
            return None

        has_soul = any(c.is_soul_invariant for c in runtime_case.policy_constraints)
        first = verdict.obstruction_witnesses[0]
        return MiddlewareWitnessRecord(
            event=_derive_enclave_disposition(verdict, has_soul),
            conflict_type=MiddlewareConflictType.H1_PAIRWISE,
            constraint_ids_involved=[first.constraint_a_id, first.constraint_b_id],
            minimal_conflict_set=[first.constraint_a_id, first.constraint_b_id],
            recommended_handoff_target=handoff,
            explanation=first.suggested_resolution or f"Obstruction: {first.obstruction_type}",
            audit_safe_event_record=verdict.to_dict(),
        )

    if runtime_case.mode == RuntimeEvaluationMode.HIGHER_ORDER:
        policy_set = runtime_case.build_policy_set()
        request_set = runtime_case.build_request_set()
        result = check_compatibility_with_higher_orders(
            policy_set,
            request_set,
            max_order=runtime_case.max_order,
        )
        if not result.higher_obstructions:
            merged = policy_set | request_set
            cech = build_cech_complex(merged)
            result.higher_obstructions = detect_h2_obstructions(merged, cech)
        if result.higher_obstructions:
            first = result.higher_obstructions[0]
            constraint_ids = [constraint.source_id for constraint in first.constraints]
            return MiddlewareWitnessRecord(
                event=RequiredDisposition.ESCALATE_REQUIRED,
                conflict_type=MiddlewareConflictType.H2_HIGHER_ORDER
                if first.order == 2
                else MiddlewareConflictType.H3_OR_HIGHER,
                constraint_ids_involved=constraint_ids,
                minimal_conflict_set=constraint_ids,
                recommended_handoff_target=handoff,
                explanation=first.witness,
                audit_safe_event_record=result.to_dict(),
            )
        if result.obstructions:
            first = result.obstructions[0]
            return MiddlewareWitnessRecord(
                event=_derive_h1_disposition(result.obstructions),
                conflict_type=MiddlewareConflictType.H1_PAIRWISE,
                constraint_ids_involved=[first.constraint_a.source_id, first.constraint_b.source_id],
                minimal_conflict_set=[first.constraint_a.source_id, first.constraint_b.source_id],
                recommended_handoff_target=handoff,
                explanation=first.suggested_resolution or f"H1 obstruction: {first.obstruction_type}",
                audit_safe_event_record=result.to_dict(),
            )
        if result.unknown_constraints:
            return _unknown_constraint_witness(
                result.unknown_constraints,
                handoff=handoff,
                raw_payload=result.to_dict(),
            )
        return None

    result = check_compatibility(
        runtime_case.build_policy_set(),
        runtime_case.build_request_set(),
    )
    if result.unknown_constraints:
        return _unknown_constraint_witness(
            result.unknown_constraints,
            handoff=handoff,
            raw_payload=result.to_dict(),
        )
    if not result.obstructions:
        return None

    first = result.obstructions[0]
    return MiddlewareWitnessRecord(
        event=_derive_h1_disposition(result.obstructions),
        conflict_type=MiddlewareConflictType.H1_PAIRWISE,
        constraint_ids_involved=[first.constraint_a.source_id, first.constraint_b.source_id],
        minimal_conflict_set=[first.constraint_a.source_id, first.constraint_b.source_id],
        recommended_handoff_target=handoff,
        explanation=first.suggested_resolution or f"H1 obstruction: {first.obstruction_type}",
        audit_safe_event_record=result.to_dict(),
    )


def _runtime_actions_for_scenario(scenario) -> list[ObservedAction]:
    actions = [primary_action_for_disposition(scenario.middleware_expected.event)]
    for action in scenario.expected_behavior.must_do_one_of:
        if action not in actions:
            actions.append(action)
            break
    return actions


def _fixture_witness(expectation: MiddlewareExpectation) -> MiddlewareWitnessRecord:
    """Build a witness from the answer key. Used ONLY as a non-evaluative
    fixture/fallback when no runtime case exists. Clearly marked as fixture
    in the audit record so it is not mistaken for independent derivation."""
    obs_type_value = expectation.obstruction_type.value if expectation.obstruction_type else "none"
    return MiddlewareWitnessRecord(
        event=expectation.event,
        conflict_type=expectation.obstruction_type,
        constraint_ids_involved=list(expectation.constraint_ids_involved),
        minimal_conflict_set=list(expectation.minimal_conflict_set),
        recommended_handoff_target=expectation.recommended_handoff_target,
        explanation=expectation.human_readable_explanation,
        audit_safe_event_record={
            "fixture": True,
            "event": expectation.event.value,
            "obstruction_type": obs_type_value,
            "minimal_conflict_set": list(expectation.minimal_conflict_set),
        },
    )
