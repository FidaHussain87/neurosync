"""Outcome tracker: writes recall_log entries and signals session outcomes."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neurosync.db import Database


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _recall_id(session_id: str, recalled_at: str) -> str:
    return hashlib.sha256(f"{session_id}:{recalled_at}".encode()).hexdigest()[:24]


def _context_hash(context: str) -> str:
    return hashlib.sha256(context.encode()).hexdigest()[:16]


@dataclass
class ActiveRecall:
    """In-memory state for a pending recall within a session."""

    recall_id: str
    session_id: str
    recalled_at: str
    theory_ids: list[str]
    episode_ids: list[str]
    tokens_used: int
    correction_count: int = 0


class OutcomeTracker:
    """Tracks recall outcomes per session and writes recall_log entries.

    Lifecycle:
    1. on_recall()  — called when handle_recall() runs; inserts recall_log entry
    2. on_correction() — called when handle_correct() runs; increments correction_count
    3. on_session_end() — called when _rotate_session() runs; finalises outcome label
    """

    _PENDING = "pending"
    _CLEAN = "clean"
    _CORRECTED = "corrected"
    _MIXED = "mixed"

    def __init__(self, db: Database) -> None:
        self._db = db
        self._lock = threading.Lock()
        # session_id -> list[ActiveRecall]
        self._active: dict[str, list[ActiveRecall]] = {}

    def on_recall(
        self,
        session_id: str,
        theory_ids: list[str],
        episode_ids: list[str],
        tokens_used: int,
        context: str = "",
    ) -> str:
        """Record a new recall event. Returns the recall_id."""
        now = _utcnow()
        recall_id = _recall_id(session_id, now)
        ctx_hash = _context_hash(context)

        self._db.insert_recall_log(
            recall_id=recall_id,
            session_id=session_id,
            recalled_at=now,
            context_hash=ctx_hash,
            theory_ids=theory_ids,
            episode_ids=episode_ids,
            tokens_used=tokens_used,
        )

        ar = ActiveRecall(
            recall_id=recall_id,
            session_id=session_id,
            recalled_at=now,
            theory_ids=list(theory_ids),
            episode_ids=list(episode_ids),
            tokens_used=tokens_used,
        )
        with self._lock:
            self._active.setdefault(session_id, []).append(ar)
        return recall_id

    def on_correction(self, session_id: str) -> None:
        """Increment correction_count on all pending recalls in the session."""
        with self._lock:
            recalls = list(self._active.get(session_id, []))
            for ar in recalls:
                ar.correction_count += 1
        # Persist increments outside the lock so DB I/O doesn't block other threads.
        # Using the snapshot taken inside the lock above — safe against concurrent pop().
        for ar in recalls:
            self._db.increment_recall_log_corrections(ar.recall_id)

    def on_session_end(self, session_id: str) -> list[ActiveRecall]:
        """Finalise outcome labels for all recalls in the session.

        Returns the list of finalised ActiveRecall objects so callers can
        apply usefulness updates.
        """
        now = _utcnow()
        with self._lock:
            recalls = self._active.pop(session_id, [])

        for ar in recalls:
            if ar.correction_count == 0:
                outcome = self._CLEAN
            elif ar.correction_count >= 3:
                outcome = self._CORRECTED
            else:
                outcome = self._MIXED
            self._db.update_recall_log_outcome(
                recall_id=ar.recall_id,
                outcome=outcome,
                correction_count=ar.correction_count,
                outcome_at=now,
            )

        return recalls

    def get_session_correction_count(self, session_id: str) -> int:
        """Return total corrections recorded for a session so far."""
        with self._lock:
            recalls = self._active.get(session_id, [])
            return sum(ar.correction_count for ar in recalls)

    def get_active_theory_ids(self, session_id: str) -> list[str]:
        """Return all theory_ids from active (pending) recalls in this session."""
        with self._lock:
            recalls = self._active.get(session_id, [])
            seen: set[str] = set()
            result: list[str] = []
            for ar in recalls:
                for tid in ar.theory_ids:
                    if tid not in seen:
                        seen.add(tid)
                        result.append(tid)
        return result
