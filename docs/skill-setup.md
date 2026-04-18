# Setting Up the `/neurosync` Slash Command

This guide adds a `/neurosync` slash command (skill) to Claude Code so you can run NeuroSync operations directly from the chat. Type `/neurosync status` instead of switching to a terminal.

## Prerequisites

Before starting, you need:

1. **NeuroSync installed** and working as an MCP server. If you haven't done this yet, follow the [Getting Started](../README.md#getting-started) section in the README first.

2. **Claude Code** installed and working. The skill system is a Claude Code feature.

Verify both are working:

```bash
# NeuroSync MCP is connected
claude mcp list
# You should see: neurosync: ... ✓ Connected

# NeuroSync CLI works
neurosync status
# You should see JSON with database stats
```

If either of these fails, stop here and fix the MCP setup first. The skill depends on both the MCP server (for `recall`, `remember`, `query`, `theories`) and the CLI (for `status`, `consolidate`, `reset`).

## Installation

### Step 1: Create the skill directory

Claude Code looks for skills in `~/.claude/skills/`. Create the directory:

```bash
mkdir -p ~/.claude/skills/neurosync
```

### Step 2: Copy the SKILL.md file

The skill definition ships with the NeuroSync repo. Copy it:

```bash
# If you cloned the repo (recommended):
cp /path/to/neurosync/skills/neurosync/SKILL.md ~/.claude/skills/neurosync/SKILL.md

# Example with a real path:
cp ~/neurosync/skills/neurosync/SKILL.md ~/.claude/skills/neurosync/SKILL.md
```

Or if you didn't clone the repo, download it directly:

```bash
curl -o ~/.claude/skills/neurosync/SKILL.md \
  https://raw.githubusercontent.com/FidaHussain87/neurosync/main/skills/neurosync/SKILL.md
```

### Step 3: Verify the file is in the right place

```bash
ls -la ~/.claude/skills/neurosync/SKILL.md
```

You should see the file. If you see "No such file or directory", go back to Step 1.

### Step 4: Restart Claude Code

The skill is picked up automatically, but if you had Claude Code open during setup, restart it (or start a new session) to load the skill.

### Step 5: Test it

In a Claude Code session, type:

```
/neurosync
```

You should see it autocomplete. Press Enter with no arguments to see the help menu:

```
/neurosync status        — Show memory health (sessions, episodes, theories)
/neurosync consolidate   — Extract theories from pending episodes
/neurosync recall        — Load project memory for this session
/neurosync remember <text> — Store an important fact
/neurosync query <text>  — Search memories (prefix: failures: causal: analogy:)
/neurosync theories      — Browse all learned patterns
/neurosync reset         — Clear all memory data (dangerous)
```

Then try:

```
/neurosync status
```

You should see a formatted table with your memory stats (sessions, episodes, theories).

## What each command does

### `/neurosync status`

Shows your memory health: how many sessions, episodes (pending vs consolidated), active theories, and ChromaDB sync state. This runs the CLI command `neurosync status`.

### `/neurosync consolidate`

Triggers the consolidation engine to extract theories from pending episodes. It runs a dry-run first and asks before proceeding. This runs the CLI command `neurosync consolidate`.

### `/neurosync recall`

Loads project memory into the current session. This calls the MCP tool `neurosync_recall` — the same thing that happens automatically at session start if you have the protocol in your CLAUDE.md.

### `/neurosync remember <text>`

Stores something important in memory with high weight (10x). Example:

```
/neurosync remember this project uses pytest-responses for HTTP mocking, never unittest.mock
```

This calls the MCP tool `neurosync_remember`.

### `/neurosync query <text>`

Searches your memories. Supports four modes:

```
/neurosync query how do we handle authentication in this project
/neurosync query failures: common mistakes with the payment module
/neurosync query causal: why did we switch from MySQL to PostgreSQL
/neurosync query analogy: similar refactoring patterns we've done before
```

This calls the MCP tool `neurosync_query`.

### `/neurosync theories`

Lists all learned theories with their confidence scores. Useful to see what NeuroSync has learned about your project over time. This calls the MCP tool `neurosync_theories`.

### `/neurosync reset`

Deletes ALL memory data (episodes, theories, ChromaDB). You'll be asked to confirm. This runs `neurosync reset --confirm`. There is no undo.

## How the skill works (under the hood)

The skill is a `SKILL.md` file with YAML frontmatter and markdown instructions. When you type `/neurosync <command>`, Claude Code:

1. Reads the `SKILL.md` file
2. Substitutes `$ARGUMENTS` with whatever you typed after `/neurosync`
3. Follows the routing instructions to either run a CLI command (via Bash) or call an MCP tool

The skill has `disable-model-invocation: true`, meaning Claude won't invoke it on its own — only you can trigger it by typing `/neurosync`. The MCP tools (recall, record, correct, etc.) still work automatically via the protocol in CLAUDE.md.

## Permissions

The skill pre-approves these tool patterns so you don't get prompted every time:

- `Bash(neurosync *)` — CLI commands like `neurosync status`, `neurosync consolidate`
- `mcp__neurosync__*` — All NeuroSync MCP tools

If you're still getting permission prompts, add these to your project's `.claude/settings.local.json`:

```json
{
  "permissions": {
    "allow": [
      "mcp__neurosync__*",
      "Bash(neurosync *)"
    ]
  }
}
```

## Troubleshooting

### `/neurosync` doesn't autocomplete

- Check the file exists: `ls ~/.claude/skills/neurosync/SKILL.md`
- Check the file starts with `---` (YAML frontmatter)
- Restart Claude Code (new session)

### `/neurosync status` shows "command not found: neurosync"

The `neurosync` CLI isn't in your PATH. Either:

1. Activate the venv first: `source /path/to/neurosync/.venv/bin/activate`
2. Or use the full path in the skill. Edit `~/.claude/skills/neurosync/SKILL.md` and replace `neurosync status` with `/path/to/neurosync/.venv/bin/neurosync status` (do this for all CLI commands in the file).

### `/neurosync recall` fails with "MCP tool not found"

The NeuroSync MCP server isn't connected. Check:

```bash
claude mcp list
```

If `neurosync` isn't listed or shows an error, re-add it:

```bash
claude mcp add -s user neurosync -- /path/to/neurosync/.venv/bin/python -m neurosync.mcp_server
```

### Permission denied errors

Add the tool permissions to your project settings. See the [Permissions](#permissions) section above.

## Updating the skill

If you cloned the NeuroSync repo and a new version has an updated `SKILL.md`, just copy it again:

```bash
cp /path/to/neurosync/skills/neurosync/SKILL.md ~/.claude/skills/neurosync/SKILL.md
```

The skill reloads automatically — no restart needed for file changes.

## Uninstalling

Remove the skill directory:

```bash
rm -rf ~/.claude/skills/neurosync
```

This only removes the `/neurosync` slash command. The MCP server and your memory data are unaffected.
