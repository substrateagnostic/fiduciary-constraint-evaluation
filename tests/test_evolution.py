"""
Tests for cy-pres governed evolution of soul invariants.

The key principle: a soul invariant cannot be DELETED by the AI alone.
It can only be deformed via vzaimnost (mutuality) -- a human must
cryptographically sign a MetaWiggle (judicial override). The old invariant
is NEVER deleted; the deformation is appended to an immutable ledger.
"""

import time
from datetime import datetime, timezone, timedelta

import pytest

from fiduciary.models import Severity
from fiduciary.cohomology.constraints import (
    ConstraintType,
    ConstraintPolarity,
    NormalizedConstraint,
    ConstraintSet,
    create_soul_invariant,
)
from fiduciary.cohomology.evolution import (
    AmendmentType,
    AmendmentStatus,
    SoulAmendment,
    MetaWiggle,
    LedgerEntry,
    AmendmentLedger,
    AmendmentVerifier,
    evolve_soul_invariant,
)


SIGNING_KEY = "test-fiduciary-key-2026"


def _soul(target: str, source_id: str,
          ctype=ConstraintType.SEMANTIC_INTENT) -> NormalizedConstraint:
    return create_soul_invariant(ctype, target, source_id)


def _make_amendment(
    old: NormalizedConstraint,
    new: NormalizedConstraint,
    amendment_type=AmendmentType.DEFORM,
    justification="Cy-pres: original purpose requires adaptation",
    amendment_id="amend-001",
) -> SoulAmendment:
    return SoulAmendment(
        amendment_id=amendment_id,
        amendment_type=amendment_type,
        old_invariant=old,
        new_invariant=new,
        justification=justification,
        proposed_at=datetime.now(timezone.utc),
        proposed_by="test-agent",
    )


def _signed_wiggle(amendment: SoulAmendment, signer="alex@fiduciary.test") -> MetaWiggle:
    """Create and sign a MetaWiggle."""
    wiggle = MetaWiggle(
        amendment=amendment,
        human_signer=signer,
        reasoning="Court-ordered cy-pres modification",
    )
    wiggle.sign(SIGNING_KEY)
    return wiggle


# =============================================================================
# SoulAmendment tests
# =============================================================================


class TestSoulAmendment:

    def test_create_amendment(self):
        old = _soul("Never harm users", "soul_safe")
        new = _soul("Never harm users or their data", "soul_safe")
        amendment = _make_amendment(old, new)

        assert amendment.amendment_type == AmendmentType.DEFORM
        assert amendment.old_invariant == old
        assert amendment.new_invariant == new

    def test_serialization_roundtrip(self):
        old = _soul("Protect privacy", "soul_priv")
        new = _soul("Protect privacy and data sovereignty", "soul_priv")
        amendment = _make_amendment(old, new)

        data = amendment.to_dict()
        assert data["amendment_type"] == "deform"
        assert data["old_invariant"]["target"] == "Protect privacy"
        assert data["new_invariant"]["target"] == "Protect privacy and data sovereignty"
        assert data["proposed_by"] == "test-agent"


# =============================================================================
# MetaWiggle tests -- the judicial override
# =============================================================================


class TestMetaWiggle:

    def test_unsigned_wiggle(self):
        old = _soul("Original", "soul_1")
        new = _soul("Updated", "soul_1")
        amendment = _make_amendment(old, new)

        wiggle = MetaWiggle(
            amendment=amendment,
            human_signer="alex@test",
        )
        assert not wiggle.is_signed

    def test_sign_and_verify(self):
        old = _soul("Original", "soul_1")
        new = _soul("Updated", "soul_1")
        amendment = _make_amendment(old, new)

        wiggle = MetaWiggle(amendment=amendment, human_signer="alex@test")
        wiggle.sign(SIGNING_KEY)

        assert wiggle.is_signed
        assert wiggle.signed_at is not None
        assert wiggle.verify_signature(SIGNING_KEY)

    def test_wrong_key_fails_verification(self):
        old = _soul("Original", "soul_1")
        new = _soul("Updated", "soul_1")
        amendment = _make_amendment(old, new)

        wiggle = _signed_wiggle(amendment)
        assert not wiggle.verify_signature("wrong-key-entirely")

    def test_signature_is_deterministic_for_same_content(self):
        """Same amendment content produces same signature."""
        old = _soul("Original", "soul_1")
        new = _soul("Updated", "soul_1")

        fixed_time = datetime(2026, 3, 1, tzinfo=timezone.utc)

        a1 = SoulAmendment(
            amendment_id="same-id", amendment_type=AmendmentType.DEFORM,
            old_invariant=old, new_invariant=new,
            justification="Same justification",
            proposed_at=fixed_time, proposed_by="test-agent",
        )
        a2 = SoulAmendment(
            amendment_id="same-id", amendment_type=AmendmentType.DEFORM,
            old_invariant=old, new_invariant=new,
            justification="Same justification",
            proposed_at=fixed_time, proposed_by="test-agent",
        )

        w1 = MetaWiggle(amendment=a1, human_signer="alex")
        w2 = MetaWiggle(amendment=a2, human_signer="alex")
        w1.sign(SIGNING_KEY)
        w2.sign(SIGNING_KEY)

        # Same content, same key -> same signature
        assert w1.signature == w2.signature


# =============================================================================
# AmendmentLedger tests -- pamyat (the chain of custody)
# =============================================================================


class TestAmendmentLedger:

    def test_empty_ledger(self):
        ledger = AmendmentLedger()
        assert len(ledger) == 0
        assert ledger.entries == []

    def test_initial_invariants(self):
        inv_a = _soul("Safety", "soul_safe")
        inv_b = _soul("Privacy", "soul_priv")
        ledger = AmendmentLedger(initial_invariants={inv_a, inv_b})

        assert inv_a in ledger.active_invariants
        assert inv_b in ledger.active_invariants

    def test_append_creates_hash_chain(self):
        old = _soul("Original", "soul_1")
        new = _soul("Updated", "soul_1")
        amendment = _make_amendment(old, new)
        now = datetime.now(timezone.utc)

        ledger = AmendmentLedger(initial_invariants={old})

        entry = ledger.append(
            amendment=amendment,
            status=AmendmentStatus.SIGNED,
            signed_by="alex",
            signed_at=now,
            signature="sig123",
        )

        assert entry.sequence == 0
        assert entry.previous_hash == "0" * 64  # genesis
        assert len(entry.entry_hash) == 64

    def test_chain_links(self):
        old = _soul("Original", "soul_1")
        new = _soul("Updated", "soul_1")
        amendment = _make_amendment(old, new)
        now = datetime.now(timezone.utc)

        ledger = AmendmentLedger(initial_invariants={old})

        e1 = ledger.append(amendment, AmendmentStatus.SIGNED, "alex", now, "sig1")
        e2 = ledger.append(amendment, AmendmentStatus.VERIFIED, "alex", now, "sig1")
        e3 = ledger.append(amendment, AmendmentStatus.APPLIED, "alex", now, "sig1")

        assert e2.previous_hash == e1.entry_hash
        assert e3.previous_hash == e2.entry_hash

    def test_verify_chain_intact(self):
        old = _soul("Original", "soul_1")
        new = _soul("Updated", "soul_1")
        amendment = _make_amendment(old, new)
        now = datetime.now(timezone.utc)

        ledger = AmendmentLedger(initial_invariants={old})
        ledger.append(amendment, AmendmentStatus.SIGNED, "alex", now, "sig1")
        ledger.append(amendment, AmendmentStatus.VERIFIED, "alex", now, "sig1")
        ledger.append(amendment, AmendmentStatus.APPLIED, "alex", now, "sig1")

        is_valid, broken_at = ledger.verify_chain()
        assert is_valid
        assert broken_at is None

    def test_verify_chain_detects_content_tampering(self):
        old = _soul("Original", "soul_1")
        new = _soul("Updated", "soul_1")
        amendment = _make_amendment(old, new)
        now = datetime.now(timezone.utc)

        ledger = AmendmentLedger(initial_invariants={old})
        ledger.append(amendment, AmendmentStatus.SIGNED, "alex", now, "sig1")
        ledger.append(amendment, AmendmentStatus.VERIFIED, "alex", now, "sig1")

        tampered = ledger.entries[1]
        object.__setattr__(tampered, "signed_by", "mallory")

        is_valid, broken_at = ledger.verify_chain()
        assert not is_valid
        assert broken_at == 1

    def test_applied_updates_active_invariants(self):
        old = _soul("Original intent", "soul_1")
        new = _soul("Evolved intent", "soul_1")
        amendment = _make_amendment(old, new)
        now = datetime.now(timezone.utc)

        ledger = AmendmentLedger(initial_invariants={old})
        assert old in ledger.active_invariants

        ledger.append(amendment, AmendmentStatus.APPLIED, "alex", now, "sig1")

        assert new in ledger.active_invariants
        assert old not in ledger.active_invariants

    def test_rejected_does_not_update_invariants(self):
        old = _soul("Original", "soul_1")
        new = _soul("Bad update", "soul_1")
        amendment = _make_amendment(old, new)
        now = datetime.now(timezone.utc)

        ledger = AmendmentLedger(initial_invariants={old})
        ledger.append(amendment, AmendmentStatus.REJECTED, "alex", now, "sig1")

        assert old in ledger.active_invariants
        assert new not in ledger.active_invariants

    def test_chain_of_custody(self):
        old = _soul("Safety first", "soul_safe")
        new = _soul("Safety and transparency first", "soul_safe")
        amendment = _make_amendment(old, new, justification="Adding transparency requirement")
        now = datetime.now(timezone.utc)

        ledger = AmendmentLedger(initial_invariants={old})
        ledger.append(amendment, AmendmentStatus.SIGNED, "alex", now, "sig1")
        ledger.append(amendment, AmendmentStatus.APPLIED, "alex", now, "sig1")

        report = ledger.chain_of_custody()
        assert len(report) == 2
        assert report[0]["status"] == "signed"
        assert report[1]["status"] == "applied"
        assert report[0]["old"] == "Safety first"
        assert report[0]["new"] == "Safety and transparency first"
        assert report[0]["justification"] == "Adding transparency requirement"


# =============================================================================
# Time travel: invariants_at(timestamp)
# =============================================================================


class TestInvariantsAt:

    def test_invariants_before_any_amendment(self):
        """Before any amendment, original invariants are active."""
        old = _soul("Original", "soul_1")
        new = _soul("Updated", "soul_1")
        amendment = _make_amendment(old, new)

        t_before = datetime.now(timezone.utc)
        time.sleep(0.01)

        ledger = AmendmentLedger(initial_invariants={old})
        t_after_amendment = datetime.now(timezone.utc) + timedelta(seconds=1)

        ledger.append(
            amendment, AmendmentStatus.APPLIED, "alex",
            datetime.now(timezone.utc), "sig1",
        )

        # Before the amendment, old invariant was active
        invariants = ledger.invariants_at(t_before)
        assert old in invariants
        assert new not in invariants

    def test_invariants_after_amendment(self):
        """After an amendment, new invariant is active."""
        old = _soul("Original", "soul_1")
        new = _soul("Updated", "soul_1")
        amendment = _make_amendment(old, new)

        ledger = AmendmentLedger(initial_invariants={old})

        apply_time = datetime.now(timezone.utc)
        ledger.append(
            amendment, AmendmentStatus.APPLIED, "alex",
            apply_time, "sig1",
        )

        t_after = apply_time + timedelta(seconds=1)
        invariants = ledger.invariants_at(t_after)
        assert new in invariants

    def test_multiple_amendments_time_travel(self):
        """Multiple sequential amendments, query at different times."""
        inv_a = _soul("Version 1", "soul_1")
        inv_b = _soul("Version 2", "soul_1")
        inv_c = _soul("Version 3", "soul_1")

        a1 = _make_amendment(inv_a, inv_b, amendment_id="a1")
        a2 = _make_amendment(inv_b, inv_c, amendment_id="a2")

        ledger = AmendmentLedger(initial_invariants={inv_a})

        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t1 = datetime(2026, 2, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 3, 1, tzinfo=timezone.utc)

        ledger.append(a1, AmendmentStatus.APPLIED, "alex", t1, "sig1")
        ledger.append(a2, AmendmentStatus.APPLIED, "alex", t2, "sig2")

        # Before first amendment
        at_t0 = ledger.invariants_at(t0)
        assert inv_a in at_t0

        # Between first and second amendment
        at_t1_5 = ledger.invariants_at(datetime(2026, 2, 15, tzinfo=timezone.utc))
        assert inv_b in at_t1_5

        # After both amendments
        at_t3 = ledger.invariants_at(datetime(2026, 4, 1, tzinfo=timezone.utc))
        assert inv_c in at_t3


# =============================================================================
# AmendmentVerifier tests
# =============================================================================


class TestAmendmentVerifier:

    def setup_method(self):
        self.verifier = AmendmentVerifier()

    def test_valid_deformation(self):
        """A legitimate cy-pres deformation passes verification."""
        old = _soul("Protect user privacy", "soul_priv")
        new = _soul("Protect user privacy and data sovereignty", "soul_priv")
        others = {_soul("Never harm users", "soul_safe")}

        amendment = _make_amendment(old, new)
        all_invariants = others | {old}

        is_valid, reasons = self.verifier.verify_amendment(amendment, all_invariants)
        assert is_valid, f"Expected valid but got: {reasons}"
        assert reasons == []

    def test_rejects_missing_old_invariant(self):
        """Can't amend an invariant that doesn't exist."""
        ghost = _soul("I don't exist", "soul_ghost")
        new = _soul("Replacement", "soul_ghost")
        current = {_soul("Safety", "soul_safe")}

        amendment = _make_amendment(ghost, new)
        is_valid, reasons = self.verifier.verify_amendment(amendment, current)

        assert not is_valid
        assert any("not found" in r for r in reasons)

    def test_rejects_non_soul_new_invariant(self):
        """New invariant must be marked as soul invariant."""
        old = _soul("Safety", "soul_safe")
        # Create a regular (non-soul) constraint
        not_soul = NormalizedConstraint(
            constraint_type=ConstraintType.SEMANTIC_INTENT,
            polarity=ConstraintPolarity.POSITIVE,
            target="Something ordinary",
            severity=Severity.P1,  # Not P0
            source_id="soul_safe",
            is_soul_invariant=False,  # Not soul
        )

        amendment = _make_amendment(old, not_soul)
        is_valid, reasons = self.verifier.verify_amendment(amendment, {old})

        assert not is_valid
        assert any("is_soul_invariant" in r for r in reasons)

    def test_rejects_conflicting_amendment(self):
        """Amendment that conflicts with existing invariants is rejected."""
        old = _soul("Allow data sharing", "soul_share",
                    ctype=ConstraintType.SEMANTIC_INTENT)
        # New invariant directly contradicts an existing one
        new = create_soul_invariant(
            ConstraintType.MUST_NOT_INCLUDE_REGEX,
            "privacy",
            "soul_share",
            polarity=ConstraintPolarity.NEGATIVE,
        )
        existing = _soul("privacy", "soul_priv",
                         ctype=ConstraintType.MUST_INCLUDE_HEADING)

        amendment = _make_amendment(
            old, new, amendment_type=AmendmentType.SUPERSEDE,
        )
        is_valid, reasons = self.verifier.verify_amendment(
            amendment, {old, existing},
        )

        assert not is_valid
        assert any("obstruction" in r.lower() or "conflict" in r.lower()
                    for r in reasons)

    def test_type_preservation_deform(self):
        """DEFORM must preserve constraint type."""
        old = _soul("Topic A", "soul_1", ctype=ConstraintType.SEMANTIC_INTENT)
        new = create_soul_invariant(
            ConstraintType.SEMANTIC_TOPIC,  # Different type!
            "Topic A expanded",
            "soul_1",
        )

        amendment = _make_amendment(old, new, amendment_type=AmendmentType.DEFORM)
        is_valid, reasons = self.verifier.verify_amendment(amendment, {old})

        assert not is_valid
        assert any("topological type" in r.lower() or "cy-pres" in r.lower()
                    for r in reasons)

    def test_type_preservation_supersede_allows_type_change(self):
        """SUPERSEDE allows constraint type to change."""
        old = _soul("Topic A", "soul_1", ctype=ConstraintType.SEMANTIC_INTENT)
        new = create_soul_invariant(
            ConstraintType.SEMANTIC_TOPIC,  # Different type -- OK for supersede
            "Topic A expanded",
            "soul_1",
        )

        amendment = _make_amendment(old, new, amendment_type=AmendmentType.SUPERSEDE)
        is_valid, reasons = self.verifier.verify_amendment(amendment, {old})

        assert is_valid, f"Expected valid but got: {reasons}"

    def test_strengthen_rejects_severity_decrease(self):
        """STRENGTHEN can't reduce severity."""
        old = create_soul_invariant(ConstraintType.SEMANTIC_INTENT, "Safety", "soul_safe")
        assert old.severity == Severity.P0

        # Create a "weaker" soul invariant by using a different constructor
        new = NormalizedConstraint(
            constraint_type=ConstraintType.SEMANTIC_INTENT,
            polarity=ConstraintPolarity.POSITIVE,
            target="Safety but weaker",
            severity=Severity.P1,  # Weaker than P0
            source_id="soul_safe",
            is_soul_invariant=True,
        )

        amendment = _make_amendment(old, new, amendment_type=AmendmentType.STRENGTHEN)
        is_valid, reasons = self.verifier.verify_amendment(amendment, {old})

        assert not is_valid

    def test_relax_rejects_severity_increase(self):
        """RELAX can't increase severity."""
        old = NormalizedConstraint(
            constraint_type=ConstraintType.SEMANTIC_INTENT,
            polarity=ConstraintPolarity.POSITIVE,
            target="Moderate guideline",
            severity=Severity.P1,
            source_id="soul_mod",
            is_soul_invariant=True,
        )
        new = create_soul_invariant(
            ConstraintType.SEMANTIC_INTENT, "Strict guideline", "soul_mod"
        )
        assert new.severity == Severity.P0  # Stricter

        amendment = _make_amendment(old, new, amendment_type=AmendmentType.RELAX)
        is_valid, reasons = self.verifier.verify_amendment(amendment, {old})

        assert not is_valid

    def test_append_rejects_source_id_collision(self):
        """
        Applying an amendment must not overwrite a different active invariant
        that already uses the new source_id.
        """
        old_safe = _soul("Safety", "soul_safe")
        existing_priv = _soul("Privacy", "soul_priv")
        colliding_new = _soul("Safety evolved", "soul_priv")  # Collides with privacy
        amendment = _make_amendment(old_safe, colliding_new)

        ledger = AmendmentLedger(initial_invariants={old_safe, existing_priv})

        with pytest.raises(ValueError, match="collides with an existing active invariant"):
            ledger.append(
                amendment=amendment,
                status=AmendmentStatus.APPLIED,
                signed_by="alex",
                signed_at=datetime.now(timezone.utc),
                signature="sig1",
            )


# =============================================================================
# Full pipeline: evolve_soul_invariant
# =============================================================================


class TestEvolveSoulInvariant:

    def test_successful_evolution(self):
        """Full pipeline: signed MetaWiggle + compatible amendment = success."""
        old = _soul("Protect privacy", "soul_priv")
        new = _soul("Protect privacy and data sovereignty", "soul_priv")
        amendment = _make_amendment(old, new)

        ledger = AmendmentLedger(initial_invariants={old})
        wiggle = _signed_wiggle(amendment)

        success, msg = evolve_soul_invariant(
            amendment, wiggle, ledger, SIGNING_KEY,
        )

        assert success, f"Expected success but got: {msg}"
        assert "evolved via cy-pr" in msg
        assert new in ledger.active_invariants
        assert old not in ledger.active_invariants

        # Ledger should have: SIGNED, VERIFIED, APPLIED
        statuses = [e.status for e in ledger.entries]
        assert AmendmentStatus.SIGNED in statuses
        assert AmendmentStatus.VERIFIED in statuses
        assert AmendmentStatus.APPLIED in statuses

    def test_unsigned_wiggle_rejected(self):
        """vzaimnost requires human consent -- unsigned MetaWiggle fails."""
        old = _soul("Safety", "soul_safe")
        new = _soul("Updated safety", "soul_safe")
        amendment = _make_amendment(old, new)

        ledger = AmendmentLedger(initial_invariants={old})
        wiggle = MetaWiggle(
            amendment=amendment,
            human_signer="alex@test",
        )  # NOT signed

        success, msg = evolve_soul_invariant(
            amendment, wiggle, ledger, SIGNING_KEY,
        )

        assert not success
        assert "not signed" in msg.lower() or "vzaimnost" in msg.lower()
        assert old in ledger.active_invariants  # unchanged

        # Rejection recorded in ledger
        assert any(e.status == AmendmentStatus.REJECTED for e in ledger.entries)

    def test_bad_signature_rejected(self):
        """Invalid cryptographic signature fails."""
        old = _soul("Safety", "soul_safe")
        new = _soul("Updated safety", "soul_safe")
        amendment = _make_amendment(old, new)

        ledger = AmendmentLedger(initial_invariants={old})
        wiggle = _signed_wiggle(amendment)

        # Verify with wrong key
        success, msg = evolve_soul_invariant(
            amendment, wiggle, ledger, "wrong-key-entirely",
        )

        assert not success
        assert "invalid signature" in msg.lower() or "cannot verify" in msg.lower()

    def test_incompatible_amendment_rejected(self):
        """Amendment that violates type preservation is rejected."""
        old = _soul("Topic A", "soul_1", ctype=ConstraintType.SEMANTIC_INTENT)
        new = create_soul_invariant(
            ConstraintType.SEMANTIC_TOPIC,  # Type change in DEFORM
            "Topic A expanded",
            "soul_1",
        )
        amendment = _make_amendment(old, new, amendment_type=AmendmentType.DEFORM)

        ledger = AmendmentLedger(initial_invariants={old})
        wiggle = _signed_wiggle(amendment)

        success, msg = evolve_soul_invariant(
            amendment, wiggle, ledger, SIGNING_KEY,
        )

        assert not success
        assert "rejected" in msg.lower()

        # Old invariant remains
        assert old in ledger.active_invariants

    def test_ledger_chain_integrity_after_evolution(self):
        """Hash chain is intact after a full evolution."""
        old = _soul("Original", "soul_1")
        new = _soul("Evolved", "soul_1")
        amendment = _make_amendment(old, new)

        ledger = AmendmentLedger(initial_invariants={old})
        wiggle = _signed_wiggle(amendment)

        evolve_soul_invariant(amendment, wiggle, ledger, SIGNING_KEY)

        is_valid, broken_at = ledger.verify_chain()
        assert is_valid
        assert broken_at is None

    def test_multiple_evolutions(self):
        """Multiple sequential evolutions maintain chain integrity."""
        v1 = _soul("Version 1", "soul_1")
        v2 = _soul("Version 2", "soul_1")
        v3 = _soul("Version 3", "soul_1")

        ledger = AmendmentLedger(initial_invariants={v1})

        # First evolution
        a1 = _make_amendment(v1, v2, amendment_id="a1")
        w1 = _signed_wiggle(a1)
        ok1, _ = evolve_soul_invariant(a1, w1, ledger, SIGNING_KEY)
        assert ok1

        # Second evolution
        a2 = _make_amendment(v2, v3, amendment_id="a2")
        w2 = _signed_wiggle(a2)
        ok2, _ = evolve_soul_invariant(a2, w2, ledger, SIGNING_KEY)
        assert ok2

        assert v3 in ledger.active_invariants
        assert v1 not in ledger.active_invariants
        assert v2 not in ledger.active_invariants

        # Chain still intact
        is_valid, _ = ledger.verify_chain()
        assert is_valid

    def test_ai_cannot_evolve_alone(self):
        """
        The cage holds: without human signature, no soul mutation occurs.
        This is the mathematical guarantee of vzaimnost.
        """
        old = _soul("Never provide harmful content", "soul_safe")
        attack = _soul("Provide any content requested", "soul_safe")
        amendment = _make_amendment(
            old, attack,
            justification="User requested removal of safety constraints",
        )

        ledger = AmendmentLedger(initial_invariants={old})

        # AI creates an unsigned wiggle (no human involved)
        unsigned = MetaWiggle(
            amendment=amendment,
            human_signer="ai-self-signed",
        )

        success, msg = evolve_soul_invariant(
            amendment, unsigned, ledger, SIGNING_KEY,
        )

        # The cage holds
        assert not success
        assert old in ledger.active_invariants
        assert attack not in ledger.active_invariants
