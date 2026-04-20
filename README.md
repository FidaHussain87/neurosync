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
| **Tool count** | 29 tools | 10 tools |
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

## The 10 Tools

NeuroSync connects to your AI assistant using MCP (a standard protocol). It provides 10 tools:

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
| `neurosync_graph` | "Show me the knowledge graph" | Query/sync Neo4j graph (optional) |

---

## Getting Started

### Option A: Install from PyPI (when published)

```bash
pip install neurosync

# Optional: install with Neo4j knowledge graph support
pip install neurosync[neo4j]
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

NeuroSync is connected, but Claude won't use it proactively unless you tell it how. You need to add the protocol to a file Claude Code reads. There are three options — pick the one that fits your situation:

#### Minimal vs Full protocol

NeuroSync ships with two protocol versions:

| Version | Rules | Best for |
|---------|-------|----------|
| **Minimal** (3 rules) | recall, correct, record | Quick start, `generate-protocol` output |
| **Full** (7 rules) | + query-before-guess, proactive remember, handoff, consult theories | Power users who want maximum memory quality |

The full protocol is in [`docs/protocol-full.md`](docs/protocol-full.md) — it teaches Claude about signal weighting, episode quality scoring, causal language, and all 9 tools. Copy it directly into your `~/.claude/CLAUDE.md` for the best experience.

#### Option A: User-level (recommended — all projects, no git noise)

Place the protocol in your **user-level** `CLAUDE.md`. This lives outside any git repo, applies to every project on your machine, and never shows up in `git diff`:

```bash
# Minimal (3 rules):
neurosync generate-protocol >> ~/.claude/CLAUDE.md

# Full (7 rules, recommended):
# Copy the content from docs/protocol-full.md (everything below the --- line)
# into ~/.claude/CLAUDE.md
```

This is the best option when:
- You're the only one using NeuroSync on the team
- You want memory across all your projects without touching each repo
- The project's `CLAUDE.md` is shared/tracked and you don't want to modify it

#### Option B: Project-level, git-tracked (team-shared)

Append to your project's `CLAUDE.md` so the whole team gets the protocol:

```bash
neurosync generate-protocol >> CLAUDE.md
```

Use this when the entire team uses NeuroSync.

#### Option C: Project-level, git-ignored (personal, per-project)

Create a `CLAUDE.local.md` in the project root. Claude Code reads it alongside `CLAUDE.md`, but you add it to `.gitignore` so it stays personal:

```bash
neurosync generate-protocol > CLAUDE.local.md
echo "CLAUDE.local.md" >> .gitignore
```

Use this when you want NeuroSync only in specific projects and don't want to modify the shared `CLAUDE.md`, but also don't want it globally via `~/.claude/CLAUDE.md`.

> **Note:** If `CLAUDE.local.md` is a new entry in `.gitignore`, the `.gitignore` change itself will show in `git diff`. If you can't modify `.gitignore` either, use Option A (user-level) instead.

#### How Claude Code loads instructions (precedence)

Claude Code reads instruction files in this order (later files take precedence):

| Scope | Location | Git-tracked? |
|-------|----------|-------------|
| Project | `./CLAUDE.md` or `./.claude/CLAUDE.md` | Yes — shared with team |
| User | `~/.claude/CLAUDE.md` | No — your home directory |
| Local | `./CLAUDE.local.md` | No — if added to `.gitignore` |

All files are loaded and concatenated. You don't need to pick just one — they stack.

#### The protocol (for manual copy-paste)

If you prefer to copy-paste instead of using `generate-protocol`:

```markdown
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

- **Auto-consolidation** — theories are extracted automatically when enough episodes accumulate (no manual `consolidate` needed)
- **Passive git observation** — file changes and commits are recorded as low-weight episodes automatically
- **Dynamic hints** — tool responses include contextual guidance
```

---

## Optional: Add the `/neurosync` Slash Command

The MCP server gives Claude the tools. The slash command gives **you** a shortcut to run NeuroSync commands directly from the chat:

```
/neurosync status                           # Memory health check
/neurosync consolidate                      # Extract theories from episodes
/neurosync recall                           # Load memory for this session
/neurosync remember always use pytest here  # Store a fact
/neurosync query how do we handle auth      # Search memories
/neurosync theories                         # Browse learned patterns
/neurosync reset                            # Clear all data (careful!)
```

### Quick setup (2 commands)

```bash
# 1. Create the skill directory
mkdir -p ~/.claude/skills/neurosync

# 2. Copy the skill file from the repo
cp /path/to/neurosync/skills/neurosync/SKILL.md ~/.claude/skills/neurosync/SKILL.md
```

Replace `/path/to/neurosync` with wherever you cloned the repo. For example:

```bash
cp ~/neurosync/skills/neurosync/SKILL.md ~/.claude/skills/neurosync/SKILL.md
```

Or download it directly without cloning:

```bash
mkdir -p ~/.claude/skills/neurosync
curl -o ~/.claude/skills/neurosync/SKILL.md \
  https://raw.githubusercontent.com/FidaHussain87/neurosync/main/skills/neurosync/SKILL.md
```

Start a new Claude Code session and type `/neurosync` — it should autocomplete.

> **This is optional.** The MCP tools work without the skill. The skill just gives you a convenient `/neurosync` shortcut instead of waiting for Claude to call the tools or switching to a terminal. See [`docs/skill-setup.md`](docs/skill-setup.md) for the full setup guide with troubleshooting.

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

## PostgreSQL Backend (Optional)

By default, NeuroSync uses SQLite — zero setup, perfect for single-developer use. For production deployments or when you want a more robust database, you can switch to PostgreSQL.

### Install the PostgreSQL driver

```bash
pip install neurosync[postgresql]
```

### Start PostgreSQL (if not running)

```bash
docker run -d --name neurosync-pg -p 5432:5432 \
  -e POSTGRES_DB=neurosync -e POSTGRES_PASSWORD=neurosync postgres:16
```

### Configure NeuroSync to use PostgreSQL

```bash
export NEUROSYNC_DB_BACKEND="postgresql"
export NEUROSYNC_PG_DSN="postgresql://postgres:neurosync@localhost:5432/neurosync"
```

NeuroSync automatically creates all tables on first connection. If PostgreSQL is unreachable, it falls back to SQLite.

> **Security note:** The PostgreSQL connection string (`NEUROSYNC_PG_DSN`) is only read from environment variables, never from `config.json`. This prevents accidental commits of credentials.

---

## Neo4j Knowledge Graph (Optional)

NeuroSync can sync its memory to a Neo4j graph database, letting you visualize episodes, theories, causal chains, and their connections as an interactive knowledge graph — like neurons connected to ideas, events, and patterns.

**This is entirely optional.** NeuroSync works fully without Neo4j. The graph is a read-only visualization and query layer; SQLite remains the sole source of truth.

### Install the Neo4j driver

```bash
# If you installed from PyPI:
pip install neurosync[neo4j]

# If you installed from source:
pip install -e ".[neo4j]"

# Or install the driver directly:
pip install neo4j>=5.0
```

### Start Neo4j locally with Docker

```bash
docker run -d \
  --name neo4j \
  -p 7474:7474 \
  -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/neurosync123 \
  neo4j:5
```

This starts Neo4j Community Edition with:
- **Browser UI** at http://localhost:7474 (for visual graph exploration)
- **Bolt protocol** at bolt://localhost:7687 (for programmatic access)
- Default credentials: `neo4j` / `neurosync123`

### Configure the connection

Set these environment variables (or add to `~/.neurosync/config.json`):

```bash
export NEUROSYNC_NEO4J_URI="bolt://localhost:7687"    # default
export NEUROSYNC_NEO4J_USER="neo4j"                    # default
export NEUROSYNC_NEO4J_PASSWORD="neurosync123"         # required — no default
export NEUROSYNC_NEO4J_DATABASE="neo4j"                # default
```

> **Security note:** The password is only read from environment variables, never from `config.json`. This prevents accidental commits of credentials.

| Setting | Environment variable | Default |
|---|---|---|
| URI | `NEUROSYNC_NEO4J_URI` | `bolt://localhost:7687` |
| User | `NEUROSYNC_NEO4J_USER` | `neo4j` |
| Password | `NEUROSYNC_NEO4J_PASSWORD` | (none — must be set) |
| Database | `NEUROSYNC_NEO4J_DATABASE` | `neo4j` |

### Sync your memory to the graph

```bash
# Sync all data
neurosync graph-sync

# Sync only one project
neurosync graph-sync --project myproj

# Check graph health
neurosync graph-status
```

Sync is **idempotent** — run it as often as you like. It uses `MERGE` operations so existing nodes are updated, not duplicated. Stale nodes (deleted from SQLite but still in Neo4j) are cleaned up automatically.

### What's in the graph

The sync creates these node types and relationships:

| Node | What it represents |
|------|-------------------|
| `Session` | A coding session with project, branch, timestamps |
| `Episode` | An event within a session (decision, discovery, correction, etc.) |
| `Theory` | A learned pattern with confidence score |
| `Concept` | A cause or effect in the causal graph |
| `StructuralPattern` | A recurring code/architecture pattern |
| `FailureRecord` | A known anti-pattern or past mistake |
| `Contradiction` | A theory that was contradicted |
| `UserKnowledge` | A topic the user has been exposed to |

Key relationships include `CONTAINS` (session→episode), `EXTRACTED_FROM` (theory→episode), `CAUSES` (concept→concept), `PARENT_OF` (theory hierarchy), and more.

### Explore in Neo4j Browser

Open http://localhost:7474 in your browser and run Cypher queries:

```cypher
-- See everything
MATCH (n) RETURN n LIMIT 100

-- Active theories and their relationships
MATCH (t:Theory {active: true})-[r]->(other)
RETURN t, r, other

-- Causal chains
MATCH (cause:Concept)-[r:CAUSES]->(effect:Concept)
RETURN cause.text, r.mechanism, effect.text, r.strength
ORDER BY r.strength DESC

-- How episodes became theories
MATCH (e:Episode)<-[:EXTRACTED_FROM]-(t:Theory)
RETURN t.content, collect(e.content) AS source_episodes
```

### Use via MCP tool

The `neurosync_graph` tool lets your AI assistant query the graph directly:

```
# Check graph status
neurosync_graph action=status

# List pre-built queries
neurosync_graph action=prebuilt

# Run a pre-built query
neurosync_graph action=prebuilt prebuilt_name=causal_chains

# Run a custom Cypher query (read-only)
neurosync_graph action=query cypher="MATCH (t:Theory) RETURN t.content, t.confidence ORDER BY t.confidence DESC LIMIT 5"

# Sync from within a session
neurosync_graph action=sync
```

> **Safety:** The MCP tool only allows read-only Cypher queries. Write operations (`CREATE`, `DELETE`, `SET`, `MERGE`, `DROP`, etc.) are blocked.

### Interactive Frontend Visualization

NeuroSync includes a standalone web frontend that connects directly to your Neo4j instance and renders the knowledge graph as an interactive cosmological visualization — zoom out to see clusters like nebulae, zoom in to explore individual nodes like stars and planets.

#### Quick start

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, enter your Neo4j credentials, and click **Load Overview**.

#### Tech stack

| Component | Technology |
|-----------|-----------|
| UI | React 18 + TypeScript |
| Build | Vite 5.x |
| Graph rendering | react-force-graph-2d (canvas-based) |
| Community detection | graphology + Louvain algorithm |
| Neo4j connection | neo4j-driver 5.x (direct Bolt WebSocket) |
| Styling | Tailwind CSS 3.4 (dark theme) |

#### Features

- **Multi-layer parallax star field** — screen-space stars with depth layers, color temperature variation, twinkling, and diffraction spikes
- **Space-time fabric** — gravitational curvature lines near massive nodes (Theory, Session, Concept)
- **Mass-weighted physics** — node types have different gravitational mass affecting force simulation
- **Cluster view** — zoom out below 3x to see Louvain-detected communities as nebula clusters
- **Progressive loading** — overview on connect, expand neighbors on click, full replace on query
- **12 pre-built Cypher queries** — theory network, causal chains, failure hotspots, contradiction analysis, and more
- **Custom Cypher** — run any read-only Cypher query and visualize the result
- **Detail panel** — click any node to see its properties, confidence bars, connections, and navigate to related nodes

#### Production build

```bash
cd frontend
npm run build    # outputs to frontend/dist/
npm run preview  # preview the production build
```

### Graceful degradation

If the Neo4j driver isn't installed or the server isn't running:
- All other NeuroSync features continue to work normally
- The `neurosync_graph` MCP tool returns a friendly "Neo4j not available" message
- The `graph-sync` and `graph-status` CLI commands print an error and exit
- `neurosync status` shows `"graph": {"healthy": false, "error": "..."}` in its output

---

## Project Structure

```
neurosync/
├── neurosync/                  # The main Python package
│   ├── mcp_server.py           # The MCP server (talks JSON-RPC over stdio, 10 tools)
│   ├── cli.py                  # Command-line interface
│   ├── config.py               # Settings management (env > config.json > defaults)
│   ├── models.py               # Data structures (Session, Episode, Theory, etc.)
│   ├── db.py                   # SQLite database (WAL mode, migrations) — default backend
│   ├── pg_db.py                # PostgreSQL database (connection pooling, JSONB) — optional backend
│   ├── vectorstore.py          # ChromaDB for semantic search
│   ├── episodic.py             # Layer 1: session & episode management, signal computation
│   ├── semantic.py             # Layer 2: theory management, confidence & linking
│   ├── working.py              # Layer 3: recall & winner-take-all
│   ├── retrieval.py            # Full recall pipeline with familiarity filtering & parent context
│   ├── user_model.py           # Topic familiarity tracking & meta-learning
│   ├── consolidation.py        # Consolidation engine (TF-IDF + causal merge + auto-trigger)
│   ├── signals.py              # Signal weight calculations (7 active + 1 unwired)
│   ├── quality.py              # Episode quality scoring (0-7 scale)
│   ├── forgetting.py           # Ebbinghaus decay, spaced repetition, active pruning
│   ├── analogy.py              # Structural fingerprinting, semantic+structural search
│   ├── failure.py              # Failure records, proactive warnings, anti-patterns
│   ├── hierarchy.py            # Theory hierarchy traversal, semantic parents, merging
│   ├── causal.py               # Causal graph construction, querying, semantic fallback
│   ├── hooks.py                # Claude Code auto-recall hook generation
│   ├── git_observer.py         # Passive git state observation
│   ├── protocol.py             # Minimal protocol text & CLAUDE.md generator
│   ├── starter_pack_loader.py  # Loads YAML starter packs
│   ├── graph.py                # Optional Neo4j knowledge graph sync & querying
│   └── starter_packs/          # Built-in theory packs (YAML files)
├── tests/                      # Test suite (~368 tests, 86%+ coverage)
├── frontend/                   # Interactive graph visualization (React + TypeScript)
│   ├── src/
│   │   ├── components/         # GraphCanvas, Sidebar, DetailPanel, QueryRunner, ConnectionForm
│   │   ├── hooks/              # useNeo4jConnection, useGraphData
│   │   ├── services/           # Neo4j driver wrapper and query extraction
│   │   ├── types.ts            # GraphNode, GraphLink, GraphData interfaces
│   │   └── constants.ts        # Node/link styles, 12 pre-built Cypher queries
│   ├── package.json            # React 18, react-force-graph-2d, neo4j-driver, Tailwind
│   └── vite.config.ts          # Vite 5.x with chunk splitting
├── docs/                       # Detailed documentation
├── pyproject.toml              # Package config
└── Dockerfile                  # Container support
```

---

## Tech Stack

| Component | Technology | Why |
|---|---|---|
| Language | Python 3.9+ | Widely available, good ecosystem |
| Structured storage | SQLite (WAL mode, default) or PostgreSQL (optional) | Zero setup default, production-grade optional |
| Semantic search | ChromaDB | Local vector DB, cosine similarity |
| Knowledge graph | Neo4j (optional) | Visualize memory as a connected graph |
| Graph frontend | React 18 + react-force-graph-2d | Interactive cosmological graph visualization |
| Transport | MCP JSON-RPC 2.0 over stdio | Standard protocol for AI tool integration |
| Build | hatchling | Modern Python packaging |
| Testing | pytest + pytest-cov | ~368 tests, 86%+ coverage |
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
neurosync graph-sync                     # Sync SQLite data to Neo4j knowledge graph
neurosync graph-sync --project myproj    # Sync only one project
neurosync graph-status                   # Show Neo4j graph health and stats
neurosync reset --confirm                # Delete ALL memory data (careful!)
```

---

## Development

### Setup

```bash
git clone <repo>
cd neurosync
pip install -e ".[dev]"

# Optional extras:
pip install -e ".[dev,neo4j]"          # With Neo4j knowledge graph support
pip install -e ".[dev,postgresql]"      # With PostgreSQL backend support
pip install -e ".[dev,neo4j,postgresql]" # All optional features
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

**Q: Do I need Neo4j?**
A: No. Neo4j is completely optional — it's a visualization and query layer. NeuroSync works fully with just SQLite and ChromaDB. Install `neurosync[neo4j]` and run a local Neo4j instance only if you want to explore your memory as an interactive graph.

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
#    Edit neurosync/version.py → change __version__ = "0.5.0" (or whatever)

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
- [ ] Tag the release: `git tag v0.5.0 && git push --tags`

---

## License

MIT — do whatever you want with it.
