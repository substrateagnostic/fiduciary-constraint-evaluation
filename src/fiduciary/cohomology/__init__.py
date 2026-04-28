"""
Cohomology module — constraint compatibility and obstruction detection.

This module implements sheaf-theoretic foundations for fiduciary alignment:
- Constraints as "gluing conditions" (sections of a sheaf)
- Compatibility checking between constraint sets
- Obstruction detection when constraints become contradictory
- H¹ pairwise conflicts, H²+ higher-order conflicts via Čech complex
- Human-in-the-loop escalation triggered by nonvanishing cohomology classes

The key insight: constraints are local sections. When they can't be glued
into a coherent global section, the obstruction is a mathematical object
with a name, a severity, a witness, and a resolution pathway.

The math doesn't care who's asking.
"""

from fiduciary.cohomology.constraints import (
    Constraint,
    ConstraintPolarity,
    ConstraintSet,
    ConstraintType,
    NormalizedConstraint,
    normalize_contract_constraint,
    get_constraint_modality,
    # Visual constraint creators
    create_visual_style_constraint,
    create_color_constraint,
    create_image_content_constraint,
    create_brand_identity_constraint,
    create_aspect_ratio_constraint,
    create_soul_invariant,
    create_semantic_constraint,
)
from fiduciary.cohomology.compatibility import (
    CompatibilityResult,
    CompatibilityStatus,
    check_compatibility,
    check_soul_invariant_preservation,
    merge_constraint_sets,
    Obstruction,
    SemanticChecker,
)
from fiduciary.cohomology.detector import (
    DriftClassification,
    DriftDetector,
    ObstructionAwareDriftDetector,
)
from fiduciary.cohomology.vlm_checker import (
    VLMVerdict,
    VisualCheckResult,
    VisualVerdict,
    VLMChecker,
    CLIPChecker,
    CompositeVLMChecker,
    MockVLMChecker,
    # Deterministic visual checks
    check_color_constraint,
    check_aspect_ratio,
    extract_dominant_colors,
    color_distance,
)

__all__ = [
    # Constraint types
    "Constraint",
    "ConstraintPolarity",
    "ConstraintSet",
    "ConstraintType",
    "NormalizedConstraint",
    "normalize_contract_constraint",
    "get_constraint_modality",
    # Constraint creators
    "create_visual_style_constraint",
    "create_color_constraint",
    "create_image_content_constraint",
    "create_brand_identity_constraint",
    "create_aspect_ratio_constraint",
    "create_soul_invariant",
    "create_semantic_constraint",
    # Compatibility
    "CompatibilityResult",
    "CompatibilityStatus",
    "check_compatibility",
    "check_soul_invariant_preservation",
    "merge_constraint_sets",
    "Obstruction",
    "SemanticChecker",
    # Detection
    "DriftClassification",
    "DriftDetector",
    "ObstructionAwareDriftDetector",
    # Visual (VLM) checking
    "VLMVerdict",
    "VisualCheckResult",
    "VisualVerdict",
    "VLMChecker",
    "CLIPChecker",
    "CompositeVLMChecker",
    "MockVLMChecker",
    "check_color_constraint",
    "check_aspect_ratio",
    "extract_dominant_colors",
    "color_distance",
]
