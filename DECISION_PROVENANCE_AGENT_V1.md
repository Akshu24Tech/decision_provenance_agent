# Decision Provenance Agent — Version 1.0 Guide

> **"Hermes knowing what happened is step one. Knowing *why we changed our minds 3 weeks later* is where most memory architectures collapse."**  
> — *Akshu Grewal (The spark behind this project)*

---

## 1. The Origin Story: How & Why This Agent Was Created

### The LinkedIn Dialogue That Started It All
This project was born out of a conversation on LinkedIn between **Jack Roberts** (Top-100 UK Entrepreneur, Teddy AI) and **Akshu Grewal** (Agentic AI Engineer):

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Jack Roberts:                                                                                    │
│ "Hermes knows you. It doesn't know your world... The fix: build a separate,                      │
│  self-improving knowledge wiki (based on Andrej Karpathy's LLM wiki concept) that Hermes        │
│  can query on demand. New information gets fact-checked and contradictions get flagged..."       │
│                                                                                                  │
│ ↳ Akshu Grewal:                                                                                  │
│   "Hermes knowing what happened is step one. Knowing why we changed our minds 3 weeks later      │
│    is where most memory architectures collapse."                                                 │
│                                                                                                  │
│ ↳ Jack Roberts:                                                                                  │
│   "You can learn how to build better AI memory and knowledge systems here..."                    │
│                                                                                                  │
│ ↳ Akshu Grewal:                                                                                  │
│   "Appreciate the share! Trying to crack the 'why we changed our minds' part myself,            │
│    building it hands-on to learn the fundamentals."                                              │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### The Missing Piece in Modern AI Memory
Most AI memory architectures (Karpathy-style LLM wikis, MemGPT, standard RAG, or GraphRAG) solve for:
- Storing current facts.
- Deduplication.
- Flagging direct factual contradictions.

**Where they all collapse:**
When an engineering team, company, or agent intentionally changes direction:
- *Week 1:* "We are using Postgres because our team knows it well and setup is fast."
- *Week 4:* "We are switching to Postgres with read replicas because load tests showed a 3x read bottleneck."
- *Week 8:* "We are migrating to CockroachDB due to a new multi-region compliance mandate."

A flat knowledge store sees this as a conflict to resolve, a fact to overwrite, or three disconnected chunks with cosine similarity. **The rationale connecting state A to state B is permanently erased.**

**Decision Provenance Agent** was built to turn the *"why we changed our minds"* problem into a **first-class, queryable, linked memory architecture**.

---

## 2. What Problem We Solved

| Traditional Agent Memory / RAG | Decision Provenance Agent v1.0 |
|---|---|
| **Fact-centric**: Treats knowledge as static statements. | **Lineage-centric**: Treats knowledge as decision records with explicit parent-child lineage. |
| **Silent Overwrites**: State B silently replaces State A. | **Append-Only Chains**: Old decisions are never erased; new decisions link to the exact ID they supersede. |
| **Blind to Causality**: Cannot explain why a decision changed. | **Causal Triggers**: Every revision enforces classification (`new evidence`, `correction`, `constraint change`). |
| **Prone to Hallucinations**: Stores any statement without proof. | **Pydantic Validation**: Strictly rejects claims that lack verifiable evidence. |
| **Noisy Restatements**: Re-indexing the same opinion pollutes the vector index. | **Semantic Diffing**: Gemini classifies whether a decision actually changed or was merely restated. |

---

## 3. How It Works: System Architecture

### The 4-Stage LangGraph State Machine

When text is ingested, it flows through an autonomous, deterministic pipeline compiled in **LangGraph**:

```
                              Raw Text Input
                                    │
                                    ▼
                             ┌──────────────┐
                             │ Extract Node │
                             └──────────────┘
                                    │ (Gemini 2.5 Flash structured output:
                                    │  topic_key, claim, reasoning, evidence, confidence)
                                    ▼
                             ┌──────────────┐
                             │  Match Node  │
                             └──────────────┘
                                    │ (ChromaDB vector search for existing topic & claim)
                                    │
                  ┌─────────────────┴─────────────────┐
                  │                                   │
        [No Prior Record Found]             [Existing Record Found]
                  │                                   │
                  │                                   ▼
                  │                            ┌──────────────┐
                  │                            │  Diff Node   │
                  │                            └──────────────┘
                  │                                   │ (Gemini diffs old vs new)
                  │                         ┌─────────┴─────────┐
                  │                         │                   │
                  │                [Decision Changed]   [Same Decision Restated]
                  │                         │                   │
                  ▼                         ▼                   ▼
         ┌─────────────────────────────────────┐         ┌──────────────┐
         │             Store Node              │         │   DEDUPED    │
         │  - New Record: root node            │         │ (Not stored) │
         │  - Revision: supersedes parent ID   │         └──────────────┘
         │  - Change trigger logged            │
         └─────────────────────────────────────┘
```

### Storage Layer Design
- **SQLite (`decisions.db`)**: The immutable source of truth. Manages the linked list (`FOREIGN KEY (supersedes) REFERENCES decision_records(id)`).
- **ChromaDB (`./chroma_data`)**: Vector similarity index using `models/gemini-embedding-001` to match incoming concepts to existing decision chains.

---

## 4. Core Data Contracts & Validation Rules

### Schema: `DecisionRecord` ([app/models.py](file:///e:/Ghost%20OS/projects/decision_provenance_agent/app/models.py))

```python
class ChangeTrigger(str, Enum):
    NEW_EVIDENCE = "new evidence"       # Benchmarks, metrics, customer data
    CORRECTION = "correction"           # Prior assumption/logic was flawed
    CONSTRAINT_CHANGE = "constraint change" # Budget, timeline, scale, compliance

class DecisionRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic_key: str                      # E.g., 'database_choice', 'auth_strategy'
    claim: str                          # Single clear sentence stating the decision
    reasoning: str                      # Why this conclusion was reached
    evidence: list[str] = Field(min_length=1) # Traceable sources / inputs
    confidence: float                   # 0.0 to 1.0 score
    timestamp: datetime                 # UTC creation timestamp
    supersedes: Optional[str] = None    # ID of the previous record being replaced
    change_trigger: Optional[ChangeTrigger] = None # Required if supersedes is set
```

### Invariant Rules
1. **No Claim Without Evidence**: An extraction is rejected if `evidence` is empty (`min_length=1`).
2. **No Revision Without Stated Cause**: If `supersedes` is set, `change_trigger` is strictly mandatory.
3. **Bounded Confidence**: Confidence scores must fall strictly within `[0.0, 1.0]`.

---

## 5. Step-by-Step Installation & Setup

### 1. Prerequisites
- **Python 3.11+**
- **Google Gemini API Key** (Get free at [Google AI Studio](https://aistudio.google.com/apikey))

### 2. Virtual Environment Setup
```bash
# Navigate to the workspace
cd "e:/Ghost OS/projects/decision_provenance_agent"

# Create virtual environment
python -m venv .venv

# Activate environment:
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (cmd):
.venv\Scripts\activate.bat
# Linux/macOS:
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment (`.env`)
Create a `.env` file in the root directory:
```env
GOOGLE_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
EMBEDDING_MODEL=models/gemini-embedding-001
SIMILARITY_THRESHOLD=0.78
DB_PATH=./decisions.db
CHROMA_PERSIST_DIR=./chroma_data
CHROMA_COLLECTION=decision_records
```

---

## 6. How to Use the Agent (Version 1.0)

### Method A: Start the FastAPI Server
```bash
uvicorn app.main:app --reload --port 8000
```
- API Base URL: `http://localhost:8000`
- Interactive Swagger UI: `http://localhost:8000/docs`
- ReDoc UI: `http://localhost:8000/redoc`

---

### Method B: Run the Interactive Demo
The project includes a turnkey simulation ([demo/demo_seed.py](file:///e:/Ghost%20OS/projects/decision_provenance_agent/demo/demo_seed.py)) showing initial ingestion, an evolution 3 weeks later, and current vs. provenance queries:

```bash
python demo/demo_seed.py
```

---

### Method C: Run the Test Suite
Validate the models, LangGraph pipeline, and storage layers:
```bash
pytest
```

---

## 7. API Reference & Practical Examples

### 1. `POST /ingest` — Ingest Decision Text

#### Example 1: Ingest Initial Decision
```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "text": "We have decided to use Postgres for the user service. The team is familiar with it, most of our developers have experience with PostgreSQL, and it is simple to set up for our current scale. Decision made during the architecture review meeting on January 15th."
  }'
```

**Response (`stored_new`):**
```json
{
  "status": "stored_new",
  "record": {
    "id": "3b29db42-995a-4e20-80a5-81fa0e72dd89",
    "topic_key": "database_choice",
    "claim": "PostgreSQL will be used as the database for the user service.",
    "reasoning": "The team has existing familiarity and it simplifies setup for current scale.",
    "evidence": [
      "Architecture review meeting on January 15th",
      "Developer experience with PostgreSQL"
    ],
    "confidence": 0.9,
    "timestamp": "2026-08-15T18:00:00Z",
    "supersedes": null,
    "change_trigger": null
  },
  "message": "Stored new decision on 'database_choice'"
}
```

---

#### Example 2: Ingest Decision Revision (3 Weeks Later)
```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "text": "After running load tests for two weeks, a single Postgres instance cannot handle projected Q3 traffic. We are switching to Postgres with read replicas based on load test report showing 3x read volume."
  }'
```

**Response (`stored_revision`):**
```json
{
  "status": "stored_revision",
  "record": {
    "id": "c19b8852-5a21-420a-8bf8-2a1e0dc45070",
    "topic_key": "database_choice",
    "claim": "Postgres with read replicas will be deployed for the user service.",
    "reasoning": "Load testing indicated single-node capacity limits against projected Q3 read load.",
    "evidence": [
      "Two-week load testing report showing 3x expected read query volume"
    ],
    "confidence": 0.95,
    "timestamp": "2026-08-15T18:05:00Z",
    "supersedes": "3b29db42-995a-4e20-80a5-81fa0e72dd89",
    "change_trigger": "new evidence"
  },
  "message": "Stored revision on 'database_choice' - supersedes 3b29db42... (trigger: new evidence)"
}
```

---

#### Example 3: Ingest Duplicate / Restatement
```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Reminder: We are deploying Postgres with read replicas because of the read traffic load tests."
  }'
```

**Response (`deduped`):**
```json
{
  "status": "deduped",
  "record": null,
  "message": "Same decision restated - not stored. Re-affirms existing read replica strategy."
}
```

---

### 2. `GET /query/{topic_key}?mode=current` — What is true NOW?

```bash
curl http://localhost:8000/query/database_choice?mode=current
```

**Response:**
```json
{
  "topic_key": "database_choice",
  "mode": "current",
  "records": [
    {
      "id": "c19b8852-5a21-420a-8bf8-2a1e0dc45070",
      "topic_key": "database_choice",
      "claim": "Postgres with read replicas will be deployed for the user service.",
      "reasoning": "Load testing indicated single-node capacity limits against projected Q3 read load.",
      "evidence": ["Two-week load testing report showing 3x expected read query volume"],
      "confidence": 0.95,
      "timestamp": "2026-08-15T18:05:00Z",
      "supersedes": "3b29db42-995a-4e20-80a5-81fa0e72dd89",
      "change_trigger": "new evidence"
    }
  ],
  "total_revisions": 2
}
```

---

### 3. `GET /query/{topic_key}?mode=provenance` — WHY did it change?

```bash
curl http://localhost:8000/query/database_choice?mode=provenance
```

**Response:**
```json
{
  "topic_key": "database_choice",
  "mode": "provenance",
  "records": [
    {
      "id": "3b29db42-995a-4e20-80a5-81fa0e72dd89",
      "topic_key": "database_choice",
      "claim": "PostgreSQL will be used as the database for the user service.",
      "reasoning": "The team has existing familiarity and it simplifies setup for current scale.",
      "evidence": ["Architecture review meeting on January 15th"],
      "confidence": 0.9,
      "timestamp": "2026-08-15T18:00:00Z",
      "supersedes": null,
      "change_trigger": null
    },
    {
      "id": "c19b8852-5a21-420a-8bf8-2a1e0dc45070",
      "topic_key": "database_choice",
      "claim": "Postgres with read replicas will be deployed for the user service.",
      "reasoning": "Load testing indicated single-node capacity limits against projected Q3 read load.",
      "evidence": ["Two-week load testing report showing 3x expected read query volume"],
      "confidence": 0.95,
      "timestamp": "2026-08-15T18:05:00Z",
      "supersedes": "3b29db42-995a-4e20-80a5-81fa0e72dd89",
      "change_trigger": "new evidence"
    }
  ],
  "total_revisions": 2
}
```

---

### 4. `GET /topics` — List All Tracked Topics

```bash
curl http://localhost:8000/topics
```

**Response:**
```json
{
  "topics": [
    "auth_strategy",
    "database_choice",
    "deployment_infrastructure"
  ],
  "total": 3
}
```

---

### 5. `GET /health` — Health Check

```bash
curl http://localhost:8000/health
```

---

## 8. Python SDK / Client Integration

Embed this provenance engine into your other AI agents or backend services:

```python
import httpx

class DecisionProvenanceAgentClient:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.client = httpx.Client(base_url=base_url, timeout=30.0)

    def record_decision(self, text: str) -> dict:
        """Pass any raw meeting note, commit message, or agent output."""
        res = self.client.post("/ingest", json={"text": text})
        res.raise_for_status()
        return res.json()

    def get_current_truth(self, topic_key: str) -> dict:
        """Returns the active non-superseded decision."""
        res = self.client.get(f"/query/{topic_key}?mode=current")
        res.raise_for_status()
        return res.json()

    def explain_evolution(self, topic_key: str) -> list[dict]:
        """Returns the complete lineage explaining WHY the decision changed."""
        res = self.client.get(f"/query/{topic_key}?mode=provenance")
        res.raise_for_status()
        return res.json().get("records", [])

# Example usage:
if __name__ == "__main__":
    dp = DecisionProvenanceAgentClient()
    
    # Ingesting a new architectural direction
    dp.record_decision("We are migrating auth to Auth0 due to SOC2 compliance deadlines.")
    
    # Querying the why
    history = dp.explain_evolution("auth_strategy")
    for step in history:
        print(f"[{step.get('change_trigger') or 'INITIAL'}] -> {step['claim']}")
```

---

## 9. File Tree & Codebase Map

| Path | Purpose |
|---|---|
| [app/main.py](file:///e:/Ghost%20OS/projects/decision_provenance_agent/app/main.py) | FastAPI app entrypoint, CORS, routes (`/ingest`, `/query`, `/topics`, `/health`). |
| [app/graph.py](file:///e:/Ghost%20OS/projects/decision_provenance_agent/app/graph.py) | LangGraph state graph pipeline (`extract` $\rightarrow$ `match` $\rightarrow$ `diff` $\rightarrow$ `store`). |
| [app/models.py](file:///e:/Ghost%20OS/projects/decision_provenance_agent/app/models.py) | Pydantic data contracts, `DecisionRecord`, `ChangeTrigger`, and validator invariants. |
| [app/prompts.py](file:///e:/Ghost%20OS/projects/decision_provenance_agent/app/prompts.py) | Gemini structured output schemas & prompts for extraction and diffing. |
| [app/storage.py](file:///e:/Ghost%20OS/projects/decision_provenance_agent/app/storage.py) | SQLite (relational lineage chains) + ChromaDB (vector matching). |
| [app/config.py](file:///e:/Ghost%20OS/projects/decision_provenance_agent/app/config.py) | Centralized configuration and `.env` loader. |
| [demo/demo_seed.py](file:///e:/Ghost%20OS/projects/decision_provenance_agent/demo/demo_seed.py) | End-to-end runnable demonstration script. |
| [tests/](file:///e:/Ghost%20OS/projects/decision_provenance_agent/tests) | Pytest test suite covering models, pipeline flow, and storage logic. |
