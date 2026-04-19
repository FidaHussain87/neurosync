---
name: neurosync
description: Run NeuroSync memory system commands — status, consolidate, recall, remember, query, theories, graph-sync, graph-status, reset
disable-model-invocation: true
allowed-tools: Bash(neurosync *) mcp__neurosync__*
argument-hint: "[status|consolidate|recall|remember|query|theories|graph-sync|graph-status|reset]"
---

# NeuroSync Skill

Run NeuroSync commands to manage persistent AI memory.

## Command Routing

Based on `$ARGUMENTS`, do the following:

### `status` — Show memory health
```bash
neurosync status
```
Display the result in a readable table.

### `consolidate` — Trigger theory extraction
Run a dry run first, then consolidate if there are pending episodes:
```bash
neurosync consolidate --dry-run
```
If there are episodes to consolidate, ask the user if they want to proceed, then run:
```bash
neurosync consolidate
```

### `recall` — Load project memory
Call the MCP tool `neurosync_recall` with the current project and branch context. Apply recalled theories as ground truth for this session.

### `remember` — Store an important fact
Call the MCP tool `neurosync_remember` with the text provided after "remember":
- Content: everything after the word "remember" in `$ARGUMENTS`
- Set `importance` to 4 (high)
- Include `reasoning` explaining why this is worth remembering

### `query` — Search memories
Call the MCP tool `neurosync_query` with the text provided after "query":
- Query: everything after the word "query" in `$ARGUMENTS`
- Default mode: `semantic`
- If the query starts with `failures:`, use mode `failures`
- If the query starts with `causal:`, use mode `causal`
- If the query starts with `analogy:`, use mode `analogy`

### `theories` — Browse learned patterns
Call the MCP tool `neurosync_theories` with `action: list`. Display results in a readable format showing theory content, confidence, and confirmation count.

### `graph-sync` — Sync memory data to Neo4j knowledge graph
Syncs all sessions, episodes, theories, concepts, contradictions, failures, patterns, and user knowledge from SQLite/ChromaDB into the Neo4j knowledge graph for visualization.
```bash
neurosync graph-sync
```
Display the sync summary (nodes and relationships created/updated). If it fails with "neo4j package not installed", tell the user to run `pip install neurosync[neo4j]`.

### `graph-status` — Check Neo4j knowledge graph health
```bash
neurosync graph-status
```
Display the connection status, node counts by type, and relationship counts.

### `reset` — Clear all memory data
**Dangerous operation.** Warn the user, then if they confirm:
```bash
neurosync reset --confirm
```

### No arguments / help
If `$ARGUMENTS` is empty, show this quick reference:

```
/neurosync status        — Show memory health (sessions, episodes, theories)
/neurosync consolidate   — Extract theories from pending episodes
/neurosync recall        — Load project memory for this session
/neurosync remember <text> — Store an important fact
/neurosync query <text>  — Search memories (prefix: failures: causal: analogy:)
/neurosync theories      — Browse all learned patterns
/neurosync graph-sync    — Sync memory to Neo4j knowledge graph
/neurosync graph-status  — Check Neo4j graph health and counts
/neurosync reset         — Clear all memory data (dangerous)
```
