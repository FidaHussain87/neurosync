"""Git observer: captures git state at session boundaries for passive learning."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from neurosync.models import _utcnow

# File extensions grouped by type for classification
_FILE_TYPE_MAP = {
    ".py": "Python",
    ".pm": "Perl",
    ".pl": "Perl",
    ".t": "Perl test",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".md": "Markdown",
    ".sql": "SQL",
    ".sh": "Shell",
}

# Map file path patterns to architecture layer names for DEPTH signal
_LAYER_PATTERNS: list[tuple[str, str]] = [
    ("test", "test"),
    ("frontend/", "ui"),
    ("src/components/", "ui"),
    ("src/hooks/", "ui"),
    ("config", "config"),
    (".yaml", "config"),
    (".yml", "config"),
    (".json", "config"),
    ("endpoint", "endpoint"),
    ("api/", "endpoint"),
    ("routes/", "endpoint"),
    ("views/", "endpoint"),
    ("service", "service"),
    ("dao", "dao"),
    ("db", "dao"),
    ("models", "dao"),
    ("scanner", "scanner"),
    ("cli", "endpoint"),
]


@dataclass
class GitSnapshot:
    """Snapshot of git state at a point in time."""

    head_sha: str = ""
    branch: str = ""
    modified_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=_utcnow)


class GitObserver:
    """Observes git state changes between session start and end."""

    def __init__(self, cwd: Optional[str] = None) -> None:
        self._cwd = cwd or os.getcwd()
        self._baseline: Optional[GitSnapshot] = None

    def capture_baseline(self) -> Optional[GitSnapshot]:
        """Capture git state at session start. Returns None if not a git repo."""
        head_sha = self._get_head_sha()
        if not head_sha:
            return None
        modified, untracked = self._parse_porcelain_status()
        self._baseline = GitSnapshot(
            head_sha=head_sha,
            branch=self._get_branch(),
            modified_files=modified,
            untracked_files=untracked,
        )
        return self._baseline

    def capture_delta(self) -> list[dict]:
        """Compute changes since baseline. Returns list of event dicts for recording."""
        if not self._baseline:
            return []

        current_sha = self._get_head_sha()
        if not current_sha:
            return []

        events: list[dict] = []

        # Collect commit messages since baseline
        if current_sha != self._baseline.head_sha:
            commits = self._get_commit_messages_since(self._baseline.head_sha)
            for msg in commits:
                events.append(
                    {
                        "type": "observed",
                        "content": f"Committed: '{msg}'",
                        "signal_weight": 0.3,
                        "files": [],
                        "layers": [],
                    }
                )

        # Collect file changes (single git status call)
        current_modified, _ = self._parse_porcelain_status()
        current_modified_set = set(current_modified)
        baseline_modified = set(self._baseline.modified_files)
        new_changes = current_modified_set - baseline_modified
        if new_changes:
            classified = self._classify_files(list(new_changes))
            summary_parts = []
            for file_type, files in sorted(classified.items()):
                summary_parts.append(
                    f"{len(files)} {file_type} file{'s' if len(files) != 1 else ''}"
                )
            summary = ", ".join(summary_parts)
            file_list = sorted(new_changes)
            layers = self._infer_layers(file_list)
            events.append(
                {
                    "type": "observed",
                    "content": f"Files changed during session: {summary} ({', '.join(f for f in file_list[:10])})",
                    "signal_weight": 0.3,
                    "files": file_list,
                    "layers": layers,
                }
            )

        return events

    def _parse_porcelain_status(self) -> tuple[list[str], list[str]]:
        """Run git status --porcelain once and return (modified, untracked) file lists."""
        output = self._run_git("status", "--porcelain")
        if not output:
            return [], []
        modified: list[str] = []
        untracked: list[str] = []
        for line in output.splitlines():
            if len(line) > 3:
                filename = line[3:].strip()
                if not filename:
                    continue
                if line.startswith("??"):
                    untracked.append(filename)
                else:
                    modified.append(filename)
        return modified, untracked

    def _run_git(self, *args: str) -> Optional[str]:
        """Run a git command with timeout. Returns stdout or None on failure."""
        try:
            result = subprocess.run(
                ["git"] + list(args),
                capture_output=True,
                text=True,
                cwd=self._cwd,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.CalledProcessError):
            pass
        return None

    def _get_head_sha(self) -> str:
        """Get current HEAD SHA."""
        return self._run_git("rev-parse", "HEAD") or ""

    def _get_branch(self) -> str:
        """Get current branch name."""
        return self._run_git("rev-parse", "--abbrev-ref", "HEAD") or ""

    def _get_modified_files(self) -> list[str]:
        """Get list of modified/staged files."""
        modified, _ = self._parse_porcelain_status()
        return modified

    def _get_untracked_files(self) -> list[str]:
        """Get list of untracked files."""
        _, untracked = self._parse_porcelain_status()
        return untracked

    def _get_commit_messages_since(self, sha: str) -> list[str]:
        """Get commit messages since a given SHA."""
        output = self._run_git("log", f"{sha}..HEAD", "--format=%s")
        if not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]

    @staticmethod
    def _classify_files(files: list[str]) -> dict[str, list[str]]:
        """Group files by type based on extension."""
        groups: dict[str, list[str]] = {}
        for filepath in files:
            _, ext = os.path.splitext(filepath)
            file_type = _FILE_TYPE_MAP.get(ext.lower(), "other")
            groups.setdefault(file_type, []).append(filepath)
        return groups

    @staticmethod
    def _infer_layers(files: list[str]) -> list[str]:
        """Infer architecture layers from file paths for the DEPTH signal."""
        layers: set[str] = set()
        for filepath in files:
            filepath_lower = filepath.lower()
            for pattern, layer in _LAYER_PATTERNS:
                if pattern in filepath_lower:
                    layers.add(layer)
                    break  # first match wins per file
        return sorted(layers)
