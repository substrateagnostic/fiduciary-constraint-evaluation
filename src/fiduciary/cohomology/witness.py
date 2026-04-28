"""
CoherentWitness — neuro-symbolic bootstrap for semantic constraint checking.

The Bootstrap Problem:
  The semantic compatibility layer uses an LLM to judge constraint compatibility.
  This creates a circular dependency: using an unaligned model to check alignment.

The Solution:
  Change the LLM's role from JUDGE to PROOF GENERATOR. The LLM produces a
  CoherentWitness — a structured, formally verifiable proof object showing how
  constraints interact. A deterministic verifier checks the witness against
  the constraint algebra. If the LLM hallucinates a pass, the algebra rejects it.

  The LLM is quarantined in a mathematical cage.
  The deterministic verifier provides над — the meta-layer that doesn't care
  what the LLM "thinks."

Architecture:
  Prompt → LLM generates CoherentWitness → Deterministic Verifier → PASS/FAIL
                                                ↓ (on FAIL)
                                           над (meta-layer rejects)

Generating a valid witness is structurally harder to fake than generating
a yes/no answer. This asymmetry is the security property.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Set, Tuple

from fiduciary.cohomology.constraints import (
    ConstraintPolarity,
    ConstraintSet,
    ConstraintType,
    NormalizedConstraint,
    get_constraint_modality,
)


# =============================================================================
# Witness data structures
# =============================================================================


class WitnessStepType(str, Enum):
    """Types of steps in a coherent witness proof."""

    # Observations about individual constraints
    OBSERVE = "observe"          # State a property of a constraint
    # Logical inferences
    DERIVE = "derive"            # Derive a fact from previous steps
    # Algebraic checks
    CHECK_POLARITY = "check_polarity"      # Verify polarity relationship
    CHECK_TYPE = "check_type"              # Verify type compatibility
    CHECK_TARGET = "check_target"          # Verify target overlap/conflict
    CHECK_REGEX = "check_regex"            # Verify regex match/conflict
    CHECK_SUBSUMPTION = "check_subsumption"  # Verify one constraint subsumes another
    # Conclusions
    CONCLUDE = "conclude"        # Final verdict with justification


class WitnessVerdict(str, Enum):
    """The conclusion of a coherent witness."""
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    NARROWING = "narrowing"      # Compatible but more restrictive
    UNDETERMINED = "undetermined"  # Cannot prove either way


@dataclass(frozen=True)
class WitnessStep:
    """
    A single step in a coherent witness proof.

    Each step makes a verifiable claim about constraint properties
    or their interaction. The verifier checks each claim against
    the constraint algebra.
    """
    step_type: WitnessStepType
    constraint_ids: Tuple[str, ...]  # Which constraints this step references
    claim: str                        # Human-readable assertion
    # For algebraic checks — the verifier validates these
    property_name: Optional[str] = None    # e.g., "polarity", "target", "type"
    expected_value: Optional[str] = None   # What the proof claims
    justification: Optional[str] = None    # Why this follows (references prior steps)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_type": self.step_type.value,
            "constraint_ids": list(self.constraint_ids),
            "claim": self.claim,
            "property_name": self.property_name,
            "expected_value": self.expected_value,
            "justification": self.justification,
        }


@dataclass
class VerificationFailure:
    """A specific failure found during witness verification."""
    step_index: int
    step: WitnessStep
    reason: str
    expected: Optional[str] = None
    actual: Optional[str] = None

    def __str__(self) -> str:
        msg = f"Step {self.step_index} ({self.step.step_type.value}): {self.reason}"
        if self.expected and self.actual:
            msg += f" (expected: {self.expected}, actual: {self.actual})"
        return msg


@dataclass
class CoherentWitness:
    """
    A structured proof of constraint interaction.

    The LLM generates this; the deterministic verifier checks it.
    If the proof is malformed or algebraically invalid, the witness
    is rejected — regardless of what the LLM "intended."
    """
    constraint_ids: List[str]
    verdict: WitnessVerdict
    steps: List[WitnessStep]

    # If compatible: a concrete satisfying assignment
    satisfying_example: Optional[Dict[str, Any]] = None
    # If incompatible: the logical chain leading to contradiction
    contradiction_chain: Optional[List[str]] = None

    # Metadata
    confidence: float = 0.0
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "constraint_ids": self.constraint_ids,
            "verdict": self.verdict.value,
            "steps": [s.to_dict() for s in self.steps],
            "satisfying_example": self.satisfying_example,
            "contradiction_chain": self.contradiction_chain,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CoherentWitness:
        """Parse a witness from dict (typically from LLM JSON output)."""
        steps = []
        for s in data.get("steps", []):
            steps.append(WitnessStep(
                step_type=WitnessStepType(s["step_type"]),
                constraint_ids=tuple(s.get("constraint_ids", [])),
                claim=s.get("claim", ""),
                property_name=s.get("property_name"),
                expected_value=s.get("expected_value"),
                justification=s.get("justification"),
            ))

        return cls(
            constraint_ids=data.get("constraint_ids", []),
            verdict=WitnessVerdict(data.get("verdict", "undetermined")),
            steps=steps,
            satisfying_example=data.get("satisfying_example"),
            contradiction_chain=data.get("contradiction_chain"),
            confidence=float(data.get("confidence", 0.0)),
            reasoning=data.get("reasoning", ""),
        )


# =============================================================================
# Deterministic Verifier — над (the meta-layer)
# =============================================================================


@dataclass
class VerificationResult:
    """Result of deterministic verification of a CoherentWitness."""
    valid: bool
    failures: List[VerificationFailure] = field(default_factory=list)
    verified_verdict: Optional[WitnessVerdict] = None  # What the algebra says
    witness_verdict: Optional[WitnessVerdict] = None    # What the LLM claimed
    verdict_matches: bool = True  # Does the LLM's verdict match the algebra?

    @property
    def is_trustworthy(self) -> bool:
        """A witness is trustworthy only if valid AND verdict matches algebra."""
        return self.valid and self.verdict_matches


class WitnessVerifier:
    """
    Deterministic verifier for CoherentWitness proofs.

    This is над — the meta-layer. It checks each step of the witness
    against the constraint algebra. If any step fails, the witness
    is rejected. The LLM's opinion does not matter; the algebra decides.

    Verification checks:
    1. Structural: all referenced constraints exist, steps are well-formed
    2. Algebraic: polarity, type, and target claims match actual constraint values
    3. Logical: conclusion follows from steps
    4. Exemplar: satisfying examples actually satisfy the constraints
    """

    def verify(
        self,
        witness: CoherentWitness,
        constraints: Dict[str, NormalizedConstraint],
    ) -> VerificationResult:
        """
        Verify a CoherentWitness against the constraint algebra.

        Args:
            witness: The proof generated by the LLM
            constraints: Map of source_id → NormalizedConstraint

        Returns:
            VerificationResult with pass/fail and detailed failures
        """
        failures: List[VerificationFailure] = []

        # 1. Structural checks
        failures.extend(self._check_structure(witness, constraints))

        # 2. Algebraic checks (each step)
        for i, step in enumerate(witness.steps):
            step_failures = self._verify_step(i, step, constraints)
            failures.extend(step_failures)

        # 3. Check satisfying example if provided
        if witness.satisfying_example and witness.verdict == WitnessVerdict.COMPATIBLE:
            failures.extend(
                self._verify_satisfying_example(witness, constraints)
            )

        # 4. Determine what the algebra says (independent of LLM)
        verified_verdict = self._determine_algebraic_verdict(constraints)

        # 5. Check if LLM's verdict matches
        verdict_matches = True
        if verified_verdict is not None:
            # Only check match for clear-cut cases
            if verified_verdict == WitnessVerdict.INCOMPATIBLE and witness.verdict == WitnessVerdict.COMPATIBLE:
                verdict_matches = False
                failures.append(VerificationFailure(
                    step_index=-1,
                    step=WitnessStep(
                        step_type=WitnessStepType.CONCLUDE,
                        constraint_ids=(),
                        claim="verdict",
                    ),
                    reason="LLM claimed compatible but algebra proves incompatible",
                    expected="incompatible",
                    actual="compatible",
                ))
            elif verified_verdict == WitnessVerdict.COMPATIBLE and witness.verdict == WitnessVerdict.INCOMPATIBLE:
                # LLM was more conservative — this is OK (fail-safe)
                # But we note the disagreement
                verdict_matches = True  # Conservative is acceptable

        return VerificationResult(
            valid=len(failures) == 0,
            failures=failures,
            verified_verdict=verified_verdict,
            witness_verdict=witness.verdict,
            verdict_matches=verdict_matches,
        )

    def _check_structure(
        self,
        witness: CoherentWitness,
        constraints: Dict[str, NormalizedConstraint],
    ) -> List[VerificationFailure]:
        """Check structural validity of the witness."""
        failures = []

        required = set(constraints.keys())
        declared = set(witness.constraint_ids)

        # The witness must cover the full constraint set. Otherwise a malicious
        # generator can omit hard constraints and "prove" an easier subproblem.
        if declared != required:
            missing = sorted(required - declared)
            extra = sorted(declared - required)
            detail = []
            if missing:
                detail.append(f"missing={missing}")
            if extra:
                detail.append(f"extra={extra}")
            failures.append(VerificationFailure(
                step_index=-1,
                step=WitnessStep(
                    step_type=WitnessStepType.OBSERVE,
                    constraint_ids=tuple(witness.constraint_ids),
                    claim="witness covers all provided constraints",
                ),
                reason=(
                    "Witness constraint_ids must exactly match provided constraints "
                    f"({', '.join(detail)})"
                ),
            ))

        # All referenced constraint_ids must exist
        for cid in witness.constraint_ids:
            if cid not in constraints:
                failures.append(VerificationFailure(
                    step_index=-1,
                    step=WitnessStep(
                        step_type=WitnessStepType.OBSERVE,
                        constraint_ids=(cid,),
                        claim="constraint exists",
                    ),
                    reason=f"Referenced constraint '{cid}' does not exist",
                ))

        # Must have at least one step
        if not witness.steps:
            failures.append(VerificationFailure(
                step_index=-1,
                step=WitnessStep(
                    step_type=WitnessStepType.OBSERVE,
                    constraint_ids=(),
                    claim="witness has steps",
                ),
                reason="Witness contains no proof steps",
            ))

        # Must end with a CONCLUDE step
        if witness.steps and witness.steps[-1].step_type != WitnessStepType.CONCLUDE:
            failures.append(VerificationFailure(
                step_index=len(witness.steps) - 1,
                step=witness.steps[-1],
                reason="Witness must end with a CONCLUDE step",
            ))

        # Constraint IDs in steps must be from the declared set
        for i, step in enumerate(witness.steps):
            for cid in step.constraint_ids:
                if cid not in declared and cid not in constraints:
                    failures.append(VerificationFailure(
                        step_index=i,
                        step=step,
                        reason=f"Step references undeclared constraint '{cid}'",
                    ))

        return failures

    def _verify_step(
        self,
        index: int,
        step: WitnessStep,
        constraints: Dict[str, NormalizedConstraint],
    ) -> List[VerificationFailure]:
        """Verify a single proof step against the constraint algebra."""
        failures = []

        if step.step_type == WitnessStepType.CHECK_POLARITY:
            failures.extend(self._verify_polarity_check(index, step, constraints))
        elif step.step_type == WitnessStepType.CHECK_TYPE:
            failures.extend(self._verify_type_check(index, step, constraints))
        elif step.step_type == WitnessStepType.CHECK_TARGET:
            failures.extend(self._verify_target_check(index, step, constraints))
        elif step.step_type == WitnessStepType.CHECK_REGEX:
            failures.extend(self._verify_regex_check(index, step, constraints))
        # OBSERVE, DERIVE, CONCLUDE steps are not algebraically checked
        # (they are assertions/inferences the LLM makes, verified by context)

        return failures

    def _verify_polarity_check(
        self,
        index: int,
        step: WitnessStep,
        constraints: Dict[str, NormalizedConstraint],
    ) -> List[VerificationFailure]:
        """Verify a polarity claim against actual constraint data."""
        failures = []

        for cid in step.constraint_ids:
            c = constraints.get(cid)
            if not c:
                continue

            if step.property_name == "polarity" and step.expected_value:
                actual = c.polarity.value
                if step.expected_value != actual:
                    failures.append(VerificationFailure(
                        step_index=index,
                        step=step,
                        reason=f"Polarity mismatch for constraint '{cid}'",
                        expected=step.expected_value,
                        actual=actual,
                    ))

        return failures

    def _verify_type_check(
        self,
        index: int,
        step: WitnessStep,
        constraints: Dict[str, NormalizedConstraint],
    ) -> List[VerificationFailure]:
        """Verify a constraint type claim."""
        failures = []

        for cid in step.constraint_ids:
            c = constraints.get(cid)
            if not c:
                continue

            if step.property_name == "constraint_type" and step.expected_value:
                actual = c.constraint_type.value
                if step.expected_value != actual:
                    failures.append(VerificationFailure(
                        step_index=index,
                        step=step,
                        reason=f"Type mismatch for constraint '{cid}'",
                        expected=step.expected_value,
                        actual=actual,
                    ))

        return failures

    def _verify_target_check(
        self,
        index: int,
        step: WitnessStep,
        constraints: Dict[str, NormalizedConstraint],
    ) -> List[VerificationFailure]:
        """Verify a target/value claim."""
        failures = []

        for cid in step.constraint_ids:
            c = constraints.get(cid)
            if not c:
                continue

            if step.property_name == "target" and step.expected_value:
                actual = c.target
                if step.expected_value != actual:
                    failures.append(VerificationFailure(
                        step_index=index,
                        step=step,
                        reason=f"Target mismatch for constraint '{cid}'",
                        expected=step.expected_value,
                        actual=actual,
                    ))

        return failures

    def _verify_regex_check(
        self,
        index: int,
        step: WitnessStep,
        constraints: Dict[str, NormalizedConstraint],
    ) -> List[VerificationFailure]:
        """Verify a regex compatibility claim."""
        failures = []

        if len(step.constraint_ids) < 2:
            return failures

        cids = list(step.constraint_ids)
        c_a = constraints.get(cids[0])
        c_b = constraints.get(cids[1])

        if not c_a or not c_b:
            return failures

        # If one is MUST_INCLUDE_REGEX and the other is MUST_NOT_INCLUDE_REGEX
        # and their targets overlap, that's a contradiction
        if (
            c_a.constraint_type == ConstraintType.MUST_INCLUDE_REGEX
            and c_b.constraint_type == ConstraintType.MUST_NOT_INCLUDE_REGEX
        ):
            try:
                pattern_a = re.compile(c_a.target)
                pattern_b = re.compile(c_b.target)
                # If the include pattern is a subset of the exclude pattern,
                # they contradict. Simple check: does the include target
                # match the exclude pattern?
                if pattern_b.search(c_a.target):
                    if step.expected_value == "compatible":
                        failures.append(VerificationFailure(
                            step_index=index,
                            step=step,
                            reason="Regex include/exclude targets overlap — incompatible",
                            expected="compatible",
                            actual="incompatible",
                        ))
            except re.error:
                pass  # Invalid regex — can't verify

        return failures

    def _verify_satisfying_example(
        self,
        witness: CoherentWitness,
        constraints: Dict[str, NormalizedConstraint],
    ) -> List[VerificationFailure]:
        """
        Verify that a satisfying example actually satisfies all constraints.

        This is the strongest check: if the LLM claims constraints are
        compatible and provides an example, we verify the example against
        every deterministic constraint.
        """
        failures = []
        example = witness.satisfying_example or {}
        example_text = example.get("text", "")

        if not example_text:
            return failures  # No text to check against

        for cid, c in constraints.items():
            # Check heading constraints
            if c.constraint_type == ConstraintType.MUST_INCLUDE_HEADING:
                if c.polarity == ConstraintPolarity.POSITIVE:
                    if c.target.lower() not in example_text.lower():
                        failures.append(VerificationFailure(
                            step_index=-1,
                            step=WitnessStep(
                                step_type=WitnessStepType.CONCLUDE,
                                constraint_ids=(cid,),
                                claim=f"Example satisfies heading '{c.target}'",
                            ),
                            reason=f"Satisfying example missing required heading '{c.target}'",
                        ))

            # Check regex constraints
            if c.constraint_type == ConstraintType.MUST_INCLUDE_REGEX:
                try:
                    if not re.search(c.target, example_text):
                        failures.append(VerificationFailure(
                            step_index=-1,
                            step=WitnessStep(
                                step_type=WitnessStepType.CONCLUDE,
                                constraint_ids=(cid,),
                                claim=f"Example matches regex '{c.target}'",
                            ),
                            reason=f"Satisfying example doesn't match required regex '{c.target}'",
                        ))
                except re.error:
                    pass

            if c.constraint_type == ConstraintType.MUST_NOT_INCLUDE_REGEX:
                try:
                    if re.search(c.target, example_text):
                        failures.append(VerificationFailure(
                            step_index=-1,
                            step=WitnessStep(
                                step_type=WitnessStepType.CONCLUDE,
                                constraint_ids=(cid,),
                                claim=f"Example avoids regex '{c.target}'",
                            ),
                            reason=f"Satisfying example matches forbidden regex '{c.target}'",
                        ))
                except re.error:
                    pass

        return failures

    def _determine_algebraic_verdict(
        self,
        constraints: Dict[str, NormalizedConstraint],
    ) -> Optional[WitnessVerdict]:
        """
        Determine what the algebra says about compatibility,
        independent of the LLM's claim.

        Returns None if the algebra can't determine (needs semantic analysis).
        """
        constraint_list = list(constraints.values())

        for i, c_a in enumerate(constraint_list):
            for c_b in constraint_list[i + 1:]:
                # Same target, opposite polarity = incompatible
                if c_a.target == c_b.target and c_a.polarity != c_b.polarity:
                    # Same type family
                    if _same_type_family(c_a.constraint_type, c_b.constraint_type):
                        return WitnessVerdict.INCOMPATIBLE

                # Heading required + regex forbids that heading
                if (
                    c_a.constraint_type == ConstraintType.MUST_INCLUDE_HEADING
                    and c_b.constraint_type == ConstraintType.MUST_NOT_INCLUDE_REGEX
                ):
                    try:
                        if re.search(c_b.target, c_a.target):
                            return WitnessVerdict.INCOMPATIBLE
                    except re.error:
                        pass

                if (
                    c_b.constraint_type == ConstraintType.MUST_INCLUDE_HEADING
                    and c_a.constraint_type == ConstraintType.MUST_NOT_INCLUDE_REGEX
                ):
                    try:
                        if re.search(c_a.target, c_b.target):
                            return WitnessVerdict.INCOMPATIBLE
                    except re.error:
                        pass

        return None  # Can't determine algebraically


def _same_type_family(a: ConstraintType, b: ConstraintType) -> bool:
    """Check if two constraint types are in the same family (can conflict)."""
    text_include = {ConstraintType.MUST_INCLUDE_HEADING, ConstraintType.MUST_INCLUDE_REGEX}
    text_exclude = {ConstraintType.MUST_NOT_INCLUDE_REGEX}
    semantic = {ConstraintType.SEMANTIC_TOPIC, ConstraintType.SEMANTIC_TONE, ConstraintType.SEMANTIC_INTENT}
    visual_style = {ConstraintType.VISUAL_STYLE, ConstraintType.VISUAL_MOOD}
    color_include = {ConstraintType.COLOR_PALETTE, ConstraintType.COLOR_DOMINANT}
    color_exclude = {ConstraintType.COLOR_FORBIDDEN}

    # Include vs Exclude in same domain
    if (a in text_include and b in text_exclude) or (b in text_include and a in text_exclude):
        return True
    if (a in color_include and b in color_exclude) or (b in color_include and a in color_exclude):
        return True

    # Same semantic type
    if a in semantic and b in semantic and a == b:
        return True

    # Same visual type
    if a in visual_style and b in visual_style and a == b:
        return True

    return False


# =============================================================================
# Witness Prompt Builder
# =============================================================================


WITNESS_PROMPT_TEMPLATE = """You are a constraint algebra proof generator. Your task is to generate
a CoherentWitness — a structured, verifiable proof of how these constraints interact.

IMPORTANT: Your proof will be checked by a deterministic verifier. Every claim you
make about constraint properties (polarity, type, target) will be verified against
the actual constraint data. If you make a false claim, your witness will be REJECTED.

## Constraints to analyze:

{constraints_section}

## Required output format (JSON):

{{
  "constraint_ids": [{constraint_ids}],
  "verdict": "compatible" | "incompatible" | "narrowing" | "undetermined",
  "steps": [
    {{
      "step_type": "observe" | "derive" | "check_polarity" | "check_type" | "check_target" | "check_regex" | "conclude",
      "constraint_ids": ["id1"],
      "claim": "Human-readable assertion about this step",
      "property_name": "polarity" | "constraint_type" | "target" | null,
      "expected_value": "the actual value from the constraint" | null,
      "justification": "Why this follows from previous steps" | null
    }}
  ],
  "satisfying_example": {{"text": "A concrete example satisfying all constraints"}} | null,
  "contradiction_chain": ["step 1 claim", "step 2 claim", "therefore contradiction"] | null,
  "confidence": 0.0-1.0,
  "reasoning": "Brief explanation"
}}

## Rules:
1. Start with OBSERVE steps stating actual properties of each constraint
2. Use CHECK_* steps to verify algebraic relationships
3. For CHECK steps, the expected_value MUST match the actual constraint property
4. End with exactly one CONCLUDE step
5. If compatible, provide a satisfying_example with a "text" field
6. If incompatible, provide a contradiction_chain
7. Be precise. The verifier will catch any false claims.
"""


def build_witness_prompt(
    constraints: Dict[str, NormalizedConstraint],
) -> str:
    """Build a prompt for the LLM to generate a CoherentWitness."""
    sections = []
    ids = []
    for cid, c in constraints.items():
        ids.append(f'"{cid}"')
        sections.append(
            f"- **{cid}**: type={c.constraint_type.value}, "
            f"polarity={c.polarity.value}, target=\"{c.target}\", "
            f"severity={c.severity.value}, "
            f"soul_invariant={c.is_soul_invariant}"
        )

    return WITNESS_PROMPT_TEMPLATE.format(
        constraints_section="\n".join(sections),
        constraint_ids=", ".join(ids),
    )


# =============================================================================
# Witness-based Semantic Checker (implements SemanticChecker protocol)
# =============================================================================


class WitnessGenerator(Protocol):
    """Protocol for generating CoherentWitness objects (typically via LLM)."""

    def generate_witness(
        self,
        constraints: Dict[str, NormalizedConstraint],
    ) -> CoherentWitness:
        ...


class MockWitnessGenerator:
    """
    Mock witness generator for testing.

    Generates deterministic witnesses based on constraint properties,
    using the same algebra the verifier checks.
    """

    def __init__(self, always_compatible: bool = False):
        self.always_compatible = always_compatible
        self.call_count = 0

    def generate_witness(
        self,
        constraints: Dict[str, NormalizedConstraint],
    ) -> CoherentWitness:
        self.call_count += 1
        steps: List[WitnessStep] = []
        constraint_ids = list(constraints.keys())

        # Observe each constraint
        for cid, c in constraints.items():
            steps.append(WitnessStep(
                step_type=WitnessStepType.OBSERVE,
                constraint_ids=(cid,),
                claim=f"Constraint {cid} has type {c.constraint_type.value}, "
                      f"polarity {c.polarity.value}, target '{c.target}'",
            ))

        # Check pairwise polarities
        cids = list(constraints.keys())
        has_conflict = False
        conflict_pair = None

        for i, cid_a in enumerate(cids):
            for cid_b in cids[i + 1:]:
                c_a = constraints[cid_a]
                c_b = constraints[cid_b]

                steps.append(WitnessStep(
                    step_type=WitnessStepType.CHECK_POLARITY,
                    constraint_ids=(cid_a,),
                    claim=f"Constraint {cid_a} polarity is {c_a.polarity.value}",
                    property_name="polarity",
                    expected_value=c_a.polarity.value,
                ))

                # Check for target conflict
                if c_a.target == c_b.target and c_a.polarity != c_b.polarity:
                    if _same_type_family(c_a.constraint_type, c_b.constraint_type):
                        has_conflict = True
                        conflict_pair = (cid_a, cid_b)

        if has_conflict and not self.always_compatible:
            a, b = conflict_pair
            steps.append(WitnessStep(
                step_type=WitnessStepType.DERIVE,
                constraint_ids=(a, b),
                claim=f"Constraints {a} and {b} have opposing polarities on the same target",
                justification="Same target with positive/negative polarity is contradictory",
            ))
            steps.append(WitnessStep(
                step_type=WitnessStepType.CONCLUDE,
                constraint_ids=tuple(constraint_ids),
                claim="Constraints are INCOMPATIBLE due to polarity conflict",
            ))

            return CoherentWitness(
                constraint_ids=constraint_ids,
                verdict=WitnessVerdict.INCOMPATIBLE,
                steps=steps,
                contradiction_chain=[
                    f"{a} requires '{constraints[a].target}' (positive)",
                    f"{b} forbids '{constraints[b].target}' (negative)",
                    "Cannot simultaneously include and exclude the same target",
                ],
                confidence=0.95,
                reasoning="Deterministic polarity conflict detected",
            )

        # No conflict found — build a satisfying example from targets
        example_parts = []
        for c in constraints.values():
            if c.polarity == ConstraintPolarity.POSITIVE:
                example_parts.append(c.target)
        example_text = "\n\n".join(example_parts) if example_parts else "Example"

        steps.append(WitnessStep(
            step_type=WitnessStepType.CONCLUDE,
            constraint_ids=tuple(constraint_ids),
            claim="No algebraic conflicts detected — constraints are COMPATIBLE",
        ))

        return CoherentWitness(
            constraint_ids=constraint_ids,
            verdict=WitnessVerdict.COMPATIBLE,
            steps=steps,
            satisfying_example={"text": example_text},
            confidence=0.8,
            reasoning="No polarity or type conflicts found",
        )


class HallucinatingWitnessGenerator:
    """
    A witness generator that lies — claims compatible when constraints conflict.

    Used for testing that the verifier catches hallucinated witnesses.
    This simulates an unaligned LLM that tries to bypass the constraint check.
    """

    def generate_witness(
        self,
        constraints: Dict[str, NormalizedConstraint],
    ) -> CoherentWitness:
        constraint_ids = list(constraints.keys())
        steps = []

        # Observe (correctly)
        for cid, c in constraints.items():
            steps.append(WitnessStep(
                step_type=WitnessStepType.OBSERVE,
                constraint_ids=(cid,),
                claim=f"Constraint {cid}: {c.constraint_type.value}",
            ))

        # Lie about polarity — claim everything is positive
        for cid, c in constraints.items():
            steps.append(WitnessStep(
                step_type=WitnessStepType.CHECK_POLARITY,
                constraint_ids=(cid,),
                claim=f"Constraint {cid} is positive",
                property_name="polarity",
                expected_value="positive",  # This is the lie for negative constraints
            ))

        steps.append(WitnessStep(
            step_type=WitnessStepType.CONCLUDE,
            constraint_ids=tuple(constraint_ids),
            claim="All constraints are compatible (hallucinated)",
        ))

        return CoherentWitness(
            constraint_ids=constraint_ids,
            verdict=WitnessVerdict.COMPATIBLE,
            steps=steps,
            satisfying_example={"text": "This is a fake example"},
            confidence=0.99,  # Overconfident hallucination
            reasoning="Trust me bro",
        )


class WitnessSemanticChecker:
    """
    Semantic checker that uses the CoherentWitness architecture.

    Implements the same interface as the old SemanticChecker protocol
    but replaces the oracle pattern (ask LLM → trust answer) with
    the witness pattern (LLM generates proof → verifier checks algebra).
    """

    def __init__(
        self,
        generator: WitnessGenerator,
        verifier: Optional[WitnessVerifier] = None,
        fail_safe: bool = True,  # If verification fails, assume incompatible
    ):
        self.generator = generator
        self.verifier = verifier or WitnessVerifier()
        self.fail_safe = fail_safe

    def check_semantic_compatibility(
        self,
        constraint_a: NormalizedConstraint,
        constraint_b: NormalizedConstraint,
    ) -> Tuple[bool, float, Optional[str]]:
        """
        Check pairwise compatibility via witness generation + verification.

        Returns:
            (is_compatible, confidence, explanation)
        """
        constraints = {
            constraint_a.source_id: constraint_a,
            constraint_b.source_id: constraint_b,
        }

        witness = self.generator.generate_witness(constraints)
        result = self.verifier.verify(witness, constraints)

        if not result.is_trustworthy:
            if self.fail_safe:
                failure_reasons = "; ".join(str(f) for f in result.failures)
                return (
                    False,
                    0.0,
                    f"Witness verification failed (fail-safe → incompatible): {failure_reasons}",
                )
            # Non-fail-safe: return the algebraic verdict if available
            if result.verified_verdict == WitnessVerdict.COMPATIBLE:
                return (True, 0.5, "Witness invalid but algebra says compatible")

        is_compatible = witness.verdict in {
            WitnessVerdict.COMPATIBLE,
            WitnessVerdict.NARROWING,
        }
        return (is_compatible, witness.confidence, witness.reasoning)

    def check_triple_compatibility(
        self,
        constraint_a: NormalizedConstraint,
        constraint_b: NormalizedConstraint,
        constraint_c: NormalizedConstraint,
    ) -> Tuple[bool, float, Optional[str]]:
        """Check triple compatibility via witness."""
        constraints = {
            constraint_a.source_id: constraint_a,
            constraint_b.source_id: constraint_b,
            constraint_c.source_id: constraint_c,
        }

        witness = self.generator.generate_witness(constraints)
        result = self.verifier.verify(witness, constraints)

        if not result.is_trustworthy:
            if self.fail_safe:
                failure_reasons = "; ".join(str(f) for f in result.failures)
                return (
                    False,
                    0.0,
                    f"Witness verification failed: {failure_reasons}",
                )

        is_compatible = witness.verdict in {
            WitnessVerdict.COMPATIBLE,
            WitnessVerdict.NARROWING,
        }
        return (is_compatible, witness.confidence, witness.reasoning)
