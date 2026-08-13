# Decision Provenance Agent

**Not just "what happened" — "why we changed our minds," as a first-class, queryable object.**

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-Pipeline-orange.svg)](https://github.com/langchain-ai/langgraph)
[![Gemini](https://img.shields.io/badge/Gemini-2.5_Flash-purple.svg)](https://ai.google.dev)

---

## The Problem

Every RAG system, every memory layer, every knowledge base answers the same question well:

> *"What is the current state of X?"*

But they all fail at:

> *"Why did we move from A to B?"*
> *"What did we used to think, and what changed our minds?"*

Because the **reasoning that connected two states was never captured** — only the states themselves were stored, and each new fact silently overwrites or sits beside the last.

## The Solution

This agent treats every stored item as a **decision record with lineage**, not a flat fact.

```
Record v1: "Using Postgres" (reason: team familiarity)
    ↓ superseded by (trigger: new evidence)
Record v2: "Using Postgres with read replicas" (reason: load test showed bottleneck)
    ↓ superseded by (trigger: constraint change)
Record v3: "Migrating to CockroachDB" (reason: multi-region requirement)
```

**Two query modes:**
- `?mode=current` → "What's the decision NOW?" → Returns Record v3
- `?mode=provenance` → "WHY did this change?" → Returns the full chain with triggers

---

## Quick Start

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env and set your GOOGLE_API_KEY
```

### 3. Run

```bash
uvicorn app.main:app --reload
```

### 4. Try it

```bash
# Ingest a decision
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"text": "We decided to use Postgres for the user service. Team is familiar with it."}'

# Ingest a revised decision
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"text": "After load testing, we are switching to Postgres with read replicas. Single instance cannot handle projected traffic."}'

# Query current state
curl http://localhost:8000/query/database_choice?mode=current

# Query provenance (WHY it changed)
curl http://localhost:8000/query/database_choice?mode=provenance
```

Or run the interactive demo:
```bash
python demo/demo_seed.py
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/ingest` | Ingest raw text through the decision pipeline |
| `GET` | `/query/{topic_key}?mode=current` | Latest non-superseded decision |
| `GET` | `/query/{topic_key}?mode=provenance` | Full decision chain with change triggers |
| `GET` | `/topics` | List all tracked decision topics |
| `GET` | `/health` | Health check |

---

## How It Works

```
Raw Text → [Extract] → [Similarity Match] → [Diff & Classify] → [Validate] → [Store]
                              ↓ no match                              ↓
                         Store as new                          Store as revision
                                                              (with change trigger)
```

### Pipeline Stages

1. **Extract** — Gemini 2.5 Flash extracts structured decision data (topic, claim, reasoning, evidence, confidence)
2. **Similarity Match** — ChromaDB vector search finds existing decisions on the same topic
3. **Diff & Classify** — If a match exists, Gemini classifies whether the decision *actually* changed and categorizes the trigger
4. **Validate** — Enforces trust rules:
   - No claim without evidence
   - No revision without a stated reason
5. **Store** — Writes to SQLite (chain) + ChromaDB (vectors). Old records are never deleted.

### Change Triggers

Every revision must classify WHY it happened:
- `new evidence` — New information changed the conclusion
- `correction` — Previous conclusion was wrong
- `constraint change` — External constraints changed (budget, timeline, requirements)

---

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| LLM | Gemini 2.5 Flash | Fast, cheap, reliable structured output |
| Pipeline | LangGraph | Clean state machine for multi-stage processing |
| Vector Search | ChromaDB | Zero-setup, pip-installable, no Docker needed |
| Storage | SQLite | Lightweight, embedded, perfect for decision chains |
| API | FastAPI | Async, auto-docs, production-ready |
| Validation | Pydantic v2 | Schema-level enforcement of trust rules |

---

## What Makes This Different

This is **memory infrastructure** — a layer other agents could plug into, not a task-executor.

- Not another validator-on-top-of-extraction
- Not another RAG pipeline
- **A trust layer underneath agent systems** that captures the one thing every other memory store loses: *why things changed*

---

## License

MIT
