# MCP Tools Reference

## neurosync_recall

Retrieve relevant context at session start.

**Parameters:**
- `project` (string, optional) — Auto-detected from git if omitted
- `branch` (string, optional) — Auto-detected from git if omitted
- `context` (string, optional) — Additional context for retrieval
- `max_tokens` (integer, default: 500) — Maximum output tokens

**Returns:** Primary theory, supporting theories, recent episodes, tokens used.

## neurosync_record

Record session episodes at session end.

**Parameters:**
- `events` (array, required) — Events to record. Each: `{type, content, files?, layers?}`
- `session_summary` (string, optional) — Summary of the session
- `project` (string, optional)
- `branch` (string, optional)
- `explicit_remember` (array of strings, optional) — High-weight memories

**Event types:** decision, discovery, correction, pattern, frustration, question, file_change, architecture, debugging, explicit

## neurosync_remember

Explicitly remember something with high signal weight (x10).

**Parameters:**
- `content` (string, required) — What to remember
- `type` (string, default: "explicit") — Event type

## neurosync_query

Semantic search across episodes and/or theories.

**Parameters:**
- `query` (string, required) — Search query
- `scope` (string, default: "all") — "all", "episodes", or "theories"
- `project` (string, optional)
- `limit` (integer, default: 10)

## neurosync_correct

Record an AI mistake with exponential weight.

**Parameters:**
- `wrong` (string, required) — What was wrong
- `right` (string, required) — What is correct
- `theory_id` (string, optional) — Theory to contradict

## neurosync_status

Health check — no parameters.

**Returns:** Episode, theory, contradiction counts; ChromaDB sizes; current session info.

## neurosync_theories

Browse, inspect, or retire theories.

**Parameters:**
- `action` (string, default: "list") — "list", "detail", or "retire"
- `scope` (string, optional) — "project", "domain", or "craft"
- `project` (string, optional)
- `theory_id` (string, optional) — Required for detail/retire
- `limit` (integer, default: 20)

## neurosync_consolidate

Trigger consolidation engine.

**Parameters:**
- `project` (string, optional) — Limit to project
- `dry_run` (boolean, default: false) — Preview only
