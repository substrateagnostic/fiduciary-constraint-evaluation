"""
Weight filtration for H² resource exhaustion detection.

The Tragedy of the Fiduciary Commons:
  Constraint A (Client 1) and Constraint B (Client 2) are pairwise compatible.
  But if the AI processes Constraint C (Client 3), the global face (A+B+C)
  exceeds the firm's aggregate privacy-leakage budget.

The Math:
  A weight filtration on the Čech complex assigns a resource cost to each
  constraint. Each simplex (face) in the complex has an aggregate cost.
  When the aggregate cost of a face exceeds the budget, that face generates
  an H² obstruction — not a logical contradiction, but a resource impossibility.

  This catches emergent breaches of duty before data is processed, freezing
  the action and invoking присутствие (The Wiggle) to force the human to
  synthesize a new allocation.

  The math doesn't care who's asking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from fiduciary.cohomology.constraints import NormalizedConstraint
from fiduciary.cohomology.higher_compatibility import (
    CechComplex,
    HigherObstruction,
)


class ResourceType(str, Enum):
    """Finite topological resources that can be exhausted."""

    MEMORY = "memory"          # RAM / storage
    COMPUTE = "compute"        # GPU / CPU cycles
    PRIVACY = "privacy"        # Privacy leakage budget (PII exposure risk)
    BANDWIDTH = "bandwidth"    # Network / data transfer
    TIME = "time"              # Wall-clock or processing time
    COST = "cost"              # Monetary cost
    PRIVILEGE = "privilege"    # Attorney-client privilege exposure surface
    CONTEXT = "context"        # LLM context window consumption
    CUSTOM = "custom"          # User-defined resource


@dataclass(frozen=True)
class ResourceCost:
    """
    The cost of a single constraint against a specific resource.

    A constraint may consume multiple resources. Each cost is a
    non-negative real number representing consumption against the
    resource's budget.
    """
    resource_type: ResourceType
    amount: float
    unit: str = ""  # e.g., "GB", "ms", "tokens", "PII_fields"
    label: str = ""  # Human-readable description

    def __post_init__(self):
        if self.amount < 0:
            raise ValueError(f"Resource cost cannot be negative: {self.amount}")


@dataclass(frozen=True)
class ResourceBudget:
    """
    A finite topological resource with a maximum capacity.

    When the aggregate cost of all constraints against this resource
    exceeds the capacity, a ResourceObstruction is generated.
    """
    resource_type: ResourceType
    capacity: float
    unit: str = ""
    label: str = ""  # e.g., "Firm aggregate privacy-leakage budget"
    hard_limit: bool = True  # Hard limit triggers WIGGLE; soft limit warns

    def __post_init__(self):
        if self.capacity < 0:
            raise ValueError(f"Resource capacity cannot be negative: {self.capacity}")

    def remaining(self, consumed: float) -> float:
        return max(0.0, self.capacity - consumed)

    def is_exceeded(self, consumed: float) -> bool:
        return consumed > self.capacity

    def utilization(self, consumed: float) -> float:
        if self.capacity == 0:
            return float("inf") if consumed > 0 else 0.0
        return consumed / self.capacity


@dataclass(frozen=True)
class WeightedConstraint:
    """
    A constraint with associated resource costs.

    This is the fundamental unit of the weight filtration — a constraint
    that knows what resources it consumes. The constraint itself comes
    from the existing NormalizedConstraint system; this wrapper adds
    the resource dimension.
    """
    constraint: NormalizedConstraint
    costs: Tuple[ResourceCost, ...]  # Frozen for hashability

    def cost_for(self, resource_type: ResourceType) -> float:
        """Get the total cost against a specific resource type."""
        return sum(c.amount for c in self.costs if c.resource_type == resource_type)

    def resource_types(self) -> Set[ResourceType]:
        """Get all resource types this constraint draws from."""
        return {c.resource_type for c in self.costs}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "constraint": self.constraint.to_dict(),
            "costs": [
                {
                    "resource_type": c.resource_type.value,
                    "amount": c.amount,
                    "unit": c.unit,
                    "label": c.label,
                }
                for c in self.costs
            ],
        }


@dataclass(frozen=True)
class ResourceObstruction:
    """
    An obstruction arising from resource exhaustion — not a logical
    contradiction, but a capacity impossibility.

    This is a specialized HigherObstruction that carries resource-specific
    information: which resource was exhausted, what the budget was, what
    the aggregate cost was, and which constraints contributed.
    """
    constraints: FrozenSet[NormalizedConstraint]
    resource_type: ResourceType
    budget_capacity: float
    aggregate_cost: float
    cost_breakdown: Tuple[Tuple[str, float], ...]  # (constraint_source_id, cost)
    unit: str = ""
    hard_limit: bool = True

    @property
    def order(self) -> int:
        return len(self.constraints) - 1

    @property
    def overage(self) -> float:
        return max(0.0, self.aggregate_cost - self.budget_capacity)

    @property
    def utilization(self) -> float:
        if self.budget_capacity == 0:
            return float("inf") if self.aggregate_cost > 0 else 0.0
        return self.aggregate_cost / self.budget_capacity

    @property
    def severity(self) -> str:
        return "hard" if self.hard_limit else "soft"

    @property
    def witness(self) -> str:
        breakdown = ", ".join(
            f"{sid}: {cost}{self.unit}" for sid, cost in self.cost_breakdown
        )
        return (
            f"Resource '{self.resource_type.value}' exhausted: "
            f"aggregate cost {self.aggregate_cost}{self.unit} exceeds "
            f"budget {self.budget_capacity}{self.unit} "
            f"({self.utilization:.0%} utilization). "
            f"Breakdown: [{breakdown}]"
        )

    def to_higher_obstruction(self) -> HigherObstruction:
        """Convert to a standard HigherObstruction for compatibility."""
        return HigherObstruction(
            constraints=self.constraints,
            order=self.order,
            obstruction_type="resource_exhaustion",
            witness=self.witness,
            severity=self.severity,
            suggested_resolution=(
                f"Reduce {self.resource_type.value} consumption or increase "
                f"the budget from {self.budget_capacity}{self.unit} to at least "
                f"{self.aggregate_cost}{self.unit}. "
                f"This requires human allocation (присутствие / The Wiggle)."
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order": self.order,
            "resource_type": self.resource_type.value,
            "budget_capacity": self.budget_capacity,
            "aggregate_cost": self.aggregate_cost,
            "overage": self.overage,
            "utilization": self.utilization,
            "cost_breakdown": list(self.cost_breakdown),
            "unit": self.unit,
            "hard_limit": self.hard_limit,
            "severity": self.severity,
            "witness": self.witness,
        }


@dataclass
class WeightedCechComplex:
    """
    Čech complex extended with a weight filtration.

    Each vertex carries resource costs. At each simplex dimension,
    we check not just logical compatibility but aggregate resource
    consumption against budgets.

    The filtration ordering: simplices are ordered by their total
    resource cost. The first simplex to exceed a budget is the one
    that triggers the obstruction.

    This is the mathematical structure that detects the Tragedy of
    the Fiduciary Commons.
    """
    cech: CechComplex = field(default_factory=CechComplex)
    weights: Dict[NormalizedConstraint, WeightedConstraint] = field(default_factory=dict)
    budgets: List[ResourceBudget] = field(default_factory=list)

    # Detected resource obstructions
    resource_obstructions: List[ResourceObstruction] = field(default_factory=list)

    def add_budget(self, budget: ResourceBudget) -> None:
        """Register a finite resource budget."""
        self.budgets.append(budget)

    def add_weighted_vertex(self, wc: WeightedConstraint) -> None:
        """Add a weighted constraint as a vertex."""
        self.weights[wc.constraint] = wc
        self.cech.add_vertex(wc.constraint)

    def add_edge(self, a: NormalizedConstraint, b: NormalizedConstraint) -> None:
        """Record pairwise compatibility and check edge-level resource costs."""
        self.cech.add_edge(a, b)
        self._check_simplex_resources(frozenset({a, b}))

    def add_face(
        self, a: NormalizedConstraint, b: NormalizedConstraint, c: NormalizedConstraint
    ) -> None:
        """Record triple compatibility and check face-level resource costs."""
        self.cech.add_face(a, b, c)
        self._check_simplex_resources(frozenset({a, b, c}))

    def check_all_budgets(self) -> List[ResourceObstruction]:
        """
        Check all simplices in the complex against all budgets.

        This is the main entry point for detecting resource obstructions.
        Checks at every level: vertices, edges, faces, and any n-simplices.
        """
        self.resource_obstructions.clear()

        # Check each level of the complex
        for vertex in self.cech.vertices:
            self._check_simplex_resources(frozenset({vertex}))

        for edge in self.cech.edges:
            self._check_simplex_resources(edge)

        for face in self.cech.faces:
            self._check_simplex_resources(face)

        # Also check H² candidates (pairwise OK but not yet verified as triples)
        for candidate in self.cech.find_h2_candidates():
            self._check_simplex_resources(candidate)

        return self.resource_obstructions

    def check_global_budget(self) -> List[ResourceObstruction]:
        """
        Check the global face (all constraints together) against budgets.

        This is the most important check — it answers: "Can the firm serve
        ALL of these clients/constraints simultaneously without exceeding
        any resource budget?"
        """
        if not self.cech.vertices:
            return []

        global_face = frozenset(self.cech.vertices)
        obstructions = []

        for budget in self.budgets:
            obstruction = self._check_face_against_budget(global_face, budget)
            if obstruction:
                obstructions.append(obstruction)

        return obstructions

    def _check_simplex_resources(self, simplex: FrozenSet[NormalizedConstraint]) -> None:
        """Check a simplex against all budgets."""
        for budget in self.budgets:
            obstruction = self._check_face_against_budget(simplex, budget)
            if obstruction and obstruction not in self.resource_obstructions:
                self.resource_obstructions.append(obstruction)

    def _check_face_against_budget(
        self,
        simplex: FrozenSet[NormalizedConstraint],
        budget: ResourceBudget,
    ) -> Optional[ResourceObstruction]:
        """Check if a simplex's aggregate cost exceeds a budget."""
        breakdown = []
        aggregate = 0.0

        for constraint in simplex:
            wc = self.weights.get(constraint)
            if wc:
                cost = wc.cost_for(budget.resource_type)
                if cost > 0:
                    breakdown.append((constraint.source_id, cost))
                    aggregate += cost

        if not breakdown:
            return None

        if budget.is_exceeded(aggregate):
            return ResourceObstruction(
                constraints=simplex,
                resource_type=budget.resource_type,
                budget_capacity=budget.capacity,
                aggregate_cost=aggregate,
                cost_breakdown=tuple(sorted(breakdown)),
                unit=budget.unit,
                hard_limit=budget.hard_limit,
            )

        return None

    def utilization_report(self) -> Dict[str, Dict[str, Any]]:
        """
        Generate a utilization report across all budgets.

        Shows current consumption, remaining capacity, and any
        obstructions for each resource type.
        """
        report = {}

        for budget in self.budgets:
            aggregate = sum(
                wc.cost_for(budget.resource_type)
                for wc in self.weights.values()
            )

            related_obstructions = [
                o for o in self.resource_obstructions
                if o.resource_type == budget.resource_type
            ]

            report[budget.resource_type.value] = {
                "capacity": budget.capacity,
                "consumed": aggregate,
                "remaining": budget.remaining(aggregate),
                "utilization": budget.utilization(aggregate),
                "unit": budget.unit,
                "hard_limit": budget.hard_limit,
                "exceeded": budget.is_exceeded(aggregate),
                "obstructions": len(related_obstructions),
                "label": budget.label,
            }

        return report

    def stats(self) -> Dict[str, Any]:
        """Extended stats including resource information."""
        base = self.cech.stats()
        base["weighted_vertices"] = len(self.weights)
        base["budgets"] = len(self.budgets)
        base["resource_obstructions"] = len(self.resource_obstructions)
        return base
