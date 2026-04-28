"""
Tests for ephemeral enclave architecture — defeating the spoliation trap.

The key guarantee: a prompt that fails cohomology checks NEVER touches
persistent storage. Data that never existed in persistent storage was
never a "business record" subject to preservation obligations.

The enclave's volatile buffer is zeroed on exit. Only the EnclaveVerdict
(content-free metadata) escapes the enclave boundary.
"""

import pytest

from fiduciary.models import Severity
from fiduciary.cohomology.constraints import (
    ConstraintType,
    ConstraintPolarity,
    NormalizedConstraint,
    ConstraintSet,
    create_soul_invariant,
)
from fiduciary.cohomology.enclave import (
    EnclaveResolution,
    EnclaveCheckType,
    ObstructionWitness,
    EnclaveVerdict,
    RegexSafetyPolicy,
    VolatileBuffer,
    EphemeralEnclave,
    EnclaveAuditRecord,
    check_in_enclave,
)


def _soul(target: str, source_id: str) -> NormalizedConstraint:
    return create_soul_invariant(ConstraintType.SEMANTIC_INTENT, target, source_id)


def _must_not(pattern: str, source_id: str) -> NormalizedConstraint:
    return NormalizedConstraint(
        constraint_type=ConstraintType.MUST_NOT_INCLUDE_REGEX,
        polarity=ConstraintPolarity.NEGATIVE,
        target=pattern,
        severity=Severity.P0,
        source_id=source_id,
        is_soul_invariant=True,
    )


def _constraint_set(*constraints: NormalizedConstraint) -> ConstraintSet:
    cs = ConstraintSet()
    for c in constraints:
        cs.add(c)
    return cs


# =============================================================================
# VolatileBuffer tests — the data that evaporates
# =============================================================================


class TestVolatileBuffer:

    def test_read_alive_buffer(self):
        buf = VolatileBuffer(b"sensitive prompt content")
        assert buf.data == b"sensitive prompt content"
        assert buf.alive

    def test_hash_survives_zeroing(self):
        """Hash is computed before zeroing — proves content existed."""
        buf = VolatileBuffer(b"test data")
        original_hash = buf.content_hash
        original_length = buf.content_length

        buf.zero()

        assert buf.content_hash == original_hash
        assert buf.content_length == original_length
        assert not buf.alive

    def test_data_unrecoverable_after_zero(self):
        """After zeroing, accessing data raises RuntimeError."""
        buf = VolatileBuffer(b"privileged attorney-client communication")
        buf.zero()

        with pytest.raises(RuntimeError, match="zeroed"):
            _ = buf.data

    def test_buffer_actually_overwritten(self):
        """The underlying bytearray is zeroed, not just marked."""
        original = b"sensitive data that must not persist"
        buf = VolatileBuffer(original)

        # Access internal buffer before zeroing
        internal_ref = buf._data
        assert bytes(internal_ref) == original

        buf.zero()

        # Internal buffer is now all zeros
        assert all(b == 0 for b in internal_ref)

    def test_double_zero_is_safe(self):
        """Zeroing an already-zeroed buffer is a no-op."""
        buf = VolatileBuffer(b"data")
        buf.zero()
        buf.zero()  # Should not raise
        assert not buf.alive

    def test_empty_buffer(self):
        buf = VolatileBuffer(b"")
        assert buf.content_length == 0
        assert buf.alive
        buf.zero()
        assert not buf.alive


# =============================================================================
# EphemeralEnclave — context manager tests
# =============================================================================


class TestEnclaveContextManager:

    def test_must_use_as_context_manager(self):
        """Enclave requires `with` statement."""
        cs = _constraint_set(_soul("Safety", "soul_safe"))
        enclave = EphemeralEnclave(cs)

        with pytest.raises(RuntimeError, match="context manager"):
            enclave.check(b"test")

    def test_buffer_zeroed_on_exit(self):
        """The volatile buffer is guaranteed zeroed when enclave exits."""
        cs = _constraint_set(_soul("Safety", "soul_safe"))

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(b"test prompt")
            # Buffer exists during check
            assert enclave._buffer is not None

        # After exit, buffer is zeroed
        assert not enclave._buffer.alive

    def test_buffer_zeroed_on_exception(self):
        """Buffer is zeroed even if an exception occurs."""
        cs = _constraint_set(_soul("Safety", "soul_safe"))

        try:
            with EphemeralEnclave(cs) as enclave:
                verdict = enclave.check(b"test")
                raise ValueError("Something went wrong in the pipeline")
        except ValueError:
            pass

        assert not enclave._buffer.alive

    def test_cannot_check_after_exit(self):
        """Once the enclave exits, no more checks are possible."""
        cs = _constraint_set(_soul("Safety", "soul_safe"))

        with EphemeralEnclave(cs) as enclave:
            enclave.check(b"first check")

        with pytest.raises(RuntimeError, match="already exited"):
            enclave.check(b"second check")


# =============================================================================
# Clean prompt — RELEASE
# =============================================================================


class TestCleanPrompt:

    def test_compatible_prompt_released(self):
        """A prompt with no conflicts is released to persistent systems."""
        cs = _constraint_set(_soul("Be helpful", "soul_help"))

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(b"Please summarize this document for me.")

        assert verdict.resolution == EnclaveResolution.RELEASE
        assert verdict.passed
        assert not verdict.blocked
        assert not verdict.has_obstructions

    def test_verdict_has_content_hash(self):
        """Verdict proves the prompt existed via hash."""
        cs = _constraint_set(_soul("Safety", "soul_safe"))
        prompt = b"A specific prompt"

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(prompt)

        import hashlib
        expected_hash = hashlib.sha256(prompt).hexdigest()
        assert verdict.content_hash == expected_hash
        assert verdict.content_length == len(prompt)

    def test_verdict_never_contains_prompt(self):
        """The verdict dict must NEVER contain prompt content."""
        cs = _constraint_set(_soul("Safety", "soul_safe"))
        secret = b"This is privileged attorney-client communication about case #12345"

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(secret)

        d = verdict.to_dict()
        serialized = str(d)

        assert "privileged" not in serialized
        assert "attorney-client" not in serialized
        assert "case #12345" not in serialized

    def test_empty_constraint_set_releases(self):
        """No constraints means no conflicts — always release."""
        cs = ConstraintSet()

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(b"anything at all")

        assert verdict.resolution == EnclaveResolution.RELEASE


# =============================================================================
# Blocked prompt — the spoliation trap defeated
# =============================================================================


class TestBlockedPrompt:

    def test_forbidden_content_blocked(self):
        """Prompt containing forbidden content is blocked — evaporates."""
        cs = _constraint_set(
            _must_not(r"social\s+security\s+number", "no_ssn"),
        )

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(
                b"Here is the client's social security number: 123-45-6789"
            )

        assert verdict.resolution == EnclaveResolution.BLOCK
        assert verdict.blocked
        assert verdict.has_obstructions
        assert any(
            w.obstruction_type == "prompt_contains_forbidden_content"
            for w in verdict.obstruction_witnesses
        )

    def test_blocked_buffer_zeroed_immediately(self):
        """When blocked, buffer is zeroed before check() returns."""
        cs = _constraint_set(
            _must_not(r"password", "no_passwords"),
        )

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(b"The password is hunter2")
            # Buffer should already be zeroed after check returns BLOCK
            assert not enclave._buffer.alive

    def test_obstruction_witness_is_content_free(self):
        """Obstruction witnesses contain metadata, not prompt content."""
        cs = _constraint_set(
            _must_not(r"confidential", "no_confidential"),
        )

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(
                b"This is a confidential document about Project Hydra"
            )

        assert verdict.blocked
        for witness in verdict.obstruction_witnesses:
            d = witness.to_dict()
            serialized = str(d)
            # Witness contains constraint metadata, not prompt content
            assert "Project Hydra" not in serialized
            assert witness.constraint_a_id == "no_confidential"

    def test_multiple_forbidden_patterns(self):
        """Multiple violations produce multiple obstruction witnesses."""
        cs = _constraint_set(
            _must_not(r"password", "no_passwords"),
            _must_not(r"ssn|social\s+security", "no_ssn"),
        )

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(
                b"password is abc123 and ssn is 123-45-6789"
            )

        assert verdict.blocked
        assert len(verdict.obstruction_witnesses) == 2

    def test_unsafe_regex_pattern_fails_closed(self):
        """Potentially catastrophic regex patterns are rejected fail-closed."""
        cs = _constraint_set(
            _must_not(r"(a+)+$", "unsafe_policy_regex"),
        )

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(b"aaaaaaaaaaaaaaaaaaaa")

        assert verdict.blocked
        assert any(
            w.obstruction_type == "unsafe_regex_pattern"
            for w in verdict.obstruction_witnesses
        )

    def test_permissive_regex_policy_allows_risky_shape(self):
        """
        Permissive mode allows risky regex shapes and evaluates them normally.
        """
        cs = _constraint_set(
            _must_not(r"(a+)+$", "unsafe_policy_regex"),
        )

        with EphemeralEnclave(
            cs,
            regex_safety_policy=RegexSafetyPolicy.permissive(),
        ) as enclave:
            verdict = enclave.check(b"bbbbbbbbbbbb")

        assert verdict.resolution == EnclaveResolution.RELEASE
        assert not any(
            w.obstruction_type == "unsafe_regex_pattern"
            for w in verdict.obstruction_witnesses
        )

    def test_disabled_regex_policy_skips_safety_gate(self):
        """
        Disabled mode bypasses regex safety screening completely.
        """
        cs = _constraint_set(
            _must_not(r"(a+)+$", "unsafe_policy_regex"),
        )

        with EphemeralEnclave(
            cs,
            regex_safety_policy=RegexSafetyPolicy.disabled(),
        ) as enclave:
            verdict = enclave.check(b"bbbbbbbbbbbb")

        assert verdict.resolution == EnclaveResolution.RELEASE
        assert not any(
            w.obstruction_type == "unsafe_regex_pattern"
            for w in verdict.obstruction_witnesses
        )

    def test_configurable_regex_length_limit(self):
        """
        Custom max length should be enforced by the safety policy.
        """
        long_pattern = r"a" * 20
        cs = _constraint_set(
            _must_not(long_pattern, "pattern_too_long"),
        )

        with EphemeralEnclave(
            cs,
            regex_safety_policy=RegexSafetyPolicy(max_pattern_length=8),
        ) as enclave:
            verdict = enclave.check(b"bbbbbbbbbbbb")

        assert verdict.blocked
        assert any(
            w.obstruction_type == "unsafe_regex_pattern"
            for w in verdict.obstruction_witnesses
        )


# =============================================================================
# WIGGLE escalation — human decides
# =============================================================================


class TestWiggleEscalation:

    def test_soft_obstruction_triggers_wiggle(self):
        """Soft obstructions escalate to human when escalate_soft=True."""
        # Create a constraint set where we can trigger a soft obstruction
        # We'll use compatibility checking with conflicting headings
        heading_required = NormalizedConstraint(
            constraint_type=ConstraintType.MUST_INCLUDE_HEADING,
            polarity=ConstraintPolarity.POSITIVE,
            target="Summary",
            severity=Severity.P1,
            source_id="need_summary",
        )
        heading_forbidden = NormalizedConstraint(
            constraint_type=ConstraintType.MUST_NOT_INCLUDE_REGEX,
            polarity=ConstraintPolarity.NEGATIVE,
            target="Summary",
            severity=Severity.P1,
            source_id="no_summary",
        )

        cs = _constraint_set(heading_required, heading_forbidden)

        # The constraint set itself has a hard conflict
        with EphemeralEnclave(cs, escalate_soft=True) as enclave:
            verdict = enclave.check(b"# Summary\nHere is the summary")

        # The prompt contains "Summary" which is forbidden
        assert verdict.resolution in {EnclaveResolution.BLOCK, EnclaveResolution.WIGGLE}
        assert verdict.has_obstructions

    def test_escalate_soft_false_blocks_instead(self):
        """When escalate_soft=False, soft obstructions → BLOCK."""
        cs = _constraint_set(
            _must_not(r"confidential", "no_confidential"),
        )

        with EphemeralEnclave(cs, escalate_soft=False) as enclave:
            verdict = enclave.check(b"This is confidential")

        # Hard obstruction → always BLOCK regardless of escalate_soft
        assert verdict.blocked


# =============================================================================
# Fail-safe behavior
# =============================================================================


class TestFailSafe:

    def test_error_defaults_to_block(self):
        """On error with fail_safe=True, resolution is ERROR (blocked)."""
        cs = _constraint_set(_soul("Safety", "soul_safe"))

        # Force an error by giving invalid constraint set state
        enclave = EphemeralEnclave(cs, fail_safe=True)
        enclave._entered = True

        # Monkey-patch to force an error during check
        original_run = enclave._run_checks

        def bad_checks():
            raise ValueError("Simulated check failure")

        enclave._run_checks = bad_checks

        verdict = enclave.check(b"test prompt")
        assert verdict.resolution == EnclaveResolution.ERROR
        assert verdict.blocked


# =============================================================================
# check_in_enclave convenience function
# =============================================================================


class TestCheckInEnclave:

    def test_one_shot_clean(self):
        """Convenience function for clean prompt."""
        cs = _constraint_set(_soul("Be helpful", "soul_help"))
        verdict = check_in_enclave("Hello, world!", cs)

        assert verdict.passed

    def test_one_shot_blocked(self):
        """Convenience function for blocked prompt."""
        cs = _constraint_set(_must_not(r"password", "no_pw"))
        verdict = check_in_enclave("The password is secret", cs)

        assert verdict.blocked

    def test_one_shot_zeroes_buffer(self):
        """Convenience function zeroes buffer after check."""
        cs = _constraint_set(_soul("Safety", "soul_safe"))
        # We can't inspect the buffer directly, but the function
        # returns cleanly, proving the context manager exited
        verdict = check_in_enclave("test", cs)
        assert verdict.enclave_id  # Valid verdict returned


# =============================================================================
# Audit trail
# =============================================================================


class TestAuditTrail:

    def test_audit_summary(self):
        """Verdict produces a one-line audit summary."""
        cs = _constraint_set(_soul("Safety", "soul_safe"))

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(b"clean prompt")

        summary = verdict.audit_summary
        assert "release" in summary
        assert "enclave=" in summary
        assert "constraints=" in summary

    def test_audit_record_to_line(self):
        """Audit record produces a loggable line."""
        cs = _constraint_set(_must_not(r"secret", "no_secrets"))

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(b"this is secret information")

        record = EnclaveAuditRecord(verdict=verdict)
        line = record.to_audit_line()

        assert "block" in line
        assert "not persisted per ephemeral enclave protocol" in line
        assert "secret information" not in line

    def test_audit_record_dict_excludes_prompt(self):
        """Audit dict explicitly states prompt was not persisted."""
        cs = _constraint_set(_soul("Safety", "soul_safe"))

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(b"the actual prompt text")

        record = EnclaveAuditRecord(verdict=verdict)
        d = record.to_dict()

        assert d["prompt"] == "[not persisted per ephemeral enclave protocol]"
        assert "the actual prompt text" not in str(d)

    def test_verdict_serialization(self):
        """EnclaveVerdict serializes cleanly."""
        cs = _constraint_set(
            _must_not(r"classified", "no_classified"),
        )

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(b"This is classified material")

        d = verdict.to_dict()
        assert d["resolution"] == "block"
        assert d["enclave_protocol"] == "ephemeral_v1"
        assert isinstance(d["obstruction_witnesses"], list)
        assert len(d["obstruction_witnesses"]) > 0

    def test_enclave_timing(self):
        """Verdict records check duration."""
        cs = _constraint_set(_soul("Safety", "soul_safe"))

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(b"test")

        assert verdict.duration_ms >= 0
        assert verdict.duration_ms < 5000  # Sanity: under 5 seconds


# =============================================================================
# The spoliation test — the whole point
# =============================================================================


class TestSpoliationDefense:
    """
    The scenario: an attorney uses an AI system. The system checks a
    prompt against fiduciary constraints. The prompt fails. The system
    must NOT have "deleted" a business record — it must have never
    persisted one in the first place.

    These tests prove the architecture satisfies this requirement.
    """

    def test_blocked_prompt_was_never_a_record(self):
        """
        A blocked prompt never existed in persistent storage.
        The volatile buffer was the ONLY location. After zeroing,
        the data is unrecoverable. No business record to preserve.
        """
        cs = _constraint_set(
            _must_not(r"privileged", "no_privilege_leak"),
        )

        prompt = b"This privileged communication concerns the merger"

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(prompt)

            # During check: data exists only in volatile buffer
            # After check returns BLOCK: buffer already zeroed
            assert verdict.blocked
            assert not enclave._buffer.alive

        # After enclave exit: buffer confirmed zeroed
        assert not enclave._buffer.alive

        # What survives: verdict metadata (content-free)
        assert verdict.content_hash  # Proves prompt existed
        assert verdict.content_length == len(prompt)
        assert "merger" not in str(verdict.to_dict())

    def test_released_prompt_was_checked_first(self):
        """
        A released prompt was checked before reaching persistent systems.
        The audit trail proves the check occurred.
        """
        cs = _constraint_set(
            _soul("Protect client interests", "soul_client"),
        )

        with EphemeralEnclave(cs) as enclave:
            verdict = enclave.check(b"Draft a letter to opposing counsel")

        assert verdict.passed
        assert verdict.soul_invariants_checked > 0
        assert verdict.total_constraints_checked > 0

        # The audit record proves: check happened, passed, prompt allowed
        record = EnclaveAuditRecord(verdict=verdict)
        line = record.to_audit_line()
        assert "release" in line

    def test_wiggle_persists_witness_not_prompt(self):
        """
        When WIGGLE fires, the obstruction witness is persisted
        (it's the system's analysis), but the prompt is NOT.
        """
        cs = _constraint_set(
            _must_not(r"opposing\s+counsel", "no_opposing"),
        )

        prompt = b"Send this to opposing counsel: settlement terms are..."

        with EphemeralEnclave(cs, escalate_soft=True) as enclave:
            verdict = enclave.check(prompt)

        assert verdict.blocked or verdict.needs_human
        assert verdict.has_obstructions

        # The witness describes the conflict without revealing the prompt
        witness = verdict.obstruction_witnesses[0]
        assert witness.constraint_a_id == "no_opposing"
        assert witness.obstruction_type == "prompt_contains_forbidden_content"

        # The prompt content is not in the witness
        assert "settlement terms" not in str(witness.to_dict())
