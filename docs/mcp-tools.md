# MCP Tools Reference

## neurosync_recall

Retrieve relevant context at session start. Uses RetrievalPipeline with winner-take-all scoring and UserModel familiarity filtering.

**Parameters:**
- `project` (string, optional) — Auto-detected from git if omitted
- `branch` (string, optional) — Auto-detected from git if omitted
- `context` (string, optional) — Additional context for retrieval
- `max_tokens` (integer, default: 500) — Maximum output tokens

**Returns:** Primary theory, supporting theories, recent episodes, continuation (if any), tokens used.

## neurosync_record

Record session episodes at session end. Computes all applicable signal types for each event.

**Parameters:**
- `events` (array, required) — Events to record. Each: `{type, content, cause?, effect?, reasoning?, files?, layers?, importance?}`
- `session_summary` (string, optional) — Summary of the session
- `project` (string, optional)
- `branch` (string, optional)
- `explicit_remember` (array of strings, optional) — High-weight memories (10x)

**Event types:** decision, discovery, correction, pattern, frustration, question, file_change, architecture, debugging, explicit, causal, observed

## neurosync_remember

Explicitly remember something with high signal weight (x10).

**Parameters:**
- `content` (string, required) — What to remember
- `type` (string, default: "explicit") — Event type
- `importance` (integer, optional, 1-5) — INTUITION signal weight
- `reasoning` (string, optional) — Why this is worth remembering
- `cause` (string, optional) — What triggered this memory
- `effect` (string, optional) — What resulted

## neurosync_query

Search across episodes, theories, analogies, causal graph, or failures.

**Parameters:**
- `query` (string, required) — Search query
- `mode` (string, default: "semantic") — Search mode: `semantic`, `analogy`, `causal`, `failures`
- `scope` (string, default: "all") — "all", "episodes", or "theories"
- `project` (string, optional)
- `limit` (integer, default: 10)

## neurosync_correct

Record an AI mistake with exponential weight (2^N where N = correction count in session).

**Parameters:**
- `wrong` (string, required) — What was wrong
- `right` (string, required) — What is correct
- `theory_id` (string, optional) — Theory to contradict (reduces confidence by 0.15)

## neurosync_handoff

Record a cross-session handoff for multi-session tasks. Creates a high-weight continuation episode.

**Parameters:**
- `goal` (string, required) — Overall goal of the task
- `accomplished` (string, required) — What was accomplished this session
- `remaining` (string, required) — What still needs to be done
- `next_step` (string, required) — Concrete next step for the next session
- `blockers` (string, optional) — Any blockers or open questions

## neurosync_status

Health check — no parameters.

**Returns:** Episode, theory, contradiction counts; ChromaDB sizes; current session info; graph health (if Neo4j configured).

## neurosync_theories

Browse, inspect, retire, relate, or view hierarchy of theories.

**Parameters:**
- `action` (string, default: "list") — "list", "detail", "retire", "relate", "graph"
- `scope` (string, optional) — "project", "domain", or "craft"
- `project` (string, optional)
- `theory_id` (string, optional) — Required for detail/retire
- `related_ids` (array of strings, optional) — Theory IDs to link (for relate action)
- `limit` (integer, default: 20)

## neurosync_consolidate

Trigger consolidation engine. Runs clustering, theory extraction (TF-IDF + causal merge), MDL pruning, and ForgettingEngine pass.

**Parameters:**
- `project` (string, optional) — Limit to project
- `dry_run` (boolean, default: false) — Preview only

## neurosync_graph

Query or sync the Neo4j knowledge graph. Requires `pip install neurosync[neo4j]`.

**Parameters:**
- `action` (string, required) — "status", "sync", "prebuilt", "query"
- `cypher` (string, optional) — Read-only Cypher query (for "query" action)
- `parameters` (object, optional) — Parameters for Cypher query
- `prebuilt_name` (string, optional) — Name of pre-built query (for "prebuilt" action)
- `project` (string, optional) — Project filter for sync

**Actions:**
- `status` — Graph health check (node/relationship counts)
- `sync` — Sync SQLite data to Neo4j (MERGE-based, idempotent)
- `prebuilt` — List or run pre-built queries (12 available)
- `query` — Run a read-only Cypher query (write operations are blocked)
