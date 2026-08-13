"""
Tests for the SQLite storage layer.
Tests ChromaDB separately since it needs Gemini API for embeddings.
"""

import os
import pytest
from datetime import datetime, timezone, timedelta

from app.models import DecisionRecord, ChangeTrigger
from app.config import settings
from app import storage


@pytest.fixture(autouse=True)
def use_temp_db(tmp_path):
    """Use a temporary SQLite database for each test."""
    original_db = settings.DB_PATH
    settings.DB_PATH = str(tmp_path / "test_decisions.db")
    storage.init_db()
    yield
    settings.DB_PATH = original_db


class TestSQLiteStorage:
    """Test SQLite CRUD and chain walking."""

    def _make_record(self, **overrides) -> DecisionRecord:
        """Helper to create a DecisionRecord with defaults."""
        defaults = {
            "topic_key": "database_choice",
            "claim": "We're using Postgres.",
            "reasoning": "Team familiarity.",
            "evidence": ["Team survey"],
            "confidence": 0.85,
        }
        defaults.update(overrides)
        return DecisionRecord(**defaults)

    def test_insert_and_retrieve(self):
        """Basic insert + get by ID."""
        record = self._make_record()
        storage.insert_record(record)

        retrieved = storage.get_record_by_id(record.id)
        assert retrieved is not None
        assert retrieved.id == record.id
        assert retrieved.claim == record.claim
        assert retrieved.topic_key == record.topic_key

    def test_get_current_record_single(self):
        """Current-state query with one record."""
        record = self._make_record()
        storage.insert_record(record)

        current = storage.get_current_record("database_choice")
        assert current is not None
        assert current.id == record.id

    def test_get_current_record_chain(self):
        """Current-state query should return the latest non-superseded record."""
        # Record v1
        r1 = self._make_record(
            claim="Using Postgres.",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        storage.insert_record(r1)

        # Record v2 supersedes v1
        r2 = self._make_record(
            claim="Using Postgres with read replicas.",
            reasoning="Load test showed bottleneck.",
            evidence=["Load test report"],
            confidence=0.92,
            supersedes=r1.id,
            change_trigger=ChangeTrigger.NEW_EVIDENCE,
            timestamp=datetime(2024, 3, 1, tzinfo=timezone.utc),
        )
        storage.insert_record(r2)

        current = storage.get_current_record("database_choice")
        assert current is not None
        assert current.id == r2.id
        assert current.claim == "Using Postgres with read replicas."

    def test_get_provenance_chain_order(self):
        """Provenance query returns all records in chronological order."""
        r1 = self._make_record(
            claim="Using Postgres.",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        storage.insert_record(r1)

        r2 = self._make_record(
            claim="Using Postgres with read replicas.",
            reasoning="Load test showed bottleneck.",
            evidence=["Load test report"],
            supersedes=r1.id,
            change_trigger=ChangeTrigger.NEW_EVIDENCE,
            timestamp=datetime(2024, 3, 1, tzinfo=timezone.utc),
        )
        storage.insert_record(r2)

        r3 = self._make_record(
            claim="Migrating to CockroachDB.",
            reasoning="Need multi-region.",
            evidence=["Architecture review doc"],
            supersedes=r2.id,
            change_trigger=ChangeTrigger.CONSTRAINT_CHANGE,
            timestamp=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        storage.insert_record(r3)

        chain = storage.get_provenance_chain("database_choice")
        assert len(chain) == 3
        assert chain[0].id == r1.id  # oldest first
        assert chain[1].id == r2.id
        assert chain[2].id == r3.id
        assert chain[0].change_trigger is None  # first record
        assert chain[1].change_trigger == ChangeTrigger.NEW_EVIDENCE
        assert chain[2].change_trigger == ChangeTrigger.CONSTRAINT_CHANGE

    def test_provenance_chain_empty_topic(self):
        """Querying a nonexistent topic returns empty list."""
        chain = storage.get_provenance_chain("nonexistent_topic")
        assert chain == []

    def test_current_record_nonexistent_topic(self):
        """Current-state query for nonexistent topic returns None."""
        result = storage.get_current_record("nonexistent_topic")
        assert result is None

    def test_list_topics(self):
        """List topics returns unique topic keys."""
        storage.insert_record(self._make_record(topic_key="database_choice"))
        storage.insert_record(self._make_record(topic_key="auth_strategy"))
        storage.insert_record(self._make_record(topic_key="database_choice"))

        topics = storage.list_topics()
        assert sorted(topics) == ["auth_strategy", "database_choice"]

    def test_list_topics_empty(self):
        """List topics returns empty list when no records exist."""
        topics = storage.list_topics()
        assert topics == []

    def test_evidence_stored_as_json(self):
        """Evidence list is properly serialized/deserialized."""
        record = self._make_record(
            evidence=["Source 1", "Source 2", "Source 3"]
        )
        storage.insert_record(record)

        retrieved = storage.get_record_by_id(record.id)
        assert retrieved.evidence == ["Source 1", "Source 2", "Source 3"]
