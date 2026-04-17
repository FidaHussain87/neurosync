"""Hook configuration generation for Claude Code auto-recall on session start."""

from __future__ import annotations

import os


def generate_settings_hook() -> dict:
    """Generate Claude Code settings.local.json structure with SessionStart hook."""
    return {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": (
                                "echo '[NeuroSync] Call neurosync_recall to load "
                                "project memory before starting work.'"
                            ),
                        }
                    ],
                }
            ]
        }
    }


def format_hook_instructions() -> str:
    """Return human-readable installation instructions."""
    return (
        "NeuroSync Auto-Recall Hook\n"
        "==========================\n\n"
        "This hook reminds the agent to call neurosync_recall at session start.\n"
        "Combined with the minimal protocol (see `neurosync generate-protocol`),\n"
        "this is all you need for NeuroSync to work autonomously.\n\n"
        "To install manually, add to .claude/settings.local.json:\n\n"
        '  "hooks": {\n'
        '    "SessionStart": [{\n'
        '      "matcher": "",\n'
        '      "hooks": [{"type": "command", "command": '
        "\"echo '[NeuroSync] Call neurosync_recall to load project memory "
        "before starting work.'\"}]\n"
        "    }]\n"
        "  }\n"
    )


def get_hook_install_path(project_dir: str) -> str:
    """Return the path where the hook settings file should be installed."""
    return os.path.join(project_dir, ".claude", "settings.local.json")
