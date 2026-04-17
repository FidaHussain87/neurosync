# NeuroSync — AI Agent Instructions

## What This Is

NeuroSync is a developer-focused memory MCP server. It provides episodic, semantic, and working memory for AI coding agents via 8 MCP tools.

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
