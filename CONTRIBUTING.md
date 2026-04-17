# Contributing to NeuroSync

## Setup

```bash
git clone <repo>
cd neurosync
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest --cov=neurosync -v
```

## Linting

```bash
ruff check neurosync/
ruff format neurosync/
```

## Architecture

See `docs/architecture.md` for the three-layer memory system design.

## Pull Requests

- Include tests for new functionality
- Maintain >85% code coverage
- Pass `ruff check` with no errors
- Keep MCP tool count at 8 — add capabilities to existing tools before creating new ones
