# NeuroSync

**A memory system for AI coding assistants.**

---

## Why Does This Exist?

AI coding assistants (Claude, Copilot, Cursor, etc.) have a big problem: **they forget everything between sessions.**

Every time you start a new conversation, it's like meeting someone with amnesia. You have to re-explain your project structure, remind it of your preferences, and watch it make the same mistakes it made yesterday. This gets worse the longer you work with AI:

- **Monday:** You correct the AI — "Don't use `unittest.mock`, we use `pytest` with `responses` in this project."
- **Tuesday:** It suggests `unittest.mock` again. You correct it again.
- **Wednesday:** Same thing. Again.

That's not learning. That's a tape recorder with no tape.

### "But what about CLAUDE.md / memory tools that already exist?"

Good question. There are existing solutions, but they have real problems:

| Existing approach | The problem |
|---|---|
| **CLAUDE.md / system prompts** | Static files you write by hand. The AI doesn't update them. They grow stale. You're doing the AI's homework for it. |
| **Long conversations** | Context windows have limits. Old messages get dropped. You can't carry knowledge across sessions. |
| **Mempalace (MCP)** | 29 tools (too many), adds ~$0.25/prompt overhead via hooks, stores 26k+ raw drawers of code/HTML that search tools handle better, uses emotional "AAAK" encoding irrelevant to developers, and never actually *learns* patterns — just stores raw data like a filing cabinet. |
| **Copy-pasting context** | You're doing manual labor that a machine should do. |

### What's different about NeuroSync?

NeuroSync doesn't just *store* things — it **learns**.

| | Mempalace / existing tools | NeuroSync |
|---|---|---|
| **Tool count** | 29 tools | 9 tools |
| **Per-prompt cost** | ~$0.25 overhead (hooks on every turn) | Zero — no hooks, no per-turn injection |
| **Storage strategy** | Stores everything raw (code, HTML, conversations) | Stores structured *events*, extracts *patterns* |
| **Learning** | None — just a filing cabinet | Clusters episodes, extracts theories, tracks confidence |
| **Mistakes** | Treated same as everything else | Exponentially weighted — corrections compound (2^N) |
| **Recall** | Returns a ranked list of matches | Winner-take-all — one clear answer, not a menu |
| **User awareness** | None | Tracks what you already know, doesn't re-explain it |

The core idea: **your AI assistant should get better at working with *you* over time, without you having to manually teach it.**

### What's automatic

- **Auto-consolidation** — theories are extracted automatically when enough episodes accumulate. No manual `consolidate` or cron jobs needed.
- **Passive git observation** — file changes and commits are recorded as low-weight "observed" episodes at session boundaries. The developer doesn't need to describe what they changed — NeuroSync sees it.
- **Dynamic protocol hints** — tool responses include contextual guidance based on session state (correction count, pending episodes).
- **Minimal protocol** — 3 rules instead of 125 lines. Run `neurosync generate-protocol` to get the CLAUDE.md snippet.

---

## What Does It Actually Do?

Imagine your brain has three types of memory:

1. **"What happened today" memory** (Episodic) — You remember that today you fixed a bug in the login page, chose PostgreSQL over MySQL, and got frustrated when the AI suggested the wrong testing library.

2. **"Things I've learned" memory** (Semantic) — After weeks of coding, you've noticed patterns: "This developer always wants TypeScript, not JavaScript" or "In this project, never touch the legacy auth module directly."

3. **"What's relevant right now" memory** (Working) — When you sit down to work on the payment system, your brain automatically pulls up everything you know about payments, not the unrelated stuff about the login page.

NeuroSync gives AI assistants all three of these memory types.

---

## How It Works (The Simple Version)

```
You work with AI  ──>  NeuroSync records what happened (episodes)
                              │
                              ▼
              After many sessions, it spots patterns
              and creates "theories" (things it learned)
                              │
                              ▼
        Next time you start working, it recalls
        the most relevant theory + recent context
```

**Not all events are remembered equally.** NeuroSync pays extra attention to:

| What happened | How much attention | Why |
|---|---|---|
| You corrected the AI | A LOT more each time (doubles!) | Mistakes matter most |
| You said "remember this" | 10x normal | You explicitly flagged it |
| Something contradicted a past lesson | 3x normal | Surprises update knowledge |
| You had to re-explain something | 5x normal | Repetition = the AI wasn't learning |
| Changes touched many code layers | More for deeper changes | Complex work = important work |

---

## The 9 Tools

NeuroSync connects to your AI assistant using MCP (a standard protocol). It provides exactly 9 tools — no more, no less:

| Tool | What it does | When it's used |
|---|---|---|
| `neurosync_recall` | "What do I know about this project?" | Start of a session |
| `neurosync_record` | "Here's what happened this session" | End of a session |
| `neurosync_remember` | "This is important — don't forget it" | When you say "remember this" |
| `neurosync_query` | "Search my memories for X" | When you need to look something up |
| `neurosync_correct` | "You got this wrong, here's the right answer" | When the AI makes a mistake |
| `neurosync_handoff` | "I'm handing off this task to the next session" | When a task spans multiple sessions |
| `neurosync_status` | "How's my memory doing?" | Health check |
| `neurosync_theories` | "Show me what I've learned" | Browse/manage learned patterns |
| `neurosync_consolidate` | "Review recent events and extract lessons" | Periodically (like studying) |

---

## Getting Started

### Option A: Install from PyPI (when published)

```bash
pip install neurosync
```

Then connect to Claude Code:

```bash
claude mcp add -s user neurosync -- python -m neurosync.mcp_server
```

### Option B: Install from GitHub (works right now)

```bash
# 1. Clone the repo
git clone https://github.com/FidaHussain87/neurosync.git
cd neurosync

# 2. Create a virtual environment (required — dependencies won't install globally)
python3 -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate

# 3. Install neurosync and its dependencies into the venv
pip install -e .
```

Now connect it to Claude Code. **Important:** use the full path to the venv's Python, not just `python`, so Claude Code can find the installed package:

```bash
# Replace /path/to/neurosync with wherever you cloned the repo
claude mcp add -s user neurosync -- /path/to/neurosync/.venv/bin/python -m neurosync.mcp_server
```

For example:
```bash
claude mcp add -s user neurosync -- /Users/yourname/neurosync/.venv/bin/python -m neurosync.mcp_server
```

> **Why `-s user`?** Without it, the MCP server is only available in the current project folder. With `-s user`, it's available in every project you open with Claude Code.

> **Why the full path to Python?** Claude Code runs the MCP server as a separate process. It doesn't know about your virtual environment, so you need to point it directly to the Python binary inside `.venv/` that has neurosync installed.

### Connect it to other AI tools (Cline, OpenCode, etc.)

Add this to your MCP configuration (use the full venv Python path):

```json
{
  "mcpServers": {
    "neurosync": {
      "command": "/path/to/neurosync/.venv/bin/python",
      "args": ["-m", "neurosync.mcp_server"]
    }
  }
}
```

### Verify it's connected

```bash
# Check the MCP server is registered and healthy
claude mcp list
```

You should see:
```
neurosync: /path/to/neurosync/.venv/bin/python -m neurosync.mcp_server - ✓ Connected
```

### Check memory status

```bash
neurosync status
```

You should see something like:

```json
{
  "database": {
    "sessions": 0,
    "episodes": { "total": 0, "pending": 0 },
    "theories": { "total": 0, "active": 0 }
  }
}
```

Zeros are normal — you haven't used it yet!

### Make Claude use NeuroSync automatically

NeuroSync is connected, but Claude won't use it proactively unless you tell it how. Add the minimal protocol to your project's `CLAUDE.md`:

```bash
# Option A: Generate and append
neurosync generate-protocol >> CLAUDE.md

# Option B: Generate a full CLAUDE.md for your project
neurosync generate-protocol --project "My App" > CLAUDE.md
```

Or copy-paste the minimal protocol manually:

```markdown
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
```

Copy-paste this into every project's `CLAUDE.md` where you want Claude to build up memory.

---

## Starter Packs

Don't want to start from zero? Import pre-built knowledge for your tech stack:

```bash
neurosync import-starter-pack python_developer
neurosync import-starter-pack perl_developer
neurosync import-starter-pack cloud_infra
neurosync import-starter-pack web_fullstack
```

These load common patterns and best practices as starter theories. NeuroSync will confirm, update, or retire them as it learns from your actual workflow.

---

## The Memory Lifecycle

Here's what happens over time:

### Week 1: Recording
You work normally. NeuroSync records episodes — decisions you made, bugs you found, corrections you gave the AI. These pile up in episodic memory.

### Week 2: Consolidation
NeuroSync auto-consolidates when enough episodes accumulate (20+ by default). You can also run `neurosync consolidate` manually. NeuroSync looks at all the episodes, groups similar ones together, and extracts "theories" — short statements about patterns it noticed.

For example, after seeing 5 episodes where you corrected the AI about your testing setup, it might create:

> **Theory** (confidence: 65%): "In this project, always use pytest with the --tb=short flag and mock external APIs with responses library, not unittest.mock"

### Week 3+: Recall
Now when you start a new session, `neurosync_recall` checks what theories are relevant to your current project and branch. It picks the single most relevant theory (winner-take-all — no information overload) and a couple of supporting ones, all within a small token budget.

### Ongoing: Confidence
Theories aren't static. They gain confidence when confirmed and lose it when contradicted. If nobody confirms a theory for 30+ days, its confidence slowly decays. Theories that drop below 5% confidence get automatically retired.

---

## Consolidation

Think of consolidation like studying after class. The AI reviews its notes (episodes) and creates study cards (theories).

**In v3, consolidation is automatic.** When enough unconsolidated episodes accumulate (20+ by default), NeuroSync runs consolidation during the next write operation (`record`, `remember`, or `correct`). No cron jobs, no manual intervention.

### Run it manually (optional)

```bash
neurosync consolidate
```

### Preview what it would do (without actually doing it)

```bash
neurosync consolidate --dry-run
```

---

## Configuration

### Where data lives

Everything is stored in `~/.neurosync/` by default:
- `neurosync.sqlite3` — structured data (sessions, episodes, theories)
- `chroma/` — vector embeddings for semantic search

### Override the data location

```bash
export NEUROSYNC_DATA_DIR=/path/to/your/data
```

### Full config file

Create `~/.neurosync/config.json` for fine-tuning:

```json
{
  "recall_max_tokens": 500,
  "consolidation_min_episodes": 5,
  "consolidation_similarity_threshold": 0.8,
  "theory_confidence_decay_days": 30,
  "theory_confidence_decay_rate": 0.01,
  "max_signal_weight": 1000.0,
  "auto_consolidation_enabled": true,
  "auto_consolidation_threshold": 20
}
```

| Setting | What it means | Default |
|---|---|---|
| `recall_max_tokens` | How much context to load at session start | 500 |
| `consolidation_min_episodes` | Minimum episodes before consolidation runs | 5 |
| `consolidation_similarity_threshold` | How similar episodes must be to cluster together (0-1) | 0.8 |
| `theory_confidence_decay_days` | Days without confirmation before confidence starts dropping | 30 |
| `theory_confidence_decay_rate` | How fast confidence drops per day after the grace period | 0.01 |
| `max_signal_weight` | Cap on how important a single episode can be | 1000 |
| `auto_consolidation_enabled` | Enable auto-consolidation on write operations | true |
| `auto_consolidation_threshold` | Number of pending episodes before auto-consolidation triggers | 20 |

---

## Project Structure

```
neurosync/
├── neurosync/                  # The main Python package
│   ├── mcp_server.py           # The MCP server (talks JSON-RPC over stdio)
│   ├── cli.py                  # Command-line interface
│   ├── config.py               # Settings management
│   ├── models.py               # Data structures (Session, Episode, Theory, etc.)
│   ├── db.py                   # SQLite database operations (with schema migrations)
│   ├── vectorstore.py          # ChromaDB for semantic search
│   ├── episodic.py             # Layer 1: session & episode management
│   ├── semantic.py             # Layer 2: theory management, confidence & linking
│   ├── working.py              # Layer 3: recall & winner-take-all
│   ├── consolidation.py        # Consolidation engine (causal extraction + auto-trigger)
│   ├── signals.py              # Signal weight calculations (8 types)
│   ├── quality.py              # Episode quality scoring
│   ├── hooks.py                # Claude Code auto-recall hook generation
│   ├── git_observer.py         # Passive git state observation
│   ├── protocol.py             # Minimal protocol text & CLAUDE.md generator
│   ├── user_model.py           # Tracks what you already know
│   ├── retrieval.py            # Full recall pipeline
│   ├── starter_pack_loader.py  # Loads YAML starter packs
│   └── starter_packs/          # Built-in theory packs (YAML files)
├── tests/                      # Test suite (~277 tests, 89%+ coverage)
├── docs/                       # Detailed documentation
├── pyproject.toml              # Package config
└── Dockerfile                  # Container support
```

---

## Tech Stack

| Component | Technology | Why |
|---|---|---|
| Language | Python 3.9+ | Widely available, good ecosystem |
| Structured storage | SQLite (WAL mode) | Zero setup, fast, thread-safe |
| Semantic search | ChromaDB | Local vector DB, cosine similarity |
| Transport | MCP JSON-RPC 2.0 over stdio | Standard protocol for AI tool integration |
| Build | hatchling | Modern Python packaging |
| Testing | pytest + pytest-cov | ~277 tests, 89%+ coverage |
| Linting | ruff | Fast, comprehensive |

---

## CLI Reference

```bash
neurosync serve                          # Start MCP server on stdio
neurosync status                         # Show memory stats
neurosync consolidate                    # Run the learning engine
neurosync consolidate --dry-run          # Preview without changing anything
neurosync consolidate --project myproj   # Only consolidate one project
neurosync import-starter-pack <name>     # Load a starter theory pack
neurosync generate-protocol              # Output minimal protocol for CLAUDE.md
neurosync generate-protocol --project X  # Generate full CLAUDE.md for project X
neurosync install-hook                   # Install auto-recall hook for Claude Code
neurosync install-hook --dry-run         # Preview hook installation
neurosync reset --confirm                # Delete ALL memory data (careful!)
```

---

## Development

### Setup

```bash
git clone <repo>
cd neurosync
pip install -e ".[dev]"
```

### Run tests

```bash
pytest --cov=neurosync -v
```

### Lint

```bash
ruff check neurosync/
```

### Run the MCP server directly

```bash
python -m neurosync.mcp_server
```

---

## Docker

```bash
docker build -t neurosync .
docker run -v ~/.neurosync:/data neurosync
```

---

## FAQ

**Q: Does this send my code to the cloud?**
A: No. Everything runs locally. SQLite and ChromaDB are both local storage. No network calls.

**Q: How is this different from just having a long conversation?**
A: Conversations get lost. NeuroSync persists across sessions, learns patterns over time, and only recalls what's relevant — instead of dumping everything into context.

**Q: What if it learns something wrong?**
A: Use `neurosync_correct` to flag mistakes (they get exponentially weighted), or use `neurosync_theories` to manually retire bad theories. Theories also decay naturally if never confirmed.

**Q: How much disk space does it use?**
A: Very little. SQLite is compact, and ChromaDB embeddings are small. Even after months of heavy use, expect under 100MB.

**Q: Can I use this with AI tools other than Claude Code?**
A: Yes — anything that supports MCP (Model Context Protocol). Add the server config to your tool's MCP settings.

---

## Publishing to PyPI

If you want to publish a new version to PyPI (so `pip install neurosync` works for everyone):

### One-time setup

1. Create an account at [pypi.org](https://pypi.org/account/register/)
2. Go to Account Settings → API tokens → "Add API token"
3. Set scope to "Entire account" (for first upload) or "Project: neurosync" (after first upload)
4. Save the token somewhere safe — you'll only see it once

### Install the publishing tools

```bash
pip install build twine
```

### Publish a release

```bash
# 1. Update the version number
#    Edit neurosync/version.py → change __version__ = "0.4.0" (or whatever)

# 2. Build the package (creates dist/ folder with .tar.gz and .whl files)
python -m build

# 3. Check the package looks correct before uploading
twine check dist/*

# 4. Upload to PyPI (will ask for credentials)
twine upload dist/*
#    Username: __token__
#    Password: pypi-AgEIcH... (paste your API token)
```

After uploading, anyone in the world can install it with:

```bash
pip install neurosync
```

### Test on TestPyPI first (optional, recommended for first time)

If you want to test the process without publishing to the real PyPI:

```bash
# Upload to the test server
twine upload --repository testpypi dist/*

# Install from the test server to verify it works
pip install --index-url https://test.pypi.org/simple/ neurosync
```

### Publishing checklist

- [ ] Version bumped in `neurosync/version.py`
- [ ] All tests pass: `pytest --cov=neurosync -v`
- [ ] Lint clean: `ruff check neurosync/`
- [ ] Clean build folder: `rm -rf dist/ build/ *.egg-info`
- [ ] Build: `python -m build`
- [ ] Check: `twine check dist/*`
- [ ] Upload: `twine upload dist/*`
- [ ] Verify: `pip install neurosync` in a fresh virtualenv
- [ ] Tag the release: `git tag v0.4.0 && git push --tags`

---

## License

MIT — do whatever you want with it.
