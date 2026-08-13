# Decision Provenance Agent — Starter Kit

## 1. Project Structure

```
decision-provenance-agent/
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI entrypoint
│   ├── models.py              # Pydantic: DecisionRecord
│   ├── graph.py                # LangGraph pipeline (ingest → match → diff → store)
│   ├── storage.py              # SQLite (record chains) + Qdrant (vectors) I/O
│   ├── prompts.py              # LLM prompt templates (extraction + diff)
│   └── config.py               # env vars, thresholds
├── tests/
│   └── test_pipeline.py
├── demo/
│   └── demo_seed.py            # seeds the Postgres example from the demo script
├── .env.example
├── requirements.txt
└── README.md                   # (already have this)
```

## 2. requirements.txt

```
fastapi
uvicorn[standard]
langgraph
langchain-anthropic
qdrant-client
pydantic
python-dotenv
sentence-transformers   # or use an API-based embedding instead if you don't want local inference
```

## 3. .env.example

```
ANTHROPIC_API_KEY=
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=decision_records
SIMILARITY_THRESHOLD=0.78
DB_PATH=./decisions.db
```

## 4. models.py — Pydantic Schema

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from enum import Enum

class ChangeTrigger(str, Enum):
    NEW_EVIDENCE = "new evidence"
    CORRECTION = "correction"
    CONSTRAINT_CHANGE = "constraint change"

class DecisionRecord(BaseModel):
    id: str
    topic_key: str
    claim: str
    reasoning: str
    evidence: list[str] = Field(min_length=1)   # enforce: no claim without evidence
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: datetime
    supersedes: Optional[str] = None
    change_trigger: Optional[ChangeTrigger] = None

    class Config:
        # enforce: if supersedes is set, change_trigger must be set too
        pass  # add a @model_validator for this rule
```

Add a `@model_validator(mode="after")` that raises if `supersedes is not None and change_trigger is None` — this is your validator-layer rule from the README, encode it directly in the schema so it can't be bypassed.

## 5. SQLite Schema (storage.py)

```sql
CREATE TABLE decision_records (
    id TEXT PRIMARY KEY,
    topic_key TEXT NOT NULL,
    claim TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    evidence TEXT NOT NULL,        -- JSON array as text
    confidence REAL NOT NULL,
    timestamp TEXT NOT NULL,
    supersedes TEXT,
    change_trigger TEXT,
    FOREIGN KEY (supersedes) REFERENCES decision_records(id)
);
CREATE INDEX idx_topic_key ON decision_records(topic_key);
```

## 6. Qdrant Collection Config

```python
from qdrant_client.models import VectorParams, Distance

client.create_collection(
    collection_name="decision_records",
    vectors_config=VectorParams(size=384, distance=Distance.COSINE)  # 384 if using bge-small; check your model's dim
)
# payload per point: {"record_id": ..., "topic_key": ...}
```

## 7. Prompt Templates (prompts.py)

**Extraction prompt** (Stage 1 — turns raw input into a candidate claim):
```
Given this input, extract:
1. topic_key: a short, normalized label for what this is about (e.g. "database_choice", not "the postgres thing")
2. claim: the conclusion/decision stated, one sentence
3. reasoning: why this conclusion, one to two sentences
4. confidence: 0-1, how certain the source seems

Input: {raw_input}

Respond ONLY as JSON: {"topic_key": "", "claim": "", "reasoning": "", "confidence": 0.0}
```

**Diff prompt** (Stage 3 — compares new claim against matched existing record):
```
Existing decision:
Claim: {old_claim}
Reasoning: {old_reasoning}

New input:
Claim: {new_claim}
Reasoning: {new_reasoning}

Did the conclusion actually change, or is this the same decision restated?
If changed, classify the trigger as exactly one of: "new evidence", "correction", "constraint change".
If not genuinely changed, respond with changed: false so it can be deduped instead of stored.

Respond ONLY as JSON: {"changed": true/false, "change_trigger": "" or null, "diff_summary": ""}
```

## 8. Build Order (do this, in this order)

1. `models.py` schema + validator rule — get this right first, everything depends on it.
2. `storage.py` — SQLite table + basic insert/query, no Qdrant yet. Test with hardcoded records.
3. Wire up embeddings + Qdrant similarity search — test that matching actually finds related topics.
4. `prompts.py` extraction call — raw text in, DecisionRecord out.
5. `prompts.py` diff call — only after 2-4 work independently.
6. `graph.py` — wire the above into a LangGraph flow (ingest → match → diff → store).
7. `main.py` — two endpoints: `POST /ingest`, `GET /query/{topic_key}?mode=current|provenance`.
8. `demo/demo_seed.py` — seed the Postgres example, confirm the provenance query returns the full chain with triggers.

Stop and demo after step 8. Don't add anything beyond this for the internship submission — no auth, no UI, no multi-tenant support. A working core loop with one working demo query beats a half-built feature-rich version.
