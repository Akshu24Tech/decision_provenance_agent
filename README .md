# Decision Provenance Agent

**Not just "what happened" — "why we changed our minds," as a first-class, queryable object.**

Most memory layers store facts as flat, overwritten state. This agent stores *decisions* — claim, reasoning, evidence, and every revision — so an agent (or a human) can ask not just "what's true now" but "why did this change, and when, and because of what."

---

## 1. Problem Statement

Standard RAG/memory stacks answer "what is the current state of X" well. They fail at "why did we move from A to B" because the reasoning that connected two states was never captured as a distinct object — only the states themselves were stored, and each new fact silently overwrites or sits beside the last.

This agent treats every stored item as a **decision record** with a lineage, not a flat fact.

---

## 2. Core Data Model

```python
class DecisionRecord(BaseModel):
    id: str
    topic_key: str              # normalized topic/entity this decision is about
    claim: str                  # the conclusion/decision itself
    reasoning: str               # why this conclusion was reached
    evidence: list[str]          # supporting sources/inputs (ids or text spans)
    confidence: float            # 0-1, self-reported or derived
    timestamp: datetime
    supersedes: str | None       # id of the previous record this replaces, if any
    change_trigger: str | None   # why it changed: "new evidence" | "correction" | "constraint change" | None for first record
```

Records form a **linked chain per topic**, not a single row that gets overwritten.

---

## 3. Pipeline Stages

### Stage 1 — Ingest & Normalize
- New input arrives (text, doc, message, tool output).
- Extract candidate claim(s) + reasoning via LLM (structured output, JSON schema above).
- Normalize `topic_key` (canonicalize entity/topic name so future related inputs match).

### Stage 2 — Similarity Match
- Embed `topic_key` + `claim` (use existing embedding stack — bge / Qdrant, per prior Knowledge Engine research).
- Search for existing `DecisionRecord`s on the same topic above a similarity threshold.
- No match → store as new record, `supersedes = None`.
- Match found → go to Stage 3.

### Stage 3 — Diff & Trigger Detection
- Compare new claim/reasoning against the matched existing record.
- LLM diff step answers: *did the conclusion change? did the reasoning change even if the conclusion didn't? what triggered it?*
- Classify `change_trigger` (new evidence / correction of prior error / changed constraint / no real change — dedupe instead of storing).
- If genuinely new: store new record with `supersedes = <old id>`. Old record is never deleted — it's marked superseded, not erased.

### Stage 4 — Query Interface
Two distinct query modes, deliberately separated:
- **Current-state query** ("what's the status of X now") → walk each topic's chain to the newest, non-superseded record, return the claim.
- **Provenance query** ("why did this change", "what did we used to think") → walk the full chain for the topic, return each record with its `change_trigger`, in order — this is the part flat memory stores can't answer at all.

### Stage 5 — Validator Layer (your trust-layer signature)
Before any record is written:
- Reject if `evidence` is empty (no claim gets stored without a traceable source).
- Reject if `change_trigger` is missing when `supersedes` is set (a change without a stated reason is the exact failure mode this agent exists to prevent).
- Flag low-confidence diffs for human review instead of auto-writing (same Review Gate pattern as Voice HITL).

---

## 4. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Orchestration | LangGraph | Matches your existing stack; stages map cleanly to graph nodes |
| Embeddings/retrieval | bge embeddings + Qdrant | Already scoped in your Knowledge Engine research |
| Schema/validation | Pydantic | Enforces the DecisionRecord contract, rejects malformed writes |
| Diff reasoning | Claude (structured JSON output) | Single-purpose call, cheap, needs to be reliable not creative |
| Storage | Qdrant (vectors) + SQLite (record chain/metadata) | Mirrors your CrowdWisdomTrading kanban pattern — proven approach for you already |
| Interface | FastAPI (reuse Voice HITL backend pattern) | You already have a working FastAPI + Review Gate setup to adapt |

---

## 5. Build Phases

**Phase 1 — Core loop (MVP, ~2-3 days)**
- DecisionRecord schema + SQLite storage
- Ingest → embed → similarity match → store (no diff logic yet, just dedupe/append)
- Basic current-state query working end-to-end

**Phase 2 — Diff & provenance (~2-3 days)**
- LLM diff step + change_trigger classification
- Provenance query mode (walk the chain)
- Validator layer (reject unsupported/untriggered writes)

**Phase 3 — Polish for submission (~1-2 days)**
- FastAPI endpoints (ingest, current-state query, provenance query)
- Small demo dataset showing a real "changed our minds" chain (3+ revisions on one topic)
- README/demo script showing the exact quote's problem solved live

---

## 6. Demo Script (for review/marketplace listing)

1. Ingest: "We're using Postgres for this service." (reasoning: simplicity, team familiarity)
2. Ingest 3 "weeks" later (simulated timestamp): "We're using Postgres with read replicas." (reasoning: load testing showed single-instance bottleneck)
3. Query current state → returns record #2.
4. Query provenance ("why did we change the database decision?") → returns both records, the diff, and the trigger ("new evidence: load test results"), in order.

This is the exact scenario from the quote — the agent should visibly do the thing flat memory can't.

---

## 7. What Makes This Different From Your Other Submissions

Not another validator-on-top-of-extraction (finagent, invoice checker). This is **memory infrastructure** — a layer other agents could plug into, not a task-executor. Positions you as building the trust layer *underneath* agent systems, not just around individual tasks.
