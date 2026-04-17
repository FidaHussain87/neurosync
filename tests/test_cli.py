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
        assert "0.1.0" in result.stdout

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

    def test_main_no_args(self, capsys):
        from neurosync.cli import main
        import sys
        old_argv = sys.argv
        sys.argv = ["neurosync"]
        main()
        sys.argv = old_argv
        captured = capsys.readouterr()
        assert "neurosync" in captured.out.lower() or captured.out == ""
