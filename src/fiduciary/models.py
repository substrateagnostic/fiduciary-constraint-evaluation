"""
Minimal model types for the fiduciary constraint algebra.

Vendored from prismloom.models.contract — only the types needed
by the cohomology module. The full loom infrastructure (IntentContract,
SigningInfo, ToneProfile, amendments) is not needed here.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class EnforcementType(str, Enum):
    MUST_INCLUDE_HEADING = "must_include_heading"
    MUST_INCLUDE_REGEX = "must_include_regex"
    MUST_NOT_INCLUDE_REGEX = "must_not_include_regex"


class ConstraintEnforcement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: EnforcementType
    value: Optional[str] = None
    params: Dict[str, object] = Field(default_factory=dict)


class ContractConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    severity: Severity
    description: str
    enforcement: ConstraintEnforcement


class ContractLike(Protocol):
    """
    Protocol for contract-like objects used by the drift detector.

    Any object with these attributes can be used — no dependency
    on the full IntentContract from the loom infrastructure.
    """

    objective: str
    objective_success_criteria: List[str]
    constraints: List[ContractConstraint]
    session_id: str
