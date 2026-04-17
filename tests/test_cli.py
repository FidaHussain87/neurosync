"""Tests for cli.py — CLI commands."""

from __future__ import annotations

import os
import subprocess
import sys


class TestCLI:
    def test_version(self):
        result = subprocess.run(
            [sys.executable, "-m", "neurosync", "--version"],
            capture_output=True, text=True,
        )
        assert "0.4.0" in result.stdout

    def test_help(self):
        result = subprocess.run(
            [sys.executable, "-m", "neurosync", "--help"],
            capture_output=True, text=True,
        )
        assert "neurosync" in result.stdout.lower()

    def test_status_command(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("NEUROSYNC_DATA_DIR", tmp_dir)
        from neurosync.cli import cmd_status
        import argparse
        args = argparse.Namespace()
        cmd_status(args)

    def test_reset_without_confirm(self, tmp_dir, monkeypatch, capsys):
        monkeypatch.setenv("NEUROSYNC_DATA_DIR", tmp_dir)
        from neurosync.cli import cmd_reset
        import argparse
        import pytest
        args = argparse.Namespace(confirm=False)
        with pytest.raises(SystemExit):
            cmd_reset(args)

    def test_reset_with_confirm(self, tmp_dir, monkeypatch, capsys):
        monkeypatch.setenv("NEUROSYNC_DATA_DIR", tmp_dir)
        # Create a database first
        from neurosync.config import NeuroSyncConfig
        from neurosync.db import Database
        config = NeuroSyncConfig(data_dir=tmp_dir)
        db = Database(config)
        db.close()
        assert os.path.exists(config.sqlite_path)
        from neurosync.cli import cmd_reset
        import argparse
        args = argparse.Namespace(confirm=True)
        cmd_reset(args)
        assert not os.path.exists(config.sqlite_path)

    def test_install_hook_dry_run(self, tmp_dir, capsys):
        from neurosync.cli import cmd_install_hook
        import argparse
        args = argparse.Namespace(project_dir=tmp_dir, dry_run=True)
        cmd_install_hook(args)
        captured = capsys.readouterr()
        assert "Would install to" in captured.out
        assert "SessionStart" in captured.out

    def test_generate_protocol(self, capsys):
        from neurosync.cli import cmd_generate_protocol
        import argparse
        args = argparse.Namespace(project=None)
        cmd_generate_protocol(args)
        captured = capsys.readouterr()
        assert "NeuroSync Memory Protocol" in captured.out
        assert "Rule 1" in captured.out

    def test_generate_protocol_with_project(self, capsys):
        from neurosync.cli import cmd_generate_protocol
        import argparse
        args = argparse.Namespace(project="MyProject")
        cmd_generate_protocol(args)
        captured = capsys.readouterr()
        assert "MyProject" in captured.out

    def test_reset_reports_chromadb_failure(self, tmp_dir, monkeypatch, capsys):
        """cmd_reset should warn on ChromaDB failure, not silently swallow it."""
        monkeypatch.setenv("NEUROSYNC_DATA_DIR", tmp_dir)
        from neurosync.config import NeuroSyncConfig
        from neurosync.db import Database
        config = NeuroSyncConfig(data_dir=tmp_dir)
        db = Database(config)
        db.close()
        from neurosync.cli import cmd_reset
        from unittest.mock import patch
        import argparse
        args = argparse.Namespace(confirm=True)
        with patch("neurosync.vectorstore.VectorStore.__init__", side_effect=RuntimeError("ChromaDB broken")):
            cmd_reset(args)
        captured = capsys.readouterr()
        assert "Warning" in captured.err or "ChromaDB" in captured.err
        assert "NeuroSync data reset" in captured.out

    def test_cmd_status_partial_health(self, tmp_dir, monkeypatch, capsys):
        """cmd_status should show database healthy even if vectorstore fails."""
        monkeypatch.setenv("NEUROSYNC_DATA_DIR", tmp_dir)
        from neurosync.cli import cmd_status
        from unittest.mock import patch
        import argparse
        import json
        args = argparse.Namespace()
        with patch("neurosync.vectorstore.VectorStore.__init__", side_effect=RuntimeError("ChromaDB broken")):
            cmd_status(args)
        captured = capsys.readouterr()
        status = json.loads(captured.out)
        assert status["database"]["healthy"] is True
        assert status["vectorstore"]["healthy"] is False
        assert "error" in status["vectorstore"]

    def test_main_no_args(self, capsys):
        from neurosync.cli import main
        import sys
        old_argv = sys.argv
        sys.argv = ["neurosync"]
        main()
        sys.argv = old_argv
        captured = capsys.readouterr()
        assert "neurosync" in captured.out.lower() or captured.out == ""
