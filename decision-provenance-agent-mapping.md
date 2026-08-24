# Graph Engineering → Decision Provenance Agent (Mapping Notes)

Simple notes connecting the paper's concepts to your project. Stack: LangGraph + SQLite + ChromaDB + FastAPI.

---

## 1. Where You Already Fit

Paper's core distinction (Section V.A):

| | Commit DAG | Knowledge Graph |
|---|---|---|
| Answers | What changed? Lineage? | What exists? How related? |

**Your agent does both at once.** SQLite = your lineage/state layer (like the commit DAG — tracks *what changed, when, why*). ChromaDB = your semantic/knowledge layer (retrieval over facts/context). That combo is literally the "production system connects the two" idea from the paper.

Your core pitch — tracing **why decisions changed, not just what happened** — maps directly to the paper's **Grounding Layer** concept (Section V.2): a claim isn't just stated, it's checked against supporting evidence edges. You're doing provenance-mode querying = walking that evidence chain.

---

## 2. Build Path — Where You Stand

From Table (Section 6):

| Stage | Exit Criterion | You? |
|---|---|---|
| Reflective loop | Measured quality improvement | ✅ likely done |
| Tool use | Tool reduces known error class | ✅ done |
| Planning | Variable tasks complete | ✅ (LangGraph = your planner/orchestrator) |
| Multi-agent | Role split beats single agent | Check — do you have distinct roles or one agent doing everything? |
| **Persistent graph** | **Cross-session queries work** | **This is your core claim — worth stress-testing** |
| Swarm workflow | Wall-clock gain, no quality loss | Not needed yet, skip |

You're sitting right at "Persistent graph" stage — which is the stage most people skip straight past. That's your differentiation.

---

## 3. Concepts Worth Stealing Directly

**Four invariants for graph writes** (Appendix) — check your system against these:
1. Every claim has a source, or is marked inference.
2. Every artifact has an authoring run + version.
3. Every evaluation identifies a rubric.
4. Every superseded object remains addressable (old decisions stay queryable, not deleted).

If your SQLite schema doesn't already track "superseded → still addressable," that's a quick, high-value add — it's exactly what "why did the decision change" needs.

**Grounding layer feedback format** — instead of vague "this looks wrong," structure evaluator output like:
```json
{
  "decision": "revise",
  "claim": "...",
  "reason": "No supported path from X to Y",
  "required_evidence": ["..."]
}
```
Useful if you add any self-evaluation step later.

---

## 4. Positioning Language (for LinkedIn / pitch)

- "Commit DAG remembers what changed. Knowledge graph remembers what's true. My agent connects both — that's provenance."
- "The graph amplifies builder judgment" (Section IX.H) — good line to show you understand the *responsibility* side, not just the tech.
- "The phrase the agent forgets, the graph does not" — fits your "why decisions changed over time" angle well.

---

## 5. One Thing to Watch (Limitation, Section IX)

**Entity resolution errors are catastrophic, not local** — if your system ever merges/links two decisions or entities incorrectly, every downstream trace-query inherits that error. Worth having a way to reverse a bad link (keep aliases/confidence/source of merge, per Section 4.4 in main notes).

---

*Keep this file lightweight — update only when the agent architecture actually changes.*
