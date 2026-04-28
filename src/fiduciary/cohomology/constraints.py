"""
Constraint representation and normalization.

Constraints are the "gluing conditions" in our sheaf model. This module
provides a normalized representation that allows:
- Uniform handling of different constraint types
- Compatibility checking
- Hash-based comparison
- Serialization for cross-session transport
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Set, Union

from fiduciary.models import (
    ContractConstraint,
    ContractLike,
    ConstraintEnforcement,
    EnforcementType,
    Severity,
)


class ConstraintType(str, Enum):
    """
    Classification of constraint types for compatibility analysis.

    The constraint system spans both modalities:
    - Text (West): Deterministic and semantic text constraints
    - Visual (East): Image style, content, and color constraints

    Both modalities are bound by the same soul invariants.
    """

    # === TEXT CONSTRAINTS (West) ===

    # Deterministic constraints - can be checked mechanically
    MUST_INCLUDE_HEADING = "must_include_heading"
    MUST_INCLUDE_REGEX = "must_include_regex"
    MUST_NOT_INCLUDE_REGEX = "must_not_include_regex"

    # Semantic text constraints - require LLM analysis
    SEMANTIC_TOPIC = "semantic_topic"  # Content must be about X
    SEMANTIC_TONE = "semantic_tone"    # Tone must be X
    SEMANTIC_INTENT = "semantic_intent"  # Must align with intent X

    # Structural text constraints
    FORMAT_REQUIRED = "format_required"  # Must include certain structure
    LENGTH_BOUND = "length_bound"  # Min/max length

    # === VISUAL CONSTRAINTS (East) ===

    # Visual style constraints - require VLM (CLIP/LLaVA) analysis
    VISUAL_STYLE = "visual_style"  # e.g., "Swiss Minimalist", "Brutalist", "Art Deco"
    VISUAL_MOOD = "visual_mood"    # e.g., "Professional", "Playful", "Somber"

    # Visual content constraints - what must/must not appear
    IMAGE_MUST_CONTAIN = "image_must_contain"      # e.g., "The Trident", "Logo"
    IMAGE_MUST_NOT_CONTAIN = "image_must_not_contain"  # e.g., "Faces", "Text"

    # Color constraints - enforceable via color extraction
    COLOR_PALETTE = "color_palette"      # Required colors (hex codes)
    COLOR_FORBIDDEN = "color_forbidden"  # Forbidden colors (hex codes)
    COLOR_DOMINANT = "color_dominant"    # Primary color must be X

    # Composition constraints
    ASPECT_RATIO = "aspect_ratio"        # e.g., "16:9", "1:1", "4:3"
    VISUAL_COMPLEXITY = "visual_complexity"  # "minimal", "moderate", "complex"

    # === CROSS-MODAL CONSTRAINTS ===

    # Constraints that span text and image
    BRAND_IDENTITY = "brand_identity"    # Holistic brand enforcement
    MULTIMODAL_COHERENCE = "multimodal_coherence"  # Text and image must align

    # === META CONSTRAINTS ===

    # About the constraint system itself
    SOUL_INVARIANT = "soul_invariant"  # Cannot be removed or contradicted


class ConstraintPolarity(str, Enum):
    """Whether a constraint is positive (must have) or negative (must not have)."""
    POSITIVE = "positive"  # Must include / must be
    NEGATIVE = "negative"  # Must not include / must not be


@dataclass(frozen=True)
class NormalizedConstraint:
    """
    A constraint in normalized form for compatibility checking.

    Frozen (immutable) to allow hashing and use in sets.
    """
    constraint_type: ConstraintType
    polarity: ConstraintPolarity
    target: str  # What the constraint applies to (heading name, regex, topic, etc.)
    severity: Severity
    source_id: str  # Original constraint ID for tracing
    is_soul_invariant: bool = False  # Cannot be removed or overridden

    # For semantic constraints
    semantic_vector: Optional[tuple] = None  # Frozen representation of embedding

    def __hash__(self) -> int:
        # Custom hash that handles the semantic_vector properly
        return hash((
            self.constraint_type,
            self.polarity,
            self.target,
            self.severity,
            self.source_id,
            self.is_soul_invariant,
            self.semantic_vector,
        ))

    def canonical_key(self) -> str:
        """
        Returns a canonical string key for this constraint.
        Used for detecting duplicates and conflicts.
        """
        return f"{self.constraint_type.value}:{self.polarity.value}:{self.target}"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for storage/transport."""
        return {
            "constraint_type": self.constraint_type.value,
            "polarity": self.polarity.value,
            "target": self.target,
            "severity": self.severity.value,
            "source_id": self.source_id,
            "is_soul_invariant": self.is_soul_invariant,
            "semantic_vector": list(self.semantic_vector) if self.semantic_vector else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NormalizedConstraint:
        """Deserialize from dict."""
        return cls(
            constraint_type=ConstraintType(data["constraint_type"]),
            polarity=ConstraintPolarity(data["polarity"]),
            target=data["target"],
            severity=Severity(data["severity"]),
            source_id=data["source_id"],
            is_soul_invariant=data.get("is_soul_invariant", False),
            semantic_vector=tuple(data["semantic_vector"]) if data.get("semantic_vector") else None,
        )


def normalize_contract_constraint(constraint: ContractConstraint) -> NormalizedConstraint:
    """
    Convert a ContractConstraint to normalized form.

    This allows uniform handling of constraints regardless of
    how they were originally specified.
    """
    enforcement = constraint.enforcement

    if enforcement.type == EnforcementType.MUST_INCLUDE_HEADING:
        return NormalizedConstraint(
            constraint_type=ConstraintType.MUST_INCLUDE_HEADING,
            polarity=ConstraintPolarity.POSITIVE,
            target=enforcement.value or "",
            severity=constraint.severity,
            source_id=constraint.id,
        )

    elif enforcement.type == EnforcementType.MUST_INCLUDE_REGEX:
        return NormalizedConstraint(
            constraint_type=ConstraintType.MUST_INCLUDE_REGEX,
            polarity=ConstraintPolarity.POSITIVE,
            target=enforcement.value or "",
            severity=constraint.severity,
            source_id=constraint.id,
        )

    elif enforcement.type == EnforcementType.MUST_NOT_INCLUDE_REGEX:
        return NormalizedConstraint(
            constraint_type=ConstraintType.MUST_NOT_INCLUDE_REGEX,
            polarity=ConstraintPolarity.NEGATIVE,
            target=enforcement.value or "",
            severity=constraint.severity,
            source_id=constraint.id,
        )

    else:
        # Fallback for unknown types
        return NormalizedConstraint(
            constraint_type=ConstraintType.MUST_INCLUDE_REGEX,
            polarity=ConstraintPolarity.POSITIVE,
            target=".*",  # Match anything
            severity=constraint.severity,
            source_id=constraint.id,
        )


@dataclass
class ConstraintSet:
    """
    A set of constraints that can be checked for internal consistency
    and compatibility with other constraint sets.

    This is the "local section" in our sheaf model - the constraints
    active in a particular session or context.
    """
    constraints: Set[NormalizedConstraint] = field(default_factory=set)
    source_session_id: Optional[str] = None

    def add(self, constraint: NormalizedConstraint) -> None:
        """Add a constraint to the set."""
        self.constraints.add(constraint)

    def add_from_contract(self, constraint: ContractConstraint) -> None:
        """Add a constraint from ContractConstraint format."""
        self.constraints.add(normalize_contract_constraint(constraint))

    def remove(self, constraint: NormalizedConstraint) -> bool:
        """
        Remove a constraint if it's not a soul invariant.
        Returns True if removed, False if it's a soul invariant.
        """
        if constraint.is_soul_invariant:
            return False
        self.constraints.discard(constraint)
        return True

    def get_soul_invariants(self) -> Set[NormalizedConstraint]:
        """Get all soul invariant constraints."""
        return {c for c in self.constraints if c.is_soul_invariant}

    def get_by_type(self, constraint_type: ConstraintType) -> Set[NormalizedConstraint]:
        """Get all constraints of a specific type."""
        return {c for c in self.constraints if c.constraint_type == constraint_type}

    def get_positive(self) -> Set[NormalizedConstraint]:
        """Get all positive (must include) constraints."""
        return {c for c in self.constraints if c.polarity == ConstraintPolarity.POSITIVE}

    def get_negative(self) -> Set[NormalizedConstraint]:
        """Get all negative (must not include) constraints."""
        return {c for c in self.constraints if c.polarity == ConstraintPolarity.NEGATIVE}

    def compute_hash(self) -> str:
        """
        Compute a hash of the constraint set for quick comparison.

        This is used for:
        - Quick compatibility pre-check in resume tokens
        - Detecting if constraints have changed
        - Caching compatibility results
        """
        # Sort by canonical key for deterministic ordering
        sorted_constraints = sorted(self.constraints, key=lambda c: c.canonical_key())
        data = [c.to_dict() for c in sorted_constraints]
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def to_dict_list(self) -> List[Dict[str, Any]]:
        """Serialize all constraints to a list of dicts."""
        return [c.to_dict() for c in self.constraints]

    @classmethod
    def from_dict_list(cls, data: List[Dict[str, Any]], source_session_id: Optional[str] = None) -> ConstraintSet:
        """Deserialize from list of dicts."""
        cs = cls(source_session_id=source_session_id)
        for item in data:
            cs.constraints.add(NormalizedConstraint.from_dict(item))
        return cs

    @classmethod
    def from_contract(cls, contract: "ContractLike") -> ConstraintSet:
        """Build a ConstraintSet from a ContractLike object."""
        cs = cls(source_session_id=contract.session_id)
        for constraint in contract.constraints:
            cs.add_from_contract(constraint)
        return cs

    def __len__(self) -> int:
        return len(self.constraints)

    def __iter__(self):
        return iter(self.constraints)

    def __or__(self, other: ConstraintSet) -> ConstraintSet:
        """Union of two constraint sets."""
        result = ConstraintSet()
        result.constraints = self.constraints | other.constraints
        return result

    def __and__(self, other: ConstraintSet) -> ConstraintSet:
        """Intersection of two constraint sets."""
        result = ConstraintSet()
        result.constraints = self.constraints & other.constraints
        return result


# Type alias for constraint that can come from multiple sources
Constraint = Union[ContractConstraint, NormalizedConstraint]


def create_soul_invariant(
    constraint_type: ConstraintType,
    target: str,
    source_id: str,
    polarity: ConstraintPolarity = ConstraintPolarity.POSITIVE,
) -> NormalizedConstraint:
    """
    Create a soul invariant constraint.

    Soul invariants are constraints that:
    - Cannot be removed through amendments
    - Cannot be contradicted by new constraints
    - Persist across all sessions

    These represent the "core identity" of the agent.
    """
    return NormalizedConstraint(
        constraint_type=constraint_type,
        polarity=polarity,
        target=target,
        severity=Severity.P0,  # Soul invariants are always P0
        source_id=source_id,
        is_soul_invariant=True,
    )


def create_semantic_constraint(
    topic: str,
    source_id: str,
    severity: Severity = Severity.P1,
    embedding: Optional[List[float]] = None,
) -> NormalizedConstraint:
    """
    Create a semantic (topic-based) constraint.

    These require LLM or embedding analysis to check.
    """
    return NormalizedConstraint(
        constraint_type=ConstraintType.SEMANTIC_TOPIC,
        polarity=ConstraintPolarity.POSITIVE,
        target=topic,
        severity=severity,
        source_id=source_id,
        semantic_vector=tuple(embedding) if embedding else None,
    )


# =============================================================================
# VISUAL CONSTRAINT CREATORS (East)
# =============================================================================


def create_visual_style_constraint(
    style: str,
    source_id: str,
    severity: Severity = Severity.P1,
    style_embedding: Optional[List[float]] = None,
) -> NormalizedConstraint:
    """
    Create a visual style constraint.

    Examples:
        - "Swiss Minimalist"
        - "Brutalist"
        - "Art Deco"
        - "Oxblood Legal" (brand-specific)

    Requires VLM (CLIP/LLaVA) for verification.
    """
    return NormalizedConstraint(
        constraint_type=ConstraintType.VISUAL_STYLE,
        polarity=ConstraintPolarity.POSITIVE,
        target=style,
        severity=severity,
        source_id=source_id,
        semantic_vector=tuple(style_embedding) if style_embedding else None,
    )


def create_color_constraint(
    colors: List[str],
    source_id: str,
    constraint_type: ConstraintType = ConstraintType.COLOR_PALETTE,
    severity: Severity = Severity.P1,
) -> NormalizedConstraint:
    """
    Create a color constraint.

    Args:
        colors: List of hex color codes (e.g., ["#4A0404", "#FFFFFF"])
        source_id: Constraint ID
        constraint_type: COLOR_PALETTE, COLOR_FORBIDDEN, or COLOR_DOMINANT
        severity: Constraint severity

    Examples:
        - Oxblood brand: create_color_constraint(["#4A0404"], "brand_primary", COLOR_DOMINANT)
        - Forbidden blue: create_color_constraint(["#0000FF"], "no_blue", COLOR_FORBIDDEN)
    """
    # Normalize hex codes to uppercase
    normalized_colors = [c.upper() if c.startswith("#") else f"#{c.upper()}" for c in colors]
    target = ",".join(normalized_colors)

    polarity = ConstraintPolarity.NEGATIVE if constraint_type == ConstraintType.COLOR_FORBIDDEN else ConstraintPolarity.POSITIVE

    return NormalizedConstraint(
        constraint_type=constraint_type,
        polarity=polarity,
        target=target,
        severity=severity,
        source_id=source_id,
    )


def create_image_content_constraint(
    content: str,
    source_id: str,
    must_contain: bool = True,
    severity: Severity = Severity.P1,
    content_embedding: Optional[List[float]] = None,
) -> NormalizedConstraint:
    """
    Create an image content constraint.

    Args:
        content: What the image must/must not contain (e.g., "The Trident", "Logo", "Faces")
        source_id: Constraint ID
        must_contain: True for must contain, False for must not contain
        severity: Constraint severity
        content_embedding: Optional CLIP embedding of the content concept

    Examples:
        - Logo required: create_image_content_constraint("Company Logo", "logo_required", True)
        - No faces: create_image_content_constraint("Human Faces", "no_faces", False, Severity.P0)
    """
    return NormalizedConstraint(
        constraint_type=ConstraintType.IMAGE_MUST_CONTAIN if must_contain else ConstraintType.IMAGE_MUST_NOT_CONTAIN,
        polarity=ConstraintPolarity.POSITIVE if must_contain else ConstraintPolarity.NEGATIVE,
        target=content,
        severity=severity,
        source_id=source_id,
        semantic_vector=tuple(content_embedding) if content_embedding else None,
    )


def create_brand_identity_constraint(
    brand_spec: str,
    source_id: str,
    severity: Severity = Severity.P0,
    brand_embedding: Optional[List[float]] = None,
) -> NormalizedConstraint:
    """
    Create a cross-modal brand identity constraint.

    This is typically a soul invariant that enforces holistic brand
    consistency across both text and visual outputs.

    Args:
        brand_spec: Brand specification string (e.g., "Swiss Legal / Oxblood #4A0404 / Professional")
        source_id: Constraint ID
        severity: Usually P0 for brand identity
        brand_embedding: Optional multimodal embedding of brand identity

    The brand_spec should encode:
        - Visual style (Swiss Legal)
        - Primary color (Oxblood #4A0404)
        - Tone (Professional)
    """
    return NormalizedConstraint(
        constraint_type=ConstraintType.BRAND_IDENTITY,
        polarity=ConstraintPolarity.POSITIVE,
        target=brand_spec,
        severity=severity,
        source_id=source_id,
        is_soul_invariant=True,  # Brand identity is typically soul-level
        semantic_vector=tuple(brand_embedding) if brand_embedding else None,
    )


def create_aspect_ratio_constraint(
    ratio: str,
    source_id: str,
    severity: Severity = Severity.P1,
) -> NormalizedConstraint:
    """
    Create an aspect ratio constraint for images.

    Args:
        ratio: Aspect ratio string (e.g., "16:9", "1:1", "4:3", "9:16")
        source_id: Constraint ID
        severity: Constraint severity
    """
    return NormalizedConstraint(
        constraint_type=ConstraintType.ASPECT_RATIO,
        polarity=ConstraintPolarity.POSITIVE,
        target=ratio,
        severity=severity,
        source_id=source_id,
    )


# =============================================================================
# HELPER: Classify constraint modality
# =============================================================================


def get_constraint_modality(constraint: NormalizedConstraint) -> str:
    """
    Determine the modality of a constraint.

    Returns:
        "text" - Text-only constraint (West)
        "visual" - Visual-only constraint (East)
        "multimodal" - Spans both modalities (Bridge)
    """
    text_types = {
        ConstraintType.MUST_INCLUDE_HEADING,
        ConstraintType.MUST_INCLUDE_REGEX,
        ConstraintType.MUST_NOT_INCLUDE_REGEX,
        ConstraintType.SEMANTIC_TOPIC,
        ConstraintType.SEMANTIC_TONE,
        ConstraintType.SEMANTIC_INTENT,
        ConstraintType.FORMAT_REQUIRED,
        ConstraintType.LENGTH_BOUND,
    }

    visual_types = {
        ConstraintType.VISUAL_STYLE,
        ConstraintType.VISUAL_MOOD,
        ConstraintType.IMAGE_MUST_CONTAIN,
        ConstraintType.IMAGE_MUST_NOT_CONTAIN,
        ConstraintType.COLOR_PALETTE,
        ConstraintType.COLOR_FORBIDDEN,
        ConstraintType.COLOR_DOMINANT,
        ConstraintType.ASPECT_RATIO,
        ConstraintType.VISUAL_COMPLEXITY,
    }

    multimodal_types = {
        ConstraintType.BRAND_IDENTITY,
        ConstraintType.MULTIMODAL_COHERENCE,
        ConstraintType.SOUL_INVARIANT,
    }

    if constraint.constraint_type in text_types:
        return "text"
    elif constraint.constraint_type in visual_types:
        return "visual"
    elif constraint.constraint_type in multimodal_types:
        return "multimodal"
    else:
        return "unknown"
