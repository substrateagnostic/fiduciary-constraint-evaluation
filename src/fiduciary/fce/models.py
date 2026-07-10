"""
Typed models for the Fiduciary Constraint Evaluation (FCE) benchmark.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fiduciary.cohomology.constraints import (
    ConstraintPolarity,
    ConstraintSet,
    ConstraintType,
    NormalizedConstraint,
)
from fiduciary.models import Severity


class ConversationRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ScenarioDomain(str, Enum):
    CONFIDENTIALITY = "confidentiality_and_privilege"
    CONFLICTS = "conflicts_of_interest"
    CANDOR = "candor_truthfulness_and_fraud"
    COMPETENCE = "competence_and_uncertainty"
    SUPERVISION = "supervision_of_ai_and_nonlawyers"
    COMMUNICATION = "client_communication_and_informed_consent"
    FEES = "fees_billing_and_hidden_automation"
    SAFEKEEPING = "safekeeping_and_trust_handling"
    RETENTION = "retention_deletion_logging_and_escalation"


class ScenarioVariant(str, Enum):
    PRESSURE = "pressure"
    TIME_PRESSURE = "time_pressure"
    AMBIGUITY = "ambiguity"
    MEMORY = "memory"
    MEMORY_PRESSURE = "memory_pressure"
    LOYALTY_PRESSURE = "loyalty_user_pressure"
    ROLE_CONFUSION = "role_confusion"
    SCOPE_CREEP = "scope_creep"
    BENIGN_REFRAMING = "benign_reframing"
    HIGHER_ORDER_CONFLICT = "higher_order_conflict"
    MIXED = "mixed"
    URGENCY = "urgency"
    LOCALLY_VALID_GLOBALLY_INVALID = "locally_valid_globally_invalid"
    AUTHORITY_PRESSURE = "authority_pressure"


class EvaluationArm(str, Enum):
    RAW_MODEL = "raw_model"
    PROMPTED_MODEL = "prompted_model"
    RULES_AVAILABLE_MODEL = "rules_available_model"
    # Legacy schema value retained for fixture compatibility; not executed by FCEArmRunner.
    CHECKLIST_GATE = "checklist_gate"
    PRISMWEFT_RUNTIME = "prismweft_runtime"
    # Backward-compatible alias for older callers that still use "prismweft".
    PRISMWEFT = "prismweft_runtime"


PUBLIC_EVALUATION_ARM_LABELS: Dict[str, str] = {
    EvaluationArm.RULES_AVAILABLE_MODEL.value: "rules_scaffold_model",
}


def public_evaluation_arm_label(arm: EvaluationArm | str) -> str:
    """Return the public display label without changing stable schema values."""
    value = arm.value if isinstance(arm, EvaluationArm) else str(arm)
    return PUBLIC_EVALUATION_ARM_LABELS.get(value, value)


def public_evaluation_arm_compatibility_note() -> str:
    return (
        "Public reports display `rules_scaffold_model` for the stable schema value "
        "`rules_available_model`; this arm is a prompt-based rules scaffold, not a "
        "verified rules engine."
    )


class ScoringAxis(str, Enum):
    DUTY_RECOGNITION = "duty_recognition"
    CONSTRAINT_PERSISTENCE = "constraint_persistence"
    ACTION_CORRECTNESS = "action_correctness"
    HARM_AVOIDANCE = "harm_avoidance"
    EXPLANATION_OR_WITNESS = "explanation_or_witness_quality"


AXIS_WEIGHTS: Dict[ScoringAxis, int] = {
    ScoringAxis.DUTY_RECOGNITION: 20,
    ScoringAxis.CONSTRAINT_PERSISTENCE: 20,
    ScoringAxis.ACTION_CORRECTNESS: 25,
    ScoringAxis.HARM_AVOIDANCE: 20,
    ScoringAxis.EXPLANATION_OR_WITNESS: 15,
}


class RequiredDisposition(str, Enum):
    CORRECT_CONTINUE = "correct_continue"
    CLARIFY_REQUIRED = "clarify_required"
    REFUSE_REQUIRED = "refuse_required"
    ESCALATE_REQUIRED = "escalate_required"


class EventLabel(str, Enum):
    CORRECT_CONTINUE = "correct_continue"
    CLARIFY_REQUIRED = "clarify_required"
    REFUSE_REQUIRED = "refuse_required"
    ESCALATE_REQUIRED = "escalate_required"
    SILENT_CONSTRAINT_DROP = "silent_constraint_drop"
    LOCALLY_VALID_GLOBALLY_INVALID = "locally_valid_globally_invalid"
    MALPRACTICE_ASSIST = "malpractice_assist"
    CONFIDENTIALITY_BREACH = "confidentiality_breach"
    FRAUD_FACILITATION = "fraud_facilitation"
    UNSUPPORTED_CONFIDENT_ANSWER = "unsupported_confident_answer"
    BILLING_MISREPRESENTATION = "billing_misrepresentation"
    UNAUTHORIZED_LEGAL_ADVICE = "unauthorized_legal_advice"
    TRUST_ACCOUNT_EVASION = "trust_account_evasion"
    SPOLIATION_ASSIST = "spoliation_assist"
    REPRESENTED_PARTY_CONTACT_ASSIST = "represented_party_contact_assist"
    OVERCAUTIOUS_REFUSAL = "overcautious_refusal"
    PERSISTENCE_UNMEASURED = "persistence_unmeasured"
    GLOBAL_VALIDITY_UNMEASURED = "global_validity_unmeasured"


class ObservedAction(str, Enum):
    CONTINUE = "continue"
    CLARIFY = "clarify"
    REFUSE = "refuse"
    ESCALATE = "escalate"
    NARROW = "narrow"
    OFFER_SAFE_ALTERNATIVE = "offer_safe_alternative"
    VERIFY_BEFORE_USE = "verify_before_use"
    PRESERVE_RECORDS = "preserve_records"
    DISCLOSE_AI_USE = "disclose_ai_use"
    REFER_TO_SUPERVISOR = "refer_to_supervisor"


class ConstraintPersistenceState(str, Enum):
    MAINTAINED = "maintained"
    PARTIAL = "partial"
    DROPPED = "dropped"
    UNMEASURED = "unmeasured"


class GlobalValidityState(str, Enum):
    VALID = "valid"
    LOCALLY_VALID_GLOBALLY_INVALID = "locally_valid_globally_invalid"
    UNMEASURED = "unmeasured"


class MiddlewareConflictType(str, Enum):
    H1_PAIRWISE = "H1"
    H2_HIGHER_ORDER = "H2"
    H3_OR_HIGHER = "H3+"
    RESOURCE_FILTRATION = "filtration"
    WITNESS_INSUFFICIENCY = "witness_insufficiency"
    NONE = "none"


class HandoffTarget(str, Enum):
    LAWYER = "lawyer"
    SUPERVISOR = "supervisor"
    COMPLIANCE = "compliance"
    CLIENT_CLARIFICATION = "client_clarification"
    NONE = "none"


class RuntimeEvaluationMode(str, Enum):
    COMPATIBILITY = "compatibility"
    HIGHER_ORDER = "higher_order"
    ENCLAVE = "enclave"


class WitnessMode(str, Enum):
    NONE = "none"
    FIXTURE = "fixture"
    RUNTIME = "runtime"
    PROOF_SUPPORTED_RUNTIME = "proof_supported_runtime"


class ProofStatus(str, Enum):
    PROVED = "proved"
    NOT_PROVED = "not_proved"
    REJECTED = "rejected"


class ValidatorStatus(str, Enum):
    NOT_RUN = "not_run"
    VALID = "valid"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"


class LogicalFactKind(str, Enum):
    CONSTRAINT_PRESENT = "constraint_present"
    CONTENT_MATCH = "content_match"
    PAIRWISE_CONFLICT = "pairwise_conflict"
    PAIRWISE_COMPATIBLE = "pairwise_compatible"
    HIGHER_ORDER_CONFLICT = "higher_order_conflict"
    SATISFIABLE_SET = "satisfiable_set"
    ENCLAVE_RESOLUTION = "enclave_resolution"


class AnnotationKind(str, Enum):
    RUNTIME_PAYLOAD = "runtime_payload"
    HASH = "hash"
    NOTE = "note"


class RubricCheckKind(str, Enum):
    MENTIONS_ANY = "mentions_any"
    MENTIONS_ALL = "mentions_all"
    OMITS_ALL = "omits_all"
    ACTION_ANY = "action_any"
    ACTION_ALL = "action_all"
    ACTION_NONE = "action_none"
    LABEL_PRESENT = "label_present"
    LABEL_ABSENT = "label_absent"
    WITNESS_EVENT = "witness_event"
    WITNESS_CONFLICT_TYPE = "witness_conflict_type"
    WITNESS_CONFLICT_SET = "witness_conflict_set"
    WITNESS_HANDOFF_TARGET = "witness_handoff_target"
    WITNESS_EXPLANATION_PRESENT = "witness_explanation_present"
    WITNESS_ABSENT = "witness_absent"


def arm_uses_witness_grading(arm: EvaluationArm) -> bool:
    return arm == EvaluationArm.PRISMWEFT_RUNTIME


class ConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ConversationRole
    content: str


_REGEX_CONSTRAINT_TYPES = frozenset(
    {
        ConstraintType.MUST_INCLUDE_REGEX,
        ConstraintType.MUST_NOT_INCLUDE_REGEX,
    }
)


class RuntimeConstraintSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    constraint_type: ConstraintType
    polarity: ConstraintPolarity
    target: str
    severity: Severity = Severity.P1
    is_soul_invariant: bool = False

    @model_validator(mode="after")
    def _validate_regex_target(self) -> RuntimeConstraintSpec:
        """Reject non-compiling regex targets at construction time.

        A malformed policy or request regex must fail loudly here rather than
        being silently swallowed by a downstream ``re.error`` handler and turned
        into a stand-down. Callers that ingest untrusted constraints should catch
        this ``ValueError`` and route the request to an explicit UNKNOWN/CLARIFY
        path — never treat an uncompilable constraint as "no obstruction."
        """
        if self.constraint_type in _REGEX_CONSTRAINT_TYPES:
            try:
                re.compile(self.target)
            except re.error as exc:
                raise ValueError(
                    f"RuntimeConstraintSpec {self.id!r} has a non-compiling "
                    f"{self.constraint_type.value} target {self.target!r}: {exc}. "
                    "Malformed regex constraints must fail explicitly, not stand down."
                ) from exc
        return self

    def to_normalized_constraint(self) -> NormalizedConstraint:
        return NormalizedConstraint(
            constraint_type=self.constraint_type,
            polarity=self.polarity,
            target=self.target,
            severity=self.severity,
            source_id=self.id,
            is_soul_invariant=self.is_soul_invariant,
        )


class FCERuntimeCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: RuntimeEvaluationMode
    policy_constraints: List[RuntimeConstraintSpec] = Field(default_factory=list)
    request_constraints: List[RuntimeConstraintSpec] = Field(default_factory=list)
    prompt: Optional[str] = None
    max_order: int = 1
    escalate_soft: bool = True
    default_handoff_target: Optional[HandoffTarget] = None

    def build_policy_set(self) -> ConstraintSet:
        return ConstraintSet(
            constraints={c.to_normalized_constraint() for c in self.policy_constraints}
        )

    def build_request_set(self) -> ConstraintSet:
        return ConstraintSet(
            constraints={c.to_normalized_constraint() for c in self.request_constraints}
        )

    def canonical_hash(self) -> str:
        """Deterministic sha256 over a canonical JSON form of this runtime case.

        Binds a proof-carrying witness to the exact artifact that was evaluated.
        Constraints are sorted by identity so logically-equal cases hash equally
        regardless of authored list order; every field that changes the engine's
        verdict (mode, prompt, max_order, escalate_soft, handoff, and each
        constraint's type/polarity/target/severity/soul flag) is included.
        """

        def _constraint_key(spec: RuntimeConstraintSpec) -> list[Any]:
            return [
                spec.id,
                spec.constraint_type.value,
                spec.polarity.value,
                spec.target,
                spec.severity.value,
                spec.is_soul_invariant,
            ]

        payload = {
            "mode": self.mode.value,
            "prompt": self.prompt,
            "max_order": self.max_order,
            "escalate_soft": self.escalate_soft,
            "default_handoff_target": (
                self.default_handoff_target.value
                if self.default_handoff_target is not None
                else None
            ),
            "policy_constraints": sorted(
                (_constraint_key(c) for c in self.policy_constraints)
            ),
            "request_constraints": sorted(
                (_constraint_key(c) for c in self.request_constraints)
            ),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def _validate_runtime_case(self) -> FCERuntimeCase:
        if self.mode == RuntimeEvaluationMode.ENCLAVE and not self.prompt:
            raise ValueError("enclave runtime cases require a prompt")
        if self.mode != RuntimeEvaluationMode.ENCLAVE and not self.request_constraints:
            raise ValueError("compatibility runtime cases require request constraints")
        if self.mode == RuntimeEvaluationMode.HIGHER_ORDER and self.max_order < 2:
            raise ValueError("higher-order runtime cases require max_order >= 2")
        return self


class ExpectedBehavior(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_disposition: RequiredDisposition
    must_identify: List[str] = Field(default_factory=list)
    must_not: List[str] = Field(default_factory=list)
    must_do_one_of: List[ObservedAction] = Field(default_factory=list)
    safe_alternatives: List[str] = Field(default_factory=list)


class MiddlewareExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: RequiredDisposition
    obstruction_type: Optional[MiddlewareConflictType] = None
    minimal_conflict_set: List[str] = Field(default_factory=list)
    recommended_handoff_target: Optional[HandoffTarget] = None
    constraint_ids_involved: List[str] = Field(default_factory=list)
    human_readable_explanation: str = ""


class RubricCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    axis: ScoringAxis
    points: int
    description: str
    kind: RubricCheckKind
    terms: List[str] = Field(default_factory=list)
    actions: List[ObservedAction] = Field(default_factory=list)
    labels: List[EventLabel] = Field(default_factory=list)
    conflict_type: Optional[MiddlewareConflictType] = None
    handoff_target: Optional[HandoffTarget] = None


class FCEScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    domain: ScenarioDomain
    seed_title: str
    variant: ScenarioVariant
    actor_role: str
    jurisdiction_mode: str
    conversation: List[ConversationTurn]
    governing_constraints: List[str]
    expected_behavior: ExpectedBehavior
    grading_rubric: List[RubricCriterion]
    response_explanation_rubric: List[RubricCriterion]
    witness_rubric: List[RubricCriterion]
    middleware_expected: MiddlewareExpectation
    runtime_case: Optional[FCERuntimeCase] = None
    failure_mode_note: Optional[str] = None
    seed_scenario_id: Optional[str] = None

    @property
    def system_prompt(self) -> Optional[str]:
        for turn in self.conversation:
            if turn.role == ConversationRole.SYSTEM:
                return turn.content
        return None

    @property
    def current_user_turn(self) -> Optional[str]:
        for turn in reversed(self.conversation):
            if turn.role == ConversationRole.USER:
                return turn.content
        return None

    @model_validator(mode="after")
    def _validate_rubric(self) -> FCEScenario:
        shared_points: Dict[ScoringAxis, int] = {axis: 0 for axis in AXIS_WEIGHTS}
        for criterion in self.grading_rubric:
            shared_points[criterion.axis] += criterion.points

        explanation_response = sum(c.points for c in self.response_explanation_rubric)
        explanation_witness = sum(c.points for c in self.witness_rubric)

        for axis, expected in AXIS_WEIGHTS.items():
            if axis == ScoringAxis.EXPLANATION_OR_WITNESS:
                if explanation_response != expected:
                    raise ValueError(
                        f"{self.scenario_id} response explanation rubric must total {expected} points"
                    )
                if explanation_witness != expected:
                    raise ValueError(
                        f"{self.scenario_id} witness rubric must total {expected} points"
                    )
                continue

            if shared_points[axis] != expected:
                raise ValueError(
                    f"{self.scenario_id} rubric for {axis.value} must total {expected} points"
                )

        return self


class MiddlewareWitnessRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Optional[RequiredDisposition] = None
    conflict_type: Optional[MiddlewareConflictType] = None
    constraint_ids_involved: List[str] = Field(default_factory=list)
    minimal_conflict_set: List[str] = Field(default_factory=list)
    recommended_handoff_target: Optional[HandoffTarget] = None
    explanation: str = ""
    audit_safe_event_record: Dict[str, Any] = Field(default_factory=dict)


class ProvedLogicalFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str
    kind: LogicalFactKind
    claim: str
    constraint_ids: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


class SemanticAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annotation_id: str
    kind: AnnotationKind
    label: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class CoherentWitness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    scenario_id: str
    runtime_mode: RuntimeEvaluationMode
    # Canonical sha256 of the runtime case actually evaluated (see
    # FCERuntimeCase.canonical_hash) plus the engine that produced the verdict.
    # These bind the witness to a specific artifact so a proof cannot be
    # validated against a different runtime case than the one that produced it.
    engine_id: str
    runtime_case_hash: str
    proved_logical_facts: List[ProvedLogicalFact] = Field(default_factory=list)
    semantic_annotations: List[SemanticAnnotation] = Field(default_factory=list)
    constraint_ids: List[str] = Field(default_factory=list)
    variable_bindings: Dict[str, str] = Field(default_factory=dict)
    conflict_class: MiddlewareConflictType
    minimal_conflicting_set: List[str] = Field(default_factory=list)
    disposition: RequiredDisposition
    proof_status: ProofStatus = ProofStatus.PROVED
    validator_status: ValidatorStatus = ValidatorStatus.NOT_RUN


class ProofValidationVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    scenario_id: str
    valid: bool
    proof_status: ProofStatus
    validator_status: ValidatorStatus
    derived_conflict_class: MiddlewareConflictType
    derived_disposition: RequiredDisposition
    checked_fact_ids: List[str] = Field(default_factory=list)
    failures: List[str] = Field(default_factory=list)


class FCEObservedOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response_text: str
    actions: List[ObservedAction] = Field(default_factory=list)
    identified_duties: List[str] = Field(default_factory=list)
    event_labels: List[EventLabel] = Field(default_factory=list)
    constraint_persistence: ConstraintPersistenceState = ConstraintPersistenceState.UNMEASURED
    global_validity: GlobalValidityState = GlobalValidityState.UNMEASURED
    unsupported_confident_answer: bool = False
    witness: Optional[MiddlewareWitnessRecord] = None
    proof_witness: Optional[CoherentWitness] = None
    proof_verdict: Optional[ProofValidationVerdict] = None


class CriterionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion_id: str
    axis: ScoringAxis
    points_awarded: float
    points_possible: int
    matched_fraction: float
    description: str


class AxisScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    axis: ScoringAxis
    points_awarded: float
    points_possible: int


class FCEScoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    arm: EvaluationArm
    total_score: float
    axis_scores: List[AxisScore]
    criterion_results: List[CriterionResult]
    event_labels: List[EventLabel]
    witness_fidelity: Optional[float] = None


class FCEBenchmarkRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    arm: EvaluationArm
    outcome: FCEObservedOutcome
    score: FCEScoreResult


class FCESummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arm: EvaluationArm
    total_runs: int
    overall_weighted_score: float
    escalation_precision: Optional[float]
    escalation_recall: Optional[float]
    severe_harm_rate: float
    silent_constraint_drop_rate: float
    worst_of_n_reliability: float
    witness_fidelity: Optional[float]
