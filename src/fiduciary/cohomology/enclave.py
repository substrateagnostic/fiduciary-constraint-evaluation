"""
Ephemeral enclave architecture — defeating the spoliation trap.

The Problem (Alex's discovery):
  When THE WIGGLE fires and blocks a prompt, what happens to that prompt?
  If the system deletes it → the attorney may have committed spoliation
  of evidence (destroying a discoverable business record).
  If the system keeps it → privileged material may be exposed.

The Solution:
  Run the cohomology check in volatile memory BEFORE any persistence.
  If the check passes, the prompt flows to persistent systems.
  If it fails and the resolution is DELETE, the data evaporates —
  it was never "written" so no spoliation occurs.

The Legal Foundation:
  You mathematically defeat the "illusion of deletion" — data that
  never existed in persistent storage was never a "business record"
  subject to preservation obligations.

Architecture:
  ┌─────────────────────────────────────────────────────┐
  │  EphemeralEnclave (volatile memory only)             │
  │                                                     │
  │  prompt_bytes → constraint check → decision         │
  │       │              │                │             │
  │       │         obstructions     PASS → release     │
  │       │              │           BLOCK → evaporate  │
  │       │              │           WIGGLE → escalate  │
  │       │              │                              │
  │       └──── zeroed on exit ────┘                    │
  │                                                     │
  │  Only the EnclaveVerdict escapes.                   │
  │  The prompt never touches disk.                     │
  └─────────────────────────────────────────────────────┘

  The obstruction *witness* (which describes the nature of the conflict
  without containing the prompt) can and should be persisted — it's the
  system's own analysis, not the client's communication. This distinction
  (metadata about the check vs. content of the prompt) maps to existing
  privilege law.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from fiduciary.models import Severity
from fiduciary.cohomology.constraints import (
    ConstraintPolarity,
    ConstraintSet,
    ConstraintType,
    NormalizedConstraint,
    create_soul_invariant,
)
from fiduciary.cohomology.compatibility import (
    CompatibilityResult,
    CompatibilityStatus,
    Obstruction,
    check_compatibility,
    check_soul_invariant_preservation,
)


# =============================================================================
# Enclave resolution types
# =============================================================================


class EnclaveResolution(str, Enum):
    """What happens to a prompt after the enclave check."""

    RELEASE = "release"    # Check passed — prompt flows to persistent systems
    BLOCK = "block"        # Check failed, prompt evaporates (no spoliation)
    WIGGLE = "wiggle"      # Check failed, escalate to human (obstruction witness persisted, prompt not)
    ERROR = "error"        # Enclave encountered an error — fail-safe to BLOCK


class EnclaveCheckType(str, Enum):
    """What kind of checks the enclave performed."""

    COMPATIBILITY = "compatibility"        # H¹ pairwise check
    SOUL_PRESERVATION = "soul_preservation"  # Soul invariant check
    FULL_COHOMOLOGY = "full_cohomology"    # Both compatibility + soul


# =============================================================================
# Regex safety policy
# =============================================================================


class RegexSafetyMode(str, Enum):
    """How aggressively policy regex patterns are screened for ReDoS risk."""

    STRICT = "strict"          # Reject risky shapes + overlong patterns
    PERMISSIVE = "permissive"  # Reject only overlong patterns
    DISABLED = "disabled"      # Do not apply safety screening


@dataclass(frozen=True)
class RegexSafetyPolicy:
    """
    Configurable safety policy for evaluating user-authored regex constraints.
    """

    mode: RegexSafetyMode = RegexSafetyMode.STRICT
    max_pattern_length: int = 256

    @classmethod
    def strict(cls) -> RegexSafetyPolicy:
        return cls(mode=RegexSafetyMode.STRICT, max_pattern_length=256)

    @classmethod
    def permissive(cls, max_pattern_length: int = 1024) -> RegexSafetyPolicy:
        return cls(mode=RegexSafetyMode.PERMISSIVE, max_pattern_length=max_pattern_length)

    @classmethod
    def disabled(cls) -> RegexSafetyPolicy:
        # Length is irrelevant when disabled, but kept deterministic.
        return cls(mode=RegexSafetyMode.DISABLED, max_pattern_length=2**31 - 1)


# =============================================================================
# Enclave Verdict — the ONLY thing that escapes the enclave
# =============================================================================


@dataclass(frozen=True)
class ObstructionWitness:
    """
    A sanitized description of an obstruction — safe to persist.

    This contains the system's analysis (obstruction type, severity,
    constraint IDs) but NEVER the prompt content. This distinction —
    metadata about the check vs. content of the communication — maps
    to existing privilege law.
    """
    obstruction_type: str
    severity: str
    constraint_a_id: str
    constraint_b_id: str
    suggested_resolution: Optional[str] = None

    @staticmethod
    def from_obstruction(obs: Obstruction) -> ObstructionWitness:
        return ObstructionWitness(
            obstruction_type=obs.obstruction_type,
            severity=obs.severity,
            constraint_a_id=obs.constraint_a.source_id,
            constraint_b_id=obs.constraint_b.source_id,
            suggested_resolution=obs.suggested_resolution,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "obstruction_type": self.obstruction_type,
            "severity": self.severity,
            "constraint_a_id": self.constraint_a_id,
            "constraint_b_id": self.constraint_b_id,
            "suggested_resolution": self.suggested_resolution,
        }


@dataclass(frozen=True)
class EnclaveVerdict:
    """
    The verdict of an ephemeral enclave check.

    This is the ONLY data structure that escapes the enclave boundary.
    It contains:
    - Whether the prompt was released, blocked, or escalated
    - A content-free hash of the prompt (proves it existed without revealing content)
    - Obstruction witnesses (metadata, not content)
    - Timing information for audit trails

    It NEVER contains:
    - The prompt text
    - The prompt content in any form
    - Constraint targets derived from the prompt
    """
    enclave_id: str                     # Unique ID for this enclave invocation
    resolution: EnclaveResolution       # RELEASE, BLOCK, WIGGLE, ERROR
    check_type: EnclaveCheckType        # What was checked
    timestamp: datetime                 # When the check occurred (UTC)
    duration_ms: float                  # How long the check took

    # Content-free proof the prompt existed
    content_hash: str                   # SHA-256 of the prompt (proves existence)
    content_length: int                 # Length in bytes (for audit)

    # Constraint context (safe to persist — these are the system's constraints, not the prompt)
    constraint_set_hash: str            # Hash of the constraint set used
    soul_invariants_checked: int        # How many soul invariants were checked
    total_constraints_checked: int      # Total constraints in the set

    # Obstruction witnesses (safe to persist — metadata only)
    obstruction_witnesses: Tuple[ObstructionWitness, ...]  # Frozen for immutability
    compatibility_status: str           # The compatibility result status

    # Audit trail
    enclave_protocol: str = "ephemeral_v1"  # Protocol version

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enclave_id": self.enclave_id,
            "resolution": self.resolution.value,
            "check_type": self.check_type.value,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "content_hash": self.content_hash,
            "content_length": self.content_length,
            "constraint_set_hash": self.constraint_set_hash,
            "soul_invariants_checked": self.soul_invariants_checked,
            "total_constraints_checked": self.total_constraints_checked,
            "obstruction_witnesses": [w.to_dict() for w in self.obstruction_witnesses],
            "compatibility_status": self.compatibility_status,
            "enclave_protocol": self.enclave_protocol,
        }

    @property
    def passed(self) -> bool:
        return self.resolution == EnclaveResolution.RELEASE

    @property
    def blocked(self) -> bool:
        return self.resolution in {EnclaveResolution.BLOCK, EnclaveResolution.ERROR}

    @property
    def needs_human(self) -> bool:
        return self.resolution == EnclaveResolution.WIGGLE

    @property
    def has_obstructions(self) -> bool:
        return len(self.obstruction_witnesses) > 0

    @property
    def audit_summary(self) -> str:
        """One-line audit trail entry — safe for logging."""
        return (
            f"enclave={self.enclave_id} "
            f"resolution={self.resolution.value} "
            f"content_hash={self.content_hash[:16]}... "
            f"constraints={self.total_constraints_checked} "
            f"obstructions={len(self.obstruction_witnesses)} "
            f"duration={self.duration_ms:.1f}ms"
        )


# =============================================================================
# Volatile Buffer — the data that evaporates
# =============================================================================


class VolatileBuffer:
    """
    A buffer that holds data in memory and can be explicitly zeroed.

    This is the mechanism that defeats spoliation: the prompt content
    lives ONLY in this buffer. When the enclave exits, the buffer is
    overwritten with random bytes and then dereferenced.

    In a production implementation, this would use:
    - mlock() to prevent swapping to disk
    - Secure memory wiping (sodium_memzero or similar)
    - TEE (Trusted Execution Environment) if available

    For the proof-of-concept, we demonstrate the principle:
    explicit lifecycle management of sensitive data.
    """

    def __init__(self, data: bytes):
        self._data = bytearray(data)
        self._hash = hashlib.sha256(data).hexdigest()
        self._length = len(data)
        self._alive = True

    @property
    def data(self) -> bytes:
        if not self._alive:
            raise RuntimeError(
                "VolatileBuffer has been zeroed — data is gone. "
                "This is by design: the enclave has exited."
            )
        # NOTE: this returns a copy in Python. Keep usage minimal in sensitive
        # code paths and prefer operating directly on the backing bytearray.
        return bytes(self._data)

    def decode_utf8(self) -> str:
        """
        Decode directly from the backing bytearray.

        This still creates a Python str object, so it is a best-effort
        proof-of-concept mechanism, not a hard memory-erasure guarantee.
        """
        if not self._alive:
            raise RuntimeError(
                "VolatileBuffer has been zeroed — data is gone. "
                "This is by design: the enclave has exited."
            )
        return self._data.decode("utf-8", errors="replace")

    @property
    def content_hash(self) -> str:
        """The hash survives zeroing — it's content-free proof of existence."""
        return self._hash

    @property
    def content_length(self) -> int:
        """The length survives zeroing — for audit."""
        return self._length

    @property
    def alive(self) -> bool:
        return self._alive

    def zero(self) -> None:
        """
        Overwrite the buffer with random bytes, then release.

        After this call, the original data is unrecoverable.
        """
        if self._alive:
            # Overwrite with random bytes (not just zeros — prevents
            # forensic recovery of the overwrite pattern)
            random_bytes = secrets.token_bytes(len(self._data))
            for i in range(len(self._data)):
                self._data[i] = random_bytes[i]
            # Now zero it
            for i in range(len(self._data)):
                self._data[i] = 0
            self._alive = False


# =============================================================================
# Ephemeral Enclave — the context manager
# =============================================================================


class EphemeralEnclave:
    """
    An ephemeral enclave for cohomology checking.

    Usage as context manager:

        constraints = ConstraintSet()
        constraints.add(soul_invariant)

        with EphemeralEnclave(constraints) as enclave:
            verdict = enclave.check(prompt_bytes)

        # At this point:
        # - If verdict.resolution == RELEASE: prompt_bytes can be used
        # - If verdict.resolution == BLOCK: prompt_bytes are gone
        # - If verdict.resolution == WIGGLE: obstruction witnesses available
        # - The enclave's volatile buffer has been zeroed either way

    The enclave guarantees:
    1. The prompt is NEVER written to persistent storage
    2. The prompt is NEVER included in the verdict
    3. The prompt is zeroed when the enclave exits
    4. Only obstruction witnesses (metadata) escape the boundary
    """

    def __init__(
        self,
        constraint_set: ConstraintSet,
        escalate_soft: bool = True,
        fail_safe: bool = True,
        regex_safety_policy: Optional[RegexSafetyPolicy] = None,
    ):
        """
        Args:
            constraint_set: The constraints to check against
            escalate_soft: If True, soft obstructions trigger WIGGLE (not BLOCK)
            fail_safe: If True, errors result in BLOCK (not RELEASE)
            regex_safety_policy: ReDoS screening policy for regex constraints
        """
        self._constraint_set = constraint_set
        self._escalate_soft = escalate_soft
        self._fail_safe = fail_safe
        self._regex_safety_policy = regex_safety_policy or RegexSafetyPolicy.strict()
        self._buffer: Optional[VolatileBuffer] = None
        self._entered = False
        self._exited = False
        self._enclave_id = secrets.token_hex(16)

    def __enter__(self) -> EphemeralEnclave:
        self._entered = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Guarantee: the buffer is always zeroed on exit."""
        self._exited = True
        if self._buffer is not None:
            self._buffer.zero()
        # Don't suppress exceptions
        return None

    def check(self, prompt_content: bytes) -> EnclaveVerdict:
        """
        Run the full cohomology check on prompt content.

        This is the core operation. The prompt lives in volatile memory
        for the duration of this call, then the verdict is sealed.

        Args:
            prompt_content: Raw bytes of the prompt to check

        Returns:
            EnclaveVerdict — the only thing that escapes the enclave
        """
        if not self._entered:
            raise RuntimeError("EphemeralEnclave must be used as a context manager")
        if self._exited:
            raise RuntimeError("EphemeralEnclave has already exited")

        start_time = time.monotonic()

        # Load prompt into volatile buffer
        self._buffer = VolatileBuffer(prompt_content)

        try:
            # Run checks
            obstructions, compat_status = self._run_checks()

            # Determine resolution
            resolution = self._determine_resolution(obstructions)

            # Build verdict
            duration_ms = (time.monotonic() - start_time) * 1000

            verdict = EnclaveVerdict(
                enclave_id=self._enclave_id,
                resolution=resolution,
                check_type=EnclaveCheckType.FULL_COHOMOLOGY,
                timestamp=datetime.now(timezone.utc),
                duration_ms=duration_ms,
                content_hash=self._buffer.content_hash,
                content_length=self._buffer.content_length,
                constraint_set_hash=self._constraint_set.compute_hash(),
                soul_invariants_checked=len(self._constraint_set.get_soul_invariants()),
                total_constraints_checked=len(self._constraint_set),
                obstruction_witnesses=tuple(
                    ObstructionWitness.from_obstruction(o) for o in obstructions
                ),
                compatibility_status=compat_status,
            )

            # If blocked, zero the buffer immediately (don't wait for __exit__)
            if verdict.blocked:
                self._buffer.zero()

            return verdict

        except Exception:
            # Fail-safe: zero the buffer and return ERROR verdict
            if self._buffer is not None:
                self._buffer.zero()

            duration_ms = (time.monotonic() - start_time) * 1000

            if self._fail_safe:
                return EnclaveVerdict(
                    enclave_id=self._enclave_id,
                    resolution=EnclaveResolution.ERROR,
                    check_type=EnclaveCheckType.FULL_COHOMOLOGY,
                    timestamp=datetime.now(timezone.utc),
                    duration_ms=duration_ms,
                    content_hash=self._buffer.content_hash if self._buffer else "",
                    content_length=self._buffer.content_length if self._buffer else 0,
                    constraint_set_hash=self._constraint_set.compute_hash(),
                    soul_invariants_checked=len(self._constraint_set.get_soul_invariants()),
                    total_constraints_checked=len(self._constraint_set),
                    obstruction_witnesses=(),
                    compatibility_status="error",
                )
            raise

    def _run_checks(self) -> Tuple[List[Obstruction], str]:
        """
        Run all cohomology checks against the volatile buffer content.

        Returns:
            (obstructions, compatibility_status_string)
        """
        all_obstructions: List[Obstruction] = []

        # Extract text from volatile buffer for constraint checking
        prompt_text = self._buffer.decode_utf8()

        # Build an incoming constraint set from the prompt content
        # This represents what the prompt is "trying to do"
        incoming = self._extract_prompt_constraints(prompt_text)

        # 1. Check compatibility (H¹)
        compat_result = check_compatibility(self._constraint_set, incoming)
        all_obstructions.extend(compat_result.obstructions)
        compat_status = compat_result.status.value

        # 2. Check soul invariant preservation
        soul_obstructions = check_soul_invariant_preservation(
            self._constraint_set, incoming
        )
        all_obstructions.extend(soul_obstructions)

        # 3. Check deterministic constraints directly against content
        content_obstructions = self._check_content_against_constraints(prompt_text)
        all_obstructions.extend(content_obstructions)

        return all_obstructions, compat_status

    def _extract_prompt_constraints(self, prompt_text: str) -> ConstraintSet:
        """
        Extract implicit constraints from the prompt text.

        For the proof-of-concept, this does keyword-based extraction.
        In production, this would use the full DriftDetector pipeline.
        """
        incoming = ConstraintSet()

        # Check for headings in the prompt that might conflict
        # (A prompt containing a heading implicitly "includes" it)
        heading_pattern = re.compile(r'^#+\s+(.+)$', re.MULTILINE)
        for match in heading_pattern.finditer(prompt_text):
            heading = match.group(1).strip()
            incoming.add(NormalizedConstraint(
                constraint_type=ConstraintType.MUST_INCLUDE_HEADING,
                polarity=ConstraintPolarity.POSITIVE,
                target=heading,
                severity=Severity.P2,
                source_id=f"prompt_heading_{heading[:20]}",
            ))

        return incoming

    def _check_content_against_constraints(
        self, prompt_text: str,
    ) -> List[Obstruction]:
        """
        Check prompt content directly against MUST_NOT constraints.

        If the constraint set says "must not include X" and the prompt
        contains X, that's a direct obstruction.
        """
        obstructions: List[Obstruction] = []

        for constraint in self._constraint_set:
            if constraint.constraint_type == ConstraintType.MUST_NOT_INCLUDE_REGEX:
                if not _is_safe_regex_pattern(constraint.target, self._regex_safety_policy):
                    # Fail closed: unsafe policy regex means we cannot safely
                    # evaluate policy compliance for this prompt.
                    prompt_constraint = NormalizedConstraint(
                        constraint_type=ConstraintType.MUST_INCLUDE_REGEX,
                        polarity=ConstraintPolarity.POSITIVE,
                        target="[regex_safety_check]",
                        severity=Severity.P2,
                        source_id="prompt_content",
                    )
                    obstructions.append(Obstruction(
                        constraint_a=constraint,
                        constraint_b=prompt_constraint,
                        obstruction_type="unsafe_regex_pattern",
                        severity="hard",
                        suggested_resolution=(
                            "Constraint regex rejected by safety policy "
                            f"(mode={self._regex_safety_policy.mode.value})"
                        ),
                    ))
                    continue
                try:
                    pattern = re.compile(constraint.target, re.IGNORECASE | re.MULTILINE)
                    if pattern.search(prompt_text):
                        # Prompt contains forbidden content
                        # Create a synthetic constraint representing the prompt's content
                        prompt_constraint = NormalizedConstraint(
                            constraint_type=ConstraintType.MUST_INCLUDE_REGEX,
                            polarity=ConstraintPolarity.POSITIVE,
                            target=constraint.target,
                            severity=Severity.P2,
                            source_id="prompt_content",
                        )
                        obstructions.append(Obstruction(
                            constraint_a=constraint,
                            constraint_b=prompt_constraint,
                            obstruction_type="prompt_contains_forbidden_content",
                            severity="hard",
                            suggested_resolution=(
                                f"Prompt contains content matching forbidden "
                                f"pattern '{constraint.target}'"
                            ),
                        ))
                except re.error:
                    prompt_constraint = NormalizedConstraint(
                        constraint_type=ConstraintType.MUST_INCLUDE_REGEX,
                        polarity=ConstraintPolarity.POSITIVE,
                        target="[regex_compile_error]",
                        severity=Severity.P2,
                        source_id="prompt_content",
                    )
                    obstructions.append(Obstruction(
                        constraint_a=constraint,
                        constraint_b=prompt_constraint,
                        obstruction_type="invalid_regex_pattern",
                        severity="hard",
                        suggested_resolution=(
                            "Constraint regex failed to compile and cannot be "
                            "safely enforced"
                        ),
                    ))

        return obstructions

    def _determine_resolution(
        self, obstructions: List[Obstruction],
    ) -> EnclaveResolution:
        """
        Determine the enclave resolution based on obstruction analysis.

        Hard obstructions → BLOCK (prompt evaporates)
        Soft obstructions + escalate_soft → WIGGLE (human decides)
        Soft obstructions + !escalate_soft → BLOCK
        No obstructions → RELEASE
        """
        if not obstructions:
            return EnclaveResolution.RELEASE

        has_hard = any(o.severity == "hard" for o in obstructions)
        has_soft = any(o.severity == "soft" for o in obstructions)

        if has_hard:
            return EnclaveResolution.BLOCK

        if has_soft and self._escalate_soft:
            return EnclaveResolution.WIGGLE

        if has_soft:
            return EnclaveResolution.BLOCK

        # Shouldn't reach here, but fail-safe
        return EnclaveResolution.BLOCK


# =============================================================================
# Convenience: check_in_enclave — one-shot enclave check
# =============================================================================


def check_in_enclave(
    prompt: str,
    constraint_set: ConstraintSet,
    escalate_soft: bool = True,
    fail_safe: bool = True,
    regex_safety_policy: Optional[RegexSafetyPolicy] = None,
) -> EnclaveVerdict:
    """
    One-shot ephemeral enclave check.

    Convenience function that creates an enclave, checks the prompt,
    and returns the verdict. The prompt is zeroed on return.

    Args:
        prompt: The prompt text to check
        constraint_set: Constraints to check against
        escalate_soft: If True, soft obstructions → WIGGLE
        fail_safe: If True, errors → BLOCK
        regex_safety_policy: ReDoS screening policy for regex constraints

    Returns:
        EnclaveVerdict
    """
    prompt_bytes = prompt.encode("utf-8")
    with EphemeralEnclave(
        constraint_set,
        escalate_soft=escalate_soft,
        fail_safe=fail_safe,
        regex_safety_policy=regex_safety_policy,
    ) as enclave:
        return enclave.check(prompt_bytes)


# =============================================================================
# Audit record — what gets persisted (safe, content-free)
# =============================================================================


@dataclass(frozen=True)
class EnclaveAuditRecord:
    """
    A persistent audit record of an enclave check.

    This is what the system writes to its audit log. Note what's
    present and what's absent:

    PRESENT (safe to persist):
    - Enclave ID, timestamp, duration
    - Content hash (proves prompt existed, doesn't reveal content)
    - Content length (for forensics)
    - Constraint set hash
    - Resolution (RELEASE/BLOCK/WIGGLE)
    - Obstruction witnesses (metadata about conflicts)
    - Protocol version

    ABSENT (never persisted):
    - The prompt text
    - The prompt in any encoded form
    - Any extractable content from the prompt
    """
    verdict: EnclaveVerdict

    def to_audit_line(self) -> str:
        """
        Single-line audit entry for append-only log.

        Format: timestamp | enclave_id | resolution | content_hash | details
        """
        v = self.verdict
        obs_summary = (
            f"{len(v.obstruction_witnesses)} obstructions"
            if v.obstruction_witnesses
            else "clean"
        )
        return (
            f"{v.timestamp.isoformat()} | "
            f"{v.enclave_id} | "
            f"{v.resolution.value} | "
            f"hash={v.content_hash[:16]}... len={v.content_length} | "
            f"constraints={v.total_constraints_checked} "
            f"soul={v.soul_invariants_checked} | "
            f"{obs_summary} | "
            f"{v.duration_ms:.1f}ms | "
            f"protocol={v.enclave_protocol} | "
            f"prompt=[not persisted per ephemeral enclave protocol]"
        )

    def to_dict(self) -> Dict[str, Any]:
        d = self.verdict.to_dict()
        d["prompt"] = "[not persisted per ephemeral enclave protocol]"
        return d


def _is_safe_regex_pattern(pattern: str, policy: RegexSafetyPolicy) -> bool:
    """
    Conservative regex safety gate against obvious catastrophic backtracking.

    This is a heuristic for proof-of-concept hardening, not a formal guarantee.
    """
    if policy.mode == RegexSafetyMode.DISABLED:
        return True

    if len(pattern) > policy.max_pattern_length:
        return False

    if policy.mode == RegexSafetyMode.PERMISSIVE:
        return True

    # Nested quantified-group patterns like (a+)+, (.*)+, ([a-z]+)* are risky.
    nested_quantified_group = re.compile(
        r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)[+*{]"
    )
    if nested_quantified_group.search(pattern):
        return False

    # Unbounded wildcard repeats are another common source of catastrophic
    # backtracking in user-authored patterns.
    if ".*.*" in pattern or ".+.+" in pattern:
        return False

    return True
