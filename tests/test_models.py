"""
Tests for DecisionRecord schema and validators.
These are the trust boundary - if these fail, the agent can't be trusted.
"""

import pytest
from datetime import datetime, timezone

from app.models import DecisionRecord, ChangeTrigger


class TestDecisionRecordValidation:
    """Test the core validation rules that make this agent different."""

    def test_valid_new_record(self):
        """A first-time record with no supersedes should pass."""
        record = DecisionRecord(
            topic_key="database_choice",
            claim="We're using Postgres for this service.",
            reasoning="Simplicity and team familiarity.",
            evidence=["Team survey results", "Prior project experience"],
            confidence=0.85,
        )
        assert record.supersedes is None
        assert record.change_trigger is None
        assert record.id  # auto-generated

    def test_valid_revision_record(self):
        """A revision with both supersedes and change_trigger should pass."""
        record = DecisionRecord(
            topic_key="database_choice",
            claim="We're using Postgres with read replicas.",
            reasoning="Load testing showed single-instance bottleneck.",
            evidence=["Load test report Q3-2024"],
            confidence=0.92,
            supersedes="old-record-id-123",
            change_trigger=ChangeTrigger.NEW_EVIDENCE,
        )
        assert record.supersedes == "old-record-id-123"
        assert record.change_trigger == ChangeTrigger.NEW_EVIDENCE

    def test_reject_supersedes_without_change_trigger(self):
        """THE critical rule: a revision without a stated reason must be rejected."""
        with pytest.raises(ValueError, match="change_trigger is required"):
            DecisionRecord(
                topic_key="database_choice",
                claim="We switched to MySQL.",
                reasoning="Someone said so.",
                evidence=["Slack message"],
                confidence=0.5,
                supersedes="old-record-id-123",
                change_trigger=None,  # <-- this should fail
            )

    def test_reject_empty_evidence(self):
        """No claim gets stored without a traceable source."""
        with pytest.raises(ValueError):
            DecisionRecord(
                topic_key="database_choice",
                claim="We're using Postgres.",
                reasoning="Because.",
                evidence=[],  # <-- empty, should fail
                confidence=0.5,
            )

    def test_reject_confidence_out_of_range(self):
        """Confidence must be 0.0 to 1.0."""
        with pytest.raises(ValueError):
            DecisionRecord(
                topic_key="database_choice",
                claim="We're using Postgres.",
                reasoning="Because.",
                evidence=["Source"],
                confidence=1.5,  # <-- out of range
            )

        with pytest.raises(ValueError):
            DecisionRecord(
                topic_key="database_choice",
                claim="We're using Postgres.",
                reasoning="Because.",
                evidence=["Source"],
                confidence=-0.1,  # <-- negative
            )

    def test_timestamp_auto_generated(self):
        """Timestamp should be auto-set to now if not provided."""
        before = datetime.now(timezone.utc)
        record = DecisionRecord(
            topic_key="test",
            claim="Test claim.",
            reasoning="Test reasoning.",
            evidence=["Test source"],
            confidence=0.7,
        )
        after = datetime.now(timezone.utc)
        assert before <= record.timestamp <= after

    def test_id_auto_generated_unique(self):
        """Each record should get a unique ID."""
        r1 = DecisionRecord(
            topic_key="test",
            claim="Claim 1",
            reasoning="Reason 1",
            evidence=["Source 1"],
            confidence=0.5,
        )
        r2 = DecisionRecord(
            topic_key="test",
            claim="Claim 2",
            reasoning="Reason 2",
            evidence=["Source 2"],
            confidence=0.5,
        )
        assert r1.id != r2.id

    def test_change_trigger_enum_values(self):
        """All three trigger types should work."""
        for trigger in ChangeTrigger:
            record = DecisionRecord(
                topic_key="test",
                claim="Updated claim.",
                reasoning="Updated reasoning.",
                evidence=["Source"],
                confidence=0.8,
                supersedes="prev-id",
                change_trigger=trigger,
            )
            assert record.change_trigger == trigger

    def test_change_trigger_without_supersedes_is_fine(self):
        """Setting change_trigger without supersedes is allowed (edge case, no harm)."""
        record = DecisionRecord(
            topic_key="test",
            claim="First record but with trigger.",
            reasoning="Reason.",
            evidence=["Source"],
            confidence=0.7,
            change_trigger=ChangeTrigger.CORRECTION,
        )
        assert record.supersedes is None
        assert record.change_trigger == ChangeTrigger.CORRECTION
