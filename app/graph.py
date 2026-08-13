"""
LangGraph pipeline for Decision Provenance Agent.

Flow: ingest → extract → similarity_match → diff (if match) → validate → store

Each node is a pure function operating on a shared state dict.
"""

from datetime import datetime, timezone
from typing import TypedDict, Optional, Literal
import uuid

from langgraph.graph import StateGraph, END

from app.models import DecisionRecord, ChangeTrigger
from app.prompts import extract_decision, diff_decisions
from app import storage


# ──────────────────────────────────────────────
#  Pipeline State
# ──────────────────────────────────────────────

class PipelineState(TypedDict, total=False):
    """State flowing through the LangGraph pipeline."""
    raw_input: str
    candidate: Optional[dict]           # extracted decision candidate
    matched_record: Optional[dict]      # existing record that matched, if any
    diff_result: Optional[dict]         # diff classification result
    final_record: Optional[dict]        # the stored DecisionRecord (serialized)
    status: str                         # "pending" | "stored_new" | "stored_revision" | "deduped" | "rejected"
    message: str                        # human-readable status message


# ──────────────────────────────────────────────
#  Node 1: Extract decision from raw text
# ──────────────────────────────────────────────

async def extract_node(state: PipelineState) -> PipelineState:
    """Call Gemini to extract a structured decision from raw text."""
    try:
        candidate = await extract_decision(state["raw_input"])
        return {
            **state,
            "candidate": candidate,
            "status": "pending",
            "message": f"Extracted decision on topic: {candidate.get('topic_key', 'unknown')}",
        }
    except Exception as e:
        return {
            **state,
            "status": "rejected",
            "message": f"Extraction failed: {str(e)}",
        }


# ──────────────────────────────────────────────
#  Node 2: Search for similar existing records
# ──────────────────────────────────────────────

async def match_node(state: PipelineState) -> PipelineState:
    """Query ChromaDB for existing records on similar topics."""
    if state.get("status") == "rejected":
        return state

    candidate = state["candidate"]
    matches = storage.find_similar(
        topic_key=candidate["topic_key"],
        claim=candidate["claim"],
    )

    if matches:
        # Get the most similar existing record from SQLite
        best_match = matches[0]
        existing = storage.get_record_by_id(best_match["record_id"])
        if existing:
            return {
                **state,
                "matched_record": existing.model_dump(mode="json"),
                "message": f"Found existing record on '{candidate['topic_key']}' (similarity: {best_match['similarity']:.2f})",
            }

    return {
        **state,
        "matched_record": None,
        "message": f"No existing record found for '{candidate['topic_key']}' — will store as new",
    }


# ──────────────────────────────────────────────
#  Node 3: Diff against matched record
# ──────────────────────────────────────────────

async def diff_node(state: PipelineState) -> PipelineState:
    """If a match was found, classify whether the decision actually changed."""
    if state.get("status") == "rejected":
        return state

    if state.get("matched_record") is None:
        # No match → skip diff, go straight to store as new
        return {**state, "diff_result": None}

    candidate = state["candidate"]
    matched = state["matched_record"]

    try:
        diff_result = await diff_decisions(
            old_claim=matched["claim"],
            old_reasoning=matched["reasoning"],
            new_claim=candidate["claim"],
            new_reasoning=candidate["reasoning"],
        )
        return {
            **state,
            "diff_result": diff_result,
            "message": f"Diff result: changed={diff_result.get('changed', False)}",
        }
    except Exception as e:
        return {
            **state,
            "status": "rejected",
            "message": f"Diff failed: {str(e)}",
        }


# ──────────────────────────────────────────────
#  Node 4: Validate and store
# ──────────────────────────────────────────────

async def store_node(state: PipelineState) -> PipelineState:
    """Validate the decision and store it (or skip if deduped)."""
    if state.get("status") == "rejected":
        return state

    candidate = state["candidate"]
    matched = state.get("matched_record")
    diff_result = state.get("diff_result")

    # Case 1: No match → store as new record
    if matched is None:
        record = DecisionRecord(
            topic_key=candidate["topic_key"],
            claim=candidate["claim"],
            reasoning=candidate["reasoning"],
            evidence=candidate.get("evidence", ["input text"]),
            confidence=float(candidate.get("confidence", 0.5)),
        )
        storage.insert_record(record)
        storage.add_embedding(record.id, record.topic_key, record.claim)

        return {
            **state,
            "final_record": record.model_dump(mode="json"),
            "status": "stored_new",
            "message": f"Stored new decision on '{record.topic_key}'",
        }

    # Case 2: Match found but no real change → deduplicate
    if diff_result and not diff_result.get("changed", False):
        return {
            **state,
            "status": "deduped",
            "message": f"Same decision restated — not stored. {diff_result.get('diff_summary', '')}",
        }

    # Case 3: Match found and decision genuinely changed → store revision
    if diff_result and diff_result.get("changed", False):
        trigger_str = diff_result.get("change_trigger", "new evidence")
        try:
            change_trigger = ChangeTrigger(trigger_str)
        except ValueError:
            change_trigger = ChangeTrigger.NEW_EVIDENCE

        # Use the matched record's topic_key to keep the chain consistent
        # even if the LLM generates a slightly different normalization
        record = DecisionRecord(
            topic_key=matched["topic_key"],
            claim=candidate["claim"],
            reasoning=candidate["reasoning"],
            evidence=candidate.get("evidence", ["input text"]),
            confidence=float(candidate.get("confidence", 0.5)),
            supersedes=matched["id"],
            change_trigger=change_trigger,
        )
        storage.insert_record(record)
        storage.add_embedding(record.id, record.topic_key, record.claim)

        return {
            **state,
            "final_record": record.model_dump(mode="json"),
            "status": "stored_revision",
            "message": (
                f"Stored revision on '{record.topic_key}' — "
                f"supersedes {matched['id'][:8]}... "
                f"(trigger: {change_trigger.value})"
            ),
        }

    # Fallback: shouldn't reach here
    return {
        **state,
        "status": "rejected",
        "message": "Unexpected state in store_node",
    }


# ──────────────────────────────────────────────
#  Routing logic
# ──────────────────────────────────────────────

def should_diff(state: PipelineState) -> str:
    """Route: if we have a match, go to diff; otherwise go to store."""
    if state.get("status") == "rejected":
        return "store"
    if state.get("matched_record") is not None:
        return "diff"
    return "store"


# ──────────────────────────────────────────────
#  Build the graph
# ──────────────────────────────────────────────

def build_pipeline() -> StateGraph:
    """
    Build the LangGraph pipeline:
    
        extract → match → [diff if matched] → store
    """
    graph = StateGraph(PipelineState)

    # Add nodes
    graph.add_node("extract", extract_node)
    graph.add_node("match", match_node)
    graph.add_node("diff", diff_node)
    graph.add_node("store", store_node)

    # Add edges
    graph.set_entry_point("extract")
    graph.add_edge("extract", "match")
    graph.add_conditional_edges("match", should_diff, {"diff": "diff", "store": "store"})
    graph.add_edge("diff", "store")
    graph.add_edge("store", END)

    return graph.compile()


# Module-level compiled pipeline
pipeline = build_pipeline()


async def run_pipeline(raw_input: str) -> PipelineState:
    """Run the full ingestion pipeline on raw text input."""
    initial_state: PipelineState = {
        "raw_input": raw_input,
        "candidate": None,
        "matched_record": None,
        "diff_result": None,
        "final_record": None,
        "status": "pending",
        "message": "",
    }

    result = await pipeline.ainvoke(initial_state)
    return result
