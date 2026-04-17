"""Dataclasses for NeuroSync memory system."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


# --- Episode event types ---

EPISODE_TYPES = frozenset({
    "decision",
    "discovery",
    "correction",
    "pattern",
    "frustration",
    "question",
    "file_change",
    "architecture",
    "debugging",
    "explicit",
})

# --- Theory scopes ---

THEORY_SCOPES = frozenset({"project", "domain", "craft"})


@dataclass
class Session:
    """A coding session — one contiguous period of work."""

    id: str = field(default_factory=_new_id)
    project: str = ""
    branch: str = ""
    started_at: str = field(default_factory=_utcnow)
    ended_at: Optional[str] = None
    duration_seconds: int = 0
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Episode:
    """Layer 1: An individual event within a session."""

    id: str = field(default_factory=_new_id)
    session_id: str = ""
    timestamp: str = field(default_factory=_utcnow)
    event_type: str = "decision"
    content: str = ""
    context: str = ""
    files_touched: list[str] = field(default_factory=list)
    layers_touched: list[str] = field(default_factory=list)
    signal_weight: float = 1.0
    consolidated: int = 0  # 0=pending, 1=consolidated, 2=decayed
    consolidated_at: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Signal:
    """Signal weight component for an episode."""

    id: Optional[int] = None
    episode_id: str = ""
    signal_type: str = ""
    raw_value: float = 0.0
    multiplier: float = 1.0
    timestamp: str = field(default_factory=_utcnow)


@dataclass
class Theory:
    """Layer 2: A consolidated pattern extracted from episodes."""

    id: str = field(default_factory=_new_id)
    content: str = ""
    scope: str = "craft"
    scope_qualifier: str = ""
    confidence: float = 0.5
    confirmation_count: int = 0
    contradiction_count: int = 0
    first_observed: str = field(default_factory=_utcnow)
    last_confirmed: Optional[str] = None
    source_episodes: list[str] = field(default_factory=list)
    superseded_by: Optional[str] = None
    active: bool = True
    description_length: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.description_length and self.content:
            self.description_length = len(self.content)


@dataclass
class Contradiction:
    """When an episode contradicts an existing theory."""

    id: Optional[int] = None
    theory_id: str = ""
    episode_id: str = ""
    description: str = ""
    resolution: Optional[str] = None
    resolved_at: Optional[str] = None
    created_at: str = field(default_factory=_utcnow)


@dataclass
class UserKnowledge:
    """What the user likely knows about a topic."""

    id: Optional[int] = None
    topic: str = ""
    project: str = ""
    familiarity: float = 0.5
    last_seen: str = field(default_factory=_utcnow)
    times_seen: int = 0
    times_explained: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
