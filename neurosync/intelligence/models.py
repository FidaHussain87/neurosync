"""Data models for the intelligence layer."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Insight:
    """A single insight produced by an analyzer."""

    id: str
    insight_type: str
    category: str = ""
    content: str = ""
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.5
    staleness_days: float = 0.0
    project: str = ""
    created_at: str = ""
    updated_at: str = ""
    expires_at: str = ""
    surfaced_count: int = 0
    dismissed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "insight_type": self.insight_type,
            "category": self.category,
            "content": self.content,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "project": self.project,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }


@dataclass
class DeveloperProfile:
    """A computed fact about the developer's work patterns."""

    profile_key: str
    profile_value: Any
    computed_at: str = ""
    observation_count: int = 0
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def value_json(self) -> str:
        return json.dumps(self.profile_value)
