"""Topic familiarity tracking — models what the user likely already knows."""

from __future__ import annotations

from typing import Optional

from neurosync.db import Database
from neurosync.models import UserKnowledge, _utcnow


class UserModel:
    """Tracks user familiarity with topics to avoid re-explaining known concepts."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def record_exposure(self, topic: str, project: str = "", explained: bool = False) -> UserKnowledge:
        """Record that the user was exposed to a topic."""
        uk = self._db.get_user_knowledge(topic, project)
        if uk is None:
            uk = UserKnowledge(topic=topic, project=project)

        uk.times_seen += 1
        if explained:
            uk.times_explained += 1
        uk.last_seen = _utcnow()

        # Update familiarity: grows with exposure, faster if user explained (vs being told)
        if explained:
            uk.familiarity = min(1.0, uk.familiarity + 0.15)
        else:
            uk.familiarity = min(1.0, uk.familiarity + 0.05)

        return self._db.save_user_knowledge(uk)

    def get_familiarity(self, topic: str, project: str = "") -> float:
        """Get user's familiarity with a topic (0.0 to 1.0)."""
        uk = self._db.get_user_knowledge(topic, project)
        if uk is None:
            return 0.0
        return uk.familiarity

    def get_familiar_topics(self, threshold: float = 0.9, project: Optional[str] = None) -> set[str]:
        """Get topics where user familiarity exceeds threshold."""
        all_knowledge = self._db.list_user_knowledge(project=project)
        return {uk.topic for uk in all_knowledge if uk.familiarity >= threshold}

    def should_explain(self, topic: str, project: str = "") -> bool:
        """Whether this topic should be explained (user not yet familiar)."""
        return self.get_familiarity(topic, project) < 0.9

    def list_knowledge(self, project: Optional[str] = None) -> list[UserKnowledge]:
        return self._db.list_user_knowledge(project=project)
