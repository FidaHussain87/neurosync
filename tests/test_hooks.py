"""Tests for hooks.py — hook configuration generation."""

from __future__ import annotations

import os

from neurosync.hooks import format_hook_instructions, generate_settings_hook, get_hook_install_path


class TestHooks:
    def test_generate_hook(self):
        hook = generate_settings_hook()
        assert "hooks" in hook
        assert "SessionStart" in hook["hooks"]
        session_hooks = hook["hooks"]["SessionStart"]
        assert len(session_hooks) == 1
        assert session_hooks[0]["hooks"][0]["type"] == "command"

    def test_hook_command_mentions_recall(self):
        hook = generate_settings_hook()
        command = hook["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        assert "neurosync_recall" in command
        assert "[NeuroSync]" in command

    def test_format_instructions(self):
        instructions = format_hook_instructions()
        assert "NeuroSync" in instructions
        assert "settings.local.json" in instructions
        assert "generate-protocol" in instructions

    def test_hook_path(self, tmp_dir):
        path = get_hook_install_path(tmp_dir)
        assert path == os.path.join(tmp_dir, ".claude", "settings.local.json")
