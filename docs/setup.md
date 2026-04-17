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

## Reset

To clear all data:
```bash
neurosync reset --confirm
```
