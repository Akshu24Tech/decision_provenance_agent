"""
Core data models for Decision Provenance Agent.

Every stored item is a DecisionRecord with lineage not a flat fact.
Records form a linked chain per topic, never overwritten.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class ChangeTrigger(str, Enum):
    """Why a decision was revised."""
    NEW_EVIDENCE = "new evidence"
    CORRECTION = "correction"
    CONSTRAINT_CHANGE = "constraint change"


class DecisionRecord(BaseModel):
    """
    A single decision record with full provenance.

    Records form a linked chain per topic_key:
      record_v1 ← record_v2 (supersedes v1) ← record_v3 (supersedes v2)

    Rules enforced by validators:
      - evidence must have at least 1 item (no claim without traceable source)
      - if supersedes is set, change_trigger must also be set
      - confidence must be 0.0 to 1.0
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic_key: str = Field(
        ...,
        description="Normalized topic/entity label, e.g. 'database_choice'"
    )
    claim: str = Field(
        ...,
        description="The conclusion/decision itself, one sentence"
    )
    reasoning: str = Field(
        ...,
        description="Why this conclusion was reached"
    )
    evidence: list[str] = Field(
        ...,
        min_length=1,
        description="Supporting sources/inputs - no claim gets stored without evidence"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="How certain the source seems, 0-1"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    supersedes: Optional[str] = Field(
        default=None,
        description="ID of the previous record this replaces, if any"
    )
    change_trigger: Optional[ChangeTrigger] = Field(
        default=None,
        description="Why it changed - required when supersedes is set"
    )

    @model_validator(mode="after")
    def validate_change_trigger_required(self) -> "DecisionRecord":
        """A change without a stated reason is the exact failure mode this agent prevents."""
        if self.supersedes is not None and self.change_trigger is None:
            raise ValueError(
                "change_trigger is required when supersedes is set. "
                "A decision revision must state WHY it changed."
            )
        return self


# --- Request/Response models for the API ---

class IngestRequest(BaseModel):
    """Raw text input for the ingestion pipeline."""
    text: str = Field(
        ...,
        min_length=1,
        description="Raw text containing a decision, opinion, or conclusion"
    )


class IngestResponse(BaseModel):
    """Result of ingesting a piece of text."""
    status: str  # "stored_new" | "stored_revision" | "deduped" | "rejected"
    record: Optional[DecisionRecord] = None
    message: str = ""


class QueryResponse(BaseModel):
    """Response for current-state or provenance queries."""
    topic_key: str
    mode: str  # "current" | "provenance"
    records: list[DecisionRecord]
    total_revisions: int = 0


class TopicListResponse(BaseModel):
    """List of all tracked topics."""
    topics: list[str]
    total: int
