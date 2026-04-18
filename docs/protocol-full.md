# NeuroSync Full Protocol — For ~/.claude/CLAUDE.md

> **How to use this file:** Copy the content below into your `~/.claude/CLAUDE.md` (user-level, applies to all projects) or into a project's `CLAUDE.local.md` (per-project, gitignored). This is the comprehensive 7-rule protocol that teaches Claude how to use all NeuroSync capabilities effectively.
>
> For placement options, see the [README setup section](../README.md#make-claude-use-neurosync-automatically).

---

## NeuroSync Memory Protocol

NeuroSync gives you persistent memory across sessions via 9 MCP tools. It uses a three-layer architecture: **episodic** (raw session events in SQLite + ChromaDB), **semantic** (consolidated theories with confidence scores), **working** (context-aware recall via winner-take-all activation). Most behavior is automatic. Follow these 7 rules:

### Rule 1: Recall at session start

Call `neurosync_recall` at the very beginning of every session. Apply recalled theories like a style guide — they are confirmed lessons from past sessions, not suggestions. Check for continuation episodes from previous sessions and resume unfinished work. Recall uses winner-take-all: one primary theory + 2-3 supporting theories, filtered by familiarity (>0.9 suppressed), within token budget.

### Rule 2: Record corrections immediately

When corrected, call `neurosync_correct` with what was wrong and what's right. Corrections compound exponentially (2^N where N = correction count in session) — they are the most valuable signal. Do not wait; record the moment you realize something was wrong. Optionally pass `theory_id` to directly contradict an existing theory (reduces its confidence by 0.15).

### Rule 3: Query before guessing

Before researching externally or giving an uncertain answer, call `neurosync_query` to check if the answer already exists in memory. Use the appropriate search mode:
- `semantic` (default) — general knowledge lookup across episodes and theories
- `failures` — check for known anti-patterns and past mistakes before suggesting an approach
- `causal` — trace cause/effect chains when debugging or understanding why something happened
- `analogy` — find structurally similar past situations (combined semantic + structural fingerprinting)

Use `scope` to narrow: `all` (default), `episodes`, or `theories`.

This avoids re-researching things already learned and prevents repeating known mistakes.

### Rule 4: Proactively remember when warranted

Call `neurosync_remember` WITHOUT being asked when ANY of these triggers are met:

1. **Knowledge gap** — You didn't know something, gave a wrong/incomplete answer, or had to research to find the answer
2. **User preference revealed** — The user shows a consistent preference, workflow habit, or explicit "I prefer X" statement
3. **Environment constraint discovered** — A setup quirk, access limitation, or tooling behavior specific to this user/project

AND the information is:
- **Reusable** across future sessions
- **Not already known** from CLAUDE.md or recalled theories
- **Not trivial or one-off**

Do NOT remember:
- Routine task outputs (file contents, search results, command outputs)
- One-off questions unlikely to recur
- Trivial facts that any LLM would know from training data

The threshold: "If I started a new session tomorrow and the user encountered the same situation, would having this memory save significant time, prevent a wrong answer, or respect a user preference?" If yes, remember it.

When calling `neurosync_remember`, always include `reasoning` (why this matters) and use `importance` (1-5) to influence the INTUITION signal weight.

### Rule 5: Record structured episodes at session end

Call `neurosync_record` when the session ends or when significant work is complete. Write **causal statements** (why, not what) — the quality scoring engine rewards causal language ("because", "so that", "therefore", "in order to") and penalizes bare activity logs ("Changed X", "Updated Y"). Use appropriate event types:
- `decision` — architectural or design choices with reasoning
- `discovery` — something new learned about the codebase, tools, or environment
- `pattern` — recurring code/workflow patterns observed
- `debugging` — root causes found and how they were resolved
- `architecture` — structural insights about the system
- `causal` — cause/effect relationships (always include `cause`, `effect`, `reasoning` fields)
- `frustration` — pain points the user experienced (signals areas for improvement)
- `question` — questions that came up during the session
- `file_change` — significant code changes (usually auto-recorded by git observer)
- `explicit` — anything explicitly flagged as important

Include `files` array when specific files were involved. Use `importance` (1-5) for the INTUITION signal. Use `explicit_remember` array for critical items that must persist at 10x weight. Always include `session_summary`.

### Rule 6: Hand off unfinished work

When a session ends with incomplete work, call `neurosync_handoff` with:
- `goal` — the overall objective
- `accomplished` — what got done this session
- `remaining` — what still needs to be done
- `next_step` — the concrete first action for the next session
- `blockers` — any open questions or blockers

This creates a high-weight continuation episode so the next session picks up seamlessly. Use this whenever work is interrupted, not just for explicitly "multi-session" tasks.

### Rule 7: Consult theories for architectural decisions

Before making significant design decisions, call `neurosync_theories` with `action: list` to review existing learned patterns. Filter by `scope` if needed: `project`, `domain`, or `craft`. If a relevant theory exists, follow it. If your decision contradicts a theory, either follow the theory or record a correction explaining why it's wrong.

Available actions:
- `list` — browse all active theories (use `scope` and `limit` to filter)
- `detail` — inspect a specific theory's full content and confidence (`theory_id` required)
- `retire` — manually retire a theory that is no longer valid (`theory_id` required)
- `relate` — link related theories together (`related_ids` array)
- `graph` — view the theory hierarchy and relationships

### Available tools

| Tool | Purpose | When to use |
|------|---------|-------------|
| `neurosync_recall` | Load project memory | Session start (Rule 1) |
| `neurosync_query` | Search memories (4 modes) | Before guessing/researching (Rule 3) |
| `neurosync_correct` | Record a mistake (2^N weight) | Immediately on correction (Rule 2) |
| `neurosync_remember` | Explicitly remember (10x weight) | On discovery/preference/constraint (Rule 4) |
| `neurosync_record` | Record session episodes | Session end or milestone (Rule 5) |
| `neurosync_handoff` | Cross-session continuity | Unfinished work at session end (Rule 6) |
| `neurosync_theories` | Browse/manage learned patterns | Before design decisions (Rule 7) |
| `neurosync_status` | Health check | On request or to diagnose issues |
| `neurosync_consolidate` | Manual consolidation trigger | Rarely needed; auto-consolidation handles this |

### Signal weighting system

Episodes are not equally weighted. NeuroSync computes composite weight as the product of applicable signal multipliers (capped at 1000):

| Signal | Multiplier | Trigger |
|--------|-----------|---------|
| CORRECTION | 2^N | User corrected AI (N = count in session) |
| EXPLICIT | x10 | User said "remember this" or `neurosync_remember` called |
| REPETITION | x5 | User re-explained something from a past session |
| SURPRISE | x3 | Episode contradicts an existing theory |
| INTUITION | importance x 0.4 | Agent rates episode importance 1-5 |
| DEPTH | N layers | Files touch N architecture layers |
| DURATION | ratio x 2.0 | Time proportion spent on topic |
| PASSIVE | x0.3 | Auto-observed events (git changes) |

**To maximize episode value**: use causal language, include file references, set `importance`, and specify `layers` when applicable.

### What's automatic

- **Auto-consolidation** — theories are extracted when unconsolidated episodes reach threshold (~20). Episodes are clustered by semantic similarity, candidate theories extracted, MDL-pruned (rejects verbose/non-generalizable patterns), and merged or created at initial confidence 0.5
- **Confidence lifecycle** — theories gain confidence on confirmation (+0.1 x (1 - current), asymptotic), lose on contradiction (-0.15), decay after 30 days without confirmation (-0.01/day), and auto-retire below 0.05
- **Passive git observation** — file changes and commits are recorded as low-weight (x0.3) episodes automatically
- **Dynamic hints** — tool responses include `_hint` fields with contextual guidance; follow them
- **Quality scoring** — episodes are scored 0-7 based on causal language, file references, reasoning language, and length. Low-quality episodes get warnings

### `neurosync_record` vs `neurosync_remember`

- **`neurosync_remember`** — Single important fact, 10x weight, fire-and-forget. Best for: mid-session discoveries, preferences, constraints. Include `reasoning` and `importance`.
- **`neurosync_record`** — Structured session summary with multiple typed events, causal links, file/layer associations. Best for: end-of-session wrap-up. Include `session_summary` and `explicit_remember` for critical items.

Both contribute to theory consolidation. Use `remember` for individual high-signal facts as they happen. Use `record` for the comprehensive session wrap-up.
