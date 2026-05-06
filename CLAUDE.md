# NeuroSync — AI Agent Instructions

## What This Is

NeuroSync is a developer-focused memory MCP server (v0.6.0). It provides episodic, semantic, and working memory — plus cognitive features (hierarchy, forgetting, analogy, causal reasoning, failure modeling, user familiarity tracking) and a background intelligence layer (pattern mining, fatigue detection, file dependency analysis) — for AI coding agents via 10 MCP tools. Supports SQLite (default) and PostgreSQL backends.

## NeuroSync Memory Protocol

NeuroSync gives you persistent memory across sessions via 10 MCP tools. Most behavior is automatic (auto-consolidation, passive git observation). Follow these 3 rules:

### Rule 1: Follow recalled theories as ground truth

Call `neurosync_recall` at session start. Apply recalled theories like a style guide — they are confirmed lessons from past sessions, not suggestions. Check for continuation episodes from previous sessions.

### Rule 2: Record corrections immediately

When corrected, call `neurosync_correct` with what was wrong and what's right. Corrections compound exponentially (2^N) — they are the most valuable signal.

### Rule 3: Record decisions at session end

Call `neurosync_record` with structured episodes when the session ends. Write causal statements (why, not what). Use `neurosync_handoff` for multi-session tasks.

### Available tools

| Tool | Purpose |
|------|---------|
| `neurosync_recall` | Load project memory at session start |
| `neurosync_record` | Record session episodes at end |
| `neurosync_remember` | Explicitly remember something (10x weight) |
| `neurosync_query` | Search memories mid-session |
| `neurosync_correct` | Record a mistake (2^N weight) |
| `neurosync_handoff` | Cross-session task continuity |
| `neurosync_status` | Health check |
| `neurosync_theories` | Browse/manage learned patterns |
| `neurosync_consolidate` | Manual consolidation trigger |
| `neurosync_graph` | Query Neo4j knowledge graph (optional) |

### What's automatic

- **Auto-consolidation** — theories are extracted automatically when enough episodes accumulate (no manual `consolidate` needed). Uses TF-IDF keyword extraction and multi-episode merge heuristics (zero LLM tokens). Runs in a non-blocking background thread.
- **Intelligence layer** — background analyzers mine stored data for patterns (peak hours, fatigue, file co-occurrence, volatility). Insights surface automatically in recall/record responses.
- **Theory versioning** — every mutation (confirm, contradict, retire) saves a snapshot; rollback to any previous version via `neurosync_theories action=rollback`.
- **Forgetting pass** — after consolidation, Ebbinghaus retention curves prune low-value episodes and decay stale theories
- **User familiarity tracking** — topics you know well are suppressed from recall; corrections reduce familiarity
- **Cross-project theory discovery** — recall finds relevant domain/craft theories from other projects
- **7 active signal types** — CORRECTION (2^N), DEPTH (layer count), SURPRISE (contradicts theory), REPETITION (re-explained), EXPLICIT (x10), INTUITION (1-5), PASSIVE (x0.3). DURATION is defined but not yet wired (requires session-level timing).
- **Outcome-based confidence** — session correction count adjusts recalled theory confidence
- **Passive git observation** — file changes and commits are recorded as low-weight episodes automatically
- **Dynamic hints** — tool responses include contextual guidance
- **Input bounds** — all inputs validated with size caps to prevent OOM (content: 50K, query: 5K, events: 100)

## Project Structure

- `neurosync/` — Main Python package
  - `mcp_server.py` — MCP JSON-RPC 2.0 stdio server (10 tools, thread pool, graceful shutdown)
  - `cli.py` — CLI commands: serve, consolidate, status, export, import, reindex, downgrade, import-starter-pack, generate-protocol, install-hook, graph-sync, graph-status, reset
  - `config.py` — Configuration (env > config.json > defaults) with validation
  - `models.py` — Dataclasses (Session, Episode, Signal, Theory, Contradiction, UserKnowledge)
  - `db.py` — SQLite database (WAL mode, thread-safe, schema v8, migrations + downgrade) — default backend
  - `pg_db.py` — PostgreSQL database (connection pooling, JSONB, schema v8) — optional backend
  - `vectorstore.py` — ChromaDB wrapper (auto-recovery, reindex, integrity check)
  - `episodic.py` — Layer 1: session/episode CRUD, causal episodes, continuations
  - `semantic.py` — Layer 2: theory CRUD, confidence, linking, versioning, rollback
  - `working.py` — Layer 3: recall with winner-take-all, continuation priority
  - `retrieval.py` — Full recall pipeline with familiarity filtering, parent context, cross-project discovery
  - `user_model.py` — Topic familiarity tracking, meta-learning (correction rate per topic)
  - `consolidation.py` — Consolidation engine: chunked batches, cluster -> extract -> MDL prune -> auto-linking
  - `signals.py` — Signal weight calculations (8 types, including PASSIVE)
  - `quality.py` — Episode quality scoring (0-7 scale, warns on low quality)
  - `logging.py` — Structured logging (JSON/text format), in-process metrics (counters + latency histograms)
  - `hooks.py` — Claude Code hook configuration for auto-recall on session start
  - `git_observer.py` — Passive git state observation at session boundaries
  - `protocol.py` — Minimal protocol text and CLAUDE.md generator
  - `starter_pack_loader.py` — YAML starter pack loader
  - `forgetting.py` — Ebbinghaus decay, spaced repetition, active pruning
  - `analogy.py` — Structural fingerprinting, combined semantic+structural search
  - `failure.py` — Failure records, proactive warnings, anti-patterns
  - `hierarchy.py` — Theory hierarchy traversal, semantic parents, merging
  - `causal.py` — Causal graph construction and querying
  - `graph.py` — Optional Neo4j knowledge graph sync and querying
  - `intelligence/` — Background intelligence layer (zero LLM cost)
    - `__init__.py` — IntelligenceEngine orchestrator (daemon thread, scheduled analyzers)
    - `models.py` — Insight + DeveloperProfile dataclasses
    - `surfacer.py` — Relevance scoring and insight selection for MCP responses
    - `analyzers/base.py` — BaseAnalyzer ABC (interval_seconds, max_runtime_ms)
    - `analyzers/work_patterns.py` — Peak hours, session rhythm, fatigue, day-of-week patterns
    - `analyzers/file_network.py` — File co-occurrence (Jaccard), volatility hotspots
- `tests/` — pytest test suite (~474 tests)
- `frontend/` — Interactive 3D graph visualization (React 18 + TypeScript)
  - `src/components/` — GraphCanvas (3D), Sidebar, DetailPanel, QueryRunner, ConnectionForm
  - `src/hooks/` — useNeo4jConnection, useGraphData
  - `src/services/neo4j.ts` — Neo4j driver wrapper, query extraction, record-to-graph transformation
  - `src/types.ts` — GraphNode, GraphLink, GraphData interfaces
  - `src/constants.ts` — Node/link styles, 12 pre-built Cypher queries

## Development Commands

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run tests
pytest --cov=neurosync -v

# Lint
ruff check neurosync/

# Run MCP server
python -m neurosync.mcp_server

# CLI
neurosync status
neurosync consolidate --dry-run
neurosync generate-protocol
neurosync generate-protocol --project MyApp
neurosync export --output backup.json
neurosync import --input backup.json
neurosync reindex --reset
neurosync downgrade --version 7 --confirm

# Neo4j knowledge graph (optional)
neurosync graph-sync
neurosync graph-status

# Frontend visualization (optional, requires Neo4j)
cd frontend && npm install && npm run dev   # dev server at localhost:5173
cd frontend && npm run build                # production build to frontend/dist/
```

## Architecture

Four-layer memory system:
1. **Episodic** (Layer 1) — Raw session events stored in SQLite/PostgreSQL + ChromaDB
2. **Semantic** (Layer 2) — Consolidated theories with confidence scores and version history
3. **Working** (Layer 3) — Context-aware recall via RetrievalPipeline with user familiarity filtering
4. **Intelligence** (Layer 4) — Background pattern mining produces insights and developer profile

Data flows: record -> episodes -> auto-consolidation (background) -> theories -> forgetting pass -> recall (+ intelligence insights) -> graph-sync -> Neo4j -> frontend visualization

### Database Backends

- **SQLite** (default) — WAL mode, thread-safe, zero setup
- **PostgreSQL** (optional) — Connection pooling, JSONB columns. Set `NEUROSYNC_DB_BACKEND=postgresql` and `NEUROSYNC_PG_DSN` to switch.

### Degraded Mode

The primary database (SQLite or PostgreSQL) is the source of truth; ChromaDB is an acceleration layer. If ChromaDB is unavailable (corrupted HNSW index, permission error, missing dependency), NeuroSync runs in **degraded mode**:
- Recording episodes and theories still works (SQLite writes always succeed)
- Vector search (semantic recall, analogy, duplicate detection) returns empty results
- The MCP server logs a warning at startup and continues operating
- ChromaDB auto-recovery: if initialization fails, corrupted directory is moved aside and a fresh instance is created
- `neurosync reindex` re-populates ChromaDB from the SQLite source of truth

All engine constructors accept `Optional[VectorStore]` and guard every vector operation with `if self._vs:` checks.

### Logging & Metrics

- **Structured logging** — set `NEUROSYNC_LOG_FORMAT=json` for JSON log lines (for log aggregation)
- **Log level** — set `NEUROSYNC_LOG_LEVEL=DEBUG|INFO|WARNING` (default: INFO)
- **In-process metrics** — counters per tool call, latency histograms (p50/p95/max), uptime tracking
- Metrics exposed via `neurosync_status` response

## Testing

- Use `pytest` with the fixtures in `tests/conftest.py`
- Tests use isolated temp directories (no real `~/.neurosync`)
- Mock external dependencies, test behavior
