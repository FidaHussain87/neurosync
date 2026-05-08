"""Beta(α,β) usefulness scorer with Thompson sampling for memory entity selection."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neurosync.db import Database


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


@dataclass
class UsefulnessRecord:
    entity_id: str
    entity_type: str  # 'theory' | 'episode' | 'distilled'
    alpha: float = 1.0
    beta: float = 1.0
    recall_count: int = 0
    last_recalled: str = ""
    last_outcome: str = ""

    @property
    def score(self) -> float:
        """Mean of Beta distribution: α / (α+β)."""
        return self.alpha / (self.alpha + self.beta)

    def thompson_sample(self) -> float:
        """Draw a Thompson sample for exploration-exploitation balance."""
        return random.betavariate(self.alpha, self.beta)

    def reward(self, weight: float = 1.0) -> None:
        """Positive signal: recall led to a clean session."""
        self.alpha += weight

    def penalize(self, weight: float = 0.6) -> None:
        """Negative signal: recall was followed by a correction."""
        self.beta += weight


class UsefulnessScorer:
    """Manages Beta-distribution usefulness scores for memory entities.

    Scoring is purely Bayesian:
    - New entity starts at Beta(1,1) = uniform prior (score=0.5)
    - Each clean session: alpha += 1.0
    - Each correction immediately: beta += 0.6
    - Each session-end correction signal: beta += 1.0 per correction
    - score = alpha / (alpha + beta)  -- the posterior mean
    - thompson_sample() for selection (natural exploration vs exploitation)
    """

    # Correction weight applied at session end per correction event
    SESSION_CORRECTION_WEIGHT = 1.0
    # Immediate correction weight (mid-session signal)
    IMMEDIATE_CORRECTION_WEIGHT = 0.6
    # Reward weight for clean session
    CLEAN_REWARD_WEIGHT = 1.0
    # Partial reward for "mixed" session (some corrections, not all recall-related)
    MIXED_REWARD_WEIGHT = 0.3

    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, entity_id: str, entity_type: str) -> UsefulnessRecord:
        """Return the usefulness record, creating a default if absent."""
        row = self._db.get_usefulness(entity_id, entity_type)
        if row is None:
            return UsefulnessRecord(
                entity_id=entity_id,
                entity_type=entity_type,
            )
        return UsefulnessRecord(
            entity_id=row["entity_id"],
            entity_type=row["entity_type"],
            alpha=float(row["alpha"]),
            beta=float(row["beta"]),
            recall_count=int(row["recall_count"]),
            last_recalled=row.get("last_recalled") or "",
            last_outcome=row.get("last_outcome") or "",
        )

    def get_bulk(
        self, entity_ids: list[str], entity_type: str
    ) -> dict[str, UsefulnessRecord]:
        """Return usefulness records for multiple entities keyed by entity_id."""
        rows = self._db.list_usefulness_for_entities(entity_ids, entity_type)
        result: dict[str, UsefulnessRecord] = {}
        for eid in entity_ids:
            if eid in rows:
                r = rows[eid]
                result[eid] = UsefulnessRecord(
                    entity_id=r["entity_id"],
                    entity_type=r["entity_type"],
                    alpha=float(r["alpha"]),
                    beta=float(r["beta"]),
                    recall_count=int(r["recall_count"]),
                    last_recalled=r.get("last_recalled") or "",
                    last_outcome=r.get("last_outcome") or "",
                )
            else:
                result[eid] = UsefulnessRecord(
                    entity_id=eid, entity_type=entity_type
                )
        return result

    def save(self, record: UsefulnessRecord) -> None:
        """Persist a usefulness record to the database."""
        self._db.upsert_usefulness(
            entity_id=record.entity_id,
            entity_type=record.entity_type,
            alpha=record.alpha,
            beta=record.beta,
            recall_count=record.recall_count,
            last_recalled=record.last_recalled or _utcnow(),
            last_outcome=record.last_outcome,
            score=record.score,
            now=_utcnow(),
        )

    def on_recall(self, entity_ids: list[str], entity_type: str) -> None:
        """Increment recall_count for all entities surfaced in a recall response."""
        if not entity_ids:
            return
        now = _utcnow()
        existing = self._db.list_usefulness_for_entities(entity_ids, entity_type)
        batch: list[dict] = []
        for eid in entity_ids:
            if eid in existing:
                r = existing[eid]
                batch.append(
                    {
                        "entity_id": eid,
                        "entity_type": entity_type,
                        "alpha": float(r["alpha"]),
                        "beta": float(r["beta"]),
                        "recall_count": int(r["recall_count"]) + 1,
                        "last_recalled": now,
                        "last_outcome": r.get("last_outcome") or "",
                        "score": float(r["alpha"]) / (float(r["alpha"]) + float(r["beta"])),
                        "now": now,
                    }
                )
            else:
                batch.append(
                    {
                        "entity_id": eid,
                        "entity_type": entity_type,
                        "alpha": 1.0,
                        "beta": 1.0,
                        "recall_count": 1,
                        "last_recalled": now,
                        "last_outcome": "",
                        "score": 0.5,
                        "now": now,
                    }
                )
        self._db.bulk_update_usefulness(batch)

    def on_correction(self, entity_ids: list[str], entity_type: str) -> None:
        """Apply immediate correction penalty (beta += 0.6) to recalled entities."""
        if not entity_ids:
            return
        now = _utcnow()
        existing = self._db.list_usefulness_for_entities(entity_ids, entity_type)
        batch: list[dict] = []
        for eid in entity_ids:
            if eid in existing:
                r = existing[eid]
                new_beta = float(r["beta"]) + self.IMMEDIATE_CORRECTION_WEIGHT
                new_alpha = float(r["alpha"])
            else:
                new_alpha = 1.0
                new_beta = 1.0 + self.IMMEDIATE_CORRECTION_WEIGHT
            new_score = new_alpha / (new_alpha + new_beta)
            existing_row = existing.get(eid, {})
            batch.append(
                {
                    "entity_id": eid,
                    "entity_type": entity_type,
                    "alpha": new_alpha,
                    "beta": new_beta,
                    "recall_count": int(existing_row.get("recall_count", 0)),
                    "last_recalled": existing_row.get("last_recalled") or now,
                    "last_outcome": "corrected",
                    "score": new_score,
                    "now": now,
                }
            )
        self._db.bulk_update_usefulness(batch)

    def on_session_end(
        self,
        entity_ids: list[str],
        entity_type: str,
        outcome: str,
        correction_count: int,
    ) -> None:
        """Apply session-end outcome signals to recalled entities.

        outcome: 'clean' | 'corrected' | 'mixed'
        correction_count: total corrections in the session
        """
        if not entity_ids:
            return
        now = _utcnow()
        existing = self._db.list_usefulness_for_entities(entity_ids, entity_type)
        batch: list[dict] = []

        for eid in entity_ids:
            r = existing.get(eid)
            alpha = float(r["alpha"]) if r else 1.0
            beta = float(r["beta"]) if r else 1.0
            recall_count = int(r["recall_count"]) if r else 0
            last_recalled = (r.get("last_recalled") or now) if r else now

            if outcome == "clean":
                alpha += self.CLEAN_REWARD_WEIGHT
            elif outcome == "corrected":
                beta += self.SESSION_CORRECTION_WEIGHT * max(1, correction_count)
            elif outcome == "mixed":
                alpha += self.MIXED_REWARD_WEIGHT

            new_score = alpha / (alpha + beta)
            batch.append(
                {
                    "entity_id": eid,
                    "entity_type": entity_type,
                    "alpha": alpha,
                    "beta": beta,
                    "recall_count": recall_count,
                    "last_recalled": last_recalled,
                    "last_outcome": outcome,
                    "score": new_score,
                    "now": now,
                }
            )
        self._db.bulk_update_usefulness(batch)
