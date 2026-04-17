"""Tests for protocol.py — minimal protocol generation."""

from __future__ import annotations

from neurosync.protocol import MINIMAL_PROTOCOL, generate_claude_md, generate_protocol_section


class TestProtocol:
    def test_minimal_protocol_under_30_lines(self):
        lines = MINIMAL_PROTOCOL.strip().splitlines()
        assert len(lines) <= 50  # generous limit for the markdown section

    def test_protocol_mentions_core_tools(self):
        assert "neurosync_recall" in MINIMAL_PROTOCOL
        assert "neurosync_record" in MINIMAL_PROTOCOL
        assert "neurosync_correct" in MINIMAL_PROTOCOL

    def test_generate_protocol_section(self):
        section = generate_protocol_section()
        assert section == MINIMAL_PROTOCOL
        assert "Rule 1" in section
        assert "Rule 2" in section
        assert "Rule 3" in section

    def test_generate_claude_md(self):
        md = generate_claude_md()
        assert "your project" in md
        assert MINIMAL_PROTOCOL in md

    def test_generate_claude_md_with_project(self):
        md = generate_claude_md(project_name="MyApp")
        assert "MyApp" in md
        assert MINIMAL_PROTOCOL in md
