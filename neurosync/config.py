"""Configuration management: env > config.json > defaults, git detection."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("neurosync.config")

_DEFAULT_DATA_DIR = os.path.join(os.path.expanduser("~"), ".neurosync")


@dataclass
class NeuroSyncConfig:
    """NeuroSync configuration with layered defaults."""

    data_dir: str = ""
    sqlite_path: str = ""
    chroma_path: str = ""
    default_project: str = ""
    default_branch: str = ""
    recall_max_tokens: int = 500
    consolidation_min_episodes: int = 5
    consolidation_similarity_threshold: float = 0.8
    theory_confidence_decay_days: int = 30
    theory_confidence_decay_rate: float = 0.01
    max_signal_weight: float = 1000.0
    episode_quality_threshold: int = 3
    continuation_weight: float = 8.0
    protocol_hints_enabled: bool = True
    auto_consolidation_enabled: bool = True
    auto_consolidation_threshold: int = 20
    neo4j_uri: str = ""
    neo4j_user: str = ""
    neo4j_password: str = ""
    neo4j_database: str = ""

    def __repr__(self) -> str:
        fields = []
        for f in self.__dataclass_fields__:
            val = getattr(self, f)
            if f == "neo4j_password" and val:
                val = "***"
            fields.append(f"{f}={val!r}")
        return f"{self.__class__.__name__}({', '.join(fields)})"

    def __post_init__(self) -> None:
        if not self.data_dir:
            self.data_dir = os.environ.get("NEUROSYNC_DATA_DIR", _DEFAULT_DATA_DIR)
        if not self.sqlite_path:
            self.sqlite_path = os.path.join(self.data_dir, "neurosync.sqlite3")
        if not self.chroma_path:
            self.chroma_path = os.path.join(self.data_dir, "chroma")
        if not self.neo4j_uri:
            self.neo4j_uri = os.environ.get("NEUROSYNC_NEO4J_URI", "bolt://localhost:7687")
        if not self.neo4j_user:
            self.neo4j_user = os.environ.get("NEUROSYNC_NEO4J_USER", "neo4j")
        if not self.neo4j_password:
            self.neo4j_password = os.environ.get("NEUROSYNC_NEO4J_PASSWORD", "")
        if not self.neo4j_database:
            self.neo4j_database = os.environ.get("NEUROSYNC_NEO4J_DATABASE", "neo4j")

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> NeuroSyncConfig:
        """Load config from env > config.json > defaults."""
        overrides: dict = {}
        if config_path is None:
            data_dir = os.environ.get("NEUROSYNC_DATA_DIR", _DEFAULT_DATA_DIR)
            config_path = os.path.join(data_dir, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path) as f:
                    overrides = json.load(f)
            except (json.JSONDecodeError, ValueError):
                logger.warning("Malformed config.json at %s, using defaults", config_path)
        for env_key in (
            "NEUROSYNC_DATA_DIR",
            "NEUROSYNC_DEFAULT_PROJECT",
            "NEUROSYNC_DEFAULT_BRANCH",
        ):
            val = os.environ.get(env_key)
            if val:
                field_name = env_key.replace("NEUROSYNC_", "").lower()
                overrides[field_name] = val
        # Never load neo4j_password from config.json — it must only come from
        # the NEUROSYNC_NEO4J_PASSWORD environment variable (handled in __post_init__)
        # to avoid storing secrets in plaintext on disk.
        overrides.pop("neo4j_password", None)
        return cls(**{k: v for k, v in overrides.items() if k in cls.__dataclass_fields__})

    def ensure_dirs(self) -> None:
        """Create data directories if they don't exist."""
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            os.makedirs(self.chroma_path, exist_ok=True)
        except OSError as e:
            raise RuntimeError(
                f"Cannot create NeuroSync data directory '{self.data_dir}': {e}. "
                f"Set NEUROSYNC_DATA_DIR to a writable path."
            ) from e


def detect_git_info(cwd: Optional[str] = None) -> dict[str, str]:
    """Detect current git project and branch from working directory."""
    info: dict[str, str] = {}
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
        )
        if result.returncode == 0:
            toplevel = result.stdout.strip()
            info["project"] = os.path.basename(toplevel)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=5,
        )
        if result.returncode == 0:
            info["branch"] = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return info
