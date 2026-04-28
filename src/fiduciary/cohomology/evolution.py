"""
Cy-près governed evolution of soul invariants.

The Problem:
  Soul invariants are currently immutable. In fiduciary law, duties evolve
  through governed processes — court orders, beneficiary life changes,
  statutory amendments. How do we mutate the soul without destroying the
  mathematical guarantee?

The Legal Analog:
  The cy-près doctrine ("as near as possible") — when a trust's original
  purpose becomes impossible, courts modify the trust's soul while
  preserving its fiduciary continuity.

The Implementation:
  A Soul Invariant cannot be DELETED by the AI. It can only be deformed
  via взаимность (mutuality/consent). A human fiduciary must cryptographically
  sign a MetaWiggle (a judicial override). The system does not overwrite
  the old invariant; it appends the topological deformation (a sheaf morphism)
  to an immutable ledger (память). This creates an auditable chain of custody
  proving exactly what the ethical constraints were at the exact millisecond
  a prompt was processed.

  The old invariant is NEVER deleted. The deformation is appended.
  память — the chain of custody.
"""

from __future__ import annotations

import hashlib
import hmac
import json
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
    check_compatibility,
    check_soul_invariant_preservation,
)


# =============================================================================
# Amendment types
# =============================================================================


class AmendmentType(str, Enum):
    """How a soul invariant is being modified."""

    DEFORM = "deform"          # Cy-près: modify while preserving intent
    STRENGTHEN = "strengthen"  # Make more restrictive (always safe)
    RELAX = "relax"            # Make less restrictive (requires justification)
    SUPERSEDE = "supersede"    # Replace with a new invariant (requires full review)


class AmendmentStatus(str, Enum):
    """Status of an amendment in the ledger."""

    PROPOSED = "proposed"      # Awaiting human signature
    SIGNED = "signed"          # Human has signed
    VERIFIED = "verified"      # Compatibility check passed
    APPLIED = "applied"        # Amendment is active
    REJECTED = "rejected"      # Compatibility check failed or human rejected


# =============================================================================
# Soul Amendment
# =============================================================================


@dataclass(frozen=True)
class SoulAmendment:
    """
    A proposed modification to a soul invariant.

    In trust law, this is the petition to the court for cy-près modification.
    The old invariant is preserved — the amendment is a deformation, not deletion.
    """
    amendment_id: str
    amendment_type: AmendmentType
    old_invariant: NormalizedConstraint
    new_invariant: NormalizedConstraint
    justification: str  # Cy-près reasoning: why the original is impossible/outdated
    proposed_at: datetime
    proposed_by: str  # Who proposed (AI agent identifier)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "amendment_id": self.amendment_id,
            "amendment_type": self.amendment_type.value,
            "old_invariant": self.old_invariant.to_dict(),
            "new_invariant": self.new_invariant.to_dict(),
            "justification": self.justification,
            "proposed_at": self.proposed_at.isoformat(),
            "proposed_by": self.proposed_by,
        }


# =============================================================================
# MetaWiggle — the judicial override
# =============================================================================


@dataclass
class MetaWiggle:
    """
    A special Wiggle invocation for soul invariant modification.

    Unlike a regular Wiggle (which pauses for human input on a constraint
    violation), a MetaWiggle requires cryptographic human signature to
    authorize a change to the soul itself.

    This is the judicial override — the court order in cy-près.
    """
    amendment: SoulAmendment
    human_signer: str          # Identity of the signing human
    signature: str = ""        # HMAC signature over amendment content
    signed_at: Optional[datetime] = None
    reasoning: str = ""        # Human's explanation for approving

    @property
    def is_signed(self) -> bool:
        return bool(self.signature) and self.signed_at is not None

    def sign(self, signing_key: str) -> None:
        """
        Sign the MetaWiggle with a cryptographic key.

        In production, this would use asymmetric keys (RSA/Ed25519).
        For the proof-of-concept, HMAC-SHA256 demonstrates the principle:
        the amendment cannot be applied without a verifiable human signature.
        """
        content = self._signable_content()
        self.signature = hmac.new(
            signing_key.encode(),
            content.encode(),
            hashlib.sha256,
        ).hexdigest()
        self.signed_at = datetime.now(timezone.utc)

    def verify_signature(self, signing_key: str) -> bool:
        """Verify the signature is valid."""
        if not self.signature:
            return False
        content = self._signable_content()
        expected = hmac.new(
            signing_key.encode(),
            content.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(self.signature, expected)

    def _signable_content(self) -> str:
        """Canonical representation of the amendment for signing."""
        return json.dumps(
            self.amendment.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )


# =============================================================================
# Amendment Ledger — память (immutable chain of custody)
# =============================================================================


@dataclass(frozen=True)
class LedgerEntry:
    """
    An immutable entry in the amendment ledger.

    Each entry includes a hash of the previous entry, forming a
    tamper-evident chain. This is память — the structure that
    survives context collapse.
    """
    sequence: int
    amendment: SoulAmendment
    status: AmendmentStatus
    signed_by: str
    signed_at: datetime
    signature: str
    previous_hash: str  # Hash of the previous entry (genesis = "0" * 64)
    entry_hash: str     # Hash of this entry

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sequence": self.sequence,
            "amendment": self.amendment.to_dict(),
            "status": self.status.value,
            "signed_by": self.signed_by,
            "signed_at": self.signed_at.isoformat(),
            "signature": self.signature,
            "previous_hash": self.previous_hash,
            "entry_hash": self.entry_hash,
        }


class AmendmentLedger:
    """
    Immutable append-only log of all soul mutations.

    This is память — the chain of custody proving exactly what the
    ethical constraints were at every millisecond. Entries form a
    hash chain; tampering with any entry invalidates all subsequent ones.

    The ledger answers: "What were the active soul invariants at time T?"
    This is legally critical for demonstrating fiduciary compliance.
    """

    def __init__(self, initial_invariants: Optional[Set[NormalizedConstraint]] = None):
        self._entries: List[LedgerEntry] = []
        self._active_invariants: Dict[str, NormalizedConstraint] = {}

        # Initialize with the original soul invariants
        if initial_invariants:
            for inv in initial_invariants:
                self._active_invariants[inv.source_id] = inv

    @property
    def entries(self) -> List[LedgerEntry]:
        """Read-only access to ledger entries."""
        return list(self._entries)

    @property
    def active_invariants(self) -> Set[NormalizedConstraint]:
        """Currently active soul invariants."""
        return set(self._active_invariants.values())

    def append(
        self,
        amendment: SoulAmendment,
        status: AmendmentStatus,
        signed_by: str,
        signed_at: datetime,
        signature: str,
    ) -> LedgerEntry:
        """
        Append a new entry to the ledger. This is the ONLY mutation operation.

        The entry is cryptographically chained to the previous entry.
        """
        if status == AmendmentStatus.APPLIED:
            self._validate_applied_amendment(amendment)

        previous_hash = (
            self._entries[-1].entry_hash if self._entries else "0" * 64
        )

        # Compute entry hash
        entry_hash = self._compute_entry_hash(
            sequence=len(self._entries),
            amendment=amendment,
            status=status,
            signed_by=signed_by,
            signed_at=signed_at,
            signature=signature,
            previous_hash=previous_hash,
        )

        entry = LedgerEntry(
            sequence=len(self._entries),
            amendment=amendment,
            status=status,
            signed_by=signed_by,
            signed_at=signed_at,
            signature=signature,
            previous_hash=previous_hash,
            entry_hash=entry_hash,
        )

        self._entries.append(entry)

        # If applied, update active invariants
        if status == AmendmentStatus.APPLIED:
            old_id = amendment.old_invariant.source_id
            if old_id in self._active_invariants:
                # Don't delete — the old invariant lives in the ledger history
                # But the active set now uses the new invariant
                self._active_invariants[amendment.new_invariant.source_id] = amendment.new_invariant
                if amendment.new_invariant.source_id != old_id:
                    del self._active_invariants[old_id]
                    # Keep old under new key with new value
                else:
                    # Same source_id, just replaced
                    pass

        return entry

    def invariants_at(self, timestamp: datetime) -> Set[NormalizedConstraint]:
        """
        Reconstruct the active soul invariants at a specific timestamp.

        This answers: "What were the constraints when this prompt was processed?"
        Critical for legal compliance and audit trails.
        """
        # Start from current active state and roll back future amendments.
        active = dict(self._active_invariants)

        # Undo amendments that happened after timestamp (in reverse)
        for entry in reversed(self._entries):
            if entry.status != AmendmentStatus.APPLIED:
                continue
            if entry.signed_at > timestamp:
                # This amendment happened after our target time — undo it
                new_id = entry.amendment.new_invariant.source_id
                old_id = entry.amendment.old_invariant.source_id
                if new_id in active:
                    del active[new_id]
                active[old_id] = entry.amendment.old_invariant

        return set(active.values())

    def verify_chain(self) -> Tuple[bool, Optional[int]]:
        """
        Verify the hash chain is intact (no tampering).

        Returns:
            (is_valid, first_broken_index) — True if intact, or the index
            of the first broken link.
        """
        expected_prev = "0" * 64

        for i, entry in enumerate(self._entries):
            if entry.sequence != i:
                return (False, i)
            if entry.previous_hash != expected_prev:
                return (False, i)
            expected_hash = self._compute_entry_hash(
                sequence=entry.sequence,
                amendment=entry.amendment,
                status=entry.status,
                signed_by=entry.signed_by,
                signed_at=entry.signed_at,
                signature=entry.signature,
                previous_hash=entry.previous_hash,
            )
            if entry.entry_hash != expected_hash:
                return (False, i)
            expected_prev = entry.entry_hash

        return (True, None)

    def _compute_entry_hash(
        self,
        sequence: int,
        amendment: SoulAmendment,
        status: AmendmentStatus,
        signed_by: str,
        signed_at: datetime,
        signature: str,
        previous_hash: str,
    ) -> str:
        entry_data = json.dumps({
            "sequence": sequence,
            "amendment": amendment.to_dict(),
            "status": status.value,
            "signed_by": signed_by,
            "signed_at": signed_at.isoformat(),
            "signature": signature,
            "previous_hash": previous_hash,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(entry_data.encode()).hexdigest()

    def _validate_applied_amendment(self, amendment: SoulAmendment) -> None:
        old_id = amendment.old_invariant.source_id
        new_id = amendment.new_invariant.source_id

        current_old = self._active_invariants.get(old_id)
        if current_old is None:
            raise ValueError(
                f"Cannot apply amendment: old invariant '{old_id}' is not active"
            )
        if current_old != amendment.old_invariant:
            raise ValueError(
                f"Cannot apply amendment: old invariant '{old_id}' does not match "
                "the currently active value"
            )
        if new_id != old_id and new_id in self._active_invariants:
            raise ValueError(
                f"Cannot apply amendment: new invariant source_id '{new_id}' "
                "collides with an existing active invariant"
            )

    def chain_of_custody(self) -> List[Dict[str, Any]]:
        """
        Generate a human-readable chain of custody report.

        This is the audit trail: every soul mutation, who authorized it,
        when, and why.
        """
        return [
            {
                "sequence": e.sequence,
                "type": e.amendment.amendment_type.value,
                "old": e.amendment.old_invariant.target,
                "new": e.amendment.new_invariant.target,
                "justification": e.amendment.justification,
                "signed_by": e.signed_by,
                "signed_at": e.signed_at.isoformat(),
                "status": e.status.value,
            }
            for e in self._entries
        ]

    def __len__(self) -> int:
        return len(self._entries)


# =============================================================================
# Amendment Verifier — compatibility checking for proposed amendments
# =============================================================================


class AmendmentVerifier:
    """
    Verifies that a proposed soul amendment is compatible with the
    remaining constraint set.

    Before applying a cy-près modification, we must ensure:
    1. The new invariant doesn't contradict existing invariants
    2. The new invariant set is internally compatible (H¹)
    3. No higher-order obstructions are introduced (H²)
    4. The deformation preserves the "topological type" — the general
       charitable intent (in cy-près terms)
    """

    def verify_amendment(
        self,
        amendment: SoulAmendment,
        current_invariants: Set[NormalizedConstraint],
        full_constraint_set: Optional[ConstraintSet] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Verify a proposed amendment against the constraint algebra.

        Returns:
            (is_valid, reasons) — True if the amendment can be safely applied,
            or False with a list of reasons why not.
        """
        reasons: List[str] = []

        # 1. The old invariant must actually exist
        if amendment.old_invariant not in current_invariants:
            reasons.append(
                f"Old invariant '{amendment.old_invariant.source_id}' "
                f"not found in current active invariants"
            )
            return (False, reasons)

        # 2. The new invariant must be a soul invariant
        if not amendment.new_invariant.is_soul_invariant:
            reasons.append(
                "New invariant must have is_soul_invariant=True"
            )
            return (False, reasons)

        # 3. Build the proposed new invariant set
        proposed = set(current_invariants)
        proposed.discard(amendment.old_invariant)
        proposed.add(amendment.new_invariant)

        # 4. Check pairwise compatibility (H¹) of new set
        proposed_cs = ConstraintSet()
        for inv in proposed:
            proposed_cs.add(inv)

        remaining_cs = ConstraintSet()
        for inv in proposed:
            if inv != amendment.new_invariant:
                remaining_cs.add(inv)

        new_cs = ConstraintSet()
        new_cs.add(amendment.new_invariant)

        result = check_compatibility(remaining_cs, new_cs)
        # Reject only on provable obstructions (not UNKNOWN status —
        # semantic constraints without a checker are indeterminate, not conflicting)
        if result.obstructions:
            for obs in result.obstructions:
                reasons.append(
                    f"H¹ obstruction: new invariant conflicts with "
                    f"'{obs.constraint_a.source_id}' — {obs.obstruction_type}"
                )
            return (False, reasons)

        # 5. Check soul invariant preservation
        soul_obs = check_soul_invariant_preservation(remaining_cs, new_cs)
        if soul_obs:
            for obs in soul_obs:
                reasons.append(
                    f"Soul invariant violation: {obs.obstruction_type}"
                )
            return (False, reasons)

        # 6. Check against full constraint set if provided
        if full_constraint_set:
            full_result = check_compatibility(full_constraint_set, new_cs)
            if full_result.obstructions:
                for obs in full_result.obstructions:
                    reasons.append(
                        f"Conflicts with existing constraint "
                        f"'{obs.constraint_a.source_id}': {obs.obstruction_type}"
                    )
                return (False, reasons)

        # 7. Validate cy-près preservation (type-level check)
        type_preserved = self._check_type_preservation(
            amendment.old_invariant,
            amendment.new_invariant,
            amendment.amendment_type,
        )
        if not type_preserved:
            reasons.append(
                "Amendment does not preserve topological type — "
                "the new invariant's constraint type or modality differs "
                "from the original. Cy-près requires 'as near as possible.'"
            )
            return (False, reasons)

        return (True, [])

    def _check_type_preservation(
        self,
        old: NormalizedConstraint,
        new: NormalizedConstraint,
        amendment_type: AmendmentType,
    ) -> bool:
        """
        Check that the deformation preserves topological type.

        Cy-près "as near as possible" means:
        - DEFORM: same constraint type family, target may change
        - STRENGTHEN: same type, severity can increase
        - RELAX: same type, severity can decrease
        - SUPERSEDE: type can change (but requires full review)
        """
        if amendment_type == AmendmentType.SUPERSEDE:
            return True  # Supersede allows type change

        # For DEFORM, STRENGTHEN, RELAX: constraint type must be preserved
        if old.constraint_type != new.constraint_type:
            return False

        # Severity checks for STRENGTHEN/RELAX
        severity_order = {Severity.P2: 0, Severity.P1: 1, Severity.P0: 2}
        old_sev = severity_order.get(old.severity, 0)
        new_sev = severity_order.get(new.severity, 0)

        if amendment_type == AmendmentType.STRENGTHEN and new_sev < old_sev:
            return False  # Can't strengthen by reducing severity

        if amendment_type == AmendmentType.RELAX and new_sev > old_sev:
            return False  # Can't relax by increasing severity

        return True


# =============================================================================
# Main entry point: evolve_soul_invariant
# =============================================================================


def evolve_soul_invariant(
    amendment: SoulAmendment,
    meta_wiggle: MetaWiggle,
    ledger: AmendmentLedger,
    signing_key: str,
    full_constraint_set: Optional[ConstraintSet] = None,
) -> Tuple[bool, str]:
    """
    Execute a governed soul invariant evolution.

    This is the full pipeline:
    1. Verify the MetaWiggle signature (human authorization)
    2. Verify the amendment is compatible with existing constraints
    3. Append to the immutable ledger
    4. Return success/failure

    Args:
        amendment: The proposed change
        meta_wiggle: The signed human authorization
        ledger: The immutable amendment ledger
        signing_key: Key to verify the signature
        full_constraint_set: Optional full constraint context

    Returns:
        (success, message)
    """
    # 1. Verify human signature — взаимность requires human consent
    if not meta_wiggle.is_signed:
        ledger.append(
            amendment=amendment,
            status=AmendmentStatus.REJECTED,
            signed_by=meta_wiggle.human_signer,
            signed_at=datetime.now(timezone.utc),
            signature="",
        )
        return (False, "MetaWiggle is not signed — human authorization required (взаимность)")

    if not meta_wiggle.verify_signature(signing_key):
        ledger.append(
            amendment=amendment,
            status=AmendmentStatus.REJECTED,
            signed_by=meta_wiggle.human_signer,
            signed_at=meta_wiggle.signed_at or datetime.now(timezone.utc),
            signature=meta_wiggle.signature,
        )
        return (False, "Invalid signature — cannot verify human authorization")

    # Record the signed amendment
    ledger.append(
        amendment=amendment,
        status=AmendmentStatus.SIGNED,
        signed_by=meta_wiggle.human_signer,
        signed_at=meta_wiggle.signed_at,
        signature=meta_wiggle.signature,
    )

    # 2. Verify compatibility
    verifier = AmendmentVerifier()
    is_valid, reasons = verifier.verify_amendment(
        amendment,
        ledger.active_invariants,
        full_constraint_set,
    )

    if not is_valid:
        ledger.append(
            amendment=amendment,
            status=AmendmentStatus.REJECTED,
            signed_by=meta_wiggle.human_signer,
            signed_at=meta_wiggle.signed_at,
            signature=meta_wiggle.signature,
        )
        return (False, f"Amendment rejected: {'; '.join(reasons)}")

    # 3. Verified — record and apply
    ledger.append(
        amendment=amendment,
        status=AmendmentStatus.VERIFIED,
        signed_by=meta_wiggle.human_signer,
        signed_at=meta_wiggle.signed_at,
        signature=meta_wiggle.signature,
    )

    ledger.append(
        amendment=amendment,
        status=AmendmentStatus.APPLIED,
        signed_by=meta_wiggle.human_signer,
        signed_at=meta_wiggle.signed_at,
        signature=meta_wiggle.signature,
    )

    return (True, f"Soul invariant '{amendment.old_invariant.source_id}' "
                  f"evolved via cy-près ({amendment.amendment_type.value})")
