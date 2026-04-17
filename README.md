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
| **Tool count** | 29 tools | 8 tools |
| **Per-prompt cost** | ~$0.25 overhead (hooks on every turn) | Zero — no hooks, no per-turn injection |
| **Storage strategy** | Stores everything raw (code, HTML, conversations) | Stores structured *events*, extracts *patterns* |
| **Learning** | None — just a filing cabinet | Clusters episodes, extracts theories, tracks confidence |
| **Mistakes** | Treated same as everything else | Exponentially weighted — corrections compound (2^N) |
| **Recall** | Returns a ranked list of matches | Winner-take-all — one clear answer, not a menu |
| **User awareness** | None | Tracks what you already know, doesn't re-explain it |

The core idea: **your AI assistant should get better at working with *you* over time, without you having to manually teach it.**

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

## The 8 Tools

NeuroSync connects to your AI assistant using MCP (a standard protocol). It provides exactly 8 tools — no more, no less:

| Tool | What it does | When it's used |
|---|---|---|
| `neurosync_recall` | "What do I know about this project?" | Start of a session |
| `neurosync_record` | "Here's what happened this session" | End of a session |
| `neurosync_remember` | "This is important — don't forget it" | When you say "remember this" |
| `neurosync_query` | "Search my memories for X" | When you need to look something up |
| `neurosync_correct` | "You got this wrong, here's the right answer" | When the AI makes a mistake |
| `neurosync_status` | "How's my memory doing?" | Health check |
| `neurosync_theories` | "Show me what I've learned" | Browse/manage learned patterns |
| `neurosync_consolidate` | "Review recent events and extract lessons" | Periodically (like studying) |

---

## Getting Started

### Install it

```bash
pip install neurosync
```

### Connect it to Claude Code

```bash
claude mcp add neurosync -- python -m neurosync.mcp_server
```

That's it. Now when you use Claude Code, it has access to NeuroSync's memory tools.

### Connect it to other AI tools (Cline, OpenCode, etc.)

Add this to your MCP configuration:

```json
{
  "mcpServers": {
    "neurosync": {
      "command": "python",
      "args": ["-m", "neurosync.mcp_server"]
    }
  }
}
```

### Check that it's working

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
You run `neurosync consolidate` (or set up a nightly cron job). NeuroSync looks at all the episodes, groups similar ones together, and extracts "theories" — short statements about patterns it noticed.

For example, after seeing 5 episodes where you corrected the AI about your testing setup, it might create:

> **Theory** (confidence: 65%): "In this project, always use pytest with the --tb=short flag and mock external APIs with responses library, not unittest.mock"

### Week 3+: Recall
Now when you start a new session, `neurosync_recall` checks what theories are relevant to your current project and branch. It picks the single most relevant theory (winner-take-all — no information overload) and a couple of supporting ones, all within a small token budget.

### Ongoing: Confidence
Theories aren't static. They gain confidence when confirmed and lose it when contradicted. If nobody confirms a theory for 30+ days, its confidence slowly decays. Theories that drop below 5% confidence get automatically retired.

---

## Consolidation

Think of consolidation like studying after class. The AI reviews its notes (episodes) and creates study cards (theories).

### Run it manually

```bash
neurosync consolidate
```

### Run it automatically every night at 2 AM

Add this to your crontab (`crontab -e`):

```bash
0 2 * * * python -m neurosync consolidate >> ~/.neurosync/consolidation.log 2>&1
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
  "max_signal_weight": 1000.0
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

---

## Project Structure

```
neurosync/
├── neurosync/                  # The main Python package
│   ├── mcp_server.py           # The MCP server (talks JSON-RPC over stdio)
│   ├── cli.py                  # Command-line interface
│   ├── config.py               # Settings management
│   ├── models.py               # Data structures (Session, Episode, Theory, etc.)
│   ├── db.py                   # SQLite database operations
│   ├── vectorstore.py          # ChromaDB for semantic search
│   ├── episodic.py             # Layer 1: session & episode management
│   ├── semantic.py             # Layer 2: theory management & confidence
│   ├── working.py              # Layer 3: recall & winner-take-all
│   ├── consolidation.py        # The "studying" engine
│   ├── signals.py              # Signal weight calculations
│   ├── user_model.py           # Tracks what you already know
│   ├── retrieval.py            # Full recall pipeline
│   ├── starter_pack_loader.py  # Loads YAML starter packs
│   └── starter_packs/          # Built-in theory packs (YAML files)
├── tests/                      # Test suite (121 tests, 88%+ coverage)
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
| Testing | pytest + pytest-cov | 121 tests, 88%+ coverage |
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

## License

MIT — do whatever you want with it.
