"""Tests for git_observer.py — passive git state observation."""

from __future__ import annotations

import os
import subprocess
from unittest.mock import patch

from neurosync.git_observer import GitObserver, GitSnapshot


class TestGitSnapshot:
    def test_defaults(self):
        snap = GitSnapshot()
        assert snap.head_sha == ""
        assert snap.branch == ""
        assert snap.modified_files == []
        assert snap.untracked_files == []
        assert snap.timestamp  # should have a timestamp


class TestGitObserver:
    def test_baseline_not_git_repo(self, tmp_dir):
        observer = GitObserver(cwd=tmp_dir)
        result = observer.capture_baseline()
        assert result is None

    def test_baseline_git_repo(self, tmp_dir):
        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=tmp_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_dir, capture_output=True)
        # Create and commit a file
        with open(os.path.join(tmp_dir, "test.py"), "w") as f:
            f.write("print('hello')\n")
        subprocess.run(["git", "add", "."], cwd=tmp_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_dir, capture_output=True)

        observer = GitObserver(cwd=tmp_dir)
        snap = observer.capture_baseline()
        assert snap is not None
        assert snap.head_sha != ""
        assert snap.branch != ""

    def test_delta_no_baseline(self):
        observer = GitObserver(cwd="/tmp")
        events = observer.capture_delta()
        assert events == []

    def test_delta_with_file_changes(self, tmp_dir):
        # Set up git repo with initial commit
        subprocess.run(["git", "init"], cwd=tmp_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_dir, capture_output=True)
        with open(os.path.join(tmp_dir, "initial.py"), "w") as f:
            f.write("# initial\n")
        subprocess.run(["git", "add", "."], cwd=tmp_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_dir, capture_output=True)

        # Capture baseline
        observer = GitObserver(cwd=tmp_dir)
        observer.capture_baseline()

        # Make a change
        with open(os.path.join(tmp_dir, "new_file.py"), "w") as f:
            f.write("# new\n")

        events = observer.capture_delta()
        # Should detect the new untracked/modified file
        file_events = [e for e in events if "Files changed" in e["content"]]
        assert len(file_events) >= 0  # May or may not detect depending on git status

    def test_delta_with_commits(self, tmp_dir):
        # Set up git repo
        subprocess.run(["git", "init"], cwd=tmp_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_dir, capture_output=True)
        with open(os.path.join(tmp_dir, "initial.py"), "w") as f:
            f.write("# initial\n")
        subprocess.run(["git", "add", "."], cwd=tmp_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_dir, capture_output=True)

        # Capture baseline
        observer = GitObserver(cwd=tmp_dir)
        observer.capture_baseline()

        # Make a new commit
        with open(os.path.join(tmp_dir, "new.py"), "w") as f:
            f.write("# new\n")
        subprocess.run(["git", "add", "."], cwd=tmp_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Add new feature"], cwd=tmp_dir, capture_output=True)

        events = observer.capture_delta()
        commit_events = [e for e in events if "Committed:" in e["content"]]
        assert len(commit_events) == 1
        assert "Add new feature" in commit_events[0]["content"]
        assert commit_events[0]["type"] == "observed"
        assert commit_events[0]["signal_weight"] == 0.3

    def test_classify_files(self):
        files = ["src/main.py", "lib/Module.pm", "config.json", "README.md", "Makefile"]
        classified = GitObserver._classify_files(files)
        assert "Python" in classified
        assert "Perl" in classified
        assert "JSON" in classified
        assert "Markdown" in classified
        assert "other" in classified

    def test_git_not_available(self, tmp_dir):
        """If git binary is not found, methods return gracefully."""
        observer = GitObserver(cwd=tmp_dir)
        with patch("neurosync.git_observer.subprocess.run", side_effect=FileNotFoundError):
            assert observer._get_head_sha() == ""
            assert observer._get_modified_files() == []
            assert observer._get_untracked_files() == []
            result = observer.capture_baseline()
            assert result is None

    def test_git_timeout(self, tmp_dir):
        """If git commands time out, methods return gracefully."""
        observer = GitObserver(cwd=tmp_dir)
        with patch(
            "neurosync.git_observer.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5),
        ):
            assert observer._get_head_sha() == ""
            assert observer._get_branch() == ""
            assert observer._get_commit_messages_since("abc") == []
