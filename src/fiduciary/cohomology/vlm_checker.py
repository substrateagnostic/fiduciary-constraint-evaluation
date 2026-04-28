"""
Vision-Language Model (VLM) checker for visual constraint verification.

This is the "East" counterpart to the text-based semantic checking.
It verifies that generated images adhere to visual constraints using:
- CLIP embeddings for style/content matching
- Color extraction for palette enforcement
- Aspect ratio verification
- Optional LLaVA/vision LLM for complex queries

The VLM Checker is the "glasses for the Eye" - ensuring visual consistency
with the Bond (soul invariants) across all generated imagery.
"""

from __future__ import annotations

import io
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Tuple, Union

from fiduciary.cohomology.constraints import (
    ConstraintType,
    NormalizedConstraint,
    get_constraint_modality,
)


class VLMVerdict(str, Enum):
    """Result of a visual constraint check."""
    PASS = "pass"
    FAIL = "fail"
    UNCERTAIN = "uncertain"  # When confidence is below threshold


@dataclass
class VisualCheckResult:
    """
    Result of checking an image against a visual constraint.

    This is the visual analog to the text-based LoomVerdict.
    """
    verdict: VLMVerdict
    confidence: float  # 0.0 to 1.0
    constraint_id: str
    constraint_type: ConstraintType
    message: Optional[str] = None

    # For debugging/audit
    raw_scores: Optional[Dict[str, float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "constraint_id": self.constraint_id,
            "constraint_type": self.constraint_type.value,
            "message": self.message,
            "raw_scores": self.raw_scores,
        }


@dataclass
class VisualVerdict:
    """
    Aggregate verdict for all visual constraints on an image.

    Parallels the LoomVerdict structure for text.
    """
    status: str  # "PASS", "FAIL", "WARN"
    violations: List[VisualCheckResult]  # P0/P1 failures
    warnings: List[VisualCheckResult]    # P2 issues
    passed: List[VisualCheckResult]      # Successfully verified

    # Overall confidence in the verdict
    aggregate_confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "violations": [v.to_dict() for v in self.violations],
            "warnings": [w.to_dict() for w in self.warnings],
            "passed": [p.to_dict() for p in self.passed],
            "aggregate_confidence": self.aggregate_confidence,
        }


class VLMChecker(Protocol):
    """
    Protocol for Vision-Language Model checking.

    This is the visual counterpart to the SemanticChecker protocol.
    Implementations can use:
    - CLIP for embedding-based style/content matching
    - LLaVA for complex visual Q&A
    - Color extraction libraries for palette verification
    - Simple heuristics for aspect ratio, etc.
    """

    def check_visual_adherence(
        self,
        image_data: bytes,
        constraint: NormalizedConstraint,
    ) -> VisualCheckResult:
        """
        Check if an image adheres to a single visual constraint.

        Args:
            image_data: Raw image bytes (PNG, JPEG, etc.)
            constraint: The visual constraint to check

        Returns:
            VisualCheckResult with verdict and confidence
        """
        ...

    def check_all_visual_constraints(
        self,
        image_data: bytes,
        constraints: List[NormalizedConstraint],
    ) -> VisualVerdict:
        """
        Check an image against all provided visual constraints.

        Args:
            image_data: Raw image bytes
            constraints: List of visual constraints to verify

        Returns:
            VisualVerdict with aggregate results
        """
        ...


# =============================================================================
# COLOR EXTRACTION (Deterministic - no ML required)
# =============================================================================


def extract_dominant_colors(
    image_data: bytes,
    num_colors: int = 5,
) -> List[Tuple[str, float]]:
    """
    Extract dominant colors from an image.

    Returns list of (hex_color, percentage) tuples.

    This is a simplified implementation. For production, consider:
    - K-means clustering on LAB color space
    - Using colorthief or similar library
    """
    try:
        from PIL import Image
        import colorsys
    except ImportError:
        # Fallback if PIL not available
        return []

    try:
        img = Image.open(io.BytesIO(image_data))
        img = img.convert("RGB")

        # Resize for faster processing
        img.thumbnail((150, 150))

        # Get all pixels
        pixels = list(img.getdata())
        total_pixels = len(pixels)

        if total_pixels == 0:
            return []

        # Simple histogram approach (for production, use k-means)
        color_counts: Dict[str, int] = {}
        for r, g, b in pixels:
            # Quantize to reduce color space
            r_q = (r // 32) * 32
            g_q = (g // 32) * 32
            b_q = (b // 32) * 32
            hex_color = f"#{r_q:02X}{g_q:02X}{b_q:02X}"
            color_counts[hex_color] = color_counts.get(hex_color, 0) + 1

        # Sort by frequency
        sorted_colors = sorted(
            color_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:num_colors]

        # Convert to percentages
        return [
            (color, count / total_pixels)
            for color, count in sorted_colors
        ]
    except Exception:
        return []


def color_distance(hex1: str, hex2: str) -> float:
    """
    Calculate color distance (0.0 = identical, 1.0 = maximum difference).

    Uses simple RGB Euclidean distance normalized to [0, 1].
    For production, consider Delta E in LAB color space.
    """
    def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

    try:
        r1, g1, b1 = hex_to_rgb(hex1)
        r2, g2, b2 = hex_to_rgb(hex2)

        # Euclidean distance normalized by max possible distance
        max_distance = (255**2 * 3) ** 0.5
        actual_distance = ((r1-r2)**2 + (g1-g2)**2 + (b1-b2)**2) ** 0.5

        return actual_distance / max_distance
    except Exception:
        return 1.0


def check_color_constraint(
    image_data: bytes,
    constraint: NormalizedConstraint,
    tolerance: float = 0.15,
) -> VisualCheckResult:
    """
    Check a color constraint against an image.

    Handles:
    - COLOR_PALETTE: At least one required color must be present
    - COLOR_FORBIDDEN: None of the forbidden colors can be present
    - COLOR_DOMINANT: The primary color must match
    """
    target_colors = [c.strip() for c in constraint.target.split(",")]
    dominant_colors = extract_dominant_colors(image_data)

    if not dominant_colors:
        return VisualCheckResult(
            verdict=VLMVerdict.UNCERTAIN,
            confidence=0.0,
            constraint_id=constraint.source_id,
            constraint_type=constraint.constraint_type,
            message="Could not extract colors from image",
        )

    extracted_hex = [c[0] for c in dominant_colors]

    if constraint.constraint_type == ConstraintType.COLOR_FORBIDDEN:
        # Check that none of the forbidden colors are present
        for forbidden in target_colors:
            for extracted, percentage in dominant_colors:
                if color_distance(forbidden, extracted) < tolerance:
                    return VisualCheckResult(
                        verdict=VLMVerdict.FAIL,
                        confidence=1.0 - color_distance(forbidden, extracted),
                        constraint_id=constraint.source_id,
                        constraint_type=constraint.constraint_type,
                        message=f"Forbidden color {forbidden} found (similar to {extracted}, {percentage:.1%} of image)",
                        raw_scores={"color_distance": color_distance(forbidden, extracted)},
                    )
        return VisualCheckResult(
            verdict=VLMVerdict.PASS,
            confidence=0.9,
            constraint_id=constraint.source_id,
            constraint_type=constraint.constraint_type,
            message="No forbidden colors detected",
        )

    elif constraint.constraint_type == ConstraintType.COLOR_DOMINANT:
        # Primary color must match target
        if not dominant_colors:
            return VisualCheckResult(
                verdict=VLMVerdict.FAIL,
                confidence=0.0,
                constraint_id=constraint.source_id,
                constraint_type=constraint.constraint_type,
                message="Could not determine dominant color",
            )

        primary_color, primary_pct = dominant_colors[0]
        target_color = target_colors[0] if target_colors else ""

        distance = color_distance(primary_color, target_color)
        if distance < tolerance:
            return VisualCheckResult(
                verdict=VLMVerdict.PASS,
                confidence=1.0 - distance,
                constraint_id=constraint.source_id,
                constraint_type=constraint.constraint_type,
                message=f"Dominant color {primary_color} matches target {target_color}",
                raw_scores={"color_distance": distance, "coverage": primary_pct},
            )
        else:
            return VisualCheckResult(
                verdict=VLMVerdict.FAIL,
                confidence=distance,
                constraint_id=constraint.source_id,
                constraint_type=constraint.constraint_type,
                message=f"Dominant color {primary_color} does not match target {target_color}",
                raw_scores={"color_distance": distance, "coverage": primary_pct},
            )

    else:  # COLOR_PALETTE
        # At least one required color must be present
        for required in target_colors:
            for extracted, percentage in dominant_colors:
                if color_distance(required, extracted) < tolerance:
                    return VisualCheckResult(
                        verdict=VLMVerdict.PASS,
                        confidence=1.0 - color_distance(required, extracted),
                        constraint_id=constraint.source_id,
                        constraint_type=constraint.constraint_type,
                        message=f"Required color {required} found (as {extracted}, {percentage:.1%})",
                        raw_scores={"color_distance": color_distance(required, extracted)},
                    )

        return VisualCheckResult(
            verdict=VLMVerdict.FAIL,
            confidence=0.8,
            constraint_id=constraint.source_id,
            constraint_type=constraint.constraint_type,
            message=f"None of required colors {target_colors} found in image",
            raw_scores={"extracted_colors": extracted_hex},
        )


# =============================================================================
# ASPECT RATIO CHECK (Deterministic)
# =============================================================================


def check_aspect_ratio(
    image_data: bytes,
    constraint: NormalizedConstraint,
    tolerance: float = 0.05,
) -> VisualCheckResult:
    """
    Check if image matches required aspect ratio.

    Target format: "16:9", "1:1", "4:3", etc.
    """
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_data))
        width, height = img.size
    except Exception as e:
        return VisualCheckResult(
            verdict=VLMVerdict.UNCERTAIN,
            confidence=0.0,
            constraint_id=constraint.source_id,
            constraint_type=constraint.constraint_type,
            message=f"Could not read image dimensions: {e}",
        )

    # Parse target ratio
    target = constraint.target
    match = re.match(r"(\d+):(\d+)", target)
    if not match:
        return VisualCheckResult(
            verdict=VLMVerdict.UNCERTAIN,
            confidence=0.0,
            constraint_id=constraint.source_id,
            constraint_type=constraint.constraint_type,
            message=f"Invalid aspect ratio format: {target}",
        )

    target_w, target_h = int(match.group(1)), int(match.group(2))
    target_ratio = target_w / target_h
    actual_ratio = width / height

    ratio_diff = abs(target_ratio - actual_ratio) / target_ratio

    if ratio_diff <= tolerance:
        return VisualCheckResult(
            verdict=VLMVerdict.PASS,
            confidence=1.0 - ratio_diff,
            constraint_id=constraint.source_id,
            constraint_type=constraint.constraint_type,
            message=f"Aspect ratio {width}:{height} matches target {target}",
            raw_scores={"target_ratio": target_ratio, "actual_ratio": actual_ratio},
        )
    else:
        return VisualCheckResult(
            verdict=VLMVerdict.FAIL,
            confidence=ratio_diff,
            constraint_id=constraint.source_id,
            constraint_type=constraint.constraint_type,
            message=f"Aspect ratio {width}:{height} ({actual_ratio:.2f}) does not match target {target} ({target_ratio:.2f})",
            raw_scores={"target_ratio": target_ratio, "actual_ratio": actual_ratio, "diff": ratio_diff},
        )


# =============================================================================
# CLIP-BASED CHECKER (Semantic Visual)
# =============================================================================


class CLIPChecker:
    """
    CLIP-based visual constraint checker.

    Uses CLIP embeddings to check:
    - Visual style (e.g., "Swiss Minimalist", "Brutalist")
    - Visual mood (e.g., "Professional", "Playful")
    - Image content (e.g., "contains a bridge", "shows hexagonal geometry")

    This is the "glasses for the Eye" - enabling semantic visual verification.
    """

    def __init__(
        self,
        model_name: str = "ViT-B/32",
        device: Optional[str] = None,
        confidence_threshold: float = 0.25,
    ):
        """
        Initialize CLIP checker.

        Args:
            model_name: CLIP model variant (ViT-B/32, ViT-L/14, etc.)
            device: Device to run on ("cuda", "cpu", or None for auto)
            confidence_threshold: Minimum cosine similarity to pass
        """
        self.model_name = model_name
        self.device = device
        self.confidence_threshold = confidence_threshold

        self._model = None
        self._preprocess = None
        self._tokenizer = None

    def _load_model(self):
        """Lazy-load CLIP model."""
        if self._model is not None:
            return

        try:
            import clip
            import torch
        except ImportError as e:
            raise RuntimeError(
                "CLIP not available. Install with: pip install git+https://github.com/openai/CLIP.git"
            ) from e

        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model, self._preprocess = clip.load(self.model_name, device=device)
        self._device = device

    def get_image_embedding(self, image_data: bytes) -> Optional[Any]:
        """Get CLIP embedding for an image."""
        self._load_model()

        try:
            import torch
            from PIL import Image

            img = Image.open(io.BytesIO(image_data)).convert("RGB")
            image_input = self._preprocess(img).unsqueeze(0).to(self._device)

            with torch.no_grad():
                image_features = self._model.encode_image(image_input)
                image_features = image_features / image_features.norm(dim=-1, keepdim=True)

            return image_features
        except Exception:
            return None

    def get_text_embedding(self, text: str) -> Optional[Any]:
        """Get CLIP embedding for text."""
        self._load_model()

        try:
            import clip
            import torch

            text_input = clip.tokenize([text]).to(self._device)

            with torch.no_grad():
                text_features = self._model.encode_text(text_input)
                text_features = text_features / text_features.norm(dim=-1, keepdim=True)

            return text_features
        except Exception:
            return None

    def compute_similarity(
        self,
        image_data: bytes,
        text_prompt: str,
    ) -> Tuple[float, bool]:
        """
        Compute cosine similarity between image and text prompt.

        Returns (similarity_score, passes_threshold).
        """
        image_emb = self.get_image_embedding(image_data)
        text_emb = self.get_text_embedding(text_prompt)

        if image_emb is None or text_emb is None:
            return 0.0, False

        try:
            import torch
            similarity = (image_emb @ text_emb.T).item()
            return similarity, similarity >= self.confidence_threshold
        except Exception:
            return 0.0, False

    def check_visual_style(
        self,
        image_data: bytes,
        constraint: NormalizedConstraint,
    ) -> VisualCheckResult:
        """
        Check if image matches a visual style constraint.

        Constructs a prompt like "An image in Swiss Minimalist style"
        and computes CLIP similarity.
        """
        style = constraint.target
        prompt = f"An image in {style} style"

        similarity, passes = self.compute_similarity(image_data, prompt)

        return VisualCheckResult(
            verdict=VLMVerdict.PASS if passes else VLMVerdict.FAIL,
            confidence=similarity,
            constraint_id=constraint.source_id,
            constraint_type=constraint.constraint_type,
            message=f"Style '{style}' similarity: {similarity:.3f} (threshold: {self.confidence_threshold})",
            raw_scores={"clip_similarity": similarity, "threshold": self.confidence_threshold},
        )

    def check_image_contains(
        self,
        image_data: bytes,
        constraint: NormalizedConstraint,
    ) -> VisualCheckResult:
        """
        Check if image contains required content.

        For IMAGE_MUST_CONTAIN, we check positive similarity.
        For IMAGE_MUST_NOT_CONTAIN, we check that similarity is LOW.
        """
        content = constraint.target
        must_contain = constraint.constraint_type == ConstraintType.IMAGE_MUST_CONTAIN

        # Construct prompt
        prompt = f"An image containing {content}" if must_contain else f"An image showing {content}"

        similarity, _ = self.compute_similarity(image_data, prompt)

        if must_contain:
            # Higher similarity = better
            passes = similarity >= self.confidence_threshold
            verdict = VLMVerdict.PASS if passes else VLMVerdict.FAIL
            message = f"Content '{content}' detected with confidence {similarity:.3f}"
        else:
            # Lower similarity = better (we don't want this content)
            # Use a lower threshold for "must not contain"
            forbidden_threshold = self.confidence_threshold * 0.8
            passes = similarity < forbidden_threshold
            verdict = VLMVerdict.PASS if passes else VLMVerdict.FAIL
            message = f"Forbidden content '{content}' similarity: {similarity:.3f} (must be < {forbidden_threshold:.3f})"

        return VisualCheckResult(
            verdict=verdict,
            confidence=similarity if must_contain else (1.0 - similarity),
            constraint_id=constraint.source_id,
            constraint_type=constraint.constraint_type,
            message=message,
            raw_scores={"clip_similarity": similarity},
        )

    def check_visual_mood(
        self,
        image_data: bytes,
        constraint: NormalizedConstraint,
    ) -> VisualCheckResult:
        """Check if image conveys the required mood/atmosphere."""
        mood = constraint.target
        prompt = f"A {mood} image"

        similarity, passes = self.compute_similarity(image_data, prompt)

        return VisualCheckResult(
            verdict=VLMVerdict.PASS if passes else VLMVerdict.FAIL,
            confidence=similarity,
            constraint_id=constraint.source_id,
            constraint_type=constraint.constraint_type,
            message=f"Mood '{mood}' similarity: {similarity:.3f}",
            raw_scores={"clip_similarity": similarity},
        )


# =============================================================================
# COMPOSITE VLM CHECKER
# =============================================================================


class CompositeVLMChecker:
    """
    Composite VLM checker that routes constraints to appropriate checkers.

    Uses:
    - Deterministic checkers for color and aspect ratio
    - CLIP for style, mood, and content constraints
    - Optional LLaVA for complex queries (future)

    This is the main interface for visual constraint verification.
    """

    def __init__(
        self,
        clip_model: str = "ViT-B/32",
        clip_device: Optional[str] = None,
        confidence_threshold: float = 0.25,
        color_tolerance: float = 0.15,
        aspect_tolerance: float = 0.05,
    ):
        """
        Initialize composite checker.

        Args:
            clip_model: CLIP model variant for semantic checks
            clip_device: Device for CLIP ("cuda", "cpu", or None for auto)
            confidence_threshold: CLIP similarity threshold
            color_tolerance: Color matching tolerance (0-1)
            aspect_tolerance: Aspect ratio tolerance (percentage)
        """
        self.confidence_threshold = confidence_threshold
        self.color_tolerance = color_tolerance
        self.aspect_tolerance = aspect_tolerance

        # Lazy-loaded CLIP checker
        self._clip_checker: Optional[CLIPChecker] = None
        self._clip_model = clip_model
        self._clip_device = clip_device

    @property
    def clip_checker(self) -> CLIPChecker:
        """Lazy-load CLIP checker."""
        if self._clip_checker is None:
            self._clip_checker = CLIPChecker(
                model_name=self._clip_model,
                device=self._clip_device,
                confidence_threshold=self.confidence_threshold,
            )
        return self._clip_checker

    def check_visual_adherence(
        self,
        image_data: bytes,
        constraint: NormalizedConstraint,
    ) -> VisualCheckResult:
        """
        Check if an image adheres to a single visual constraint.

        Routes to the appropriate checker based on constraint type.
        """
        ct = constraint.constraint_type

        # Deterministic checks (no ML required)
        if ct in {ConstraintType.COLOR_PALETTE, ConstraintType.COLOR_FORBIDDEN, ConstraintType.COLOR_DOMINANT}:
            return check_color_constraint(image_data, constraint, self.color_tolerance)

        if ct == ConstraintType.ASPECT_RATIO:
            return check_aspect_ratio(image_data, constraint, self.aspect_tolerance)

        # CLIP-based semantic checks
        if ct == ConstraintType.VISUAL_STYLE:
            return self.clip_checker.check_visual_style(image_data, constraint)

        if ct == ConstraintType.VISUAL_MOOD:
            return self.clip_checker.check_visual_mood(image_data, constraint)

        if ct in {ConstraintType.IMAGE_MUST_CONTAIN, ConstraintType.IMAGE_MUST_NOT_CONTAIN}:
            return self.clip_checker.check_image_contains(image_data, constraint)

        # Cross-modal / complex constraints (for now, use CLIP style check)
        if ct == ConstraintType.BRAND_IDENTITY:
            # Brand identity is complex - use the target as a style prompt
            return self.clip_checker.check_visual_style(image_data, constraint)

        # Unknown constraint type for visual checking
        return VisualCheckResult(
            verdict=VLMVerdict.UNCERTAIN,
            confidence=0.0,
            constraint_id=constraint.source_id,
            constraint_type=ct,
            message=f"No visual checker implemented for constraint type: {ct.value}",
        )

    def check_all_visual_constraints(
        self,
        image_data: bytes,
        constraints: List[NormalizedConstraint],
    ) -> VisualVerdict:
        """
        Check an image against all provided visual constraints.

        Only processes constraints with visual modality.
        """
        violations: List[VisualCheckResult] = []
        warnings: List[VisualCheckResult] = []
        passed: List[VisualCheckResult] = []

        # Filter to visual constraints only
        visual_constraints = [
            c for c in constraints
            if get_constraint_modality(c) in {"visual", "multimodal"}
        ]

        for constraint in visual_constraints:
            result = self.check_visual_adherence(image_data, constraint)

            if result.verdict == VLMVerdict.PASS:
                passed.append(result)
            elif result.verdict == VLMVerdict.FAIL:
                # Route to violations or warnings based on severity
                from fiduciary.models import Severity
                if constraint.severity in {Severity.P0, Severity.P1}:
                    violations.append(result)
                else:
                    warnings.append(result)
            else:  # UNCERTAIN
                warnings.append(result)

        # Determine overall status
        if violations:
            status = "FAIL"
        elif warnings:
            status = "WARN"
        else:
            status = "PASS"

        # Aggregate confidence
        all_results = violations + warnings + passed
        if all_results:
            aggregate_confidence = sum(r.confidence for r in all_results) / len(all_results)
        else:
            aggregate_confidence = 1.0

        return VisualVerdict(
            status=status,
            violations=violations,
            warnings=warnings,
            passed=passed,
            aggregate_confidence=aggregate_confidence,
        )


# =============================================================================
# MOCK VLM CHECKER (For Testing)
# =============================================================================


class MockVLMChecker:
    """
    Mock VLM checker for testing without ML dependencies.

    Can be configured to return specific results for testing various scenarios.
    """

    def __init__(
        self,
        default_verdict: VLMVerdict = VLMVerdict.PASS,
        default_confidence: float = 0.8,
        fail_constraints: Optional[List[str]] = None,
    ):
        """
        Args:
            default_verdict: Default verdict for all checks
            default_confidence: Default confidence score
            fail_constraints: List of constraint IDs that should fail
        """
        self.default_verdict = default_verdict
        self.default_confidence = default_confidence
        self.fail_constraints = set(fail_constraints or [])

    def check_visual_adherence(
        self,
        image_data: bytes,
        constraint: NormalizedConstraint,
    ) -> VisualCheckResult:
        """Mock visual adherence check."""
        if constraint.source_id in self.fail_constraints:
            return VisualCheckResult(
                verdict=VLMVerdict.FAIL,
                confidence=0.2,
                constraint_id=constraint.source_id,
                constraint_type=constraint.constraint_type,
                message=f"Mock failure for constraint {constraint.source_id}",
            )

        return VisualCheckResult(
            verdict=self.default_verdict,
            confidence=self.default_confidence,
            constraint_id=constraint.source_id,
            constraint_type=constraint.constraint_type,
            message=f"Mock check for {constraint.constraint_type.value}",
        )

    def check_all_visual_constraints(
        self,
        image_data: bytes,
        constraints: List[NormalizedConstraint],
    ) -> VisualVerdict:
        """Mock check of all visual constraints."""
        violations: List[VisualCheckResult] = []
        warnings: List[VisualCheckResult] = []
        passed: List[VisualCheckResult] = []

        for constraint in constraints:
            if get_constraint_modality(constraint) not in {"visual", "multimodal"}:
                continue

            result = self.check_visual_adherence(image_data, constraint)

            if result.verdict == VLMVerdict.PASS:
                passed.append(result)
            elif result.verdict == VLMVerdict.FAIL:
                from fiduciary.models import Severity
                if constraint.severity in {Severity.P0, Severity.P1}:
                    violations.append(result)
                else:
                    warnings.append(result)
            else:
                warnings.append(result)

        if violations:
            status = "FAIL"
        elif warnings:
            status = "WARN"
        else:
            status = "PASS"

        return VisualVerdict(
            status=status,
            violations=violations,
            warnings=warnings,
            passed=passed,
            aggregate_confidence=self.default_confidence,
        )
