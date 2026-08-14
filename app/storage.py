"""
Storage layer for Decision Provenance Agent.

Two sub-systems:
  - SQLite: record chains & metadata (the linked-list of decisions)
  - ChromaDB: vector similarity search (find related topics)

SQLite is the source of truth. ChromaDB is for matching only.
"""

import json
import sqlite3
from typing import Optional

import chromadb
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.config import settings
from app.models import DecisionRecord, ChangeTrigger


# ──────────────────────────────────────────────
#  SQLite - Record chain storage
# ──────────────────────────────────────────────

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS decision_records (
    id TEXT PRIMARY KEY,
    topic_key TEXT NOT NULL,
    claim TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    evidence TEXT NOT NULL,
    confidence REAL NOT NULL,
    timestamp TEXT NOT NULL,
    supersedes TEXT,
    change_trigger TEXT,
    FOREIGN KEY (supersedes) REFERENCES decision_records(id)
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_topic_key ON decision_records(topic_key);
"""


def get_db_connection() -> sqlite3.Connection:
    """Get a SQLite connection with row factory."""
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create the decision_records table if it doesn't exist."""
    conn = get_db_connection()
    try:
        conn.execute(_CREATE_TABLE)
        conn.execute(_CREATE_INDEX)
        conn.commit()
    finally:
        conn.close()


def _row_to_record(row: sqlite3.Row) -> DecisionRecord:
    """Convert a SQLite row to a DecisionRecord."""
    return DecisionRecord(
        id=row["id"],
        topic_key=row["topic_key"],
        claim=row["claim"],
        reasoning=row["reasoning"],
        evidence=json.loads(row["evidence"]),
        confidence=row["confidence"],
        timestamp=row["timestamp"],
        supersedes=row["supersedes"],
        change_trigger=ChangeTrigger(row["change_trigger"]) if row["change_trigger"] else None,
    )


def insert_record(record: DecisionRecord) -> None:
    """Insert a DecisionRecord into SQLite."""
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO decision_records 
            (id, topic_key, claim, reasoning, evidence, confidence, timestamp, supersedes, change_trigger)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.topic_key,
                record.claim,
                record.reasoning,
                json.dumps(record.evidence),
                record.confidence,
                record.timestamp.isoformat(),
                record.supersedes,
                record.change_trigger.value if record.change_trigger else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_record_by_id(record_id: str) -> Optional[DecisionRecord]:
    """Fetch a single record by ID."""
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM decision_records WHERE id = ?", (record_id,)
        )
        row = cursor.fetchone()
        return _row_to_record(row) if row else None
    finally:
        conn.close()


def get_current_record(topic_key: str) -> Optional[DecisionRecord]:
    """
    Get the latest (non-superseded) record for a topic.
    
    Walk the chain: find the record that no other record supersedes.
    """
    conn = get_db_connection()
    try:
        # Find records for this topic that are NOT superseded by any other record
        cursor = conn.execute(
            """
            SELECT dr.* FROM decision_records dr
            WHERE dr.topic_key = ?
            AND dr.id NOT IN (
                SELECT supersedes FROM decision_records 
                WHERE supersedes IS NOT NULL AND topic_key = ?
            )
            ORDER BY dr.timestamp DESC
            LIMIT 1
            """,
            (topic_key, topic_key),
        )
        row = cursor.fetchone()
        return _row_to_record(row) if row else None
    finally:
        conn.close()


def get_provenance_chain(topic_key: str) -> list[DecisionRecord]:
    """
    Get the full decision chain for a topic, oldest first.
    
    This is the query that flat memory stores can't answer.
    Returns every revision with its change_trigger, in chronological order.
    """
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            """
            SELECT * FROM decision_records 
            WHERE topic_key = ?
            ORDER BY timestamp ASC
            """,
            (topic_key,),
        )
        return [_row_to_record(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def list_topics() -> list[str]:
    """Return all unique topic_keys."""
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT DISTINCT topic_key FROM decision_records ORDER BY topic_key"
        )
        return [row["topic_key"] for row in cursor.fetchall()]
    finally:
        conn.close()


# ──────────────────────────────────────────────
#  ChromaDB - Vector similarity search
# ──────────────────────────────────────────────

_chroma_client: Optional[chromadb.PersistentClient] = None
_chroma_collection = None
_embeddings_model: Optional[GoogleGenerativeAIEmbeddings] = None


def _get_embeddings_model() -> GoogleGenerativeAIEmbeddings:
    """Lazily initialize the Gemini embeddings model."""
    global _embeddings_model
    if _embeddings_model is None:
        _embeddings_model = GoogleGenerativeAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            google_api_key=settings.GOOGLE_API_KEY,
        )
    return _embeddings_model


def init_chroma():
    """Initialize ChromaDB persistent client and collection."""
    global _chroma_client, _chroma_collection
    _chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
    _chroma_collection = _chroma_client.get_or_create_collection(
        name=settings.CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    return _chroma_collection


def get_chroma_collection():
    """Get or initialize the ChromaDB collection."""
    global _chroma_collection
    if _chroma_collection is None:
        init_chroma()
    return _chroma_collection


def add_embedding(record_id: str, topic_key: str, claim: str) -> None:
    """Embed topic_key + claim and store in ChromaDB."""
    collection = get_chroma_collection()
    model = _get_embeddings_model()

    text = f"{topic_key}: {claim}"
    embedding = model.embed_query(text)

    collection.add(
        ids=[record_id],
        embeddings=[embedding],
        metadatas=[{"record_id": record_id, "topic_key": topic_key}],
        documents=[text],
    )


def find_similar(
    topic_key: str, claim: str, threshold: Optional[float] = None
) -> list[dict]:
    """
    Find existing records similar to the given topic + claim.
    
    Returns list of {record_id, topic_key, distance, similarity} 
    for matches above the similarity threshold.
    """
    if threshold is None:
        threshold = settings.SIMILARITY_THRESHOLD

    collection = get_chroma_collection()
    model = _get_embeddings_model()

    text = f"{topic_key}: {claim}"
    embedding = model.embed_query(text)

    results = collection.query(
        query_embeddings=[embedding],
        n_results=5,
        include=["metadatas", "distances"],
    )

    matches = []
    if results["ids"] and results["ids"][0]:
        for i, record_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i]
            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            # Convert to similarity: 1 - (distance / 2)
            similarity = 1 - (distance / 2)
            if similarity >= threshold:
                matches.append({
                    "record_id": record_id,
                    "topic_key": results["metadatas"][0][i]["topic_key"],
                    "distance": distance,
                    "similarity": similarity,
                })

    return matches


# ──────────────────────────────────────────────
#  Initialization helper
# ──────────────────────────────────────────────

def init_storage() -> None:
    """Initialize both SQLite and ChromaDB."""
    init_db()
    init_chroma()
