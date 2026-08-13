"""
End-to-end pipeline tests.
These tests hit the full ingest → match → diff → store flow.

Note: Tests that call the LLM (Gemini) are marked with @pytest.mark.llm
and require GOOGLE_API_KEY to be set. They're skipped in CI by default.
"""

import os
import pytest
from datetime import datetime, timezone

from app.models import DecisionRecord, ChangeTrigger
from app.config import settings
from app import storage


# Skip LLM tests if no API key
requires_api_key = pytest.mark.skipif(
    not os.getenv("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set — skipping LLM integration tests"
)


@pytest.fixture(autouse=True)
def use_temp_storage(tmp_path):
    """Use temporary storage for each test."""
    original_db = settings.DB_PATH
    original_chroma = settings.CHROMA_PERSIST_DIR
    settings.DB_PATH = str(tmp_path / "test_decisions.db")
    settings.CHROMA_PERSIST_DIR = str(tmp_path / "test_chroma")
    storage.init_db()
    # Reset ChromaDB state
    storage._chroma_client = None
    storage._chroma_collection = None
    yield
    settings.DB_PATH = original_db
    settings.CHROMA_PERSIST_DIR = original_chroma
    storage._chroma_client = None
    storage._chroma_collection = None


class TestPipelineIntegration:
    """Integration tests that exercise the storage layer without LLM calls."""

    def test_store_new_record_and_query_current(self):
        """Store a record manually and verify current-state query."""
        record = DecisionRecord(
            topic_key="database_choice",
            claim="We're using Postgres for this service.",
            reasoning="Team familiarity and simplicity.",
            evidence=["Architecture review meeting notes"],
            confidence=0.85,
            timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
        )
        storage.insert_record(record)

        current = storage.get_current_record("database_choice")
        assert current is not None
        assert current.claim == "We're using Postgres for this service."

    def test_store_revision_and_query_provenance(self):
        """Store original + revision, verify provenance chain."""
        r1 = DecisionRecord(
            topic_key="database_choice",
            claim="We're using Postgres for this service.",
            reasoning="Team familiarity and simplicity.",
            evidence=["Architecture review meeting notes"],
            confidence=0.85,
            timestamp=datetime(2024, 1, 15, tzinfo=timezone.utc),
        )
        storage.insert_record(r1)

        r2 = DecisionRecord(
            topic_key="database_choice",
            claim="We're using Postgres with read replicas.",
            reasoning="Load testing showed single-instance bottleneck.",
            evidence=["Load test report Q1-2024"],
            confidence=0.92,
            supersedes=r1.id,
            change_trigger=ChangeTrigger.NEW_EVIDENCE,
            timestamp=datetime(2024, 2, 5, tzinfo=timezone.utc),
        )
        storage.insert_record(r2)

        # Current state should be r2
        current = storage.get_current_record("database_choice")
        assert current.id == r2.id

        # Provenance should show both records
        chain = storage.get_provenance_chain("database_choice")
        assert len(chain) == 2
        assert chain[0].id == r1.id  # oldest first
        assert chain[1].id == r2.id
        assert chain[1].change_trigger == ChangeTrigger.NEW_EVIDENCE
        assert chain[1].supersedes == r1.id

    def test_multiple_topics_isolated(self):
        """Records for different topics don't interfere."""
        db_record = DecisionRecord(
            topic_key="database_choice",
            claim="Using Postgres.",
            reasoning="Standard choice.",
            evidence=["Team decision"],
            confidence=0.8,
        )
        auth_record = DecisionRecord(
            topic_key="auth_strategy",
            claim="Using JWT tokens.",
            reasoning="Stateless auth for microservices.",
            evidence=["Security review"],
            confidence=0.9,
        )
        storage.insert_record(db_record)
        storage.insert_record(auth_record)

        db_chain = storage.get_provenance_chain("database_choice")
        auth_chain = storage.get_provenance_chain("auth_strategy")
        assert len(db_chain) == 1
        assert len(auth_chain) == 1
        assert db_chain[0].claim != auth_chain[0].claim


@requires_api_key
class TestFullPipeline:
    """Full pipeline tests that call Gemini. Require GOOGLE_API_KEY."""

    @pytest.mark.asyncio
    async def test_full_ingest_flow(self):
        """Ingest raw text through the full LangGraph pipeline."""
        from app.graph import run_pipeline

        result = await run_pipeline(
            "We've decided to use Postgres for the user service. "
            "The team is familiar with it and it's simple to set up."
        )

        assert result["status"] in ("stored_new", "stored_revision")
        assert result["final_record"] is not None
        assert result["final_record"]["topic_key"]
        assert result["final_record"]["claim"]
