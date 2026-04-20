"""Minimal protocol for NeuroSync v3 — 3 rules instead of 125 lines."""

from __future__ import annotations

MINIMAL_PROTOCOL = """\
## NeuroSync Memory Protocol

NeuroSync gives you persistent memory across sessions via 10 MCP tools. \
Most behavior is automatic (auto-consolidation, passive git observation). \
Follow these 3 rules:

### Rule 1: Follow recalled theories as ground truth

Call `neurosync_recall` at session start. Apply recalled theories like a \
style guide — they are confirmed lessons from past sessions, not suggestions. \
Check for continuation episodes from previous sessions.

### Rule 2: Record corrections immediately

When corrected, call `neurosync_correct` with what was wrong and what's right. \
Corrections compound exponentially (2^N) — they are the most valuable signal.

### Rule 3: Record decisions at session end

Call `neurosync_record` with structured episodes when the session ends. \
Write causal statements (why, not what). Use `neurosync_handoff` for \
multi-session tasks.

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

- **Auto-consolidation** — theories are extracted automatically when enough \
episodes accumulate (no manual `consolidate` needed)
- **Passive git observation** — file changes and commits are recorded as \
low-weight episodes automatically
- **Dynamic hints** — tool responses include contextual guidance\
"""


def generate_protocol_section() -> str:
    """Return the minimal protocol as a markdown section."""
    return MINIMAL_PROTOCOL


def generate_claude_md(project_name: str = "your project") -> str:
    """Generate a complete minimal CLAUDE.md with the NeuroSync protocol."""
    return f"# {project_name} — AI Agent Instructions\n\n{MINIMAL_PROTOCOL}\n"
