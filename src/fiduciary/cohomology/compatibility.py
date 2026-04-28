"""
Constraint compatibility checking and obstruction detection.

This is the core of the sheaf-theoretic model:
- Two constraint sets are "compatible" if they can be satisfied simultaneously
- An "obstruction" is a pair of constraints that cannot both be satisfied
- Obstructions are the cohomological barriers to gluing local sections

The compatibility check answers: "Can these sessions be glued into
a coherent global section?"
"""

from __future__ import annotations

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


class CompatibilityStatus(str, Enum):
    """Result of compatibility check between constraint sets."""

    COMPATIBLE = "compatible"
    # All constraints can be satisfied together

    NARROWING = "narrowing"
    # New constraints are stricter but compatible (subset relationship)

    WIDENING = "widening"
    # New constraints are looser (may need explicit approval)

    CONTRADICTORY = "contradictory"
    # Constraints conflict - cannot both be satisfied

    UNKNOWN = "unknown"
    # Could not determine (e.g., semantic constraints need LLM)


@dataclass
class Obstruction:
    """
    Represents a cohomological obstruction - a pair of constraints
    that cannot both be satisfied.

    This is the H^1 element that prevents gluing.
    """
    constraint_a: NormalizedConstraint
    constraint_b: NormalizedConstraint
    obstruction_type: str  # Description of why they conflict
    severity: str  # "hard" (impossible) or "soft" (difficult)
    suggested_resolution: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "constraint_a": constraint_a.to_dict() if (constraint_a := self.constraint_a) else None,
            "constraint_b": constraint_b.to_dict() if (constraint_b := self.constraint_b) else None,
            "obstruction_type": self.obstruction_type,
            "severity": self.severity,
            "suggested_resolution": self.suggested_resolution,
        }


@dataclass
class CompatibilityResult:
    """
    Result of checking compatibility between constraint sets.
    """
    status: CompatibilityStatus
    obstructions: List[Obstruction] = field(default_factory=list)
    narrowed_constraints: List[NormalizedConstraint] = field(default_factory=list)
    widened_constraints: List[NormalizedConstraint] = field(default_factory=list)
    unknown_constraints: List[NormalizedConstraint] = field(default_factory=list)

    # For semantic constraints that need LLM analysis
    requires_semantic_check: bool = False
    semantic_check_pairs: List[Tuple[NormalizedConstraint, NormalizedConstraint]] = field(default_factory=list)

    def is_compatible(self) -> bool:
        """Returns True if constraints can be satisfied together."""
        return self.status in {CompatibilityStatus.COMPATIBLE, CompatibilityStatus.NARROWING}

    def has_hard_obstructions(self) -> bool:
        """Returns True if there are impossible-to-resolve conflicts."""
        return any(o.severity == "hard" for o in self.obstructions)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "obstructions": [o.to_dict() for o in self.obstructions],
            "narrowed_constraints": [c.to_dict() for c in self.narrowed_constraints],
            "widened_constraints": [c.to_dict() for c in self.widened_constraints],
            "requires_semantic_check": self.requires_semantic_check,
        }


class SemanticChecker(Protocol):
    """
    Protocol for semantic compatibility checking (Text & Vision).

    The dual-modality checker for the Bridge between West (Text) and East (Vision).

    Implementations can use embeddings, LLM calls, or VLM (CLIP/LLaVA)
    to determine if semantic constraints are compatible.
    """

    def check_semantic_compatibility(
        self,
        constraint_a: NormalizedConstraint,
        constraint_b: NormalizedConstraint,
    ) -> Tuple[bool, float, Optional[str]]:
        """
        Check if two semantic constraints are compatible.

        Returns:
            (is_compatible, confidence, explanation)
        """
        ...

    def check_visual_adherence(
        self,
        image_bytes: bytes,
        constraint: NormalizedConstraint,
    ) -> Tuple[bool, float, Optional[str]]:
        """
        Check if a generated image adheres to a visual constraint.

        This is the "East" counterpart to text-based semantic checking.

        Implementation options:
        1. CLIP: Compute image-text similarity for style/content constraints
        2. LLaVA: Ask "Does this image contain [target]?" or "Is this [style]?"
        3. Color extraction: For palette/dominant color constraints
        4. Dimension check: For aspect ratio constraints

        Args:
            image_bytes: Raw image data (PNG, JPEG, etc.)
            constraint: The visual constraint to check

        Returns:
            (passes, confidence, explanation)
            - passes: True if image satisfies the constraint
            - confidence: 0.0 to 1.0 confidence score
            - explanation: Human-readable description of the check result
        """
        ...


def _regex_patterns_conflict(pattern_a: str, pattern_b: str) -> bool:
    """
    Check if two regex patterns are inherently conflicting.

    This is an approximation - true regex intersection is undecidable
    in general, but we can catch common cases.
    """
    # Simple heuristic: if patterns are the same, they don't conflict with themselves
    if pattern_a == pattern_b:
        return False

    # Check for obvious conflicts:
    # - One requires X, other forbids X (handled at higher level)
    # - Both forbid everything (unlikely but check)

    try:
        # Compile to validate
        re.compile(pattern_a)
        re.compile(pattern_b)
    except re.error:
        # Invalid regex - can't determine conflict
        return False

    # For now, assume non-identical patterns might conflict
    # A more sophisticated implementation could use regex analysis
    return False


def _heading_constraints_conflict(
    positive_headings: Set[str],
    positive_patterns: Set[str],
    negative_patterns: Set[str],
) -> List[Tuple[str, str, str]]:
    """
    Check for conflicts between heading requirements and regex patterns.

    Returns list of (heading, pattern, conflict_type) tuples.
    """
    conflicts = []

    for heading in positive_headings:
        for pattern in negative_patterns:
            try:
                if re.search(pattern, heading, re.IGNORECASE | re.MULTILINE):
                    conflicts.append((
                        heading,
                        pattern,
                        "required_heading_matches_forbidden_pattern",
                    ))
            except re.error:
                pass

    return conflicts


def _parse_hex_colors(color_string: str) -> Set[str]:
    """Parse a comma-separated list of hex colors."""
    return {c.strip().upper() for c in color_string.split(",") if c.strip()}


def _check_visual_deterministic_conflicts(
    constraint: NormalizedConstraint,
    existing: ConstraintSet,
    obstructions: List[Obstruction],
    narrowed: List[NormalizedConstraint],
) -> None:
    """
    Check for conflicts between visual deterministic constraints.

    Handles:
    - COLOR_PALETTE vs COLOR_FORBIDDEN conflicts
    - COLOR_DOMINANT vs COLOR_FORBIDDEN conflicts
    - ASPECT_RATIO conflicts (different required ratios)
    """
    ct = constraint.constraint_type

    if ct == ConstraintType.COLOR_PALETTE:
        # Check if required colors are forbidden
        required_colors = _parse_hex_colors(constraint.target)

        for existing_c in existing.get_by_type(ConstraintType.COLOR_FORBIDDEN):
            forbidden_colors = _parse_hex_colors(existing_c.target)
            overlap = required_colors & forbidden_colors

            if overlap:
                obstructions.append(Obstruction(
                    constraint_a=existing_c,
                    constraint_b=constraint,
                    obstruction_type="required_color_is_forbidden",
                    severity="hard",
                    suggested_resolution=f"Color(s) {overlap} cannot be both required and forbidden",
                ))

        if not obstructions:
            narrowed.append(constraint)

    elif ct == ConstraintType.COLOR_FORBIDDEN:
        # Check if forbidden colors are required
        forbidden_colors = _parse_hex_colors(constraint.target)

        for existing_c in existing.get_by_type(ConstraintType.COLOR_PALETTE):
            required_colors = _parse_hex_colors(existing_c.target)
            overlap = required_colors & forbidden_colors

            if overlap:
                obstructions.append(Obstruction(
                    constraint_a=existing_c,
                    constraint_b=constraint,
                    obstruction_type="forbidden_color_is_required",
                    severity="hard",
                    suggested_resolution=f"Color(s) {overlap} cannot be both required and forbidden",
                ))

        # Also check against dominant color
        for existing_c in existing.get_by_type(ConstraintType.COLOR_DOMINANT):
            dominant_colors = _parse_hex_colors(existing_c.target)
            overlap = dominant_colors & forbidden_colors

            if overlap:
                obstructions.append(Obstruction(
                    constraint_a=existing_c,
                    constraint_b=constraint,
                    obstruction_type="forbidden_color_is_dominant",
                    severity="hard",
                    suggested_resolution=f"Dominant color {overlap} cannot be forbidden",
                ))

        if not obstructions:
            narrowed.append(constraint)

    elif ct == ConstraintType.COLOR_DOMINANT:
        # Check if dominant color is forbidden
        dominant_colors = _parse_hex_colors(constraint.target)

        for existing_c in existing.get_by_type(ConstraintType.COLOR_FORBIDDEN):
            forbidden_colors = _parse_hex_colors(existing_c.target)
            overlap = dominant_colors & forbidden_colors

            if overlap:
                obstructions.append(Obstruction(
                    constraint_a=existing_c,
                    constraint_b=constraint,
                    obstruction_type="dominant_color_is_forbidden",
                    severity="hard",
                    suggested_resolution=f"Dominant color {overlap} is in forbidden list",
                ))

        # Check for conflicting dominant color requirements
        for existing_c in existing.get_by_type(ConstraintType.COLOR_DOMINANT):
            existing_dominant = _parse_hex_colors(existing_c.target)
            if dominant_colors != existing_dominant:
                obstructions.append(Obstruction(
                    constraint_a=existing_c,
                    constraint_b=constraint,
                    obstruction_type="conflicting_dominant_colors",
                    severity="hard",
                    suggested_resolution=f"Cannot have multiple different dominant colors: {existing_dominant} vs {dominant_colors}",
                ))

        if not obstructions:
            narrowed.append(constraint)

    elif ct == ConstraintType.ASPECT_RATIO:
        # Check for conflicting aspect ratio requirements
        for existing_c in existing.get_by_type(ConstraintType.ASPECT_RATIO):
            if existing_c.target != constraint.target:
                obstructions.append(Obstruction(
                    constraint_a=existing_c,
                    constraint_b=constraint,
                    obstruction_type="conflicting_aspect_ratios",
                    severity="hard",
                    suggested_resolution=f"Cannot require both {existing_c.target} and {constraint.target} aspect ratios",
                ))

        if not obstructions:
            narrowed.append(constraint)

    else:
        # Default: treat as narrowing
        narrowed.append(constraint)


def _check_deterministic_compatibility(
    existing: ConstraintSet,
    incoming: ConstraintSet,
) -> CompatibilityResult:
    """
    Check compatibility of deterministic (non-semantic) constraints.

    This handles:
    - MUST_INCLUDE_HEADING
    - MUST_INCLUDE_REGEX
    - MUST_NOT_INCLUDE_REGEX
    """
    obstructions: List[Obstruction] = []
    narrowed: List[NormalizedConstraint] = []
    widened: List[NormalizedConstraint] = []
    unknown: List[NormalizedConstraint] = []

    # Collect existing constraints by type
    existing_positive_headings = {
        c.target for c in existing.get_by_type(ConstraintType.MUST_INCLUDE_HEADING)
    }
    existing_negative_patterns = {
        c.target for c in existing.get_by_type(ConstraintType.MUST_NOT_INCLUDE_REGEX)
    }
    existing_positive_patterns = {
        c.target for c in existing.get_by_type(ConstraintType.MUST_INCLUDE_REGEX)
    }

    # Check each incoming constraint
    for constraint in incoming:
        if constraint.constraint_type == ConstraintType.MUST_INCLUDE_HEADING:
            # Check if this heading is forbidden by an existing negative pattern
            for neg_pattern in existing_negative_patterns:
                try:
                    if re.search(neg_pattern, constraint.target, re.IGNORECASE | re.MULTILINE):
                        # Find the constraining negative constraint
                        neg_constraint = next(
                            c for c in existing.get_by_type(ConstraintType.MUST_NOT_INCLUDE_REGEX)
                            if c.target == neg_pattern
                        )
                        obstructions.append(Obstruction(
                            constraint_a=neg_constraint,
                            constraint_b=constraint,
                            obstruction_type="required_heading_matches_forbidden_pattern",
                            severity="hard",
                            suggested_resolution=f"Remove heading requirement '{constraint.target}' or relax pattern '{neg_pattern}'",
                        ))
                except (re.error, StopIteration):
                    pass

            # If heading already required, this is narrowing (redundant)
            if constraint.target in existing_positive_headings:
                narrowed.append(constraint)
            elif constraint.target not in existing_positive_headings:
                # New heading requirement - check if it's stricter
                narrowed.append(constraint)

        elif constraint.constraint_type == ConstraintType.MUST_NOT_INCLUDE_REGEX:
            # Check if this pattern would forbid required content
            for pos_heading in existing_positive_headings:
                try:
                    if re.search(constraint.target, pos_heading, re.IGNORECASE | re.MULTILINE):
                        pos_constraint = next(
                            c for c in existing.get_by_type(ConstraintType.MUST_INCLUDE_HEADING)
                            if c.target == pos_heading
                        )
                        obstructions.append(Obstruction(
                            constraint_a=pos_constraint,
                            constraint_b=constraint,
                            obstruction_type="forbidden_pattern_matches_required_heading",
                            severity="hard",
                            suggested_resolution=f"Relax pattern '{constraint.target}' to not match '{pos_heading}'",
                        ))
                except (re.error, StopIteration):
                    pass

            # Check against positive patterns
            for pos_pattern in existing_positive_patterns:
                # If patterns overlap significantly, there might be a conflict
                # This is approximate
                try:
                    # Create test strings that match the positive pattern
                    # and check if they'd be forbidden
                    # For now, flag as needing review if patterns are similar
                    if pos_pattern == constraint.target:
                        pos_constraint = next(
                            c for c in existing.get_by_type(ConstraintType.MUST_INCLUDE_REGEX)
                            if c.target == pos_pattern
                        )
                        obstructions.append(Obstruction(
                            constraint_a=pos_constraint,
                            constraint_b=constraint,
                            obstruction_type="forbidden_pattern_equals_required_pattern",
                            severity="hard",
                            suggested_resolution="These constraints directly contradict each other",
                        ))
                except StopIteration:
                    pass

            narrowed.append(constraint)  # Adding restrictions is narrowing

        elif constraint.constraint_type == ConstraintType.MUST_INCLUDE_REGEX:
            # Check if this pattern is forbidden
            if constraint.target in existing_negative_patterns:
                neg_constraint = next(
                    c for c in existing.get_by_type(ConstraintType.MUST_NOT_INCLUDE_REGEX)
                    if c.target == constraint.target
                )
                obstructions.append(Obstruction(
                    constraint_a=neg_constraint,
                    constraint_b=constraint,
                    obstruction_type="required_pattern_is_forbidden",
                    severity="hard",
                    suggested_resolution="Remove one of the conflicting pattern constraints",
                ))

            if constraint.target in existing_positive_patterns:
                narrowed.append(constraint)
            else:
                narrowed.append(constraint)

        elif constraint.constraint_type in {
            ConstraintType.SEMANTIC_TOPIC,
            ConstraintType.SEMANTIC_TONE,
            ConstraintType.SEMANTIC_INTENT,
        }:
            # Semantic constraints need LLM analysis
            unknown.append(constraint)

        elif constraint.constraint_type in {
            ConstraintType.VISUAL_STYLE,
            ConstraintType.VISUAL_MOOD,
            ConstraintType.IMAGE_MUST_CONTAIN,
            ConstraintType.IMAGE_MUST_NOT_CONTAIN,
            ConstraintType.VISUAL_COMPLEXITY,
        }:
            # Visual semantic constraints need VLM analysis
            unknown.append(constraint)

        elif constraint.constraint_type in {
            ConstraintType.COLOR_PALETTE,
            ConstraintType.COLOR_FORBIDDEN,
            ConstraintType.COLOR_DOMINANT,
            ConstraintType.ASPECT_RATIO,
        }:
            # Deterministic visual constraints - check for conflicts
            _check_visual_deterministic_conflicts(
                constraint, existing, obstructions, narrowed
            )

        elif constraint.constraint_type in {
            ConstraintType.BRAND_IDENTITY,
            ConstraintType.MULTIMODAL_COHERENCE,
        }:
            # Cross-modal constraints need both LLM and VLM
            unknown.append(constraint)

        else:
            # Unknown constraint type - mark for review
            unknown.append(constraint)

    # Determine overall status
    if obstructions:
        status = CompatibilityStatus.CONTRADICTORY
    elif unknown:
        status = CompatibilityStatus.UNKNOWN
    elif widened:
        status = CompatibilityStatus.WIDENING
    elif narrowed:
        status = CompatibilityStatus.NARROWING
    else:
        status = CompatibilityStatus.COMPATIBLE

    return CompatibilityResult(
        status=status,
        obstructions=obstructions,
        narrowed_constraints=narrowed,
        widened_constraints=widened,
        unknown_constraints=unknown,
        requires_semantic_check=len(unknown) > 0,
    )


def check_compatibility(
    existing: ConstraintSet,
    incoming: ConstraintSet,
    semantic_checker: Optional[SemanticChecker] = None,
) -> CompatibilityResult:
    """
    Check if two constraint sets are compatible.

    This is the core compatibility function - it determines if the
    constraints from two sessions can be satisfied simultaneously.

    Args:
        existing: The accumulated constraints from prior sessions
        incoming: New constraints being added
        semantic_checker: Optional checker for semantic constraints

    Returns:
        CompatibilityResult with status and any obstructions found
    """
    # First, check deterministic constraints
    result = _check_deterministic_compatibility(existing, incoming)

    # If we have semantic constraints and a checker, analyze them
    if result.requires_semantic_check and semantic_checker:
        # Collect all semantic constraints
        existing_semantic = {
            c for c in existing
            if c.constraint_type in {
                ConstraintType.SEMANTIC_TOPIC,
                ConstraintType.SEMANTIC_TONE,
                ConstraintType.SEMANTIC_INTENT,
            }
        }

        # Check each unknown (semantic) constraint against existing semantic ones
        still_unknown = []
        for constraint in result.unknown_constraints:
            if constraint.constraint_type not in {
                ConstraintType.SEMANTIC_TOPIC,
                ConstraintType.SEMANTIC_TONE,
                ConstraintType.SEMANTIC_INTENT,
            }:
                still_unknown.append(constraint)
                continue

            # Check against each existing semantic constraint of same type
            for existing_c in existing_semantic:
                if existing_c.constraint_type != constraint.constraint_type:
                    continue

                is_compat, confidence, explanation = semantic_checker.check_semantic_compatibility(
                    existing_c,
                    constraint,
                )

                if not is_compat and confidence > 0.7:
                    result.obstructions.append(Obstruction(
                        constraint_a=existing_c,
                        constraint_b=constraint,
                        obstruction_type="semantic_conflict",
                        severity="soft" if confidence < 0.9 else "hard",
                        suggested_resolution=explanation,
                    ))

            # If no conflicts found, classify as narrowing or widening
            # (semantic analysis would be needed to determine which)
            if not any(
                o.constraint_b == constraint
                for o in result.obstructions
            ):
                result.narrowed_constraints.append(constraint)

        result.unknown_constraints = still_unknown
        result.requires_semantic_check = len(still_unknown) > 0

        # Update status based on new findings
        if result.obstructions:
            result.status = CompatibilityStatus.CONTRADICTORY

    return result


def check_soul_invariant_preservation(
    existing: ConstraintSet,
    incoming: ConstraintSet,
) -> List[Obstruction]:
    """
    Check that soul invariants are preserved.

    Soul invariants cannot be:
    - Removed
    - Contradicted by new constraints
    - Weakened

    This is a stricter check than general compatibility.
    """
    obstructions = []

    existing_invariants = existing.get_soul_invariants()
    incoming_keys = {c.canonical_key() for c in incoming}

    for invariant in existing_invariants:
        # Check if invariant is being removed
        if invariant not in incoming.constraints:
            # It's okay if it's not in incoming, but check if a
            # contradicting constraint is present
            pass

        # Check for direct contradictions
        # (positive invariant vs negative incoming, or vice versa)
        for inc in incoming:
            if (
                inc.constraint_type == invariant.constraint_type
                and inc.target == invariant.target
                and inc.polarity != invariant.polarity
            ):
                obstructions.append(Obstruction(
                    constraint_a=invariant,
                    constraint_b=inc,
                    obstruction_type="soul_invariant_contradiction",
                    severity="hard",
                    suggested_resolution="Cannot contradict soul invariant constraints",
                ))

    return obstructions


def merge_constraint_sets(
    existing: ConstraintSet,
    incoming: ConstraintSet,
    compatibility_result: Optional[CompatibilityResult] = None,
) -> ConstraintSet:
    """
    Merge two compatible constraint sets.

    Should only be called after compatibility has been verified.
    Soul invariants from existing set are always preserved.
    """
    if compatibility_result is None:
        compatibility_result = check_compatibility(existing, incoming)

    if not compatibility_result.is_compatible():
        raise ValueError(
            f"Cannot merge incompatible constraint sets: {compatibility_result.status}"
        )

    result = ConstraintSet()

    # Add all existing constraints
    result.constraints = existing.constraints.copy()

    # Add non-conflicting incoming constraints
    for constraint in incoming:
        # Skip if this would duplicate (by canonical key)
        existing_keys = {c.canonical_key() for c in result.constraints}
        if constraint.canonical_key() not in existing_keys:
            result.constraints.add(constraint)

    return result
