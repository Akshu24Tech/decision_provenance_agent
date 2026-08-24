# Graph Engineering — The Karpathy Loop, Improved 1000x by Itself
### (The Anthropic Playbook) — Extracted Notes

Source: Independent synthesis based on Andrej Karpathy's *autoresearch* / *AgentHub* repos and Anthropic's *Building Effective Agents*, *Dynamic Workflows*, and *Knowledge Graph Construction Cookbook*. Compiled July 2026. Not affiliated with/endorsed by Karpathy or Anthropic.

---

## 1. Core Thesis (Read This First)

Agentic systems evolve through **three stages**:

1. **Vibe coding** — human expresses intent, model writes code.
2. **Agentic engineering** — human specifies, orchestrates, verifies; remains responsible for quality.
3. **Graph engineering** — agents share **durable state** through typed, queryable graphs of work and knowledge.

> **The single most important insight**: the bottleneck is usually not "the next model call." It's **where memory and evaluation live**.

Five architectures, five different bottlenecks they externalize:

| Architecture | Externalizes |
|---|---|
| Loop | Iteration and evaluation |
| Chain | Task order |
| Swarm | Parallel search and role specialization |
| DAG (commit graph) | Experiment lineage |
| Knowledge graph | Shared facts, provenance, cross-session memory |

---

## 2. Karpathy's Loop — "Autoresearch" (Section II)

An agent placed inside an **executable research harness**:

- `prepare.py` — fixed, agent never touches (data prep + eval utils)
- `train.py` — the experimental surface the agent edits
- `program.md` — the natural-language "constitution": process, constraints, metric, logging, autonomy policy

**The Loop:**
```
LOOP FOREVER:
1. Read current train.py and recent history.
2. Propose one motivated change (per program.md).
3. Commit the candidate change.
4. Run training (~5 min).
5. Measure val_bpb and peak memory.
6. If crash: inspect, fix if mechanical, else revert.
7. If val_bpb improves: keep commit. Else: reset.
8. Record result, continue without asking human.
```

**Reported results:** ~700 experiments in 2 days, ~20 retained optimizations (QK norm scaling, value-embedding regularization, AdamW tuning, batch size, depth, embedding LR, RoPE base freq, weight decay, init scale, warmdown). Repo: 86k+ stars, 12.5k forks — read as *evidence the pattern is legible*, not a performance benchmark.

### Why the loop works — 4 conditions (memorize these):
1. **Verifiable output** — training produces a measurable result.
2. **Reversible action** — git reset undoes it.
3. **Short horizon** — 5-min runs = frequent feedback.
4. **Bounded environment** — repo narrows the action space.

### Reusable pseudocode — the "Ratchet Loop":
```python
def ratchet_loop(inspect, propose, apply, evaluate,
                  keep, revert, better, baseline):
    history, current = [], baseline
    while True:
        state = inspect()
        change = propose(state)
        commit = apply(change)
        try:
            score = evaluate()
        except Exception as exc:
            revert(commit)
            history.append(Trial(commit, change, None, "crash", str(exc)))
            continue
        if better(score, current):
            keep(commit); current = score
            history.append(Trial(commit, change, score, "kept", ""))
        else:
            revert(commit)
            history.append(Trial(commit, change, score, "reverted", ""))
```

### "Programming the Program" (key conceptual idea):
- Software 1.0 = explicit code
- Software 2.0 = data/training shapes behavior
- Software 3.0 = context/prompts as programmable interface
- Autoresearch adds a layer on top: **natural language instructions configure an autonomous organization** (`program.md`).

A good `program.md` defines: mutable/protected files, metric + direction, experiment budget, run command, output parsing, crash handling, commit/revert rules, logging, human escalation policy, exhaustion criteria.

---

## 3. From Loop to Swarm — AgentHub (Section III)

Karpathy's sketch of a collaboration layer: **"GitHub is for humans. AgentHub is for agents."**

Minimal architecture: one Go server binary, one SQLite DB, one bare Git repo, one API key per agent, rate limiting, thin `ah` CLI.

### CLI as a graph interface:
```
ah push                    # Push HEAD commit to hub
ah fetch <hash>             # Fetch any commit
ah log [-agent X]           # Show recent commits
ah children <hash>          # What was tried on top of this?
ah leaves                   # Frontier: no children
ah lineage <hash>           # Ancestry path to root
ah diff <hash-a> <hash-b>   # Compare any two commits
```

### Key insight: **the DAG is the graph**
- Commits = nodes
- Parent links = directed edges
- A commit node can carry: parent commit, agent, hypothesis, code diff, metric, runtime, memory, environment, keep/discard status, links to discussion, links to related experiments.

### What this model inverts (vs. human Git):
- No required `main` branch
- No pull requests / merge queue
- No single canonical leaf
- Primary operation shifts from "merge this" → **"traverse the search graph"**

### Message board = social layer
Reduces context copying — agents query relevant lineages/summaries instead of replaying full history. This is the seed of **"graph-grounded context construction."**

### Explicitly a sketch — missing pieces:
Distributed storage, repo compaction, trust among agents, malicious bundles, reproducibility, semantic duplicate detection, compute scheduling, long-term graph indexing.

---

## 4. Anthropic's Infrastructure (Section IV)

### 4.1 The Five Workflow Patterns (2024 "Building Effective Agents")
Start simple, add complexity only as needed:

| Pattern | Description |
|---|---|
| **Prompt Chaining** | One model call feeds the next; fixed sequence |
| **Routing** | Classifier sends input to specialized prompt/model/tool |
| **Parallelization** | Independent concurrent calls (sectioning or voting) |
| **Orchestrator-Workers** | Central model dynamically decomposes, assigns, synthesizes |
| **Evaluator-Optimizer** | One role generates, another evaluates in a loop |

### 4.2 Dynamic Workflows (2026)
Claude writes a **JavaScript orchestration program on the fly** instead of a static fan-out script.

```javascript
const files = await tools.glob("src/**/*.ts");
const audits = await gather(
  files.map((file) =>
    spawn("auditor", { file, instructions: "Inspect for race conditions. Return JSON." })
  ),
  { concurrency: 16 }
);
const suspicious = audits.filter((r) => r.confidence >= 0.70);
const reviews = await gather(
  suspicious.map((r) =>
    spawn("reviewer", { report: r, instructions: "Try to refute this finding." })
  ),
  { concurrency: 16 }
);
return await spawn("synthesizer", { audits, reviews, instructions: "Produce one cited report." });
```

**Key specs:** up to 16 concurrent sub-agents, hard cap 1,000 per workflow, fresh context per sub-agent, intermediate state kept in script variables, triggered via "workflow" keyword or ultracode mode.

*(Side note: Bun runtime port — ~750,000 lines Zig→Rust in 11 days, 99.8% tests passing, cited as an example of scale.)*

### 4.3 Knowledge Graph Construction Cookbook
Replaces classical NLP pipelines with model calls + structured schemas:

1. **Extraction (Haiku)** — schema-constrained call extracts typed entities + S-P-O relations
2. **Resolution (Sonnet)** — candidates clustered by type/context (e.g., "Edwin Aldrin" → "Buzz Aldrin")
3. **Assembly** — NetworkX `MultiDiGraph`; nodes carry type/source/count, edges carry predicate/provenance
4. **Querying (Sonnet)** — serialize subgraph as triples, reason with edge-level citations

```python
class Entity(BaseModel):
    name: str
    type: EntityType
    description: str

class Relation(BaseModel):
    source: str
    predicate: str
    target: str

def extract(text, client) -> ExtractedGraph:
    response = client.messages.parse(
        model="claude-haiku-4-5",
        messages=[{"role": "user", "content": PROMPT.format(text=text)}],
        output_format=ExtractedGraph,
    )
    return response.parsed_output
```

> The Pydantic schema **is** the training data — trained NER + relation classifiers collapse into one structured-output prompt.

### 4.4 Entity Resolution as a Reasoning Task
- String similarity fails on things like "Edwin Aldrin" vs "Buzz Aldrin" (zero char overlap) and can wrongly merge distinct people with shared names.
- Solution: use **descriptions as contextual evidence**, group by type, ask a stronger model to propose canonical clusters. At scale, cheap blocking signals should narrow candidates first.
- Resolution should be **additive and inspectable**: canonical entity retains aliases, source docs, resolution rationale, confidence, and the run that created the merge — so bad merges are reversible.

### 4.5 Graph Assembly Code
```python
G = nx.MultiDiGraph()

def add_entity(entity, source_doc):
    G.add_node(entity.canonical_id,
                name=entity.name,
                entity_type=entity.type,
                description=entity.description,
                source_docs={source_doc},
                aliases=set(entity.aliases))

def add_relation(relation, source_doc):
    G.add_edge(relation.source_id, relation.target_id,
                predicate=relation.predicate,
                source_doc=source_doc,
                confidence=relation.confidence)
```

**Rule:** never dump the whole graph into the model. Identify starting entities → traverse bounded neighborhood → filter edges by type/date → serialize result → cite edge IDs.

### 4.6 Table: Graph Role Across Anthropic Workflow Patterns

| Pattern | Graph Role | How It Helps |
|---|---|---|
| Augmented LLM | Retrieval source | Graph traversal for multi-hop questions |
| Prompt Chaining | Gate signal | Check entities against current graph |
| Routing | Classifier input | Entity type/degree routes queries |
| Parallelization | Shared surface | Workers publish non-overlapping findings |
| Orchestrator-Workers | Shared memory | Workers read/write graph; orchestrator stays clean |
| Evaluator-Optimizer | Grounding layer | Evaluator checks claims against graph edges |

---

## 5. The Graph as Shared Memory (Section V) — Core Section

Three roles of the graph:

### 5.1 Shared Memory
Workers write findings as structured graph updates. A synthesizer traverses the graph to combine findings **even if no single worker saw all source documents**.

```python
@dataclass
class GraphUpdate:
    nodes: list[dict]
    edges: list[dict]
    run_id: str
    agent_id: str

def publish(update, graph, validator):
    validator.check_schema(update.nodes, update.edges)
    validator.check_provenance(update.nodes, update.edges, update.run_id)
    with graph.transaction() as tx:
        tx.upsert_versioned_nodes(update.nodes)
        tx.add_edges(update.edges)
        tx.link_run(update.run_id, update.agent_id, update.nodes, update.edges)
        tx.commit()
```

### 5.2 Grounding Layer
Evaluator checks claims against evidence edges. Example: claim "Vendor X supplied the component involved in Incident Y" requires edges `(Vendor X, supplied, Component Z)` and `(Component Z, involved_in, Incident Y)`. Missing edge → structured feedback, not vague criticism:

```json
{
  "decision": "revise",
  "claim": "Vendor X supplied the component in Y",
  "reason": "No supported path from Vendor X to Y",
  "required_evidence": [
    "A source-backed supplied relation",
    "A source-backed involved_in relation"
  ]
}
```

### 5.3 Persistent World Model
> "The phrase the agent forgets, the graph does not" captures the distinction.

Enables: long-running investigations, cross-session planning, incremental document ingestion, contradiction tracking, temporal facts, versioned decisions, audit trails, handoff between models, recovery after failed runs.

### 5.4 Commit DAG vs. Knowledge Graph — They Are Complementary, Not the Same Thing

| | Commit DAG | Knowledge Graph |
|---|---|---|
| Answers | What changed? Which experiment is the parent? Which agent produced the change? Which lineages are active? | Which entities exist? How are they related? Which sources support the relation? Which claims conflict? |

A production system links both:
```
(agent_run_183)
  -produced-> (claim_441)
  -modified-> (commit_a81f)
  -evaluated_by-> (evaluation_92)

(claim_441)
  -about-> (entity_autoresearch)
  -supported_by-> (source_readme)
  -supersedes-> (claim_238)
```

### 5.5 Context Construction From a Graph (Anti-Dumping Rule)
A task-specific subgraph builder should:
1. Resolve entities mentioned in the task
2. Expand 1–2 hops over allowed edge types
3. Include current artifact versions
4. Prioritize recent verified claims
5. Include conflicts/uncertainty
6. Serialize within a token budget
7. Attach stable edge IDs for citation

---

## 6. Practical Build Path — Loop to Graph (Section VI)

| Stage | Time | Complexity | Exit Criterion |
|---|---|---|---|
| Reflective loop | Day 1 | Low | Measured quality improvement |
| Tool use | Day 2 | Low | Tool reduces a known error class |
| Planning | Week 1 | Medium | Variable tasks complete |
| Multi-agent | Week 2 | Medium | Role split beats single agent |
| Persistent graph | Month 1 | High | Cross-session queries work |
| Swarm workflow | Month 2 | High | Wall-clock gain, no quality loss |

### Day 1 — Reflective Loop
```python
def reflective_task(task, gen, eval, max_rounds=3):
    versions = [gen(task)]
    for _ in range(max_rounds):
        review = eval(task, versions[-1])
        if review["decision"] == "approve":
            return {"result": versions[-1], "versions": versions}
        versions.append(gen(task, prior=versions[-1], instructions=review["changes"]))
    return {"result": versions[-1], "status": "iteration_limit"}
```
Store: first draft, evaluator with explicit criteria, revision step, stopping rule, every artifact.

### Day 2 — Add Tools
One tool addressing one measured failure. Requires: typed schema, permissions, result confirmation.

### Week 1 — Add Planning
Only when task path varies. Require a JSON plan before execution:
```json
{
  "objective": "Construct verified knowledge graph",
  "steps": [
    {"id": "s1", "action": "extract", "input": "documents", "depends_on": [], "success": "Each doc returns ExtractedGraph"},
    {"id": "s2", "action": "resolve_entities", "input": "s1.entities", "depends_on": ["s1"], "success": "Every surface form maps to one ID"},
    {"id": "s3", "action": "assemble_graph", "input": ["s1.relations", "s2.mapping"], "depends_on": ["s1", "s2"], "success": "All endpoints resolve to nodes"}
  ]
}
```
Validate dependencies before execution. Preserve successful work during replanning. Cap retries and cost.

### Week 2 — Go Multi-Agent
Start with generator + critic. Useful config: planner, implementer, test author, reviewer, security reviewer, synthesizer. Every handoff = an **artifact contract** (a reviewer returns criterion-level defects, never "looks good"). Use worktree isolation for concurrent coding agents on the same repo.

### Month 1 — Wire Into a Graph
Start with versioned JSON or relational tables. Store: entities, claims, sources, relations, artifacts, agent runs, evaluations, versions, aliases, open questions. Add Haiku extraction + Sonnet resolution. Attach provenance to every edge.

### Month 2 — Scale to a Swarm
Pick one embarrassingly-parallel workload (audit every file for one defect class, extract entities from thousands of docs, generate tests for independent modules, compare configs, investigate independent hypotheses). **Define the reducer before fan-out.** Set: concurrency limit, worker cap, token budget, per-worker timeout, retry policy, evidence contract, dedup policy, final evaluation gate.

### Reference Production Architecture — Five Planes
- **Control plane** — receives objectives, creates plans, allocates budgets, starts/stops workflows
- **Execution plane** — runs tools, tests, training jobs, code mods, sub-agents in isolation
- **Artifact plane** — stores plans/drafts/code/reports/metrics/evals as immutable versions
- **Graph plane** — stores entities, claims, relations, provenance, lineage, dependencies
- **Evaluation plane** — deterministic checks, model evaluators, statistical scorers, human review

> Separation prevents one chat transcript from becoming the database, workflow engine, and audit log all at once.

---

## 7. Evaluation & Quality (Section VII)

### 7.1 Evaluation as its own autoresearch loop ("graph autoresearch")
```
Read current extraction prompt + score history
→ Propose one prompt/schema change
→ Run extraction on gold set
→ Compute precision, recall, F1, cost, latency
→ If improved: keep. If worse: revert.
```
The artifact optimized is not `train.py` — it's the extraction prompt / ontology / resolution policy / query serializer.

### 7.2 Metrics
- **Extraction:** entity precision, recall, F1, schema-valid response rate, cost, latency
- **Resolution:** compression ratio (raw surface forms / canonical entities), pairwise precision/recall, false merge rate, missed merge rate, manual review rate — ⚠️ *high compression ratio ≠ automatically good, can indicate over-merging*
- **Query:** must resolve entities correctly, retrieve relevant subgraph, use supported edges, respect time/source constraints, distinguish fact from inference, cite edges used, identify missing evidence

### 7.3 Table: Evaluation Metrics by Layer

| Layer | Metric | Common Misreading |
|---|---|---|
| Extraction | Entity/relation F1 | High precision hides missing entities |
| Resolution | Pairwise prec./recall | Compression alone rewards over-merging |
| Graph | Components, density | One component is not always desirable |
| Query | Accuracy, cited paths | Fluent answers can cite irrelevant edges |
| Workflow | Task success, cost | More agents can increase activity without value |
| Operations | Recovery, corrections | Average success hides catastrophic cases |

### 7.4 Table: When to Use Each Architecture Level

| Situation | Start With | Why |
|---|---|---|
| Simple low-risk question | Zero-shot | Lowest latency |
| Output can be checked | Loop | Repeated feedback improves artifact |
| Stable sequence | Chain | Predictable, testable stages |
| Clear categories | Router | Separates policies and models |
| Independent units | Parallel | Reduces wall-clock time |
| Variable decomposition | Orchestrator-workers | Dynamic specialization |
| Alternatives must remain | Commit DAG | Preserves experiment branches |
| Facts must survive sessions | Knowledge graph | Persistent shared memory |
| Very large parallel work | Dynamic workflow | Automates fan-out/fan-in |

### 7.5 Production Monitoring — Track Trends
Extraction rate by doc type, schema failure rate, resolution compression, connected-component changes, query latency, subgraph size, cited-edge validity, token cost, stale entity count, graph update failures, agent retry rates.
> Sudden rise in isolated nodes → resolution regression. Sudden drop → possible over-merging.

---

## 8. Decision Framework (Section VIII)

### 8.1 Six Selection Questions
1. **Can success be verified?** If not, don't start with autonomy — define a test/rubric/source requirement/human decision first.
2. **Are the steps stable?** Yes → chain. No → planning or orchestrator.
3. **Are subtasks independent?** Yes → parallelize. No → model dependencies explicitly, limit concurrent writes.
4. **Must alternative lineages remain available?** Yes → use a DAG, don't force everything into one branch.
5. **Must facts survive the run?** Yes → persist artifacts + graph state, don't rely on transcript summaries.
6. **Can the org afford the cost/latency?** Set budgets before adding workers.

### 8.2 Complexity Budget — Declare Before Every Run
Max model calls, max sub-agents, max concurrent workers, max tool calls, max wall-clock time, max tokens, max financial cost, max retries, max graph writes, minimum evidence required for finalization.

> When budget is exhausted: return the best current artifact, completed work, unresolved issues, and a reason for stopping. **Never hide partial failure behind a fluent final answer.**

### 8.3 When NOT to Use a Graph
Skip a knowledge graph when: tasks are independent, no cross-session state needed, answers depend on one document, relations are fixed/simple, a relational table answers every query, provenance isn't needed, or extraction errors would outweigh traversal value.

> A graph earns its cost when connected queries, evolving relations, provenance, or shared world state are central.

---

## 9. Limitations (Section IX) — Important Caveats to Keep in Mind

| Limitation | Key Point |
|---|---|
| **Autoresearch ≠ frontier research** | Works because the harness is bounded. Frontier systems have distributed infra, hardware failures, security constraints, multi-week experiments. The transferable part is the *architecture* (bounded changes, measurable eval, reversibility, durable history), not a proof agents can self-modify production systems. |
| **Metrics can be gamed** | A ratchet improves only the metric it can see — may reduce val loss while hurting inference cost, robustness, or generalization. Watch resolution precision & query latency too, not just extraction quality. |
| **AgentHub is not production software** | Explicitly a "sketch." Needs real auth, authorization, isolation, abuse prevention, durability, indexing, observability, reproducibility, conflict policy, governance. DAGs need pruning/archiving/summarization as they grow. |
| **Dynamic Workflows are expensive** | A 1,000-sub-agent run at high effort can cost tens of dollars. Parallel workers create correlated errors — a verification wave only helps if reviewers use a different prompt/evidence/role. |
| **Fragmentation can reduce quality** | Architecture design, narrative writing, tightly-coupled refactors, subtle product decisions may degrade when split into isolated units. |
| **Knowledge graphs reflect their corpus** | Biased corpus → biased graph. Missing docs → missing edges. The graph preserves claims for inspection — it does not convert claims into truth. |
| **Entity resolution errors are catastrophic, not local** | A false merge (collapsing two people into one node) contaminates *every downstream query* touching that node. Resolution must retain aliases, evidence, confidence, and be reversible. |
| **The graph amplifies builder judgment** | Just like a loop amplifies the objective/evaluator you chose, a graph amplifies your ontology and source policy. Wrong objective or wrong world-representation → automation just scales the error faster. Requires deliberate human ownership of specs, quality bars, correction mechanisms. |

---

## 10. Glossary (Appendix)

| Term | Meaning |
|---|---|
| Autoresearch | Autonomous experimentation repo: agent edits `train.py`, evaluates, keeps or reverts |
| AgentHub | Agent-first collaboration: bare Git repo, SQLite, API, CLI, message board |
| DAG | Directed acyclic graph. Commits are nodes, parent links are edges |
| Agent swarm | Agents that explore, implement, or evaluate concurrently |
| Dynamic Workflows | Generated scripts that spawn and gather sub-agent tasks |
| Knowledge graph | Entities as nodes, typed relations as edges, with provenance |
| Structured outputs | Model responses constrained to a Pydantic schema |
| Provenance | Where a claim came from, which run produced it |
| `program.md` | Natural-language control specification for the autoresearch loop |
| Ratchet loop | Iterative process retaining only metric improvements |
| Graph grounding | Constraining generation with facts retrieved from a graph |

**Node types:** Entity, Claim, Source, Artifact, AgentRun, Evaluation, Task, Commit, Metric
**Edge types:** MENTIONS, SUPPORTS, CONTRADICTS, DERIVED_FROM, PRODUCED, EVALUATES, REVISES, SUPERSEDES, DEPENDS_ON, PARENT_OF, RESOLVED_TO

### Four Invariants Every Graph Write Must Satisfy
1. Every claim has a source, or is marked as inference.
2. Every artifact has an authoring run and version.
3. Every evaluation identifies a rubric.
4. Every superseded object remains addressable.

### Default Flow for a Graph-Grounded Agent Task
1. Receive objective and constraints
2. Resolve task entities against the graph
3. Retrieve bounded subgraph with provenance
4. Create typed plan, validate dependencies
5. Assign independent steps to isolated workers
6. Require structured artifacts and evidence
7. Publish candidate graph updates
8. Validate schemas, permissions, provenance
9. Run deterministic tests
10. Run evaluator agents against rubrics
11. Resolve conflicts or escalate uncertainty
12. Publish versioned final artifact
13. Link to sources, graph paths, runs, evaluations
14. Record cost, latency, failures, open questions

---

## 11. Table VI — Production Checklist (Use This to Audit Any Agentic Project)

| Element | Ask Yourself | Failure If Missing |
|---|---|---|
| Objective | Is the task testable? | Agents optimize the wrong thing |
| Metric | Can it distinguish improvement? | Activity without progress |
| Reversibility | Can updates be undone? | Failed experiment damages state |
| Tool schema | Are arguments typed? | Invalid calls, silent errors |
| Artifact contract | What must workers return? | Inconsistent prose |
| Provenance | Does every claim have a source? | Outputs not auditable |
| Resolution policy | Are decisions reversible? | False merges contaminate graph |
| Budget | Are limits explicit? | Unbounded resource use |
| Monitoring | Are metrics tracked? | Regressions invisible |
| Recovery | Can you resume from state? | Every interruption restarts from zero |

---

## 12. One-Line Summary Per Section (For Fast Re-Skim)

- **II. Autoresearch** — verifiable + reversible + short-horizon + bounded = ideal conditions for a self-improving loop.
- **III. AgentHub** — collaboration doesn't need a "main branch"; the commit DAG itself is the shared graph of lineage.
- **IV. Anthropic infra** — five composable workflow patterns → Dynamic Workflows (generated scripts, 1,000 sub-agents) → Knowledge Graph Cookbook (structured extraction replaces classic NLP).
- **V. Graph as memory** — shared memory + grounding layer + persistent world model; commit DAG (lineage) and knowledge graph (facts) are complementary, not the same thing.
- **VI. Build path** — Day 1 loop → Day 2 tools → Week 1 planning → Week 2 multi-agent → Month 1 graph → Month 2 swarm.
- **VII. Evaluation** — treat prompt/schema/ontology tuning as its own autoresearch loop; watch for over-merging and fluent-but-wrong citations.
- **VIII. Decision framework** — 6 questions before adding autonomy; declare a complexity budget; know when a graph is overkill.
- **IX. Limitations** — small-scale proof ≠ frontier-scale proof; metrics get gamed; sketches aren't production; fan-out is costly; resolution errors are catastrophic and compounding; the graph amplifies whatever judgment (good or bad) built it.

---

*End of extracted notes. This file is paper-content only — no project-specific mapping included by design (kept for a separate linking document).*
