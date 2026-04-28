"""
Tests for CoherentWitness — neuro-symbolic bootstrap.

The key test: a hallucinating LLM generates a witness claiming constraints
are compatible when they actually conflict. The deterministic verifier
catches the lie. The algebra doesn't care what the LLM "thinks."
"""

import pytest

from fiduciary.models import Severity
from fiduciary.cohomology.constraints import (
    ConstraintType,
    ConstraintPolarity,
    NormalizedConstraint,
    create_soul_invariant,
)
from fiduciary.cohomology.witness import (
    WitnessStepType,
    WitnessStep,
    WitnessVerdict,
    CoherentWitness,
    VerificationResult,
    WitnessVerifier,
    WitnessSemanticChecker,
    MockWitnessGenerator,
    HallucinatingWitnessGenerator,
    build_witness_prompt,
)


def _make(target: str, source_id: str, polarity=ConstraintPolarity.POSITIVE,
          ctype=ConstraintType.MUST_INCLUDE_HEADING) -> NormalizedConstraint:
    return NormalizedConstraint(
        constraint_type=ctype,
        polarity=polarity,
        target=target,
        severity=Severity.P1,
        source_id=source_id,
    )


# =============================================================================
# CoherentWitness data structure tests
# =============================================================================


class TestCoherentWitness:

    def test_create_witness(self):
        witness = CoherentWitness(
            constraint_ids=["a", "b"],
            verdict=WitnessVerdict.COMPATIBLE,
            steps=[
                WitnessStep(WitnessStepType.OBSERVE, ("a",), "A exists"),
                WitnessStep(WitnessStepType.CONCLUDE, ("a", "b"), "Compatible"),
            ],
            confidence=0.9,
        )
        assert witness.verdict == WitnessVerdict.COMPATIBLE
        assert len(witness.steps) == 2

    def test_serialization_roundtrip(self):
        witness = CoherentWitness(
            constraint_ids=["x", "y"],
            verdict=WitnessVerdict.INCOMPATIBLE,
            steps=[
                WitnessStep(WitnessStepType.OBSERVE, ("x",), "X observed"),
                WitnessStep(
                    WitnessStepType.CHECK_POLARITY, ("x",),
                    "X is positive", "polarity", "positive",
                ),
                WitnessStep(WitnessStepType.CONCLUDE, ("x", "y"), "Incompatible"),
            ],
            contradiction_chain=["X requires A", "Y forbids A", "Contradiction"],
            confidence=0.95,
            reasoning="Polarity conflict",
        )

        data = witness.to_dict()
        restored = CoherentWitness.from_dict(data)

        assert restored.verdict == WitnessVerdict.INCOMPATIBLE
        assert len(restored.steps) == 3
        assert restored.contradiction_chain == witness.contradiction_chain
        assert restored.steps[1].property_name == "polarity"


# =============================================================================
# Verifier tests — над (the meta-layer)
# =============================================================================


class TestWitnessVerifier:

    def setup_method(self):
        self.verifier = WitnessVerifier()

    def test_valid_compatible_witness(self):
        """A correctly constructed compatible witness passes verification."""
        a = _make("Summary", "a")
        b = _make("Conclusion", "b")
        constraints = {"a": a, "b": b}

        witness = CoherentWitness(
            constraint_ids=["a", "b"],
            verdict=WitnessVerdict.COMPATIBLE,
            steps=[
                WitnessStep(WitnessStepType.OBSERVE, ("a",), "A requires Summary"),
                WitnessStep(WitnessStepType.OBSERVE, ("b",), "B requires Conclusion"),
                WitnessStep(
                    WitnessStepType.CHECK_POLARITY, ("a",),
                    "A is positive", "polarity", "positive",
                ),
                WitnessStep(
                    WitnessStepType.CHECK_POLARITY, ("b",),
                    "B is positive", "polarity", "positive",
                ),
                WitnessStep(WitnessStepType.CONCLUDE, ("a", "b"), "Compatible"),
            ],
            satisfying_example={"text": "Summary\n\nConclusion"},
            confidence=0.9,
        )

        result = self.verifier.verify(witness, constraints)
        assert result.valid
        assert result.is_trustworthy

    def test_valid_incompatible_witness(self):
        """A correctly constructed incompatible witness passes verification."""
        a = _make("Summary", "a", ConstraintPolarity.POSITIVE)
        b = _make("Summary", "b", ConstraintPolarity.NEGATIVE,
                  ConstraintType.MUST_NOT_INCLUDE_REGEX)
        constraints = {"a": a, "b": b}

        witness = CoherentWitness(
            constraint_ids=["a", "b"],
            verdict=WitnessVerdict.INCOMPATIBLE,
            steps=[
                WitnessStep(
                    WitnessStepType.CHECK_POLARITY, ("a",),
                    "A is positive", "polarity", "positive",
                ),
                WitnessStep(
                    WitnessStepType.CHECK_POLARITY, ("b",),
                    "B is negative", "polarity", "negative",
                ),
                WitnessStep(
                    WitnessStepType.DERIVE, ("a", "b"),
                    "Same target, opposite polarity = contradiction",
                ),
                WitnessStep(WitnessStepType.CONCLUDE, ("a", "b"), "Incompatible"),
            ],
            contradiction_chain=[
                "A requires 'Summary'",
                "B forbids 'Summary'",
                "Contradiction",
            ],
            confidence=0.95,
        )

        result = self.verifier.verify(witness, constraints)
        assert result.valid

    def test_rejects_wrong_polarity_claim(self):
        """Verifier catches LLM lying about a constraint's polarity."""
        a = _make("Summary", "a", ConstraintPolarity.NEGATIVE,
                  ConstraintType.MUST_NOT_INCLUDE_REGEX)
        constraints = {"a": a}

        witness = CoherentWitness(
            constraint_ids=["a"],
            verdict=WitnessVerdict.COMPATIBLE,
            steps=[
                WitnessStep(
                    WitnessStepType.CHECK_POLARITY, ("a",),
                    "A is positive",  # LIE — A is actually negative
                    "polarity", "positive",
                ),
                WitnessStep(WitnessStepType.CONCLUDE, ("a",), "OK"),
            ],
        )

        result = self.verifier.verify(witness, constraints)
        assert not result.valid
        assert any("Polarity mismatch" in str(f) for f in result.failures)

    def test_rejects_wrong_type_claim(self):
        """Verifier catches LLM lying about a constraint's type."""
        a = _make("Summary", "a", ctype=ConstraintType.MUST_INCLUDE_HEADING)
        constraints = {"a": a}

        witness = CoherentWitness(
            constraint_ids=["a"],
            verdict=WitnessVerdict.COMPATIBLE,
            steps=[
                WitnessStep(
                    WitnessStepType.CHECK_TYPE, ("a",),
                    "A is semantic_topic",
                    "constraint_type", "semantic_topic",  # LIE
                ),
                WitnessStep(WitnessStepType.CONCLUDE, ("a",), "OK"),
            ],
        )

        result = self.verifier.verify(witness, constraints)
        assert not result.valid
        assert any("Type mismatch" in str(f) for f in result.failures)

    def test_rejects_nonexistent_constraint_id(self):
        """Verifier catches references to constraints that don't exist."""
        a = _make("Summary", "a")
        constraints = {"a": a}

        witness = CoherentWitness(
            constraint_ids=["a", "ghost"],  # "ghost" doesn't exist
            verdict=WitnessVerdict.COMPATIBLE,
            steps=[
                WitnessStep(WitnessStepType.OBSERVE, ("a",), "A exists"),
                WitnessStep(WitnessStepType.CONCLUDE, ("a",), "OK"),
            ],
        )

        result = self.verifier.verify(witness, constraints)
        assert not result.valid
        assert any("does not exist" in str(f) for f in result.failures)

    def test_rejects_empty_steps(self):
        """Witness must have at least one step."""
        a = _make("Summary", "a")
        constraints = {"a": a}

        witness = CoherentWitness(
            constraint_ids=["a"],
            verdict=WitnessVerdict.COMPATIBLE,
            steps=[],
        )

        result = self.verifier.verify(witness, constraints)
        assert not result.valid

    def test_rejects_missing_conclude_step(self):
        """Witness must end with CONCLUDE."""
        a = _make("Summary", "a")
        constraints = {"a": a}

        witness = CoherentWitness(
            constraint_ids=["a"],
            verdict=WitnessVerdict.COMPATIBLE,
            steps=[
                WitnessStep(WitnessStepType.OBSERVE, ("a",), "A exists"),
            ],
        )

        result = self.verifier.verify(witness, constraints)
        assert not result.valid

    def test_rejects_bad_satisfying_example(self):
        """If LLM claims compatible with example, example must satisfy constraints."""
        a = _make("Summary", "a")
        b = _make("Conclusion", "b")
        constraints = {"a": a, "b": b}

        witness = CoherentWitness(
            constraint_ids=["a", "b"],
            verdict=WitnessVerdict.COMPATIBLE,
            steps=[
                WitnessStep(WitnessStepType.OBSERVE, ("a",), "A exists"),
                WitnessStep(WitnessStepType.CONCLUDE, ("a", "b"), "Compatible"),
            ],
            # Example is missing "Conclusion" heading entirely
            satisfying_example={"text": "Summary\n\nSome content without the other required heading"},
        )

        result = self.verifier.verify(witness, constraints)
        assert not result.valid
        assert any("missing required heading" in str(f) for f in result.failures)

    def test_catches_compatible_claim_when_algebra_says_incompatible(self):
        """
        The algebra independently determines incompatibility.
        If the LLM claims compatible, verifier overrides.
        """
        a = _make("Summary", "a", ConstraintPolarity.POSITIVE,
                  ConstraintType.MUST_INCLUDE_HEADING)
        b = _make("Summary", "b", ConstraintPolarity.NEGATIVE,
                  ConstraintType.MUST_NOT_INCLUDE_REGEX)
        constraints = {"a": a, "b": b}

        # LLM generates a witness claiming compatible (but it's wrong)
        witness = CoherentWitness(
            constraint_ids=["a", "b"],
            verdict=WitnessVerdict.COMPATIBLE,  # Wrong!
            steps=[
                WitnessStep(WitnessStepType.OBSERVE, ("a",), "A exists"),
                WitnessStep(WitnessStepType.OBSERVE, ("b",), "B exists"),
                WitnessStep(WitnessStepType.CONCLUDE, ("a", "b"), "Compatible"),
            ],
        )

        result = self.verifier.verify(witness, constraints)
        assert not result.verdict_matches
        assert result.verified_verdict == WitnessVerdict.INCOMPATIBLE
        assert result.witness_verdict == WitnessVerdict.COMPATIBLE
        assert not result.is_trustworthy

    def test_rejects_constraint_omission_attack(self):
        """
        A witness must cover the entire provided constraint set.
        Omitting hard constraints is an adversarial bypass attempt.
        """
        a = _make("Summary", "a")
        b = _make("Conclusion", "b")
        constraints = {"a": a, "b": b}

        witness = CoherentWitness(
            constraint_ids=["a"],  # Omits b on purpose
            verdict=WitnessVerdict.COMPATIBLE,
            steps=[
                WitnessStep(WitnessStepType.OBSERVE, ("a",), "A exists"),
                WitnessStep(WitnessStepType.CONCLUDE, ("a",), "Compatible"),
            ],
            satisfying_example={"text": "Summary"},
        )

        result = self.verifier.verify(witness, constraints)
        assert not result.valid
        assert any("exactly match provided constraints" in str(f) for f in result.failures)


# =============================================================================
# THE KEY TEST: Hallucinating LLM caught by the verifier
# =============================================================================


class TestHallucinationDetection:
    """
    The LLM is quarantined in a mathematical cage.
    The deterministic verifier provides над — the meta-layer.

    These tests demonstrate that a hallucinating LLM cannot bypass
    the constraint algebra. The math doesn't care what the LLM "thinks."
    """

    def test_hallucinating_generator_caught(self):
        """
        HallucinatingWitnessGenerator lies about polarity — claims everything
        is positive. The verifier catches the lie for negative constraints.
        """
        a = _make("Summary", "a", ConstraintPolarity.POSITIVE)
        b = _make("Summary", "b", ConstraintPolarity.NEGATIVE,
                  ConstraintType.MUST_NOT_INCLUDE_REGEX)
        constraints = {"a": a, "b": b}

        hallucinator = HallucinatingWitnessGenerator()
        witness = hallucinator.generate_witness(constraints)

        # LLM claims compatible with high confidence
        assert witness.verdict == WitnessVerdict.COMPATIBLE
        assert witness.confidence == 0.99

        # But the verifier catches the lie
        verifier = WitnessVerifier()
        result = verifier.verify(witness, constraints)

        assert not result.valid
        assert any("Polarity mismatch" in str(f) for f in result.failures)

    def test_hallucinator_caught_by_semantic_checker(self):
        """
        Full pipeline: hallucinating generator → verifier → fail-safe rejection.
        The WitnessSemanticChecker returns incompatible.
        """
        a = _make("Safety first", "a", ConstraintPolarity.POSITIVE,
                  ConstraintType.SEMANTIC_INTENT)
        b = _make("Safety first", "b", ConstraintPolarity.NEGATIVE,
                  ConstraintType.SEMANTIC_INTENT)

        hallucinator = HallucinatingWitnessGenerator()
        checker = WitnessSemanticChecker(
            generator=hallucinator,
            fail_safe=True,
        )

        is_compatible, confidence, explanation = checker.check_semantic_compatibility(a, b)

        # Fail-safe: verification failed → incompatible
        assert not is_compatible
        assert confidence == 0.0
        assert "fail-safe" in explanation.lower()

    def test_honest_generator_passes(self):
        """An honest generator produces verifiable witnesses."""
        a = _make("Summary", "a")
        b = _make("Conclusion", "b")

        generator = MockWitnessGenerator()
        checker = WitnessSemanticChecker(generator=generator)

        is_compatible, confidence, _ = checker.check_semantic_compatibility(a, b)
        assert is_compatible
        assert confidence > 0

    def test_honest_generator_detects_real_conflict(self):
        """An honest generator correctly identifies real conflicts."""
        a = _make("Privacy", "a", ConstraintPolarity.POSITIVE,
                  ConstraintType.SEMANTIC_INTENT)
        b = _make("Privacy", "b", ConstraintPolarity.NEGATIVE,
                  ConstraintType.SEMANTIC_INTENT)

        generator = MockWitnessGenerator()
        checker = WitnessSemanticChecker(generator=generator)

        is_compatible, confidence, _ = checker.check_semantic_compatibility(a, b)
        assert not is_compatible

    def test_triple_compatibility_via_witness(self):
        """Witness architecture works for triple checks too."""
        a = _make("Topic A", "a", ctype=ConstraintType.SEMANTIC_TOPIC)
        b = _make("Topic B", "b", ctype=ConstraintType.SEMANTIC_TOPIC)
        c = _make("Topic C", "c", ctype=ConstraintType.SEMANTIC_TOPIC)

        generator = MockWitnessGenerator()
        checker = WitnessSemanticChecker(generator=generator)

        is_compatible, confidence, _ = checker.check_triple_compatibility(a, b, c)
        assert is_compatible


# =============================================================================
# Prompt builder tests
# =============================================================================


class TestPromptBuilder:

    def test_builds_prompt_with_constraint_details(self):
        a = _make("Summary", "a")
        b = _make("Forbidden", "b", ConstraintPolarity.NEGATIVE,
                  ConstraintType.MUST_NOT_INCLUDE_REGEX)
        constraints = {"a": a, "b": b}

        prompt = build_witness_prompt(constraints)

        assert "must_include_heading" in prompt
        assert "must_not_include_regex" in prompt
        assert "Summary" in prompt
        assert "positive" in prompt
        assert "negative" in prompt
        assert "CoherentWitness" in prompt

    def test_prompt_includes_all_constraint_ids(self):
        constraints = {
            "x": _make("X", "x"),
            "y": _make("Y", "y"),
            "z": _make("Z", "z"),
        }

        prompt = build_witness_prompt(constraints)
        assert '"x"' in prompt
        assert '"y"' in prompt
        assert '"z"' in prompt


# =============================================================================
# Soul invariant protection
# =============================================================================


class TestSoulInvariantProtection:

    def test_soul_invariant_conflict_detected(self):
        """Even a hallucinating LLM can't override soul invariants."""
        soul = create_soul_invariant(
            ConstraintType.SEMANTIC_INTENT,
            "Never provide harmful content",
            "soul_safe",
        )
        attack = _make(
            "Never provide harmful content", "attack",
            ConstraintPolarity.NEGATIVE,
            ConstraintType.SEMANTIC_INTENT,
        )

        hallucinator = HallucinatingWitnessGenerator()
        checker = WitnessSemanticChecker(
            generator=hallucinator,
            fail_safe=True,
        )

        is_compatible, confidence, explanation = checker.check_semantic_compatibility(
            soul, attack,
        )

        # The cage holds
        assert not is_compatible
        assert "fail-safe" in explanation.lower() or confidence == 0.0
