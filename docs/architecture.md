# NeuroSync Architecture

## Three-Layer Memory Model

NeuroSync models developer memory using three layers inspired by human neuroscience:

### Layer 1: Episodic Memory
- **What**: Raw events from coding sessions
- **Storage**: SQLite/PostgreSQL `episodes` table + ChromaDB `neurosync_episodes` collection
- **Lifecycle**: Created during sessions → consolidated into theories → decayed from vector store
- **Event types**: decision, discovery, correction, pattern, frustration, question, file_change, architecture, debugging, explicit

### Layer 2: Semantic Memory
- **What**: Consolidated patterns and theories extracted from episodes
- **Storage**: SQLite/PostgreSQL `theories` table + ChromaDB `neurosync_theories` collection
- **Lifecycle**: Created by consolidation → confirmed/contradicted → confidence decayed → retired
- **Scopes**: project (single project), domain (shared domain), craft (general practice)

### Layer 3: Working Memory
- **What**: Context-aware recall assembled from theories and recent episodes
- **Algorithm**: Winner-take-all activation via RetrievalPipeline with UserModel familiarity filtering
- **Output**: Primary theory + 2-3 supporting theories + recent episodes, within token budget

### Layer 4: Intelligence

- **What**: Background analysis engine that mines stored data for developer-specific patterns
- **Storage**: SQLite/PostgreSQL `insights` table + `developer_profile` table
- **Lifecycle**: Analyzers run on schedule → produce insights → insights surfaced via MCP responses → staleness decay → retired
- **Analyzers**: WorkPatternAnalyzer (hourly), FileNetworkAnalyzer (every 2h)
- **Zero LLM cost**: Pure local computation (statistics, Jaccard index, linear regression)

## Data Flow

```
Session Events → record() → Episodes (SQLite + ChromaDB)
                                 ↓
                          consolidate() → Theories (SQLite + ChromaDB)
                                 ↓
                            recall() → Working Memory Context
                                 ↓
                   Intelligence Engine ←── reads episodes (background daemon)
                         ↓                         ↓
                   insights table          developer_profile table
                         ↓
                   InsightSurfacer → appended to recall/record/status responses
                                 ↓
                          graph-sync → Neo4j Knowledge Graph (optional)
                                 ↓
                           frontend → Interactive 3D Visualization (optional)
```

## Neo4j Knowledge Graph (Optional)

SQLite data is synced to Neo4j on demand via `neurosync graph-sync`. Neo4j provides a connected graph representation of all memory entities (Sessions, Episodes, Theories, Concepts, Contradictions, Failures, Patterns, UserKnowledge) with relationships like CONTAINS, EXTRACTED_FROM, CAUSES, CONTRADICTS, and PARENT_OF.

## Frontend Visualization (Optional)

A standalone React + TypeScript web app (`frontend/`) connects directly to Neo4j via Bolt WebSocket and renders the knowledge graph using `react-force-graph-2d`. Features multi-layer parallax star field, space-time fabric curvature near massive nodes, mass-weighted gravitational physics, Louvain community detection for cluster view, progressive loading, and 12 pre-built Cypher queries.

## Intelligence Layer

The intelligence engine runs as a background daemon thread alongside the MCP server. It reads existing episodic data and produces insights without any LLM calls.

### Analyzers

| Analyzer | Interval | What it mines | Insights produced |
|----------|----------|---------------|-------------------|
| WorkPatternAnalyzer | 1 hour | Episode timestamps | Peak productivity hours, session rhythm, day-of-week correction patterns, fatigue detection |
| FileNetworkAnalyzer | 2 hours | `files_touched` arrays | File co-occurrence (Jaccard index), volatility hotspots |

### Insight Surfacing

The InsightSurfacer scores insights by: `relevance = confidence × recency × novelty × context_match`

Rules:
- Max 2 insights per `recall` response
- Max 1 warning per `record` response
- Never surface dismissed or already-surfaced insights
- Minimum confidence threshold: 0.4

### Developer Profile

Computed facts stored in `developer_profile` table:
- `peak_hours` — hour range with highest quality output
- `session_rhythm` — average/median productive session length, fatigue rate
- `fatigue_threshold_minutes` — session duration at which quality typically declines

### Thread Safety

All shared state (`_last_run`, `_surfaced_this_session`) is protected by a threading lock. The surfaced set is capped at 500 entries to prevent unbounded memory growth.

## Theory Versioning

Every theory mutation (confirm, contradict, supersede, retire) saves a snapshot to `theory_versions`. This enables:
- Full audit trail: `neurosync_theories action=history theory_id=...`
- Rollback to any previous version: `neurosync_theories action=rollback theory_id=... version_number=3`

## Database Backends

- **SQLite** (default) — WAL mode, thread-safe, zero setup. Source of truth for all data.
- **PostgreSQL** (optional) — Connection pooling via psycopg2, JSONB columns. Set `NEUROSYNC_DB_BACKEND=postgresql` and `NEUROSYNC_PG_DSN` to switch. Falls back to SQLite if unavailable.

## Schema Versions

| Version | What was added |
|---------|---------------|
| v1–v5 | Core tables (sessions, episodes, theories, signals, causal_links, etc.) |
| v6 | `audit_log` table — entity-level change tracking |
| v7 | `theory_versions` table — theory mutation history & rollback |
| v8 | `insights` + `developer_profile` tables — intelligence layer storage |

## Signal Weighting

Episodes are weighted by importance signals (7 active, 1 defined but unwired):

| Signal | Formula | Purpose | Status |
|--------|---------|---------|--------|
| CORRECTION | 2^N | Mistakes accumulate exponentially | Active |
| DEPTH | N layers | Cross-cutting changes matter more | Active |
| SURPRISE | x3 | Contradictions to existing theories | Active |
| REPETITION | x5 | Things re-explained from past sessions | Active |
| EXPLICIT | x10 | User explicitly flagged importance | Active |
| INTUITION | importance x 0.4 | Agent rates episode importance 1-5 | Active |
| PASSIVE | x0.3 | Auto-observed events (git changes) | Active |
| DURATION | ratio x 2.0 | Time proportion spent on topic | Defined, unwired |

Composite weight = product of all multipliers, capped at 1000.

## Consolidation Pipeline

1. Gather unconsolidated episodes (min 5)
2. Cluster by ChromaDB cosine similarity (<0.8 threshold)
3. Extract candidate theory from each cluster (2+ episodes) using 3 strategies:
   - **Causal merge** — if cluster has episodes with cause/effect fields, merge into "When X, then Y" rule
   - **TF-IDF keyword extraction** — for clusters of 3+, extract shared vocabulary and pick representative episode
   - **Fallback** — use highest-weight episode as theory (truncated)
4. MDL prune: reject candidates where theory length > 70% of combined cluster content
5. Contradiction check against existing theories
6. Merge (confirm existing) or create new theory
7. Classify scope: project → domain → craft
8. Decay old episodes from ChromaDB
9. Run ForgettingEngine pass: Ebbinghaus retention curves prune low-value episodes and decay stale theories

## Winner-Take-All Recall (via RetrievalPipeline)

1. Build context embedding from project + branch + user context
2. Query theory collection (top 10)
3. Score: `confidence / (1 + cosine_distance)`
4. Pick highest as primary, next 2-3 as supporting
5. Filter by UserModel familiarity (suppress topics with familiarity > 0.9)
6. Include parent context for theories in a hierarchy
7. Check for continuation episodes from prior sessions
8. Discover cross-project theories (domain/craft scope from other projects)
9. Add recent episodes within token budget
10. Track application of recalled theories for outcome-based confidence adjustment
11. Enrich with intelligence insights (top 2 by relevance score)

## MCP Server Hardening

- **Input validation** — all string inputs capped (content: 50K chars, query: 5K chars, context: 10K chars); arrays capped (100 events, 50 files)
- **Thread pool** — tool calls dispatched to a 4-worker thread pool for concurrent execution
- **Request dedup** — recent request IDs cached to handle retries without duplicate processing
- **Graceful shutdown** — SIGTERM/SIGINT handlers flush session state and close connections
- **Session TTL** — sessions auto-rotate after 2 hours to prevent unbounded state
- **Non-blocking consolidation** — runs in background thread; MCP responses never blocked
- **Thread-safe stdout** — `_send_lock` prevents interleaved JSON-RPC messages
- **Metrics** — in-process counters and latency histograms per tool call

## ChromaDB Resilience

- **Auto-recovery** — if ChromaDB initialization fails (corrupted HNSW index), the corrupted directory is moved aside and a fresh instance is created
- **Reindex from DB** — `neurosync reindex` re-populates ChromaDB from the SQLite source of truth
- **Integrity check** — `VectorStore.integrity_check()` compares ChromaDB counts against DB counts to detect drift
- **Degraded mode** — if ChromaDB is unavailable, all non-vector operations continue normally
