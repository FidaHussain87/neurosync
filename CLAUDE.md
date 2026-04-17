# NeuroSync — AI Agent Instructions

## What This Is

NeuroSync is a developer-focused memory MCP server (v0.4.0). It provides episodic, semantic, and working memory — plus cognitive features (hierarchy, forgetting, analogy, causal reasoning, failure modeling) — for AI coding agents via 9 MCP tools.

## NeuroSync Memory Protocol

NeuroSync gives you persistent memory across sessions via 9 MCP tools. Most behavior is automatic (auto-consolidation, passive git observation). Follow these 3 rules:

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

### What's automatic

- **Auto-consolidation** — theories are extracted automatically when enough episodes accumulate (no manual `consolidate` needed)
- **Passive git observation** — file changes and commits are recorded as low-weight episodes automatically
- **Dynamic hints** — tool responses include contextual guidance

## Project Structure

- `neurosync/` — Main Python package
  - `mcp_server.py` — MCP JSON-RPC 2.0 stdio server (9 tools)
  - `cli.py` — CLI commands: serve, consolidate, status, import-starter-pack, generate-protocol, install-hook, reset
  - `config.py` — Configuration (env > config.json > defaults)
  - `models.py` — Dataclasses (Session, Episode, Signal, Theory, Contradiction, UserKnowledge)
  - `db.py` — SQLite database (WAL mode, thread-safe, schema migrations)
  - `vectorstore.py` — ChromaDB wrapper (episodes + theories collections)
  - `episodic.py` — Layer 1: session/episode CRUD, causal episodes, continuations
  - `semantic.py` — Layer 2: theory CRUD, confidence, linking, validation tracking
  - `working.py` — Layer 3: recall with winner-take-all, continuation priority
  - `consolidation.py` — Consolidation engine: cluster -> extract -> MDL prune -> auto-linking + auto-trigger
  - `signals.py` — Signal weight calculations (8 types, including PASSIVE)
  - `quality.py` — Episode quality scoring (0-7 scale, warns on low quality)
  - `hooks.py` — Claude Code hook configuration for auto-recall on session start
  - `git_observer.py` — Passive git state observation at session boundaries
  - `protocol.py` — Minimal protocol text and CLAUDE.md generator
  - `user_model.py` — Topic familiarity tracking
  - `retrieval.py` — Full recall pipeline with application tracking
  - `starter_pack_loader.py` — YAML starter pack loader
  - `forgetting.py` — Ebbinghaus decay, spaced repetition, active pruning
  - `analogy.py` — Structural fingerprinting, combined semantic+structural search
  - `failure.py` — Failure records, proactive warnings, anti-patterns
  - `hierarchy.py` — Theory hierarchy traversal, semantic parents, merging
  - `causal.py` — Causal graph construction and querying
- `tests/` — pytest test suite (~277 tests)

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
```

## Architecture

Three-layer memory system:
1. **Episodic** (Layer 1) — Raw session events stored in SQLite + ChromaDB
2. **Semantic** (Layer 2) — Consolidated theories with confidence scores
3. **Working** (Layer 3) — Context-aware recall with winner-take-all activation

Data flows: record -> episodes -> auto-consolidation -> theories -> recall

### Degraded Mode

SQLite is the source of truth; ChromaDB is an acceleration layer. If ChromaDB is unavailable (corrupted HNSW index, permission error, missing dependency), NeuroSync runs in **degraded mode**:
- Recording episodes and theories still works (SQLite writes always succeed)
- Vector search (semantic recall, analogy, duplicate detection) returns empty results
- The MCP server logs a warning at startup and continues operating
- Next restart with a working ChromaDB picks up where it left off

All engine constructors accept `Optional[VectorStore]` and guard every vector operation with `if self._vs:` checks.

## Testing

- Use `pytest` with the fixtures in `tests/conftest.py`
- Tests use isolated temp directories (no real `~/.neurosync`)
- Mock external dependencies, test behavior
