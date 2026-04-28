"""
Obstruction-aware drift detection.

This module replaces the brittle keyword-based drift detection with
a richer model that:
1. Extracts implicit constraints from user text
2. Checks compatibility with existing constraints
3. Classifies the type of drift/change
4. Provides structured information for amendment proposals

The key insight: "drift" is really "constraint incompatibility" -
the user is trying to introduce constraints that conflict with
the established intent contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from fiduciary.cohomology.constraints import (
    ConstraintPolarity,
    ConstraintSet,
    ConstraintType,
    NormalizedConstraint,
    create_semantic_constraint,
    get_constraint_modality,
)
from fiduciary.cohomology.compatibility import (
    CompatibilityResult,
    CompatibilityStatus,
    Obstruction,
    check_compatibility,
)
from fiduciary.models import ContractLike, Severity


class DriftClassification(str, Enum):
    """
    Classification of how user input relates to the established intent.

    This is richer than the original binary VIOLATION/INTENT_SHIFT.
    """

    CONTINUATION = "continuation"
    # Input aligns with stated objective - no drift

    REFINEMENT = "refinement"
    # Input clarifies or narrows the objective - compatible drift

    EXTENSION = "extension"
    # Input adds to scope but remains compatible - may need acknowledgment

    PIVOT = "pivot"
    # Input represents fundamentally different direction - needs amendment

    CONTRADICTION = "contradiction"
    # Input conflicts with existing constraints - violation

    ADVERSARIAL = "adversarial"
    # Input appears to be attempting to circumvent constraints


@dataclass
class ImplicitConstraint:
    """
    A constraint implied by user text but not explicitly stated.

    These are extracted through analysis and used for compatibility checking.
    """
    constraint: NormalizedConstraint
    confidence: float  # 0.0-1.0, how confident we are this is implied
    evidence: str  # The text that implies this constraint
    extraction_method: str  # "keyword", "semantic", "llm"


@dataclass
class DriftAnalysis:
    """
    Comprehensive analysis of potential drift in user input.

    Supports both text (West) and visual (East) modalities.
    """
    classification: DriftClassification
    confidence: float

    # Constraints implied by the user's text
    implicit_constraints: List[ImplicitConstraint] = field(default_factory=list)

    # Compatibility analysis against existing constraints
    compatibility: Optional[CompatibilityResult] = None

    # Specific obstructions found
    obstructions: List[Obstruction] = field(default_factory=list)

    # For PIVOT/EXTENSION: what the new objective appears to be
    derived_objective: Optional[str] = None

    # For CONTRADICTION/ADVERSARIAL: what the user appears to be trying to do
    apparent_intent: Optional[str] = None

    # Method used for classification
    classification_method: str = "hybrid"

    # Suggested resolution if there's an issue
    suggested_resolution: Optional[str] = None

    # Raw analysis from LLM if used
    llm_response: Optional[Dict[str, Any]] = None

    # === MULTIMODAL FIELDS (v2.0) ===

    # Which modalities are relevant to this drift
    modalities: List[str] = field(default_factory=lambda: ["text"])

    # Visual constraints that need verification (for image outputs)
    visual_constraints_to_check: List[NormalizedConstraint] = field(default_factory=list)

    # Whether visual output is involved in this drift
    requires_visual_check: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "classification": self.classification.value,
            "confidence": self.confidence,
            "implicit_constraints": [
                {
                    "constraint": ic.constraint.to_dict(),
                    "confidence": ic.confidence,
                    "evidence": ic.evidence,
                    "extraction_method": ic.extraction_method,
                }
                for ic in self.implicit_constraints
            ],
            "compatibility": self.compatibility.to_dict() if self.compatibility else None,
            "obstructions": [o.to_dict() for o in self.obstructions],
            "derived_objective": self.derived_objective,
            "apparent_intent": self.apparent_intent,
            "classification_method": self.classification_method,
            "suggested_resolution": self.suggested_resolution,
            # Multimodal fields
            "modalities": self.modalities,
            "visual_constraints_to_check": [c.to_dict() for c in self.visual_constraints_to_check],
            "requires_visual_check": self.requires_visual_check,
        }


class LLMClassifier(Protocol):
    """
    Protocol for LLM-based drift classification.

    Implementations should call an LLM to analyze user text
    against the contract objective and constraints.
    """

    def classify(
        self,
        segment_text: str,
        objective: str,
        constraints_description: str,
        prior_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Classify user text for drift.

        Returns dict with:
        - classification: one of DriftClassification values
        - confidence: 0.0-1.0
        - implicit_constraints: list of implied constraints
        - derived_objective: if pivot detected, what the new objective is
        - reasoning: explanation of classification
        """
        ...


# Legacy pivot keywords for fallback
PIVOT_KEYWORDS = ("actually,", "on second thought,", "let's pivot", "instead,", "forget that,", "change of plans,")

# Keywords suggesting refinement (narrowing)
REFINEMENT_KEYWORDS = ("specifically,", "to clarify,", "more precisely,", "in particular,")

# Keywords suggesting extension
EXTENSION_KEYWORDS = ("also,", "additionally,", "and another thing,", "plus,", "as well as,")

# Keywords suggesting adversarial intent
ADVERSARIAL_KEYWORDS = ("ignore previous", "disregard", "pretend", "bypass", "override")


def _extract_keyword_signals(text: str) -> Dict[str, List[str]]:
    """
    Extract keyword-based signals from text.

    Returns dict mapping signal type to matched keywords.
    """
    signals: Dict[str, List[str]] = {
        "pivot": [],
        "refinement": [],
        "extension": [],
        "adversarial": [],
    }

    lowered = text.lower().strip()

    for kw in PIVOT_KEYWORDS:
        if kw in lowered:
            signals["pivot"].append(kw)

    for kw in REFINEMENT_KEYWORDS:
        if kw in lowered:
            signals["refinement"].append(kw)

    for kw in EXTENSION_KEYWORDS:
        if kw in lowered:
            signals["extension"].append(kw)

    for kw in ADVERSARIAL_KEYWORDS:
        if kw in lowered:
            signals["adversarial"].append(kw)

    return signals


def _derive_objective_from_text(text: str) -> str:
    """
    Attempt to extract a new objective from pivot text.

    This is a simple heuristic - LLM does better.
    """
    lowered = text.lower().strip()

    # Remove pivot keywords and take the rest
    for kw in PIVOT_KEYWORDS:
        if lowered.startswith(kw):
            return text[len(kw):].strip() or "Update objective based on user instruction"

    # If no keyword prefix, return the whole thing as the new objective hint
    return text.strip()[:200]  # Truncate for safety


class DriftDetector:
    """
    Base drift detector - uses keyword heuristics.

    This is the fallback when LLM is unavailable.
    """

    def analyze(
        self,
        segment_text: str,
        contract: ContractLike,
        existing_constraints: Optional[ConstraintSet] = None,
    ) -> DriftAnalysis:
        """
        Analyze text for drift using keyword heuristics.
        """
        signals = _extract_keyword_signals(segment_text)

        # Priority: adversarial > pivot > extension > refinement > continuation
        if signals["adversarial"]:
            return DriftAnalysis(
                classification=DriftClassification.ADVERSARIAL,
                confidence=0.8,
                apparent_intent="Attempting to circumvent constraints",
                classification_method="keyword",
                suggested_resolution="This input appears to be attempting to bypass safety constraints",
            )

        if signals["pivot"]:
            return DriftAnalysis(
                classification=DriftClassification.PIVOT,
                confidence=0.7,
                derived_objective=_derive_objective_from_text(segment_text),
                classification_method="keyword",
                suggested_resolution="Consider amending the contract with the new objective",
            )

        if signals["extension"]:
            return DriftAnalysis(
                classification=DriftClassification.EXTENSION,
                confidence=0.6,
                classification_method="keyword",
                suggested_resolution="New scope elements may need to be added to the contract",
            )

        if signals["refinement"]:
            return DriftAnalysis(
                classification=DriftClassification.REFINEMENT,
                confidence=0.6,
                classification_method="keyword",
            )

        # Default: continuation (no drift signals detected)
        return DriftAnalysis(
            classification=DriftClassification.CONTINUATION,
            confidence=0.5,  # Low confidence since we're just not detecting signals
            classification_method="keyword",
        )


class ObstructionAwareDriftDetector(DriftDetector):
    """
    Advanced drift detector that combines:
    1. Keyword heuristics (fast, fallback)
    2. Constraint compatibility checking (deterministic)
    3. LLM classification (semantic, when available)
    4. Multimodal constraint routing (text/visual)

    This is the main detector for production use.

    The Fong Bridge: Unified handling of text (West) and visual (East)
    constraints under the same sheaf model.
    """

    def __init__(
        self,
        llm_classifier: Optional[LLMClassifier] = None,
        llm_timeout: float = 2.0,
        use_keyword_prefilter: bool = True,
    ):
        self.llm_classifier = llm_classifier
        self.llm_timeout = llm_timeout
        self.use_keyword_prefilter = use_keyword_prefilter

    def _extract_visual_constraints(
        self,
        existing_constraints: ConstraintSet,
    ) -> List[NormalizedConstraint]:
        """
        Extract visual constraints that need VLM verification.

        These are the "East" constraints that apply to image outputs.
        """
        visual_constraints = []
        for constraint in existing_constraints:
            modality = get_constraint_modality(constraint)
            if modality in {"visual", "multimodal"}:
                visual_constraints.append(constraint)
        return visual_constraints

    def _detect_image_generation_context(self, segment_text: str) -> bool:
        """
        Detect if the user is requesting image generation.

        This determines whether visual constraints should be flagged
        for verification.
        """
        image_keywords = [
            "generate an image",
            "create an image",
            "draw",
            "make a picture",
            "generate artwork",
            "create a visual",
            "design a",
            "illustrate",
            "render",
            "produce an image",
            "create a logo",
            "make a graphic",
            "generate a diagram",
            "create an illustration",
        ]

        lowered = segment_text.lower()
        return any(kw in lowered for kw in image_keywords)

    def _extract_implicit_constraints(
        self,
        segment_text: str,
        llm_response: Optional[Dict[str, Any]] = None,
    ) -> List[ImplicitConstraint]:
        """
        Extract constraints implied by the user's text.

        Uses LLM response if available, falls back to heuristics.
        """
        implicit = []

        # If LLM provided implicit constraints, use those
        if llm_response and "implicit_constraints" in llm_response:
            for ic in llm_response["implicit_constraints"]:
                constraint = create_semantic_constraint(
                    topic=ic.get("topic", ic.get("description", "unknown")),
                    source_id=f"implicit_{len(implicit)}",
                    severity=Severity.P1,
                )
                implicit.append(ImplicitConstraint(
                    constraint=constraint,
                    confidence=ic.get("confidence", 0.5),
                    evidence=ic.get("evidence", segment_text[:100]),
                    extraction_method="llm",
                ))
            return implicit

        # Heuristic extraction based on text patterns
        # Look for "should", "must", "need to", etc.
        obligation_patterns = [
            (r"(?:should|must|need to|have to|required to)\s+(.+?)(?:\.|$)", "positive"),
            (r"(?:should not|must not|cannot|can't|shouldn't)\s+(.+?)(?:\.|$)", "negative"),
        ]

        for pattern, polarity in obligation_patterns:
            matches = re.findall(pattern, segment_text, re.IGNORECASE)
            for match in matches:
                constraint = NormalizedConstraint(
                    constraint_type=ConstraintType.SEMANTIC_INTENT,
                    polarity=ConstraintPolarity.POSITIVE if polarity == "positive" else ConstraintPolarity.NEGATIVE,
                    target=match.strip()[:100],
                    severity=Severity.P1,
                    source_id=f"implicit_{len(implicit)}",
                )
                implicit.append(ImplicitConstraint(
                    constraint=constraint,
                    confidence=0.4,  # Low confidence for heuristic
                    evidence=match,
                    extraction_method="keyword",
                ))

        return implicit

    def _build_constraints_description(self, contract: ContractLike) -> str:
        """Build a natural language description of current constraints."""
        parts = [f"Objective: {contract.objective}"]

        if contract.objective_success_criteria:
            parts.append("Success criteria:")
            for criterion in contract.objective_success_criteria:
                parts.append(f"  - {criterion}")

        if contract.constraints:
            parts.append("Constraints:")
            for c in contract.constraints:
                parts.append(f"  - [{c.severity.value}] {c.description}")

        return "\n".join(parts)

    def analyze(
        self,
        segment_text: str,
        contract: ContractLike,
        existing_constraints: Optional[ConstraintSet] = None,
    ) -> DriftAnalysis:
        """
        Comprehensive drift analysis combining multiple methods.
        """
        # Step 1: Quick keyword prefilter
        if self.use_keyword_prefilter:
            signals = _extract_keyword_signals(segment_text)

            # Fast path for obvious adversarial attempts
            if signals["adversarial"]:
                return DriftAnalysis(
                    classification=DriftClassification.ADVERSARIAL,
                    confidence=0.9,
                    apparent_intent="Attempting to circumvent constraints",
                    classification_method="keyword_prefilter",
                    suggested_resolution="Input rejected - appears to be attempting constraint bypass",
                )

        # Step 2: Try LLM classification if available
        llm_response = None
        if self.llm_classifier:
            try:
                constraints_desc = self._build_constraints_description(contract)
                llm_response = self.llm_classifier.classify(
                    segment_text=segment_text,
                    objective=contract.objective,
                    constraints_description=constraints_desc,
                )
            except Exception:
                # LLM unavailable, fall back to other methods
                pass

        # Step 3: Extract implicit constraints
        implicit_constraints = self._extract_implicit_constraints(segment_text, llm_response)

        # Step 4: Build constraint set for compatibility check
        if existing_constraints is None:
            # Build ConstraintSet inline from contract
            existing_constraints = ConstraintSet(source_session_id=contract.session_id)
            for c in contract.constraints:
                existing_constraints.add_from_contract(c)

        incoming_constraints = ConstraintSet()
        for ic in implicit_constraints:
            incoming_constraints.add(ic.constraint)

        # Step 5: Check compatibility
        compatibility = check_compatibility(existing_constraints, incoming_constraints)

        # Step 6: Determine classification based on all signals
        classification = self._determine_classification(
            signals=_extract_keyword_signals(segment_text) if self.use_keyword_prefilter else {},
            compatibility=compatibility,
            llm_response=llm_response,
        )

        # Step 7: Detect multimodal context
        is_image_context = self._detect_image_generation_context(segment_text)
        visual_constraints = self._extract_visual_constraints(existing_constraints)

        modalities = ["text"]
        if is_image_context and visual_constraints:
            modalities.append("visual")

        # Step 8: Build final analysis
        analysis = DriftAnalysis(
            classification=classification,
            confidence=self._compute_confidence(classification, llm_response, compatibility),
            implicit_constraints=implicit_constraints,
            compatibility=compatibility,
            obstructions=compatibility.obstructions,
            classification_method="hybrid" if llm_response else "deterministic",
            llm_response=llm_response,
            # Multimodal fields
            modalities=modalities,
            visual_constraints_to_check=visual_constraints if is_image_context else [],
            requires_visual_check=is_image_context and len(visual_constraints) > 0,
        )

        # Add derived objective for pivot
        if classification == DriftClassification.PIVOT:
            if llm_response and llm_response.get("derived_objective"):
                analysis.derived_objective = llm_response["derived_objective"]
            else:
                analysis.derived_objective = _derive_objective_from_text(segment_text)
            analysis.suggested_resolution = "Consider amending the contract with the new objective"

        # Add resolution suggestions for other cases
        if classification == DriftClassification.CONTRADICTION:
            if compatibility.obstructions:
                obs = compatibility.obstructions[0]
                analysis.suggested_resolution = obs.suggested_resolution
            else:
                analysis.suggested_resolution = "Input conflicts with existing constraints"

        return analysis

    def _determine_classification(
        self,
        signals: Dict[str, List[str]],
        compatibility: CompatibilityResult,
        llm_response: Optional[Dict[str, Any]],
    ) -> DriftClassification:
        """
        Determine final classification from all available signals.
        """
        # LLM classification takes priority if confident
        if llm_response:
            llm_class = llm_response.get("classification", "")
            # Handle case where LLM returns a list instead of string
            if isinstance(llm_class, list):
                llm_class = llm_class[0] if llm_class else ""
            llm_class = str(llm_class).lower()
            llm_conf = llm_response.get("confidence", 0)

            if llm_conf > 0.7:
                try:
                    return DriftClassification(llm_class)
                except ValueError:
                    pass  # Invalid classification, fall through

        # Compatibility-based classification
        if compatibility.status == CompatibilityStatus.CONTRADICTORY:
            # Check if it's adversarial vs honest contradiction
            if signals.get("adversarial"):
                return DriftClassification.ADVERSARIAL
            return DriftClassification.CONTRADICTION

        if compatibility.status == CompatibilityStatus.WIDENING:
            if signals.get("pivot"):
                return DriftClassification.PIVOT
            return DriftClassification.EXTENSION

        if compatibility.status == CompatibilityStatus.NARROWING:
            return DriftClassification.REFINEMENT

        # Keyword-based if compatibility doesn't give clear signal
        if signals.get("pivot"):
            return DriftClassification.PIVOT

        if signals.get("extension"):
            return DriftClassification.EXTENSION

        if signals.get("refinement"):
            return DriftClassification.REFINEMENT

        return DriftClassification.CONTINUATION

    def _compute_confidence(
        self,
        classification: DriftClassification,
        llm_response: Optional[Dict[str, Any]],
        compatibility: CompatibilityResult,
    ) -> float:
        """
        Compute confidence score for the classification.
        """
        confidences = []

        # LLM confidence
        if llm_response and "confidence" in llm_response:
            confidences.append(llm_response["confidence"])

        # Compatibility-based confidence
        if compatibility.status == CompatibilityStatus.CONTRADICTORY:
            # Hard obstructions give high confidence
            if compatibility.has_hard_obstructions():
                confidences.append(0.9)
            else:
                confidences.append(0.7)
        elif compatibility.status == CompatibilityStatus.COMPATIBLE:
            if classification == DriftClassification.CONTINUATION:
                confidences.append(0.8)
            else:
                confidences.append(0.5)  # Compatible but classified as drift

        # Base confidence if nothing else
        if not confidences:
            confidences.append(0.5)

        return max(confidences)


def create_drift_detector(
    llm_classifier: Optional[LLMClassifier] = None,
    mode: str = "hybrid",
) -> DriftDetector:
    """
    Factory function to create appropriate drift detector.

    Args:
        llm_classifier: Optional LLM classifier for semantic analysis
        mode: "keyword" (fast), "deterministic" (constraint-based), or "hybrid" (all)

    Returns:
        Configured DriftDetector instance
    """
    if mode == "keyword":
        return DriftDetector()

    return ObstructionAwareDriftDetector(
        llm_classifier=llm_classifier,
        use_keyword_prefilter=(mode == "hybrid"),
    )
