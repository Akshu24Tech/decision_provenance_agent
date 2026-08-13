"""
FastAPI entrypoint for Decision Provenance Agent.

Endpoints:
  POST /ingest        — Accept raw text, run through pipeline
  GET  /query/{topic}  — Current state or provenance chain
  GET  /topics         — List all tracked topics
  GET  /health         — Health check
"""

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models import (
    IngestRequest,
    IngestResponse,
    QueryResponse,
    TopicListResponse,
    DecisionRecord,
)
from app import storage
from app.graph import run_pipeline


# ──────────────────────────────────────────────
#  App lifecycle
# ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize storage on startup."""
    settings.validate()
    storage.init_storage()
    yield


app = FastAPI(
    title="Decision Provenance Agent",
    description=(
        "Not just 'what happened' — 'why we changed our minds,' "
        "as a first-class, queryable object. "
        "Stores decisions with full lineage: claim, reasoning, evidence, "
        "and every revision with its trigger."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
#  Endpoints
# ──────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "agent": "Decision Provenance Agent",
        "model": settings.GEMINI_MODEL,
    }


@app.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest):
    """
    Ingest raw text through the decision pipeline.
    
    The pipeline will:
    1. Extract a decision from the text (topic, claim, reasoning, evidence)
    2. Search for existing decisions on the same topic
    3. If a match exists, classify whether the decision actually changed
    4. Store as new, store as revision, or deduplicate
    """
    try:
        result = await run_pipeline(request.text)

        record = None
        if result.get("final_record"):
            record = DecisionRecord(**result["final_record"])

        return IngestResponse(
            status=result.get("status", "rejected"),
            record=record,
            message=result.get("message", ""),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")


@app.get("/query/{topic_key}", response_model=QueryResponse)
async def query_topic(
    topic_key: str,
    mode: str = Query(
        default="current",
        description="Query mode: 'current' (latest record) or 'provenance' (full chain)",
        pattern="^(current|provenance)$",
    ),
):
    """
    Query decisions by topic.
    
    Two modes:
    - **current**: Returns the latest, non-superseded record (what's true NOW)
    - **provenance**: Returns the full chain of revisions with change triggers
      (WHY it changed — the thing flat memory can't answer)
    """
    if mode == "current":
        record = storage.get_current_record(topic_key)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail=f"No decisions found for topic: {topic_key}",
            )
        return QueryResponse(
            topic_key=topic_key,
            mode="current",
            records=[record],
            total_revisions=len(storage.get_provenance_chain(topic_key)),
        )

    elif mode == "provenance":
        chain = storage.get_provenance_chain(topic_key)
        if not chain:
            raise HTTPException(
                status_code=404,
                detail=f"No decisions found for topic: {topic_key}",
            )
        return QueryResponse(
            topic_key=topic_key,
            mode="provenance",
            records=chain,
            total_revisions=len(chain),
        )


@app.get("/topics", response_model=TopicListResponse)
async def list_topics():
    """List all tracked decision topics."""
    topics = storage.list_topics()
    return TopicListResponse(topics=topics, total=len(topics))
