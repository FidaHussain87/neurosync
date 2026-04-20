# Setup Guide

## Installation

```bash
pip install neurosync
```

For development:
```bash
git clone <repo>
cd neurosync
pip install -e ".[dev]"
```

## Claude Code Integration

```bash
claude mcp add neurosync -- python -m neurosync.mcp_server
```

## Cline / OpenCode

Add to your MCP config:

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

## Docker

```bash
docker build -t neurosync .
docker run -v ~/.neurosync:/data neurosync
```

## Automated Consolidation

Add to crontab:

```bash
0 2 * * * python -m neurosync consolidate >> ~/.neurosync/consolidation.log 2>&1
```

## Starter Packs

Bootstrap with pre-built theories:

```bash
neurosync import-starter-pack python_developer
neurosync import-starter-pack perl_developer
neurosync import-starter-pack cloud_infra
neurosync import-starter-pack web_fullstack
```

## Configuration

Environment variables:
- `NEUROSYNC_DATA_DIR` — Data directory (default: `~/.neurosync`)
- `NEUROSYNC_DEFAULT_PROJECT` — Default project name
- `NEUROSYNC_DEFAULT_BRANCH` — Default branch name
- `NEUROSYNC_DB_BACKEND` — Database backend: `sqlite` (default) or `postgresql`
- `NEUROSYNC_PG_DSN` — PostgreSQL connection string (when using postgresql backend)

Config file (`~/.neurosync/config.json`):
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

## PostgreSQL Backend (Optional)

By default, NeuroSync uses SQLite. To switch to PostgreSQL:

### Install the driver

```bash
pip install neurosync[postgresql]
# or directly:
pip install psycopg2-binary
```

### Option A: Local PostgreSQL (Homebrew / pgAdmin)

If PostgreSQL is already installed locally (via Homebrew, pgAdmin, Postgres.app, etc.):

```bash
# Create the database
createdb neurosync

# Verify it works
psql -d neurosync -c "SELECT current_database();"
```

Set the environment variables (add to `~/.zshrc` or `~/.bashrc`):

```bash
export NEUROSYNC_DB_BACKEND="postgresql"
export NEUROSYNC_PG_DSN="postgresql://yourusername@localhost:5432/neurosync"
```

Replace `yourusername` with your system username (run `whoami` to check). If your PostgreSQL requires a password:

```bash
export NEUROSYNC_PG_DSN="postgresql://yourusername:yourpassword@localhost:5432/neurosync"
```

### Option B: Docker

```bash
docker run -d --name neurosync-pg -p 5432:5432 \
  -e POSTGRES_DB=neurosync -e POSTGRES_PASSWORD=neurosync postgres:16

export NEUROSYNC_DB_BACKEND="postgresql"
export NEUROSYNC_PG_DSN="postgresql://postgres:neurosync@localhost:5432/neurosync"
```

### Verify

```bash
# Reload shell config
source ~/.zshrc

# Check NeuroSync connects to PostgreSQL
neurosync status
```

NeuroSync automatically creates all 13 tables on first connection. If PostgreSQL is unreachable, it falls back to SQLite with a warning.

> **Security note:** `NEUROSYNC_PG_DSN` is only read from environment variables, never from `config.json`. This prevents accidental commits of credentials.

## Neo4j Knowledge Graph (Optional)

```bash
# Install the Neo4j driver
pip install neurosync[neo4j]

# Start Neo4j with Docker
docker run -d --name neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/neurosync123 neo4j:5

# Set the password
export NEUROSYNC_NEO4J_PASSWORD="neurosync123"

# Sync your memory to the graph
neurosync graph-sync
```

## Frontend Visualization (Optional)

The interactive graph visualization connects directly to Neo4j and renders your knowledge graph as a cosmological universe.

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, enter your Neo4j credentials (same as above), and click **Load Overview**.

For production builds:
```bash
npm run build     # outputs to frontend/dist/
npm run preview   # preview the production build
```

## Reset

To clear all data:
```bash
neurosync reset --confirm
```
