"""Auto-pruner: detects retirement candidates from memory_usefulness + theory metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from neurosync.logging import get_logger

if TYPE_CHECKING:
    from neurosync.db import Database

logger = get_logger("selflearn.pruner")

# Thresholds for retirement candidacy
_MIN_RECALL_COUNT = 10     # must have been recalled at least N times
_MAX_SCORE = 0.20          # usefulness score <= this
_MIN_CONTRADICTIONS = 1    # theory must have at least 1 contradiction
_MAX_CONFIRMATIONS = 1     # theory must have < 2 confirmations


@dataclass
class PruneCandidate:
    entity_id: str
    entity_type: str
    usefulness_score: float
    recall_count: int
    reason: str


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


class Pruner:
    """Detects theories that should be considered for retirement.

    Criteria (ALL must be satisfied):
    - recall_count >= 10  (enough data to be confident)
    - usefulness score <= 0.20  (consistently unhelpful)
    - contradiction_count >= 1  (has known contradictions)
    - confirmation_count < 2  (never confirmed)

    The pruner does NOT directly retire theories — it surfaces retirement
    candidates as insights in the intelligence layer, letting the user
    or a human-in-the-loop decide. This avoids destructive auto-deletion.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def find_candidates(self) -> list[PruneCandidate]:
        """Return theories that meet retirement criteria."""
        low_usefulness = self._db.list_low_usefulness(
            entity_type="theory",
            max_score=_MAX_SCORE,
            min_recall_count=_MIN_RECALL_COUNT,
        )
        if not low_usefulness:
            return []

        # Batch-fetch all theories in one query instead of N+1 individual fetches
        theory_ids = [row["entity_id"] for row in low_usefulness]
        theory_rows = self._db.get_theories_by_ids(theory_ids)

        candidates: list[PruneCandidate] = []
        for row in low_usefulness:
            theory_id = row["entity_id"]
            t = theory_rows.get(theory_id)
            if t is None:
                continue
            if not t["active"]:
                continue

            contradiction_count = t["contradiction_count"] or 0
            confirmation_count = t["confirmation_count"] or 0

            if (
                contradiction_count >= _MIN_CONTRADICTIONS
                and confirmation_count <= _MAX_CONFIRMATIONS
            ):
                reason = (
                    f"Recalled {row['recall_count']}x with usefulness score "
                    f"{row['score']:.2f}; {contradiction_count} contradiction(s), "
                    f"{confirmation_count} confirmation(s)."
                )
                candidates.append(
                    PruneCandidate(
                        entity_id=theory_id,
                        entity_type="theory",
                        usefulness_score=float(row["score"]),
                        recall_count=int(row["recall_count"]),
                        reason=reason,
                    )
                )

        return candidates

    def build_prune_insights(self) -> list[dict]:
        """Return insight dicts for retirement candidates (for the intelligence layer)."""
        import hashlib

        candidates = self.find_candidates()
        if not candidates:
            return []

        now = _utcnow()
        insights: list[dict] = []
        for c in candidates:
            insight_id = hashlib.sha256(
                f"prune:{c.entity_id}".encode()
            ).hexdigest()[:24]
            insights.append(
                {
                    "id": insight_id,
                    "insight_type": "self_learning",
                    "category": "retirement_candidate",
                    "content": (
                        f"Theory '{c.entity_id}' is a retirement candidate. {c.reason}"
                    ),
                    "confidence": 0.75,
                    "created_at": now,
                    "updated_at": now,
                    "metadata": {
                        "entity_id": c.entity_id,
                        "entity_type": c.entity_type,
                        "usefulness_score": c.usefulness_score,
                        "recall_count": c.recall_count,
                        "reason": c.reason,
                    },
                }
            )

        logger.info("Pruner found %d retirement candidate(s)", len(candidates))
        return insights
