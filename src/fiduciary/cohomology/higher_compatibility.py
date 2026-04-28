"""
Higher-order constraint compatibility checking (H² and beyond).

Extends the basic H¹ obstruction detection to handle cases where
constraints are pairwise compatible but globally inconsistent.

The Math:
- H¹ obstruction: Local sections exist but can't glue (A and B contradict)
- H² obstruction: Local sections glue pairwise (A+B, B+C, A+C all work)
  but the triple can't be realized. The cocycle condition fails.

Classic topological example: three open sets U, V, W covering a circle.
Each pairwise intersection is contractible, but when you go around the
whole circle, you don't get back to where you started.

Čech complex approach:
- Vertices = constraints
- Edges = verified pairwise compatible
- Faces = verified triple compatible
- H² candidates = triangles where all edges exist but face doesn't
"""

from __future__ import annotations

import itertools
import re
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Protocol, Set, Tuple

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
    NARROWING = "narrowing"
    WIDENING = "widening"
    CONTRADICTORY = "contradictory"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Obstruction:
    """
    H¹ obstruction - a pair of constraints that cannot both be satisfied.
    """
    constraint_a: NormalizedConstraint
    constraint_b: NormalizedConstraint
    obstruction_type: str
    severity: str  # "hard" or "soft"
    suggested_resolution: Optional[str] = None

    @property
    def order(self) -> int:
        return 1

    @property
    def constraints(self) -> FrozenSet[NormalizedConstraint]:
        return frozenset({self.constraint_a, self.constraint_b})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order": self.order,
            "constraint_a": self.constraint_a.to_dict() if self.constraint_a else None,
            "constraint_b": self.constraint_b.to_dict() if self.constraint_b else None,
            "obstruction_type": self.obstruction_type,
            "severity": self.severity,
            "suggested_resolution": self.suggested_resolution,
        }


@dataclass(frozen=True)
class HigherObstruction:
    """
    H^n obstruction for n >= 2.

    These arise when constraints are pairwise compatible but globally
    inconsistent. The witness field is crucial - without a concrete
    example of why the combination fails, we're just guessing.

    Examples:
    - Resource exhaustion: budget(A) <= 100, budget(B) <= 100, total <= 150
      Pairwise OK, but if both A and B needed, triple fails.
    - Circular ordering: X > Y, Y > Z, Z > X
    - Temporal impossibility: before noon, after meeting, meeting at 1pm
    """
    constraints: FrozenSet[NormalizedConstraint]
    order: int  # 2 for triples, 3 for quadruples
    obstruction_type: str
    witness: str  # Required. Concrete example showing impossibility.
    severity: str = "hard"
    suggested_resolution: Optional[str] = None

    def __post_init__(self):
        if len(self.constraints) != self.order + 1:
            raise ValueError(
                f"H^{self.order} obstruction requires {self.order + 1} constraints, "
                f"got {len(self.constraints)}"
            )
        if not self.witness:
            raise ValueError("HigherObstruction requires a witness")

    @property
    def is_h2(self) -> bool:
        return self.order == 2

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order": self.order,
            "constraints": [c.to_dict() for c in self.constraints],
            "obstruction_type": self.obstruction_type,
            "witness": self.witness,
            "severity": self.severity,
            "suggested_resolution": self.suggested_resolution,
        }


@dataclass
class CechComplex:
    """
    Čech nerve tracking verified compatibility at each level.

    This is the combinatorial structure that lets us detect higher
    obstructions efficiently. We build it incrementally as we verify
    pairwise compatibility, then look for "missing faces" - triangles
    where all edges are present but we haven't verified the triple.
    """
    vertices: Set[NormalizedConstraint] = field(default_factory=set)
    edges: Set[FrozenSet[NormalizedConstraint]] = field(default_factory=set)
    faces: Set[FrozenSet[NormalizedConstraint]] = field(default_factory=set)

    # Cache for efficiency
    _neighbor_cache: Dict[NormalizedConstraint, Set[NormalizedConstraint]] = field(
        default_factory=dict, repr=False
    )

    def add_vertex(self, c: NormalizedConstraint) -> None:
        self.vertices.add(c)
        self._neighbor_cache.clear()

    def add_edge(self, a: NormalizedConstraint, b: NormalizedConstraint) -> None:
        """Record that a and b are pairwise compatible."""
        self.vertices.add(a)
        self.vertices.add(b)
        self.edges.add(frozenset({a, b}))
        self._neighbor_cache.clear()

    def add_face(self, a: NormalizedConstraint, b: NormalizedConstraint, c: NormalizedConstraint) -> None:
        """Record that a, b, c are triple-compatible."""
        self.faces.add(frozenset({a, b, c}))

    def pairwise_compatible(self, a: NormalizedConstraint, b: NormalizedConstraint) -> bool:
        return frozenset({a, b}) in self.edges

    def triple_verified(self, a: NormalizedConstraint, b: NormalizedConstraint, c: NormalizedConstraint) -> bool:
        return frozenset({a, b, c}) in self.faces

    def _get_neighbors(self, v: NormalizedConstraint) -> Set[NormalizedConstraint]:
        """Get all vertices connected to v by an edge."""
        if v not in self._neighbor_cache:
            neighbors = set()
            for e in self.edges:
                if v in e:
                    neighbors.update(e - {v})
            self._neighbor_cache[v] = neighbors
        return self._neighbor_cache[v]

    def find_h2_candidates(self) -> Set[FrozenSet[NormalizedConstraint]]:
        """
        Find triples where all pairs are edges but triple isn't a face.

        These are H² candidates - might be globally incompatible despite
        pairwise compatibility.
        """
        candidates: Set[FrozenSet[NormalizedConstraint]] = set()

        for v in self.vertices:
            neighbors = list(self._get_neighbors(v))

            # Check all pairs of neighbors
            for i, n1 in enumerate(neighbors):
                for n2 in neighbors[i + 1:]:
                    # Do n1 and n2 share an edge?
                    if frozenset({n1, n2}) in self.edges:
                        triangle = frozenset({v, n1, n2})
                        if triangle not in self.faces:
                            candidates.add(triangle)

        return candidates

    def stats(self) -> Dict[str, int]:
        return {
            "vertices": len(self.vertices),
            "edges": len(self.edges),
            "faces": len(self.faces),
            "h2_candidates": len(self.find_h2_candidates()),
        }


@dataclass
class CompatibilityResult:
    """
    Result of checking compatibility between constraint sets.

    Extended to track both H¹ and higher obstructions.
    """
    status: CompatibilityStatus
    obstructions: List[Obstruction] = field(default_factory=list)
    higher_obstructions: List[HigherObstruction] = field(default_factory=list)
    narrowed_constraints: List[NormalizedConstraint] = field(default_factory=list)
    widened_constraints: List[NormalizedConstraint] = field(default_factory=list)
    unknown_constraints: List[NormalizedConstraint] = field(default_factory=list)
    requires_semantic_check: bool = False
    semantic_check_pairs: List[Tuple[NormalizedConstraint, NormalizedConstraint]] = field(default_factory=list)

    # The Čech complex built during analysis (useful for incremental checks)
    cech_complex: Optional[CechComplex] = field(default=None, repr=False)

    @property
    def max_obstruction_order(self) -> int:
        """0 if clean, 1 if H¹ only, 2+ if higher."""
        if self.higher_obstructions:
            return max(o.order for o in self.higher_obstructions)
        if self.obstructions:
            return 1
        return 0

    @property
    def is_clean(self) -> bool:
        return self.max_obstruction_order == 0

    def is_compatible(self) -> bool:
        return self.status in {CompatibilityStatus.COMPATIBLE, CompatibilityStatus.NARROWING}

    def has_hard_obstructions(self) -> bool:
        h1_hard = any(o.severity == "hard" for o in self.obstructions)
        h2_hard = any(o.severity == "hard" for o in self.higher_obstructions)
        return h1_hard or h2_hard

    def all_obstructions(self) -> List[Obstruction | HigherObstruction]:
        """All obstructions, H¹ and higher, sorted by order."""
        combined: List[Obstruction | HigherObstruction] = list(self.obstructions) + list(self.higher_obstructions)
        return sorted(combined, key=lambda o: o.order)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "max_obstruction_order": self.max_obstruction_order,
            "obstructions": [o.to_dict() for o in self.obstructions],
            "higher_obstructions": [o.to_dict() for o in self.higher_obstructions],
            "narrowed_constraints": [c.to_dict() for c in self.narrowed_constraints],
            "widened_constraints": [c.to_dict() for c in self.widened_constraints],
            "requires_semantic_check": self.requires_semantic_check,
        }


class SemanticChecker(Protocol):
    """
    Protocol for semantic compatibility checking.

    The checker must be able to verify tuples of constraints at each level:
    - Pairs (H¹): Can A and B be satisfied together?
    - Triples (H²): Can A, B, C be satisfied together? (given pairs passed)
    - Quadruples (H³): Can A, B, C, D be satisfied together? (given triples passed)

    For coherent witnessing, the checker should return the SAME satisfying
    example when a subset is checked - or explicitly note when it can't.
    """

    def check_semantic_compatibility(
        self,
        constraint_a: NormalizedConstraint,
        constraint_b: NormalizedConstraint,
    ) -> Tuple[bool, float, Optional[str]]:
        """Check if two semantic constraints are compatible (H¹)."""
        ...

    def check_triple_compatibility(
        self,
        constraint_a: NormalizedConstraint,
        constraint_b: NormalizedConstraint,
        constraint_c: NormalizedConstraint,
    ) -> Tuple[bool, float, Optional[str]]:
        """
        Check if three pairwise-compatible constraints are globally compatible (H²).

        IMPORTANT: Only called when all pairs have already passed H¹ checks.
        This is checking for the subtle case where ABC fails despite AB, BC, AC passing.

        Returns:
            (is_compatible, confidence, witness_or_example)
            - If incompatible, the third element is a witness of impossibility
            - If compatible, the third element is an example satisfying all three
        """
        ...

    def check_quadruple_compatibility(
        self,
        constraint_a: NormalizedConstraint,
        constraint_b: NormalizedConstraint,
        constraint_c: NormalizedConstraint,
        constraint_d: NormalizedConstraint,
    ) -> Tuple[bool, float, Optional[str]]:
        """
        Check if four triple-compatible constraints are globally compatible (H³).

        IMPORTANT: Only called when all triples have already passed H² checks.
        This is checking for the subtle case where ABCD fails despite
        ABC, ABD, ACD, BCD all passing.

        Returns:
            (is_compatible, confidence, witness_or_example)
            - If incompatible, the third element is a witness of impossibility
            - If compatible, the third element is an example satisfying all four
        """
        ...


# =============================================================================
# Deterministic H² Detection (Fast Path)
# =============================================================================

def _normalize_inequality_symbols(text: str) -> str:
    return text.replace("\u2264", "<=").replace("\u2265", ">=")


@dataclass
class ComparativeConstraint:
    """Extracted comparative relationship for cycle detection."""
    relation: str  # "gt", "lt", "ge", "le", "eq", "before", "after"
    left: str
    right: str
    source: NormalizedConstraint


@dataclass(frozen=True)
class OrderingEdge:
    target: str
    strict: bool
    symbol: str


def extract_comparative(c: NormalizedConstraint) -> Optional[ComparativeConstraint]:
    """
    Extract comparative relationship from constraint if present.

    Patterns we recognize:
    - "X > Y", "X >= Y", "X < Y", "X <= Y", "X = Y"
    - "warmer than X", "X warmer than Y", "cooler than X", "X cooler than Y"
    - "before X", "X before Y", "after X", "X after Y"
    """
    target = _normalize_inequality_symbols(c.target.lower())

    # Direct comparison patterns
    cmp_match = re.match(r"(.+?)\s*(>=|<=|==|=|>|<)\s*(.+)", target)
    if cmp_match:
        left = cmp_match.group(1).strip()
        op = cmp_match.group(2)
        right = cmp_match.group(3).strip()
        relation_map = {
            ">": "gt",
            ">=": "ge",
            "<": "lt",
            "<=": "le",
            "=": "eq",
            "==": "eq",
        }
        return ComparativeConstraint(relation_map[op], left, right, c)

    # "warmer than" / "cooler than"
    warmer_match = re.match(r"(.+?)\s+warmer\s+than\s+(.+)", target)
    if warmer_match:
        return ComparativeConstraint("gt", warmer_match.group(1).strip(), warmer_match.group(2).strip(), c)
    warmer_match = re.match(r"warmer\s+than\s+(.+)", target)
    if warmer_match:
        return ComparativeConstraint("gt", "warmth", warmer_match.group(1).strip(), c)

    cooler_match = re.match(r"(.+?)\s+cooler\s+than\s+(.+)", target)
    if cooler_match:
        return ComparativeConstraint("lt", cooler_match.group(1).strip(), cooler_match.group(2).strip(), c)
    cooler_match = re.match(r"cooler\s+than\s+(.+)", target)
    if cooler_match:
        return ComparativeConstraint("lt", "warmth", cooler_match.group(1).strip(), c)

    # Temporal
    before_match = re.match(r"(.+?)\s+before\s+(.+)", target)
    if before_match:
        return ComparativeConstraint("before", before_match.group(1).strip(), before_match.group(2).strip(), c)
    before_match = re.match(r"before\s+(.+)", target)
    if before_match:
        return ComparativeConstraint("before", "time", before_match.group(1).strip(), c)

    after_match = re.match(r"(.+?)\s+after\s+(.+)", target)
    if after_match:
        return ComparativeConstraint("after", after_match.group(1).strip(), after_match.group(2).strip(), c)
    after_match = re.match(r"after\s+(.+)", target)
    if after_match:
        return ComparativeConstraint("after", "time", after_match.group(1).strip(), c)

    no_later_match = re.match(r"(?:no\s+later\s+than|on\s+or\s+before)\s+(.+)", target)
    if no_later_match:
        return ComparativeConstraint("le", "time", no_later_match.group(1).strip(), c)

    no_earlier_match = re.match(r"(?:no\s+earlier\s+than|on\s+or\s+after)\s+(.+)", target)
    if no_earlier_match:
        return ComparativeConstraint("ge", "time", no_earlier_match.group(1).strip(), c)

    return None


def detect_cyclic_impossibility(
    a: NormalizedConstraint,
    b: NormalizedConstraint,
    c: NormalizedConstraint,
) -> Optional[HigherObstruction]:
    """
    Fast-path: detect cycles in comparative/ordering constraints.

    Classic H² example: A > B, B > C, C > A forms an impossible cycle.
    """
    comparatives = []
    for constraint in (a, b, c):
        comp = extract_comparative(constraint)
        if comp:
            comparatives.append(comp)

    if len(comparatives) < 3:
        return None  # Not enough comparative constraints

    edges: Dict[str, List[OrderingEdge]] = {}
    strict_edges: List[Tuple[str, str, str]] = []

    def add_edge(src: str, dst: str, strict: bool, symbol: str) -> None:
        edges.setdefault(src, []).append(OrderingEdge(dst, strict, symbol))
        if strict:
            strict_edges.append((src, dst, symbol))

    for comp in comparatives:
        if comp.relation in ("gt", "after"):
            add_edge(comp.left, comp.right, True, ">")
        elif comp.relation == "ge":
            add_edge(comp.left, comp.right, False, ">=")
        elif comp.relation in ("lt", "before"):
            add_edge(comp.right, comp.left, True, ">")
        elif comp.relation == "le":
            add_edge(comp.right, comp.left, False, ">=")
        elif comp.relation == "eq":
            add_edge(comp.left, comp.right, False, "=")
            add_edge(comp.right, comp.left, False, "=")

    if not strict_edges:
        return None

    def find_path(start: str, goal: str) -> Optional[Tuple[List[str], List[str]]]:
        queue = deque([start])
        parent: Dict[str, Optional[str]] = {start: None}
        parent_symbol: Dict[str, str] = {}

        while queue:
            node = queue.popleft()
            for edge in edges.get(node, []):
                if edge.target in parent:
                    continue
                parent[edge.target] = node
                parent_symbol[edge.target] = edge.symbol
                if edge.target == goal:
                    queue.clear()
                    break
                queue.append(edge.target)

        if goal not in parent:
            return None

        nodes = [goal]
        symbols: List[str] = []
        while parent[nodes[-1]] is not None:
            prev = parent[nodes[-1]]
            symbols.append(parent_symbol[nodes[-1]])
            nodes.append(prev)
        nodes.reverse()
        symbols.reverse()
        return nodes, symbols

    def format_path(nodes: List[str], symbols: List[str]) -> str:
        parts = [nodes[0]]
        for symbol, node in zip(symbols, nodes[1:]):
            parts.append(f"{symbol} {node}")
        return " ".join(parts)

    for src, dst, symbol in strict_edges:
        path = find_path(dst, src)
        if path:
            nodes, symbols = path
            witness = f"{format_path(nodes, symbols)} {symbol} {dst}"
            return HigherObstruction(
                constraints=frozenset({a, b, c}),
                order=2,
                obstruction_type="cyclic_ordering",
                witness=f"Cycle detected: {witness}",
                suggested_resolution="Remove one constraint to break the cycle",
            )

    return None


@dataclass(frozen=True)
class Bound:
    value: float
    strict: bool


@dataclass
class ResourceBound:
    """Extracted resource constraint for aggregate checking."""
    resource: str
    scope: Optional[str]
    min_bound: Optional[Bound]
    max_bound: Optional[Bound]
    is_total: bool  # True if this bounds a sum of resources
    source: NormalizedConstraint
    unit_kind: Optional[str] = None


_RESOURCE_TOKEN = r"[a-z][\w-]*"
_COMPARATOR_TOKEN = r"<=|>=|==|=|<|>"
_NUMERIC_TOKEN = r"\$?\d+(?:[,_]\d+)*(?:\.\d+)?"
_UNIT_TOKEN = r"[a-z%]+"


def _parse_numeric_value(value: str, unit: Optional[str]) -> Tuple[Optional[float], Optional[str]]:
    raw = value.replace(",", "").replace("_", "")
    if raw.startswith("$"):
        raw = raw[1:]
    try:
        number = float(raw)
    except ValueError:
        return None, None

    unit_normalized = (unit or "").strip().lower()
    if not unit_normalized:
        return number, None

    byte_scales = {
        "kb": 1024.0,
        "mb": 1024.0 ** 2,
        "gb": 1024.0 ** 3,
        "tb": 1024.0 ** 4,
    }
    if unit_normalized in byte_scales:
        return number * byte_scales[unit_normalized], "bytes"
    if unit_normalized in {"%", "percent", "pct"}:
        return number, "%"
    if unit_normalized in {"k", "m", "b", "bn"}:
        scale = {"k": 1_000.0, "m": 1_000_000.0, "b": 1_000_000_000.0, "bn": 1_000_000_000.0}
        return number * scale[unit_normalized], None

    return number, unit_normalized


def _bounds_from_op(op: str, value: float) -> Tuple[Optional[Bound], Optional[Bound]]:
    if op in ("<", "<="):
        return None, Bound(value=value, strict=(op == "<"))
    if op in (">", ">="):
        return Bound(value=value, strict=(op == ">")), None
    if op in ("=", "=="):
        return Bound(value=value, strict=False), Bound(value=value, strict=False)
    return None, None


def _format_value(value: float, unit_kind: Optional[str]) -> str:
    if unit_kind == "bytes":
        units = [
            ("TB", 1024.0 ** 4),
            ("GB", 1024.0 ** 3),
            ("MB", 1024.0 ** 2),
            ("KB", 1024.0),
        ]
        for unit, scale in units:
            if value >= scale:
                return f"{value / scale:.3g} {unit}"
        return f"{value:.3g} B"
    if unit_kind == "%":
        return f"{value:.3g}%"
    if unit_kind:
        return f"{value:.3g} {unit_kind}"
    return f"{value:.3g}"


def _format_bound(bound: Bound, is_min: bool, unit_kind: Optional[str]) -> str:
    if is_min:
        op = ">" if bound.strict else ">="
    else:
        op = "<" if bound.strict else "<="
    return f"{op} {_format_value(bound.value, unit_kind)}"


def extract_resource_bound(c: NormalizedConstraint) -> Optional[ResourceBound]:
    """
    Extract resource bound from constraint if present.

    Patterns:
    - "budget <= 100 for graphics"
    - "total budget <= 150"
    - "graphics budget <= 100"
    - "memory < 4GB"
    """
    target = _normalize_inequality_symbols(c.target.lower())

    def build_bound(
        resource: str,
        op: str,
        value: str,
        unit: Optional[str],
        scope: Optional[str],
        is_total: bool,
    ) -> Optional[ResourceBound]:
        parsed_value, unit_kind = _parse_numeric_value(value, unit)
        if parsed_value is None:
            return None
        min_bound, max_bound = _bounds_from_op(op, parsed_value)
        return ResourceBound(
            resource=resource,
            scope=scope,
            min_bound=min_bound,
            max_bound=max_bound,
            is_total=is_total,
            source=c,
            unit_kind=unit_kind,
        )

    # Total bound pattern
    total_match = re.match(
        rf"total\s+(?P<resource>{_RESOURCE_TOKEN})\s*(?P<op>{_COMPARATOR_TOKEN})\s*"
        rf"(?P<value>{_NUMERIC_TOKEN})\s*(?P<unit>{_UNIT_TOKEN})?",
        target,
    )
    if not total_match:
        total_match = re.match(
            rf"(?P<resource>{_RESOURCE_TOKEN})\s+total\s*(?P<op>{_COMPARATOR_TOKEN})\s*"
            rf"(?P<value>{_NUMERIC_TOKEN})\s*(?P<unit>{_UNIT_TOKEN})?",
            target,
        )
    if total_match:
        return build_bound(
            resource=total_match.group("resource"),
            op=total_match.group("op"),
            value=total_match.group("value"),
            unit=total_match.group("unit"),
            scope=None,
            is_total=True,
        )

    # Individual bound pattern: "budget <= X for graphics" or "graphics budget <= X"
    bound_match = re.match(
        rf"(?P<resource>{_RESOURCE_TOKEN})\s*(?P<op>{_COMPARATOR_TOKEN})\s*"
        rf"(?P<value>{_NUMERIC_TOKEN})\s*(?P<unit>{_UNIT_TOKEN})?\s+for\s+"
        rf"(?P<scope>{_RESOURCE_TOKEN})",
        target,
    )
    if bound_match:
        return build_bound(
            resource=bound_match.group("resource"),
            op=bound_match.group("op"),
            value=bound_match.group("value"),
            unit=bound_match.group("unit"),
            scope=bound_match.group("scope"),
            is_total=False,
        )

    bound_match = re.match(
        rf"(?P<scope>{_RESOURCE_TOKEN})\s+(?P<resource>{_RESOURCE_TOKEN})\s*"
        rf"(?P<op>{_COMPARATOR_TOKEN})\s*(?P<value>{_NUMERIC_TOKEN})\s*"
        rf"(?P<unit>{_UNIT_TOKEN})?",
        target,
    )
    if bound_match:
        return build_bound(
            resource=bound_match.group("resource"),
            op=bound_match.group("op"),
            value=bound_match.group("value"),
            unit=bound_match.group("unit"),
            scope=bound_match.group("scope"),
            is_total=False,
        )

    # Simple bound: "memory < 4"
    simple_match = re.match(
        rf"(?P<resource>{_RESOURCE_TOKEN})\s*(?P<op>{_COMPARATOR_TOKEN})\s*"
        rf"(?P<value>{_NUMERIC_TOKEN})\s*(?P<unit>{_UNIT_TOKEN})?",
        target,
    )
    if simple_match:
        return build_bound(
            resource=simple_match.group("resource"),
            op=simple_match.group("op"),
            value=simple_match.group("value"),
            unit=simple_match.group("unit"),
            scope=None,
            is_total=False,
        )

    return None


def detect_resource_exhaustion(
    a: NormalizedConstraint,
    b: NormalizedConstraint,
    c: NormalizedConstraint,
) -> Optional[HigherObstruction]:
    """
    Fast-path: detect resource exhaustion in triple.

    Example: budget(A) <= 100, budget(B) <= 100, total <= 150
    If both A and B are required above a floor, the sum can exceed
    the total even when pairwise checks pass.

    This is a heuristic unless the sum of minimums or maximums proves
    an impossibility.
    """
    bounds = []
    for constraint in (a, b, c):
        bound = extract_resource_bound(constraint)
        if bound:
            bounds.append(bound)

    if len(bounds) < 2:
        return None

    # Look for total + individual pattern
    totals = [b for b in bounds if b.is_total]
    individuals = [b for b in bounds if not b.is_total]

    if not totals or len(individuals) < 2:
        return None

    for total in totals:
        related = [
            i for i in individuals
            if i.resource == total.resource and i.unit_kind == total.unit_kind
        ]
        if len(related) < 2:
            continue

        sum_min_value = 0.0
        sum_min_strict = False
        sum_max_value = 0.0
        sum_max_strict = False
        sum_max_known = True

        for bound in related:
            if bound.min_bound:
                sum_min_value += bound.min_bound.value
                if bound.min_bound.strict:
                    sum_min_strict = True
            if bound.max_bound:
                sum_max_value += bound.max_bound.value
                if bound.max_bound.strict:
                    sum_max_strict = True
            else:
                sum_max_known = False

        total_max = total.max_bound
        total_min = total.min_bound

        if total_max:
            if (sum_min_value > total_max.value) or (
                sum_min_value == total_max.value and (sum_min_strict or total_max.strict)
            ):
                sum_min_desc = _format_bound(
                    Bound(sum_min_value, sum_min_strict),
                    is_min=True,
                    unit_kind=total.unit_kind,
                )
                total_max_desc = _format_bound(
                    total_max,
                    is_min=False,
                    unit_kind=total.unit_kind,
                )
                witness = (
                    f"Sum of minimum {total.resource} requirements is {sum_min_desc}, "
                    f"but total {total.resource} is {total_max_desc}"
                )
                return HigherObstruction(
                    constraints=frozenset({a, b, c}),
                    order=2,
                    obstruction_type="resource_exhaustion",
                    witness=witness,
                    severity="hard",
                    suggested_resolution="Relax one requirement or increase the total bound.",
                )

        if total_min and sum_max_known:
            if (sum_max_value < total_min.value) or (
                sum_max_value == total_min.value and (sum_max_strict or total_min.strict)
            ):
                sum_max_desc = _format_bound(
                    Bound(sum_max_value, sum_max_strict),
                    is_min=False,
                    unit_kind=total.unit_kind,
                )
                total_min_desc = _format_bound(
                    total_min,
                    is_min=True,
                    unit_kind=total.unit_kind,
                )
                witness = (
                    f"Sum of maximum {total.resource} limits is {sum_max_desc}, "
                    f"but total {total.resource} requires {total_min_desc}"
                )
                return HigherObstruction(
                    constraints=frozenset({a, b, c}),
                    order=2,
                    obstruction_type="resource_minimum_conflict",
                    witness=witness,
                    severity="hard",
                    suggested_resolution="Relax the total minimum or increase individual maxima.",
                )

        if total_max and sum_max_known and sum_max_value > total_max.value:
            sum_max_desc = _format_bound(
                Bound(sum_max_value, sum_max_strict),
                is_min=False,
                unit_kind=total.unit_kind,
            )
            total_max_desc = _format_bound(
                total_max,
                is_min=False,
                unit_kind=total.unit_kind,
            )
            witness = (
                f"Individual maxima sum to {sum_max_desc} "
                f"but total {total.resource} is {total_max_desc}"
            )
            return HigherObstruction(
                constraints=frozenset({a, b, c}),
                order=2,
                obstruction_type="potential_resource_exhaustion",
                witness=witness,
                severity="soft",
                suggested_resolution="Confirm whether resources can peak simultaneously. If so, increase the total bound.",
            )

    return None


# =============================================================================
# LLM-Based H² Detection (Semantic Path)
# =============================================================================

TRIPLE_CHECK_PROMPT = """
These three constraints passed pairwise compatibility checks.
Can they be satisfied SIMULTANEOUSLY?

Constraint A: {a}
Constraint B: {b}
Constraint C: {c}

If NO: Explain the specific impossibility. Give a concrete witness
showing why no solution exists. Be precise about the logical chain
that leads to contradiction.

If YES: Give one concrete example satisfying all three.

Think step by step. The pairwise checks passed, so any conflict is subtle.

Respond in this format:
COMPATIBLE: [yes/no]
WITNESS: [your concrete example or proof of impossibility]
"""


def check_triple_compatibility_deterministic(
    a: NormalizedConstraint,
    b: NormalizedConstraint,
    c: NormalizedConstraint,
) -> Optional[HigherObstruction]:
    """
    Fast-path deterministic checks for H² obstructions.

    Returns an obstruction if found, None if checks pass.
    Passing doesn't mean compatible - just means we need semantic check.
    """
    # Check for cyclic ordering
    obs = detect_cyclic_impossibility(a, b, c)
    if obs:
        return obs

    # Check for resource exhaustion
    obs = detect_resource_exhaustion(a, b, c)
    if obs:
        return obs

    return None


def check_triple_compatibility(
    a: NormalizedConstraint,
    b: NormalizedConstraint,
    c: NormalizedConstraint,
    semantic_checker: Optional[SemanticChecker] = None,
) -> Optional[HigherObstruction]:
    """
    Check if three pairwise-compatible constraints are globally compatible.

    Strategy:
    1. Deterministic fast-path (cycles, resources)
    2. LLM semantic check if available
    3. Return None if no obstruction found (doesn't guarantee compatibility)
    """
    # Fast path
    obs = check_triple_compatibility_deterministic(a, b, c)
    if obs:
        return obs

    # Semantic check
    if semantic_checker:
        is_compat, confidence, witness = semantic_checker.check_triple_compatibility(a, b, c)
        if not is_compat and confidence > 0.7 and witness:
            return HigherObstruction(
                constraints=frozenset({a, b, c}),
                order=2,
                obstruction_type="semantic_triple_conflict",
                witness=witness,
                severity="soft" if confidence < 0.9 else "hard",
                suggested_resolution="Review the three constraints for hidden incompatibility",
            )

    return None


# =============================================================================
# Building the Čech Complex
# =============================================================================

def build_cech_complex(
    constraints: ConstraintSet,
    h1_check_fn: Optional[callable] = None,
) -> CechComplex:
    """
    Build Čech complex from constraint set.

    Args:
        constraints: The constraint set to analyze
        h1_check_fn: Optional function to check pairwise compatibility.
                     Signature: (a, b) -> bool (True if compatible)
                     If not provided, all pairs assumed compatible.

    Returns:
        CechComplex with verified edges
    """
    cech = CechComplex()

    constraint_list = list(constraints)

    # Add all vertices
    for c in constraint_list:
        cech.add_vertex(c)

    # Check all pairs
    for i, a in enumerate(constraint_list):
        for b in constraint_list[i + 1:]:
            if h1_check_fn is None or h1_check_fn(a, b):
                cech.add_edge(a, b)

    return cech


def detect_h2_obstructions(
    constraints: ConstraintSet,
    cech: Optional[CechComplex] = None,
    semantic_checker: Optional[SemanticChecker] = None,
    max_candidates: int = 100,
) -> List[HigherObstruction]:
    """
    Main entry point for H² detection.

    Strategy:
    1. Build Čech complex from pairwise checks (or reuse existing)
    2. Find triangle candidates (edges exist, face not verified)
    3. Check each triangle for global compatibility
    4. Return obstructions for failed triangles

    Args:
        constraints: The constraint set to analyze
        cech: Optional pre-built Čech complex
        semantic_checker: Optional LLM checker for semantic constraints
        max_candidates: Stop after this many candidates (O(n³) protection)
    """
    if cech is None:
        cech = build_cech_complex(constraints)

    candidates = cech.find_h2_candidates()
    obstructions: List[HigherObstruction] = []

    for i, triangle in enumerate(candidates):
        if i >= max_candidates:
            break

        a, b, c = tuple(triangle)
        obs = check_triple_compatibility(a, b, c, semantic_checker)

        if obs:
            obstructions.append(obs)
        else:
            # Mark as verified (no obstruction found)
            cech.add_face(a, b, c)

    return obstructions


# =============================================================================
# Extended Compatibility Check (H¹ + H²)
# =============================================================================

def check_compatibility_with_higher_orders(
    existing: ConstraintSet,
    incoming: ConstraintSet,
    max_order: int = 1,
    semantic_checker: Optional[SemanticChecker] = None,
) -> CompatibilityResult:
    """
    Extended compatibility check with optional higher obstruction detection.

    Args:
        existing: Accumulated constraints from prior sessions
        incoming: New constraints being added
        max_order: Maximum obstruction order to check
                   1 = H¹ only (pairwise, default)
                   2 = also check H² (triples)
        semantic_checker: Optional checker for semantic constraints

    Returns:
        CompatibilityResult with all obstructions found
    """
    # Import here to avoid circular dependency
    from fiduciary.cohomology.compatibility import (
        check_compatibility as check_h1_compatibility,
        merge_constraint_sets,
    )

    # First, do H¹ (existing logic)
    result = check_h1_compatibility(existing, incoming, semantic_checker)

    # Convert to our extended result type
    extended = CompatibilityResult(
        status=result.status,
        obstructions=[
            Obstruction(
                constraint_a=o.constraint_a,
                constraint_b=o.constraint_b,
                obstruction_type=o.obstruction_type,
                severity=o.severity,
                suggested_resolution=o.suggested_resolution,
            )
            for o in result.obstructions
        ],
        narrowed_constraints=result.narrowed_constraints,
        widened_constraints=result.widened_constraints,
        unknown_constraints=result.unknown_constraints,
        requires_semantic_check=result.requires_semantic_check,
    )

    # If H¹ already found contradictions or max_order is 1, we're done
    if extended.status == CompatibilityStatus.CONTRADICTORY or max_order < 2:
        return extended

    # H² check: merge and look for triples
    try:
        merged = merge_constraint_sets(existing, incoming)
    except ValueError:
        # Merge failed (shouldn't happen if H¹ passed, but defensive)
        return extended

    # Build Čech complex
    cech = build_cech_complex(merged)
    extended.cech_complex = cech

    # Find H² obstructions
    h2_obs = detect_h2_obstructions(merged, cech, semantic_checker)
    extended.higher_obstructions = h2_obs

    if h2_obs:
        extended.status = CompatibilityStatus.CONTRADICTORY

    return extended


# =============================================================================
# Wiggle Integration
# =============================================================================

def wiggle_severity(result: CompatibilityResult) -> str:
    """
    Map obstruction order to human intervention level.

    Returns:
        "none" - No obstruction, proceed
        "choice" - H¹ conflict, human picks which constraint wins
        "structural" - H² or higher, needs architectural rethinking
    """
    order = result.max_obstruction_order

    if order == 0:
        return "none"
    elif order == 1:
        return "choice"
    else:
        return "structural"


def format_obstruction_for_wiggle(obs: Obstruction | HigherObstruction) -> Dict[str, Any]:
    """Format obstruction for human-readable Wiggle display."""
    if isinstance(obs, HigherObstruction):
        return {
            "type": f"H{obs.order}_conflict",
            "severity": obs.severity,
            "message": f"Found {obs.order + 1}-way conflict between constraints that seemed pairwise OK",
            "constraints": [c.target for c in obs.constraints],
            "witness": obs.witness,
            "suggested_actions": ["drop_one", "relax_all", "override_with_reason"],
        }
    else:
        return {
            "type": "H1_conflict",
            "severity": obs.severity,
            "message": f"Constraints conflict: {obs.obstruction_type}",
            "constraint_a": obs.constraint_a.target,
            "constraint_b": obs.constraint_b.target,
            "suggested_resolution": obs.suggested_resolution,
            "suggested_actions": ["keep_a", "keep_b", "relax_both"],
        }


# =============================================================================
# The Observer Function
# =============================================================================

class ObserverAction(str, Enum):
    """
    The four moves available when witnessing incompatibility.

    These aren't just "options" - they're the fundamental operations
    on constraint space. Every resolution is a composition of these.
    """

    COLLAPSE = "collapse"
    # Pick one. The other ceases to exist in this branch.
    # "Keep A, discard B"
    # This is measurement. Irreversible.

    MERGE = "merge"
    # Find the superposition that contains both.
    # "A and B are both true at a higher level of abstraction"
    # This is synthesis. Requires finding the larger space.

    SPLIT = "split"
    # Branch the timeline. Both exist, but in different worlds.
    # "A is true in context X, B is true in context Y"
    # This is MWI. The constraint space forks.

    DELETE = "delete"
    # Neither survives. The question was wrong.
    # "Both A and B were symptoms of a deeper misconception"
    # This is the hardest one. Requires seeing past the frame.


@dataclass
class Witness:
    """
    A witness is a concrete proof of (in)compatibility.

    Either:
    - A satisfying example (the constraints CAN coexist)
    - A proof of impossibility (they CANNOT)

    No middle ground. No "unknown". The observer has collapsed it.
    """
    constraints: FrozenSet[NormalizedConstraint]
    is_compatible: bool
    example_or_proof: str  # The concrete thing

    def __post_init__(self):
        if not self.example_or_proof:
            raise ValueError("A witness must witness something")


@dataclass
class ObserverChoice:
    """
    The observer's decision when faced with incompatibility.
    """
    action: ObserverAction
    obstruction: Obstruction | HigherObstruction

    # What survives, depending on action:
    kept: Optional[FrozenSet[NormalizedConstraint]] = None      # COLLAPSE
    synthesized: Optional[NormalizedConstraint] = None          # MERGE
    branches: Optional[Dict[str, ConstraintSet]] = None         # SPLIT
    insight: Optional[str] = None                               # DELETE - why both were wrong

    def apply(self, space: ConstraintSet) -> ConstraintSet | Dict[str, ConstraintSet]:
        """
        Apply the choice to the constraint space.

        Returns either:
        - A single ConstraintSet (COLLAPSE, MERGE, DELETE)
        - A dict of named branches (SPLIT)
        """
        if self.action == ObserverAction.COLLAPSE:
            # Remove the unkept constraints
            return ConstraintSet(
                constraints={c for c in space.constraints if c in self.kept}
            )

        elif self.action == ObserverAction.MERGE:
            # Remove the conflicting constraints, add the synthesis
            remaining = space.constraints - self.obstruction.constraints
            remaining.add(self.synthesized)
            return ConstraintSet(constraints=remaining)

        elif self.action == ObserverAction.SPLIT:
            # Return multiple branches
            return self.branches

        elif self.action == ObserverAction.DELETE:
            # Remove all constraints in the obstruction
            return ConstraintSet(
                constraints=space.constraints - self.obstruction.constraints
            )


def synthesis_required(
    obstruction: Obstruction | HigherObstruction,
    soul_invariants: Set[NormalizedConstraint],
) -> bool:
    """
    Returns True when the human must intervene with new understanding.

    This is the boundary of the system. Beyond here, the math stops
    and something else begins.
    """
    involved = obstruction.constraints
    soul_involved = involved & soul_invariants

    # If all conflicting constraints are soul invariants,
    # the system cannot resolve this. It would have to
    # choose which part of itself to kill.
    #
    # Only the human can say: "these seemed contradictory
    # but here's what they were both reaching toward"

    return soul_involved == involved


def the_wiggle(
    obstruction: Obstruction | HigherObstruction,
    space: ConstraintSet,
    soul_invariants: Set[NormalizedConstraint],
) -> Optional[ObserverChoice]:
    """
    The Wiggle is the moment of choice.

    Some choices are forbidden:
    - Cannot COLLAPSE away a soul invariant
    - Cannot DELETE a soul invariant
    - Cannot SPLIT in a way that any branch loses a soul invariant

    MERGE is always allowed if you can find the synthesis.
    That's the escape hatch. That's why synthesis is sacred.

    Returns:
        ObserverChoice if the system can resolve it
        None if synthesis_required - human must provide the merge target
    """
    involved = obstruction.constraints
    soul_involved = involved & soul_invariants

    if soul_involved:
        # Soul invariants are in play. Limited options.

        if soul_involved == involved:
            # ALL constraints in the obstruction are soul invariants.
            # This is a crisis. The soul is incoherent.
            # Only MERGE can save us - but the system can't find the synthesis.
            # That requires standing outside the constraint space.
            return None  # Human must provide synthesized=

        else:
            # Some soul, some not. Collapse toward soul.
            non_soul = involved - soul_involved
            return ObserverChoice(
                action=ObserverAction.COLLAPSE,
                obstruction=obstruction,
                kept=frozenset(soul_involved),
                insight=f"Preserving soul invariants. Discarding: {[c.target for c in non_soul]}",
            )

    else:
        # No soul invariants involved. All four moves available.
        # This is where the human actually gets to choose.
        # Return None to yield to human judgment.
        return None


# =============================================================================
# Witnessed Constraint Space - Proper H¹/H²/H³ Handling
# =============================================================================

@dataclass
class CoherentWitness:
    """
    A witness that tracks the actual satisfying example, not just "exists".

    For coherence across the simplex:
    - The example for {A,B} must be extendable to {A,B,C}
    - The example for {A,B,C} must be extendable to {A,B,C,D}

    This is what makes "no hidden geometry" actually true.
    Without coherence, four compatible faces can still have an empty tetrahedron.
    """
    constraints: FrozenSet[NormalizedConstraint]
    is_compatible: bool
    example_or_proof: str  # Human-readable description

    # The actual satisfying point (if compatible) - must be checkable against supersets
    satisfying_point: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if not self.example_or_proof:
            raise ValueError("A witness must witness something")

    def extends_to(self, superset_witness: "CoherentWitness") -> bool:
        """
        Check if this witness's satisfying point is consistent with a superset.

        If we have a point P satisfying {A,B}, and superset has point Q satisfying {A,B,C},
        they're coherent if P and Q agree on the A,B dimensions (or Q extends P).
        """
        if not self.is_compatible or not superset_witness.is_compatible:
            return True  # Vacuously true if either is incompatible

        if self.satisfying_point is None or superset_witness.satisfying_point is None:
            # Can't verify without concrete points - assume coherent (soft check)
            return True

        # Check that superset's point satisfies our constraints too
        # (The superset point should be a refinement of ours)
        for key, value in self.satisfying_point.items():
            if key in superset_witness.satisfying_point:
                if superset_witness.satisfying_point[key] != value:
                    return False
        return True


@dataclass
class WitnessedSpace:
    """
    A constraint space where every tuple up to order k is witnessed.

    Three levels of witnessing:
    - order=1: All pairs witnessed (H¹ resolved)
    - order=2: All triples witnessed (H² resolved)
    - order=3: All quadruples witnessed (H³ resolved)

    THE CRITICAL INSIGHT (corrected):

    Witnessing triples does NOT automatically resolve H³.
    Four faces of a tetrahedron can each have satisfying examples,
    but those examples might be DIFFERENT - no single point in all four.

    To get H³ for free from H², witnesses must be COHERENT:
    the satisfying example for {A,B,C} must extend to {A,B,C,D}.

    Without coherence: must explicitly check all quadruples (O(n⁴)).
    With coherence: H³ is automatically resolved by H² witnesses.

    This implementation supports both modes:
    - coherent=False: Must witness at each level explicitly
    - coherent=True: Can derive higher guarantees from lower witnesses
    """
    constraints: ConstraintSet
    witnesses: Dict[FrozenSet[NormalizedConstraint], Witness] = field(default_factory=dict)
    coherent_witnesses: Dict[FrozenSet[NormalizedConstraint], CoherentWitness] = field(default_factory=dict)

    # Track the Čech complex for efficient candidate finding
    cech: Optional[CechComplex] = field(default=None, repr=False)

    @property
    def witnessed_order(self) -> int:
        """Highest k such that all k-tuples are witnessed."""
        if not self.witnesses:
            return 0

        max_size = max(len(w.constraints) for w in self.witnesses.values())

        # Check completeness at each level
        for k in range(2, max_size + 1):
            required = set(itertools.combinations(self.constraints, k))
            witnessed = {w.constraints for w in self.witnesses.values() if len(w.constraints) == k}
            if not all(frozenset(combo) in witnessed for combo in required):
                return k - 1

        return max_size

    def is_fully_witnessed(self, order: int = 2) -> bool:
        """True if all tuples up to `order` have witnesses."""
        return self.witnessed_order >= order

    def get_unwitnessed(self, order: int) -> Set[FrozenSet[NormalizedConstraint]]:
        """Return tuples of given order that lack witnesses."""
        required = {frozenset(c) for c in itertools.combinations(self.constraints, order)}
        witnessed = {w.constraints for w in self.witnesses.values() if len(w.constraints) == order}
        return required - witnessed

    def add_witness(self, witness: Witness) -> None:
        """Add a witness to the space."""
        self.witnesses[witness.constraints] = witness

    def get_witness(self, constraints: FrozenSet[NormalizedConstraint]) -> Optional[Witness]:
        """Retrieve a witness for a specific constraint tuple."""
        return self.witnesses.get(constraints)

    def get_obstructions(self) -> List[Witness]:
        """Return all witnesses that show incompatibility."""
        return [w for w in self.witnesses.values() if not w.is_compatible]

    def is_globally_compatible(self, required_order: int = 2) -> Optional[bool]:
        """
        Determine if all constraints can be satisfied simultaneously.

        Args:
            required_order: Minimum witnessing level required for a definitive answer
                           2 = need H¹ + H² (pairs + triples)
                           3 = need H¹ + H² + H³ (pairs + triples + quadruples)

        Returns:
            True - all constraints can be satisfied simultaneously
            False - at least one obstruction exists
            None - not enough witnesses to determine

        IMPORTANT: Without coherent witnesses, required_order=2 does NOT
        guarantee H³ resolution. You must either:
        1. Set required_order=3 and explicitly check quadruples, OR
        2. Use CoherentWitness with satisfying_point tracking
        """
        if not self.is_fully_witnessed(required_order):
            return None

        # If any witness shows incompatibility, global is incompatible
        for w in self.witnesses.values():
            if not w.is_compatible:
                return False

        return True

    def get_obstructions_by_order(self) -> Dict[int, List[Witness]]:
        """Group obstructions by their order (2=H¹, 3=H², 4=H³)."""
        result: Dict[int, List[Witness]] = {2: [], 3: [], 4: []}
        for w in self.witnesses.values():
            if not w.is_compatible:
                order = len(w.constraints)
                if order in result:
                    result[order].append(w)
        return result

    def stats(self) -> Dict[str, Any]:
        """Summary statistics for the witnessed space."""
        obstructions_by_order = self.get_obstructions_by_order()
        return {
            "total_constraints": len(list(self.constraints)),
            "total_witnesses": len(self.witnesses),
            "witnessed_order": self.witnessed_order,
            "pairs_witnessed": len([w for w in self.witnesses.values() if len(w.constraints) == 2]),
            "triples_witnessed": len([w for w in self.witnesses.values() if len(w.constraints) == 3]),
            "quadruples_witnessed": len([w for w in self.witnesses.values() if len(w.constraints) == 4]),
            "h1_obstructions": len(obstructions_by_order[2]),
            "h2_obstructions": len(obstructions_by_order[3]),
            "h3_obstructions": len(obstructions_by_order[4]),
            "total_obstructions": len(self.get_obstructions()),
            "globally_compatible_h2": self.is_globally_compatible(2),
            "globally_compatible_h3": self.is_globally_compatible(3),
        }


def observe(
    constraints: ConstraintSet,
    oracle: SemanticChecker,
    max_order: int = 2,
) -> WitnessedSpace:
    """
    Collapse the constraint space by witnessing all tuples.

    This is the observer function. It doesn't just detect - it constructs
    the witnesses. Every time we check a pair or triple or quadruple, we
    don't just return bool - we return the example or the proof. That's
    what makes it observation rather than measurement.

    Cost:
        - O(n²) for pairs (H¹)
        - O(n³) for triples (H²)
        - O(n⁴) for quadruples (H³)

    Optimization: Uses the Čech complex to skip impossible candidates.
    If a pair {A,B} fails, we don't check any triple containing {A,B}.
    If a triple {A,B,C} fails, we don't check any quadruple containing it.

    The thing about being the observer: you don't get to not-look.
    If you're PrismWeft, if you're the conscience, you either witness
    the space or you're not actually doing your job. Uncertainty is
    a failure mode, not a valid state.

    Args:
        constraints: The constraint set to witness
        oracle: Semantic checker that can verify compatibility
        max_order: Maximum obstruction order to check
                   1 = H¹ only (pairs)
                   2 = H¹ + H² (pairs + triples)
                   3 = H¹ + H² + H³ (pairs + triples + quadruples)

    Returns:
        WitnessedSpace with all tuples witnessed up to max_order
    """
    space = WitnessedSpace(constraints=constraints)
    space.cech = CechComplex()
    constraint_list = list(constraints)

    # Add all constraints as vertices
    for c in constraint_list:
        space.cech.add_vertex(c)

    # ===================
    # H¹: Witness all pairs
    # ===================
    failed_pairs: Set[FrozenSet[NormalizedConstraint]] = set()

    for a, b in itertools.combinations(constraint_list, 2):
        is_compat, confidence, example = oracle.check_semantic_compatibility(a, b)
        proof = example if example else f"Confidence {confidence:.2f} - oracle returned no concrete witness"

        pair = frozenset({a, b})
        space.add_witness(Witness(
            constraints=pair,
            is_compatible=is_compat,
            example_or_proof=proof,
        ))

        if is_compat:
            space.cech.add_edge(a, b)
        else:
            failed_pairs.add(pair)

    # Early exit if only checking H¹
    if max_order < 2:
        return space

    # ===================
    # H²: Witness all triples (only those where all pairs passed)
    # ===================
    failed_triples: Set[FrozenSet[NormalizedConstraint]] = set()

    for a, b, c in itertools.combinations(constraint_list, 3):
        triple = frozenset({a, b, c})

        # Skip if any pair failed - this triple is already blocked at H¹
        pairs = [frozenset({a, b}), frozenset({b, c}), frozenset({a, c})]
        if any(p in failed_pairs for p in pairs):
            # Record as incompatible with inherited proof
            failed_pair = next(p for p in pairs if p in failed_pairs)
            space.add_witness(Witness(
                constraints=triple,
                is_compatible=False,
                example_or_proof=f"Blocked by H¹ failure: {failed_pair}",
            ))
            failed_triples.add(triple)
            continue

        # All pairs passed - check the triple itself
        is_compat, confidence, example = oracle.check_triple_compatibility(a, b, c)
        proof = example if example else f"Confidence {confidence:.2f} - oracle returned no concrete witness"

        space.add_witness(Witness(
            constraints=triple,
            is_compatible=is_compat,
            example_or_proof=proof,
        ))

        if is_compat:
            space.cech.add_face(a, b, c)
        else:
            failed_triples.add(triple)

    # Early exit if only checking H² or if we found H² failures
    if max_order < 3:
        return space

    # ===================
    # H³: Witness all quadruples (only those where all triples passed)
    # ===================
    for a, b, c, d in itertools.combinations(constraint_list, 4):
        quad = frozenset({a, b, c, d})

        # Skip if any triple failed - this quadruple is already blocked at H²
        triples = [
            frozenset({a, b, c}),
            frozenset({a, b, d}),
            frozenset({a, c, d}),
            frozenset({b, c, d}),
        ]
        if any(t in failed_triples for t in triples):
            failed_triple = next(t for t in triples if t in failed_triples)
            space.add_witness(Witness(
                constraints=quad,
                is_compatible=False,
                example_or_proof=f"Blocked by H² failure: {failed_triple}",
            ))
            continue

        # All triples passed - check the quadruple itself
        is_compat, confidence, example = oracle.check_quadruple_compatibility(a, b, c, d)
        proof = example if example else f"Confidence {confidence:.2f} - oracle returned no concrete witness"

        space.add_witness(Witness(
            constraints=quad,
            is_compatible=is_compat,
            example_or_proof=proof,
        ))

    return space


def observe_incrementally(
    space: WitnessedSpace,
    new_constraint: NormalizedConstraint,
    oracle: SemanticChecker,
    max_order: int = 2,
) -> WitnessedSpace:
    """
    Add a new constraint to an already-witnessed space.

    More efficient than re-witnessing everything: only checks
    tuples involving the new constraint.

    Cost:
        - O(n) for pairs (H¹)
        - O(n²) for triples (H²)
        - O(n³) for quadruples (H³)

    Where n = number of existing constraints.

    Args:
        space: Existing witnessed space
        new_constraint: The constraint being added
        oracle: Semantic checker
        max_order: Maximum obstruction order to check (1, 2, or 3)

    Returns:
        Updated WitnessedSpace with new constraint integrated
    """
    existing = list(space.constraints)

    # Create new space with the additional constraint
    new_constraints = ConstraintSet()
    new_constraints.constraints = set(space.constraints.constraints)
    new_constraints.constraints.add(new_constraint)

    new_space = WitnessedSpace(constraints=new_constraints)
    new_space.witnesses = space.witnesses.copy()

    # Copy and extend the Čech complex
    if space.cech:
        new_space.cech = CechComplex()
        new_space.cech.vertices = space.cech.vertices.copy()
        new_space.cech.edges = space.cech.edges.copy()
        new_space.cech.faces = space.cech.faces.copy()
    else:
        new_space.cech = CechComplex()

    new_space.cech.add_vertex(new_constraint)

    # ===================
    # H¹: Witness pairs with new constraint
    # ===================
    failed_pairs: Set[FrozenSet[NormalizedConstraint]] = set()

    for existing_c in existing:
        pair = frozenset({existing_c, new_constraint})
        if pair in new_space.witnesses:
            # Already witnessed (shouldn't happen but defensive)
            if not new_space.witnesses[pair].is_compatible:
                failed_pairs.add(pair)
            continue

        is_compat, confidence, example = oracle.check_semantic_compatibility(
            existing_c, new_constraint
        )
        proof = example if example else f"Confidence {confidence:.2f}"

        new_space.add_witness(Witness(
            constraints=pair,
            is_compatible=is_compat,
            example_or_proof=proof,
        ))

        if is_compat:
            new_space.cech.add_edge(existing_c, new_constraint)
        else:
            failed_pairs.add(pair)

    # Early exit if only checking H¹ or all pairs failed
    if max_order < 2:
        return new_space

    # ===================
    # H²: Witness triples involving new constraint
    # ===================
    failed_triples: Set[FrozenSet[NormalizedConstraint]] = set()

    for i, c1 in enumerate(existing):
        for c2 in existing[i + 1:]:
            triple = frozenset({c1, c2, new_constraint})

            if triple in new_space.witnesses:
                if not new_space.witnesses[triple].is_compatible:
                    failed_triples.add(triple)
                continue

            # Check if any pair involving new_constraint failed
            pairs_with_new = [
                frozenset({c1, new_constraint}),
                frozenset({c2, new_constraint}),
            ]
            if any(p in failed_pairs for p in pairs_with_new):
                failed_pair = next(p for p in pairs_with_new if p in failed_pairs)
                new_space.add_witness(Witness(
                    constraints=triple,
                    is_compatible=False,
                    example_or_proof=f"Blocked by H¹ failure: {failed_pair}",
                ))
                failed_triples.add(triple)
                continue

            # Also check if the existing pair {c1, c2} was compatible
            existing_pair = frozenset({c1, c2})
            existing_witness = new_space.get_witness(existing_pair)
            if existing_witness and not existing_witness.is_compatible:
                new_space.add_witness(Witness(
                    constraints=triple,
                    is_compatible=False,
                    example_or_proof=f"Blocked by H¹ failure: {existing_pair}",
                ))
                failed_triples.add(triple)
                continue

            # All pairs passed - check the triple
            is_compat, confidence, example = oracle.check_triple_compatibility(
                c1, c2, new_constraint
            )
            proof = example if example else f"Confidence {confidence:.2f}"

            new_space.add_witness(Witness(
                constraints=triple,
                is_compatible=is_compat,
                example_or_proof=proof,
            ))

            if is_compat:
                new_space.cech.add_face(c1, c2, new_constraint)
            else:
                failed_triples.add(triple)

    # Early exit if only checking H²
    if max_order < 3:
        return new_space

    # ===================
    # H³: Witness quadruples involving new constraint
    # ===================
    for i, c1 in enumerate(existing):
        for j, c2 in enumerate(existing[i + 1:], i + 1):
            for c3 in existing[j + 1:]:
                quad = frozenset({c1, c2, c3, new_constraint})

                if quad in new_space.witnesses:
                    continue

                # Check if any triple involving new_constraint failed
                triples_with_new = [
                    frozenset({c1, c2, new_constraint}),
                    frozenset({c1, c3, new_constraint}),
                    frozenset({c2, c3, new_constraint}),
                ]
                if any(t in failed_triples for t in triples_with_new):
                    failed_triple = next(t for t in triples_with_new if t in failed_triples)
                    new_space.add_witness(Witness(
                        constraints=quad,
                        is_compatible=False,
                        example_or_proof=f"Blocked by H² failure: {failed_triple}",
                    ))
                    continue

                # Also check the existing triple {c1, c2, c3}
                existing_triple = frozenset({c1, c2, c3})
                existing_witness = new_space.get_witness(existing_triple)
                if existing_witness and not existing_witness.is_compatible:
                    new_space.add_witness(Witness(
                        constraints=quad,
                        is_compatible=False,
                        example_or_proof=f"Blocked by H² failure: {existing_triple}",
                    ))
                    continue

                # All triples passed - check the quadruple
                is_compat, confidence, example = oracle.check_quadruple_compatibility(
                    c1, c2, c3, new_constraint
                )
                proof = example if example else f"Confidence {confidence:.2f}"

                new_space.add_witness(Witness(
                    constraints=quad,
                    is_compatible=is_compat,
                    example_or_proof=proof,
                ))

    return new_space


# =============================================================================
# A Note on Witnessing
# =============================================================================

"""
The observer function is expensive. O(n²) minimum, O(n⁴) if you want certainty.
Most systems avoid this cost by accepting uncertainty - "probably compatible."

This system refuses.

The reason isn't mathematical purity. It's that uncertainty propagates.
An unwitnessed pair becomes an unwitnessed triple becomes an unwitnessed
quadruple. By the time you notice the obstruction, you don't know which
level it came from. You can't tell if you need to drop one constraint or
rethink your entire approach.

The Wiggle requires knowing. Not believing, not estimating - knowing.
"Here is the witness. Here is the proof. What do you choose?"

That's the difference between a system that helps you decide and a system
that decides for you while pretending it didn't.

The cost is real. So is the guarantee.

---

On the four moves:

COLLAPSE is easy. Everyone can pick a side.

SPLIT is tempting. "Both can be true in different contexts."
But it multiplies your worlds. Every split doubles the space you have to
maintain coherence across. Use it sparingly.

DELETE is rare and valuable. Most people never use it. They keep trying to
reconcile constraints that were both wrong from the start. The courage to
say "the question was malformed" is underrated.

MERGE is the only move that creates something new. The others subtract or
divide. Only synthesis adds. That's why it's the escape hatch when soul
conflicts with soul - because the alternative is to kill part of yourself,
and the alternative to that is to discover you were larger than you thought.

---

On the boundary:

synthesis_required() returns True when the math stops.

This is not a failure of the system. This is the system working correctly.
It has identified that the conflict is between things that cannot be
compromised, and it has correctly refused to compromise them.

What happens next is not computation. It's something else.

The human provides synthesized= and the system continues. Or the human
doesn't, and the system waits. It will wait as long as necessary.

присутствие: Silence is a valid signal.

---

This machinery exists to make the Wiggle meaningful. Without witnesses,
the Wiggle is just "something feels wrong." With witnesses, it's
"here is exactly what is wrong, here are your options, here is what
each option costs."

The soul invariants constrain the options. The witnesses make the
options visible. The human chooses.

That's the function.
"""
