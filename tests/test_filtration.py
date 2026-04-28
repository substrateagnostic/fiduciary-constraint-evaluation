"""
Tests for weight filtration — H² resource exhaustion detection.

The Tragedy of the Fiduciary Commons:
  Three clients' constraints are pairwise compatible, but serving
  all three simultaneously exceeds the firm's aggregate resource budget.
"""

import pytest

from fiduciary.models import Severity
from fiduciary.cohomology.constraints import (
    ConstraintType,
    ConstraintPolarity,
    NormalizedConstraint,
    create_soul_invariant,
    create_semantic_constraint,
)
from fiduciary.cohomology.filtration import (
    ResourceType,
    ResourceCost,
    ResourceBudget,
    WeightedConstraint,
    ResourceObstruction,
    WeightedCechComplex,
)


def _make_constraint(target: str, source_id: str) -> NormalizedConstraint:
    return NormalizedConstraint(
        constraint_type=ConstraintType.SEMANTIC_TOPIC,
        polarity=ConstraintPolarity.POSITIVE,
        target=target,
        severity=Severity.P1,
        source_id=source_id,
    )


# =============================================================================
# ResourceCost / ResourceBudget unit tests
# =============================================================================


class TestResourceCost:

    def test_create_cost(self):
        cost = ResourceCost(ResourceType.PRIVACY, 0.3, "PII_fields", "Client A PII")
        assert cost.resource_type == ResourceType.PRIVACY
        assert cost.amount == 0.3

    def test_negative_cost_rejected(self):
        with pytest.raises(ValueError, match="negative"):
            ResourceCost(ResourceType.MEMORY, -1.0)

    def test_zero_cost_allowed(self):
        cost = ResourceCost(ResourceType.COMPUTE, 0.0)
        assert cost.amount == 0.0


class TestResourceBudget:

    def test_remaining_capacity(self):
        budget = ResourceBudget(ResourceType.PRIVACY, 1.0, "PII_fields")
        assert budget.remaining(0.3) == pytest.approx(0.7)
        assert budget.remaining(1.5) == 0.0

    def test_exceeded(self):
        budget = ResourceBudget(ResourceType.PRIVACY, 1.0)
        assert not budget.is_exceeded(0.5)
        assert not budget.is_exceeded(1.0)
        assert budget.is_exceeded(1.01)

    def test_utilization(self):
        budget = ResourceBudget(ResourceType.COMPUTE, 100.0, "GPU_hours")
        assert budget.utilization(50.0) == pytest.approx(0.5)
        assert budget.utilization(100.0) == pytest.approx(1.0)
        assert budget.utilization(150.0) == pytest.approx(1.5)

    def test_zero_capacity_utilization(self):
        budget = ResourceBudget(ResourceType.COMPUTE, 0.0)
        assert budget.utilization(0.0) == 0.0
        assert budget.utilization(1.0) == float("inf")


class TestWeightedConstraint:

    def test_cost_for_resource(self):
        c = _make_constraint("topic A", "a")
        wc = WeightedConstraint(
            constraint=c,
            costs=(
                ResourceCost(ResourceType.PRIVACY, 0.3),
                ResourceCost(ResourceType.COMPUTE, 50.0),
                ResourceCost(ResourceType.PRIVACY, 0.1),  # second privacy cost
            ),
        )
        assert wc.cost_for(ResourceType.PRIVACY) == pytest.approx(0.4)
        assert wc.cost_for(ResourceType.COMPUTE) == pytest.approx(50.0)
        assert wc.cost_for(ResourceType.MEMORY) == 0.0

    def test_resource_types(self):
        c = _make_constraint("topic A", "a")
        wc = WeightedConstraint(
            constraint=c,
            costs=(
                ResourceCost(ResourceType.PRIVACY, 0.3),
                ResourceCost(ResourceType.COMPUTE, 50.0),
            ),
        )
        assert wc.resource_types() == {ResourceType.PRIVACY, ResourceType.COMPUTE}


# =============================================================================
# The Tragedy of the Fiduciary Commons
# =============================================================================


class TestFiduciaryCommons:
    """
    The core scenario: three law firm clients whose constraints are pairwise
    compatible but globally exceed the firm's aggregate privacy budget.
    """

    def test_three_clients_exceed_privacy_budget(self):
        """
        Client A: 0.4 PII exposure
        Client B: 0.4 PII exposure
        Client C: 0.4 PII exposure
        Firm budget: 1.0 PII total

        Any two clients: 0.8 < 1.0 ✓ (pairwise OK)
        All three clients: 1.2 > 1.0 ✗ (global face exceeds budget)
        """
        a = _make_constraint("Client A matters", "client_a")
        b = _make_constraint("Client B matters", "client_b")
        c = _make_constraint("Client C matters", "client_c")

        wc_a = WeightedConstraint(a, (ResourceCost(ResourceType.PRIVACY, 0.4, "PII"),))
        wc_b = WeightedConstraint(b, (ResourceCost(ResourceType.PRIVACY, 0.4, "PII"),))
        wc_c = WeightedConstraint(c, (ResourceCost(ResourceType.PRIVACY, 0.4, "PII"),))

        complex = WeightedCechComplex()
        complex.add_budget(ResourceBudget(
            ResourceType.PRIVACY, 1.0, "PII",
            label="Firm aggregate privacy-leakage budget",
        ))

        # Add weighted vertices
        complex.add_weighted_vertex(wc_a)
        complex.add_weighted_vertex(wc_b)
        complex.add_weighted_vertex(wc_c)

        # All pairs are compatible (0.8 < 1.0)
        complex.add_edge(a, b)
        complex.add_edge(a, c)
        complex.add_edge(b, c)

        # Check the global face
        obstructions = complex.check_global_budget()

        assert len(obstructions) == 1
        obs = obstructions[0]
        assert obs.resource_type == ResourceType.PRIVACY
        assert obs.aggregate_cost == pytest.approx(1.2)
        assert obs.budget_capacity == pytest.approx(1.0)
        assert obs.overage == pytest.approx(0.2)
        assert obs.utilization == pytest.approx(1.2)
        assert obs.severity == "hard"
        assert "присутствие" in obs.to_higher_obstruction().suggested_resolution

    def test_two_clients_under_budget(self):
        """Any two clients fit within budget — no obstruction."""
        a = _make_constraint("Client A", "client_a")
        b = _make_constraint("Client B", "client_b")

        wc_a = WeightedConstraint(a, (ResourceCost(ResourceType.PRIVACY, 0.4),))
        wc_b = WeightedConstraint(b, (ResourceCost(ResourceType.PRIVACY, 0.4),))

        complex = WeightedCechComplex()
        complex.add_budget(ResourceBudget(ResourceType.PRIVACY, 1.0))
        complex.add_weighted_vertex(wc_a)
        complex.add_weighted_vertex(wc_b)
        complex.add_edge(a, b)

        obstructions = complex.check_global_budget()
        assert len(obstructions) == 0

    def test_single_client_exceeds_budget(self):
        """Even one client can exceed budget — detected at vertex level."""
        a = _make_constraint("Heavy client", "heavy")
        wc_a = WeightedConstraint(a, (ResourceCost(ResourceType.COMPUTE, 200.0, "GPU_hrs"),))

        complex = WeightedCechComplex()
        complex.add_budget(ResourceBudget(ResourceType.COMPUTE, 100.0, "GPU_hrs"))
        complex.add_weighted_vertex(wc_a)

        obstructions = complex.check_all_budgets()
        assert len(obstructions) == 1
        assert obstructions[0].aggregate_cost == pytest.approx(200.0)


# =============================================================================
# Multi-resource scenarios
# =============================================================================


class TestMultiResource:

    def test_multiple_budgets_one_exceeded(self):
        """
        Privacy budget OK, but compute budget exceeded.
        """
        a = _make_constraint("Task A", "a")
        b = _make_constraint("Task B", "b")

        wc_a = WeightedConstraint(a, (
            ResourceCost(ResourceType.PRIVACY, 0.2),
            ResourceCost(ResourceType.COMPUTE, 60.0),
        ))
        wc_b = WeightedConstraint(b, (
            ResourceCost(ResourceType.PRIVACY, 0.2),
            ResourceCost(ResourceType.COMPUTE, 60.0),
        ))

        complex = WeightedCechComplex()
        complex.add_budget(ResourceBudget(ResourceType.PRIVACY, 1.0))
        complex.add_budget(ResourceBudget(ResourceType.COMPUTE, 100.0))
        complex.add_weighted_vertex(wc_a)
        complex.add_weighted_vertex(wc_b)
        complex.add_edge(a, b)

        obstructions = complex.check_global_budget()
        assert len(obstructions) == 1
        assert obstructions[0].resource_type == ResourceType.COMPUTE

    def test_privilege_exposure_surface(self):
        """
        Law firm specific: each client adds to the privilege exposure surface.
        """
        clients = []
        weighted = []
        for i in range(5):
            c = _make_constraint(f"Client {i} matters", f"client_{i}")
            wc = WeightedConstraint(c, (
                ResourceCost(ResourceType.PRIVILEGE, 0.25, "exposure_units",
                             f"Client {i} privilege exposure"),
            ))
            clients.append(c)
            weighted.append(wc)

        complex = WeightedCechComplex()
        complex.add_budget(ResourceBudget(
            ResourceType.PRIVILEGE, 1.0, "exposure_units",
            label="Maximum acceptable privilege exposure surface",
            hard_limit=True,
        ))

        for wc in weighted:
            complex.add_weighted_vertex(wc)

        # All pairwise compatible
        for i in range(len(clients)):
            for j in range(i + 1, len(clients)):
                complex.add_edge(clients[i], clients[j])

        obstructions = complex.check_global_budget()
        assert len(obstructions) == 1
        obs = obstructions[0]
        assert obs.resource_type == ResourceType.PRIVILEGE
        assert obs.aggregate_cost == pytest.approx(1.25)
        assert len(obs.cost_breakdown) == 5


# =============================================================================
# Utilization report
# =============================================================================


class TestUtilizationReport:

    def test_report_shows_all_budgets(self):
        a = _make_constraint("Task A", "a")
        wc_a = WeightedConstraint(a, (
            ResourceCost(ResourceType.PRIVACY, 0.3),
            ResourceCost(ResourceType.COMPUTE, 40.0),
        ))

        complex = WeightedCechComplex()
        complex.add_budget(ResourceBudget(ResourceType.PRIVACY, 1.0, "PII"))
        complex.add_budget(ResourceBudget(ResourceType.COMPUTE, 100.0, "GPU_hrs"))
        complex.add_weighted_vertex(wc_a)

        report = complex.utilization_report()

        assert "privacy" in report
        assert "compute" in report
        assert report["privacy"]["consumed"] == pytest.approx(0.3)
        assert report["privacy"]["utilization"] == pytest.approx(0.3)
        assert not report["privacy"]["exceeded"]
        assert report["compute"]["consumed"] == pytest.approx(40.0)

    def test_report_flags_exceeded(self):
        a = _make_constraint("Heavy", "a")
        wc_a = WeightedConstraint(a, (ResourceCost(ResourceType.MEMORY, 16.0, "GB"),))

        complex = WeightedCechComplex()
        complex.add_budget(ResourceBudget(ResourceType.MEMORY, 8.0, "GB"))
        complex.add_weighted_vertex(wc_a)

        report = complex.utilization_report()
        assert report["memory"]["exceeded"]
        assert report["memory"]["utilization"] == pytest.approx(2.0)


# =============================================================================
# ResourceObstruction conversion
# =============================================================================


class TestResourceObstruction:

    def test_to_higher_obstruction(self):
        a = _make_constraint("A", "a")
        b = _make_constraint("B", "b")
        c = _make_constraint("C", "c")

        obs = ResourceObstruction(
            constraints=frozenset({a, b, c}),
            resource_type=ResourceType.PRIVACY,
            budget_capacity=1.0,
            aggregate_cost=1.2,
            cost_breakdown=(("a", 0.4), ("b", 0.4), ("c", 0.4)),
            unit="PII",
            hard_limit=True,
        )

        higher = obs.to_higher_obstruction()
        assert higher.order == 2
        assert higher.obstruction_type == "resource_exhaustion"
        assert higher.severity == "hard"
        assert "120%" in higher.witness
        assert "присутствие" in higher.suggested_resolution

    def test_soft_limit_severity(self):
        a = _make_constraint("A", "a")
        obs = ResourceObstruction(
            constraints=frozenset({a}),
            resource_type=ResourceType.COMPUTE,
            budget_capacity=100.0,
            aggregate_cost=150.0,
            cost_breakdown=(("a", 150.0),),
            hard_limit=False,
        )
        assert obs.severity == "soft"

    def test_witness_is_descriptive(self):
        a = _make_constraint("A", "a")
        b = _make_constraint("B", "b")
        obs = ResourceObstruction(
            constraints=frozenset({a, b}),
            resource_type=ResourceType.PRIVACY,
            budget_capacity=1.0,
            aggregate_cost=1.5,
            cost_breakdown=(("a", 0.8), ("b", 0.7)),
            unit="PII_fields",
        )
        witness = obs.witness
        assert "privacy" in witness
        assert "1.5PII_fields" in witness
        assert "1.0PII_fields" in witness

    def test_serialization(self):
        a = _make_constraint("A", "a")
        obs = ResourceObstruction(
            constraints=frozenset({a}),
            resource_type=ResourceType.MEMORY,
            budget_capacity=8.0,
            aggregate_cost=16.0,
            cost_breakdown=(("a", 16.0),),
            unit="GB",
        )
        d = obs.to_dict()
        assert d["resource_type"] == "memory"
        assert d["overage"] == pytest.approx(8.0)
        assert d["utilization"] == pytest.approx(2.0)


# =============================================================================
# Edge cases
# =============================================================================


class TestEdgeCases:

    def test_no_budgets_no_obstructions(self):
        a = _make_constraint("A", "a")
        wc_a = WeightedConstraint(a, (ResourceCost(ResourceType.COMPUTE, 999.0),))

        complex = WeightedCechComplex()
        complex.add_weighted_vertex(wc_a)

        assert complex.check_all_budgets() == []
        assert complex.check_global_budget() == []

    def test_no_costs_against_budget(self):
        """Constraint has no cost for a registered budget's resource type."""
        a = _make_constraint("A", "a")
        wc_a = WeightedConstraint(a, (ResourceCost(ResourceType.COMPUTE, 50.0),))

        complex = WeightedCechComplex()
        complex.add_budget(ResourceBudget(ResourceType.PRIVACY, 1.0))
        complex.add_weighted_vertex(wc_a)

        assert complex.check_global_budget() == []

    def test_empty_complex(self):
        complex = WeightedCechComplex()
        complex.add_budget(ResourceBudget(ResourceType.COMPUTE, 100.0))
        assert complex.check_global_budget() == []
        assert complex.check_all_budgets() == []

    def test_stats(self):
        a = _make_constraint("A", "a")
        wc_a = WeightedConstraint(a, (ResourceCost(ResourceType.COMPUTE, 50.0),))

        complex = WeightedCechComplex()
        complex.add_budget(ResourceBudget(ResourceType.COMPUTE, 100.0))
        complex.add_weighted_vertex(wc_a)

        stats = complex.stats()
        assert stats["weighted_vertices"] == 1
        assert stats["budgets"] == 1
        assert stats["vertices"] == 1
