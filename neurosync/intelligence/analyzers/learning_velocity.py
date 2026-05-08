"""Learning Velocity Analyzer — tracks skill trajectory from user_model familiarity over time."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from neurosync.db import Database
from neurosync.intelligence.analyzers.base import BaseAnalyzer
from neurosync.intelligence.models import Insight
from neurosync.vectorstore import VectorStore

_PLATEAU_THRESHOLD = 0.02   # familiarity change per week below this = plateau
_MASTERY_THRESHOLD = 0.85   # familiarity above this = near mastery


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _insight_id(prefix: str, key: str) -> str:
    return hashlib.sha256(f"{prefix}:{key}".encode()).hexdigest()[:24]


def _weeks_ago(ts: str) -> float:
    """Return how many weeks ago the timestamp was (negative = in future)."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - dt).total_seconds() / (7 * 86400)
    except (ValueError, AttributeError):
        return 0.0


class LearningVelocityAnalyzer(BaseAnalyzer):
    """Analyzes skill trajectory from user_model familiarity data."""

    interval_seconds = 7200  # every 2 hours
    max_runtime_ms = 5000

    def name(self) -> str:
        return "learning_velocity"

    def analyze(self, db: Database, vs: Optional[VectorStore]) -> list[Insight]:
        user_knowledge = db.list_user_knowledge()
        if len(user_knowledge) < 5:
            return []

        insights: list[Insight] = []
        insights.extend(self._analyze_learning_rates(user_knowledge, db))
        insights.extend(self._analyze_plateaus(user_knowledge))
        insights.extend(self._analyze_near_mastery(user_knowledge))
        return insights

    def _analyze_learning_rates(self, user_knowledge: list, db: Database) -> list[Insight]:
        """Compute per-topic learning rates from familiarity + times_seen progression."""
        # Velocity = avg familiarity gain per observation (familiarity / times_seen).
        velocities: list[tuple[str, float, float, int]] = []  # (topic, familiarity, velocity, times_seen)

        for uk in user_knowledge:
            topic = uk.topic
            familiarity = uk.familiarity or 0.0
            times_seen = uk.times_seen or 0

            if times_seen < 2 or familiarity < 0.05:
                continue

            # Velocity = average familiarity gain per observation.
            # Time-based rate is misleading: a recently-started topic with
            # low familiarity would dominate over a deeply-learned older one.
            velocity = familiarity / times_seen
            velocities.append((topic, familiarity, velocity, times_seen))

        if len(velocities) < 3:
            return []

        # Find fastest learners
        velocities.sort(key=lambda x: -x[2])
        top_learning = velocities[:3]

        # Store learning velocity profile
        velocity_map = {t: round(v, 4) for t, _, v, _ in top_learning}
        db.upsert_developer_profile(
            "learning_velocity_by_topic",
            velocity_map,
            len(velocities),
            min(0.8, 0.3 + len(velocities) / 50),
        )

        confidence = min(0.75, 0.3 + (len(velocities) / 40))
        now = _utcnow()

        velocity_strs = [
            f"'{t}' ({v:.3f}/obs, familiarity {f:.0%})"
            for t, f, v, _ in top_learning
        ]
        content = (
            f"Fastest learning topics: {'; '.join(velocity_strs)}. "
            f"Based on {len(velocities)} tracked topics."
        )

        return [
            Insight(
                id=_insight_id("learning_velocity", "top_velocity"),
                insight_type="learning_velocity",
                category="learning_rate",
                content=content,
                confidence=confidence,
                created_at=now,
                updated_at=now,
                metadata={
                    "top_topics": [
                        {"topic": t, "familiarity": round(f, 3), "velocity_per_observation": round(v, 4)}
                        for t, f, v, _ in top_learning
                    ],
                    "total_topics": len(velocities),
                },
            )
        ]

    def _analyze_plateaus(self, user_knowledge: list) -> list[Insight]:
        """Detect topics where familiarity has stalled (seen many times, low familiarity growth)."""
        plateaus: list[tuple[str, float, int]] = []

        for uk in user_knowledge:
            topic = uk.topic
            familiarity = uk.familiarity or 0.0
            times_seen = uk.times_seen or 0
            last_seen = uk.last_seen or ""

            # Plateau: seen many times, familiarity stuck in mid range, not recently active
            if times_seen < 5:
                continue
            if familiarity < 0.2 or familiarity > 0.75:
                continue  # not in learning zone

            weeks_since = _weeks_ago(last_seen) if last_seen else 999
            if weeks_since < 1.0:
                continue  # recently active, not a plateau yet

            # Estimate plateau: familiarity / times_seen < threshold
            avg_gain_per_see = familiarity / max(times_seen, 1)
            if avg_gain_per_see < _PLATEAU_THRESHOLD:
                plateaus.append((topic, familiarity, times_seen))

        if not plateaus:
            return []

        plateaus.sort(key=lambda x: x[1])  # worst stuck first
        top_plateaus = plateaus[:3]
        # Store plateau info in developer profile
        # (done as part of the insight metadata — no separate DB write needed here)
        confidence = min(0.75, 0.3 + (len(plateaus) / 10))
        now = _utcnow()

        plateau_strs = [
            f"'{t}' (familiarity {f:.0%}, seen {n}x)"
            for t, f, n in top_plateaus
        ]
        content = (
            f"Learning plateaus detected: {'; '.join(plateau_strs)}. "
            f"Consider deliberate practice or a different approach for these topics."
        )

        return [
            Insight(
                id=_insight_id("learning_velocity", "plateaus"),
                insight_type="learning_velocity",
                category="plateau_detection",
                content=content,
                confidence=confidence,
                created_at=now,
                updated_at=now,
                metadata={
                    "plateau_topics": [
                        {"topic": t, "familiarity": round(f, 3), "times_seen": n}
                        for t, f, n in top_plateaus
                    ],
                    "total_plateaus": len(plateaus),
                },
            )
        ]

    def _analyze_near_mastery(self, user_knowledge: list) -> list[Insight]:
        """Surface topics approaching mastery (familiarity > threshold)."""
        near_mastery = [
            (uk.topic, uk.familiarity, uk.times_seen)
            for uk in user_knowledge
            if (uk.familiarity or 0) >= _MASTERY_THRESHOLD
        ]

        if not near_mastery:
            return []

        near_mastery.sort(key=lambda x: -x[1])
        top = near_mastery[:5]

        confidence = min(0.85, 0.4 + len(near_mastery) / 20)
        now = _utcnow()

        topic_strs = [f"'{t}' ({f:.0%})" for t, f, _ in top]
        content = (
            f"Near-mastery topics: {', '.join(topic_strs)}. "
            f"These topics can be suppressed from verbose recall (already well known)."
        )

        return [
            Insight(
                id=_insight_id("learning_velocity", "near_mastery"),
                insight_type="learning_velocity",
                category="mastery_progress",
                content=content,
                confidence=confidence,
                created_at=now,
                updated_at=now,
                metadata={
                    "mastery_topics": [
                        {"topic": t, "familiarity": round(f, 3), "times_seen": n}
                        for t, f, n in top
                    ],
                    "mastery_count": len(near_mastery),
                    "mastery_threshold": _MASTERY_THRESHOLD,
                },
            )
        ]
