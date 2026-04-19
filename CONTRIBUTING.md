# Contributing to NeuroSync

Thanks for your interest in contributing! This guide covers everything you need to know — from setting up your environment to getting your PR merged.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Issues](#issues)
- [Branch Naming](#branch-naming)
- [Commit Messages](#commit-messages)
- [Pull Requests](#pull-requests)
- [Development Workflow](#development-workflow)
- [Code Style](#code-style)
- [Testing](#testing)
- [Architecture Overview](#architecture-overview)
- [What Not to Do](#what-not-to-do)

## Code of Conduct

Be respectful, constructive, and patient. We're building something useful together. No tolerance for harassment, personal attacks, or dismissive behavior. If you see it, report it.

## Getting Started

### Prerequisites

- Python 3.9 or later
- Git

### Setup

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/<your-username>/neurosync.git
cd neurosync

# 2. Add the upstream remote
git remote add upstream https://github.com/FidaHussain87/neurosync.git

# 3. Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate

# 4. Install in dev mode
pip install -e ".[dev]"

# 5. Verify everything works
pytest --cov=neurosync -v
ruff check neurosync/
```

### Keep your fork in sync

```bash
git fetch upstream
git checkout main
git merge upstream/main
```

## Issues

### Before opening an issue

1. Search existing issues — someone may have reported it already.
2. Check [Discussions](https://github.com/FidaHussain87/neurosync/discussions) for Q&A.
3. Run `neurosync status` and include the output in bug reports.

### Issue types

| Type | Label | Use when |
|------|-------|----------|
| **Bug report** | `bug` | Something is broken or behaving unexpectedly |
| **Feature request** | `enhancement` | You want new functionality or a change in behavior |
| **Documentation** | `docs` | Something is unclear, missing, or incorrect in the docs |

### Writing a good issue

- **Be specific.** "Recall doesn't work" is hard to debug. "Recall returns 0 theories after consolidation with 30 episodes on Python 3.12 / macOS" is actionable.
- **Include reproduction steps.** Numbered steps, not paragraphs.
- **Include `neurosync status` output.** This tells us your database state, schema version, and ChromaDB health.
- **Include error messages.** Full tracebacks, not summaries.

## Branch Naming

Use this format:

```
<type>/<issue-number>-<short-description>
```

### Types

| Type | When |
|------|------|
| `feat/` | New feature or capability |
| `fix/` | Bug fix |
| `docs/` | Documentation only |
| `refactor/` | Code restructuring, no behavior change |
| `test/` | Adding or improving tests |
| `chore/` | Build, CI, dependency updates |

### Examples

```
feat/42-add-export-command
fix/87-recall-empty-on-first-session
docs/15-improve-setup-guide
refactor/63-simplify-consolidation-clustering
test/91-add-degraded-mode-tests
chore/100-update-chromadb-dependency
```

### Rules

- Always branch from `main`.
- Use lowercase, hyphens for separators.
- Include the issue number when one exists.
- Keep it short but descriptive — someone should understand the intent from the branch name alone.

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types

| Type | When |
|------|------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation changes |
| `test` | Adding or updating tests |
| `refactor` | Restructuring without behavior change |
| `chore` | Build, CI, tooling |
| `perf` | Performance improvement |

### Scopes (optional)

Use the module name: `db`, `vectorstore`, `mcp`, `cli`, `episodic`, `semantic`, `working`, `consolidation`, `config`, `protocol`, `signals`, `quality`, `retrieval`, `graph`, `frontend`.

### Examples

```
feat(mcp): add neurosync_export tool for data portability

fix(db): handle corrupted JSON in episode metadata

Previously, malformed JSON in the files_touched column caused
_row_to_episode to crash. Now _from_json returns a typed fallback
(empty list for arrays, empty dict for objects).

test(consolidation): add tests for single-cluster fallback

docs: update README with user-level CLAUDE.md setup

chore: bump chromadb to 0.5.5

BREAKING CHANGE: removed neurosync_search tool, use neurosync_query instead
```

### Rules

- First line: 72 characters max.
- Use imperative mood: "add" not "added", "fix" not "fixes".
- Body: explain **why**, not what (the diff shows what).
- Reference issues: `Fixes #42` or `Closes #87` in the footer.

## Pull Requests

### Before you start coding

1. **Check for an existing issue.** If there isn't one, open one first to discuss the approach. This prevents wasted effort on changes that won't be merged.
2. **For large changes**, comment on the issue with your proposed approach before starting. Get a thumbs-up.
3. **One PR per concern.** Don't mix a bug fix with a feature. Don't sneak in refactoring with a docs change.

### PR workflow

```bash
# 1. Create your branch from main
git checkout main
git pull upstream main
git checkout -b feat/42-add-export-command

# 2. Make your changes
# ... code, test, lint ...

# 3. Ensure quality
pytest --cov=neurosync -v        # All tests pass
ruff check neurosync/            # No lint errors

# 4. Commit (see commit message format above)
git add <specific-files>
git commit -m "feat(cli): add export command for data portability

Adds `neurosync export` CLI command that dumps episodes and theories
to JSON for backup or migration purposes.

Fixes #42"

# 5. Push and open PR
git push origin feat/42-add-export-command
```

Then open a PR on GitHub. The PR template will guide you through the checklist.

### PR requirements

All of these must pass before merge:

- [ ] **Tests pass** — `pytest --cov=neurosync -v`
- [ ] **Lint clean** — `ruff check neurosync/`
- [ ] **Coverage >= 85%** — enforced in `pyproject.toml`
- [ ] **New code has tests** — no untested features
- [ ] **No new dependencies** without prior discussion in the issue
- [ ] **CI passes** — GitHub Actions runs tests on Python 3.9, 3.11, 3.12

### PR review process

1. A maintainer will review within a few days.
2. Expect feedback — it's not personal, it's about code quality.
3. Address review comments by pushing new commits (don't force-push during review).
4. Once approved, a maintainer will squash-merge into `main`.

### What makes a PR easy to review

- **Small and focused.** Under 300 lines changed is ideal. Over 500 needs a good reason.
- **Clear description.** What changed, why, how to test.
- **Tests included.** Reviewers shouldn't have to guess if it works.
- **One concern per PR.** Feature in one PR, refactor in another.

## Development Workflow

### Running tests

```bash
# Full suite with coverage
pytest --cov=neurosync -v

# Single file
pytest tests/test_db.py -v

# Single test
pytest tests/test_db.py::TestDatabase::test_from_json_corrupted -v

# With coverage report
pytest --cov=neurosync --cov-report=html -v
open htmlcov/index.html
```

### Linting

```bash
# Check for issues
ruff check neurosync/

# Auto-fix where possible
ruff check neurosync/ --fix

# Format
ruff format neurosync/
```

### Testing the MCP server locally

```bash
# Run the server directly (speaks JSON-RPC on stdin/stdout)
python -m neurosync.mcp_server

# Check status via CLI
neurosync status

# Test consolidation
neurosync consolidate --dry-run
```

## Code Style

- Follow `ruff` rules (configured in `.ruff.toml`).
- Python 3.9+ compatible — use `Optional[X]` not `X | None`, `dict[str, Any]` not `Dict[str, Any]`.
- No new external dependencies without discussion.
- Docstrings for public functions — one line if simple, Google style if complex.
- Type hints on function signatures.

## Testing

### Guidelines

- Use `pytest` with fixtures from `tests/conftest.py`.
- Tests use isolated temp directories — no real `~/.neurosync` state.
- Mock external boundaries (ChromaDB, filesystem), not internal pure functions.
- Test behavior, not implementation details.
- Aim for meaningful coverage, not 100% coverage of trivial code.

### Test file naming

```
tests/test_<module>.py         # e.g., tests/test_db.py
tests/test_<feature>.py        # e.g., tests/test_hardening.py
```

### Adding tests for a new feature

1. Add tests in the corresponding `test_<module>.py` file.
2. If the module doesn't have a test file yet, create one.
3. Prefer extending existing test files over creating new ones when the change belongs to the same unit.

## Architecture Overview

Read `docs/architecture.md` for the full design. Quick summary:

```
record -> episodes (SQLite + ChromaDB)
       -> auto-consolidation
       -> theories (SQLite + ChromaDB)
       -> recall (winner-take-all)
```

**Key principle:** SQLite is the source of truth. ChromaDB is an acceleration layer. Everything must work (in degraded mode) without ChromaDB.

### Module map

| Module | Layer | Responsibility |
|--------|-------|---------------|
| `db.py` | Storage | SQLite CRUD, migrations, JSON handling |
| `vectorstore.py` | Storage | ChromaDB wrapper, safe search |
| `episodic.py` | Layer 1 | Session/episode lifecycle |
| `semantic.py` | Layer 2 | Theory CRUD, confidence |
| `working.py` | Layer 3 | Recall with winner-take-all |
| `consolidation.py` | Engine | Cluster + extract + MDL prune |
| `mcp_server.py` | Interface | MCP JSON-RPC tool handlers |
| `cli.py` | Interface | CLI commands |
| `signals.py` | Scoring | Episode weight calculation |
| `quality.py` | Scoring | Episode quality scoring |
| `graph.py` | Storage | Neo4j knowledge graph sync & querying |
| `frontend/` | Visualization | React + TypeScript interactive graph viewer |

## What Not to Do

- **Don't add MCP tools without discussion.** The tool count is deliberate. Propose new capabilities as extensions to existing tools first.
- **Don't add external dependencies** without opening an issue. NeuroSync intentionally has minimal deps (chromadb, pyyaml).
- **Don't break Python 3.9 compatibility.** No walrus operators in required paths, no `X | None` union syntax.
- **Don't skip tests.** Every behavioral change needs a test.
- **Don't force-push to shared branches.** Rebase locally before pushing, but don't rewrite shared history.
- **Don't open PRs without a related issue** (except for typo fixes and tiny docs changes).
