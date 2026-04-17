# NeuroSync — AI Agent Instructions

## What This Is

NeuroSync is a developer-focused memory MCP server. It provides episodic, semantic, and working memory for AI coding agents via 8 MCP tools.

## NeuroSync Memory Protocol

If `neurosync_*` tools are available, follow this protocol:

### On session start
- Call `neurosync_recall` with the current project name and context to load relevant memories.
- Review returned theories and recent episodes before starting work.

### During the session
- When the user says "remember this", "don't forget", or similar → call `neurosync_remember` immediately.
- When the user corrects you ("that's wrong", "no, the right way is...") → call `neurosync_correct` with what was wrong and what's right.
- When you discover something surprising or non-obvious → call `neurosync_remember` with the discovery.

### On session end (when asked, or before a long task completes)
- Call `neurosync_record` with structured episodes covering what happened:
  - Decisions made (and why)
  - Bugs found or fixed
  - Corrections received
  - Patterns noticed
  - Architecture discussions
  - Files and layers touched
- Include a brief session summary.
- Add any important takeaways to `explicit_remember`.

### When searching for past context
- Call `neurosync_query` to search across past episodes and theories.

## Project Structure

- `neurosync/` — Main Python package
  - `mcp_server.py` — MCP JSON-RPC 2.0 stdio server (8 tools)
  - `cli.py` — CLI commands: serve, consolidate, status, import-starter-pack, reset
  - `config.py` — Configuration (env > config.json > defaults)
  - `models.py` — Dataclasses (Session, Episode, Signal, Theory, Contradiction, UserKnowledge)
  - `db.py` — SQLite database (WAL mode, thread-safe)
  - `vectorstore.py` — ChromaDB wrapper (episodes + theories collections)
  - `episodic.py` — Layer 1: session/episode CRUD
  - `semantic.py` — Layer 2: theory CRUD, confidence
  - `working.py` — Layer 3: recall with winner-take-all
  - `consolidation.py` — Offline engine: cluster → extract → MDL prune
  - `signals.py` — Signal weight calculations (6 types)
  - `user_model.py` — Topic familiarity tracking
  - `retrieval.py` — Full recall pipeline
  - `starter_packs.py` — YAML starter pack loader
- `tests/` — pytest test suite

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
```

## Architecture

Three-layer memory system:
1. **Episodic** (Layer 1) — Raw session events stored in SQLite + ChromaDB
2. **Semantic** (Layer 2) — Consolidated theories with confidence scores
3. **Working** (Layer 3) — Context-aware recall with winner-take-all activation

Data flows: record → episodes → consolidation → theories → recall

## Testing

- Use `pytest` with the fixtures in `tests/conftest.py`
- Tests use isolated temp directories (no real `~/.neurosync`)
- Mock external dependencies, test behavior
