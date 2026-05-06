"""Insight surfacing logic — decides what to show and when."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

from neurosync.db import Database


class InsightSurfacer:
    """Selects relevant insights for MCP responses."""

    MIN_CONFIDENCE = 0.4
    MAX_RECALL_INSIGHTS = 2
    MAX_RECORD_WARNINGS = 1

    def __init__(self, db: Database) -> None:
        self._db = db

    def select(
        self,
        project: str = "",
        context: str = "",
        limit: int = 2,
        exclude_ids: Optional[set[str]] = None,
    ) -> list[dict[str, Any]]:
        """Select top insights to surface in recall response."""
        insights = self._db.list_insights(
            min_confidence=self.MIN_CONFIDENCE,
            dismissed=False,
            limit=20,
        )

        exclude = exclude_ids or set()
        candidates = []

        for ins in insights:
            if ins["id"] in exclude:
                continue
            relevance = self._score_relevance(ins, project, context)
            if relevance > 0:
                candidates.append((relevance, ins))

        candidates.sort(key=lambda x: -x[0])
        return [c[1] for c in candidates[:limit]]

    def select_warnings(
        self,
        project: str = "",
        session_start: Optional[float] = None,
        exclude_ids: Optional[set[str]] = None,
    ) -> list[dict[str, Any]]:
        """Select warning-type insights for record response."""
        insights = self._db.list_insights(
            min_confidence=self.MIN_CONFIDENCE,
            dismissed=False,
            insight_type="work_pattern",
            limit=10,
        )

        exclude = exclude_ids or set()
        warnings = []

        for ins in insights:
            if ins["id"] in exclude:
                continue
            if ins.get("category") not in ("fatigue_warning", "session_rhythm"):
                continue

            # Check if session duration exceeds fatigue threshold
            if session_start and ins.get("category") == "fatigue_warning":
                elapsed_min = (time.time() - session_start) / 60
                threshold = ins.get("metadata", {}).get("threshold_minutes", 150)
                if elapsed_min >= threshold:
                    warnings.append(ins)
            elif ins.get("category") == "session_rhythm":
                warnings.append(ins)

        return warnings[: self.MAX_RECORD_WARNINGS]

    def _score_relevance(
        self,
        insight: dict[str, Any],
        project: str,
        context: str,
    ) -> float:
        """Compute relevance score for an insight."""
        confidence = insight.get("confidence", 0.5)
        updated_at = insight.get("updated_at", "")
        surfaced_count = insight.get("surfaced_count", 0)
        insight_project = insight.get("project", "")

        # Recency: newer insights more relevant
        recency_factor = 0.5
        if updated_at:
            try:
                dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                elapsed = datetime.now(timezone.utc) - dt
                days_old = elapsed.total_seconds() / 86400
                recency_factor = max(0.3, 1.0 - (days_old / 30))
            except (ValueError, AttributeError):
                pass

        # Novelty: insights surfaced less are more interesting
        novelty_factor = 1.0 / (1 + surfaced_count)

        # Context match: same project = boost
        context_factor = 1.0
        if project and insight_project:
            context_factor = 1.5 if insight_project == project else 0.8
        elif not insight_project:
            context_factor = 1.0

        return confidence * recency_factor * novelty_factor * context_factor
