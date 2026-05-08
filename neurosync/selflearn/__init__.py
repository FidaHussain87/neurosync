"""Self-Learning Memory Layer (Layer 9) — Bayesian feedback loop for memory quality.

Entry point: SelfLearningLayer

Lifecycle integration points:
1. on_recall()   — after handle_recall(): log recall, update usefulness recall_counts
2. on_correction() — in handle_correct(): immediate beta penalty + log increment
3. on_session_end() — in _rotate_session(): finalise outcome labels, apply rewards/penalties
4. get_ranked_theories() — replaces raw retrieval output with usefulness-reranked, budget-packed result
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from neurosync.logging import get_logger
from neurosync.selflearn.budget_packer import BudgetPacker
from neurosync.selflearn.distiller import Distiller
from neurosync.selflearn.outcome_tracker import OutcomeTracker
from neurosync.selflearn.pruner import Pruner
from neurosync.selflearn.reranker import Reranker
from neurosync.selflearn.usefulness import UsefulnessScorer

if TYPE_CHECKING:
    from neurosync.db import Database

logger = get_logger("selflearn")


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: 4 characters per token."""
    return max(1, len(text) // 4)


class SelfLearningLayer:
    """Orchestrates all self-learning components.

    Designed to be created once in mcp_server._init() and shared across
    tool handlers. Thread-safe — all writes use database locks and the
    outcome_tracker's internal lock.

    Token budget shrinks over time as quality improves:
    - Initial default: 500 tokens
    - After 50 sessions with avg score ≥ 0.7: 350 tokens
    - After 200 sessions with avg score ≥ 0.8: 200 tokens
    """

    _INITIAL_BUDGET = 500
    _REDUCED_BUDGET = 350
    _MINIMAL_BUDGET = 200

    def __init__(self, db: Database) -> None:
        self._db = db
        self._scorer = UsefulnessScorer(db)
        self._tracker = OutcomeTracker(db)
        self._reranker = Reranker(self._scorer)
        self._packer = BudgetPacker()
        self._distiller = Distiller(db)
        self._pruner = Pruner(db)
        self._lock = threading.Lock()
        # session_id -> list[str] of recalled theory_ids
        self._session_theory_ids: dict[str, list[str]] = {}

    # ------------------------------------------------------------------ #
    # Integration Point 1: on_recall                                       #
    # ------------------------------------------------------------------ #

    def on_recall(
        self,
        session_id: str,
        theory_ids: list[str],
        episode_ids: list[str],
        tokens_used: int,
        context: str = "",
    ) -> str:
        """Record a recall event. Returns recall_id for traceability."""
        recall_id = self._tracker.on_recall(
            session_id=session_id,
            theory_ids=theory_ids,
            episode_ids=episode_ids,
            tokens_used=tokens_used,
            context=context,
        )
        # Update recall_counts in memory_usefulness
        self._scorer.on_recall(theory_ids, "theory")
        if episode_ids:
            self._scorer.on_recall(episode_ids, "episode")

        # Track for session-end processing
        with self._lock:
            existing = self._session_theory_ids.setdefault(session_id, [])
            seen = set(existing)
            for tid in theory_ids:
                if tid not in seen:
                    existing.append(tid)
                    seen.add(tid)

        return recall_id

    # ------------------------------------------------------------------ #
    # Integration Point 2: on_correction                                   #
    # ------------------------------------------------------------------ #

    def on_correction(self, session_id: str) -> None:
        """Apply immediate correction penalty to theories recalled in this session."""
        self._tracker.on_correction(session_id)
        theory_ids = self._tracker.get_active_theory_ids(session_id)
        if theory_ids:
            self._scorer.on_correction(theory_ids, "theory")

    # ------------------------------------------------------------------ #
    # Integration Point 3: on_session_end                                  #
    # ------------------------------------------------------------------ #

    def on_session_end(self, session_id: str) -> dict:
        """Finalise outcome labels and apply session-end rewards/penalties.

        Returns a summary dict with outcome stats for logging.
        """
        finalised = self._tracker.on_session_end(session_id)

        with self._lock:
            session_theory_ids = self._session_theory_ids.pop(session_id, [])

        if not finalised or not session_theory_ids:
            return {"session_id": session_id, "recalls_finalised": 0}

        total_corrections = sum(ar.correction_count for ar in finalised)

        # Apply outcome signals per-recall so theories are only penalised
        # for corrections that happened in the recall where they appeared —
        # not for unrelated errors in the same session.
        for ar in finalised:
            if not ar.theory_ids:
                continue
            if ar.correction_count == 0:
                outcome = "clean"
            elif ar.correction_count >= 3:
                outcome = "corrected"
            else:
                outcome = "mixed"
            self._scorer.on_session_end(
                entity_ids=ar.theory_ids,
                entity_type="theory",
                outcome=outcome,
                correction_count=ar.correction_count,
            )

        # Derive session-level outcome for reporting only
        if total_corrections == 0:
            session_outcome = "clean"
        elif total_corrections >= 3:
            session_outcome = "corrected"
        else:
            session_outcome = "mixed"

        logger.info(
            "Session %s ended: outcome=%s corrections=%d recalls=%d",
            session_id,
            session_outcome,
            total_corrections,
            len(finalised),
        )

        return {
            "session_id": session_id,
            "outcome": session_outcome,
            "total_corrections": total_corrections,
            "recalls_finalised": len(finalised),
            "theories_updated": len(session_theory_ids),
        }

    # ------------------------------------------------------------------ #
    # Integration Point 4: rerank + pack theories for recall               #
    # ------------------------------------------------------------------ #

    def get_ranked_theories(
        self,
        theories: list[dict],
        token_budget: int | None = None,
        use_distilled: bool = True,
    ) -> list[dict]:
        """Rerank and budget-pack theories for a recall response.

        Args:
            theories: Raw theory dicts from retrieval pipeline. Each must have
                      'id', 'content', and optionally 'relevance' (0-1 float).
            token_budget: Override token budget (default: adaptive based on history).
            use_distilled: If True, replace verbose content with distilled version.

        Returns:
            Filtered, reranked, budget-packed list of theory dicts.
        """
        if not theories:
            return []

        budget = token_budget if token_budget is not None else self._compute_budget()

        # Optionally replace content with distilled version
        if use_distilled:
            for t in theories:
                tid = t.get("id", "")
                content = t.get("content", "")
                if tid and content:
                    t["content"] = self._distiller.get_or_distill(tid, content)

        # Build candidate list for reranker
        candidates = []
        for t in theories:
            candidates.append(
                {
                    "id": t.get("id", ""),
                    "relevance": float(t.get("relevance", 0.5)),
                    "tokens": _estimate_tokens(t.get("content", "")),
                    "content": t.get("content", ""),
                    "metadata": t.get("metadata", {}),
                }
            )

        ranked = self._reranker.rerank(candidates, entity_type="theory")
        packed = self._packer.pack(ranked, budget=budget)

        # Reconstruct theory dicts from packed items preserving original fields
        id_to_theory = {t.get("id", ""): t for t in theories}
        result: list[dict] = []
        for item in packed.items:
            original = id_to_theory.get(item.entity_id, {})
            out = dict(original)
            out["content"] = item.content  # possibly distilled
            out["_usefulness_score"] = round(item.usefulness_score, 3)
            out["_tokens"] = item.tokens
            result.append(out)

        return result

    def _compute_budget(self) -> int:
        """Compute adaptive token budget based on observed theory usefulness."""
        try:
            # Use retirement candidates list (min_recall_count=1 for broad sample)
            # as a proxy — higher avg score in the bottom = generally improving quality
            rows = self._db.list_low_usefulness(
                entity_type="theory", max_score=0.99, min_recall_count=1
            )
            if not rows:
                return self._INITIAL_BUDGET
            scores = [float(r["score"]) for r in rows]
            n = len(scores)
            avg_score = sum(scores) / n
            # If we have many low-quality entries, budget needs to stay high
            # to compensate. If entries are moderately good (avg ≥ 0.5), reduce.
            if n >= 200 and avg_score >= 0.5:
                return self._MINIMAL_BUDGET
            if n >= 50 and avg_score >= 0.4:
                return self._REDUCED_BUDGET
        except Exception:
            pass
        return self._INITIAL_BUDGET

    # ------------------------------------------------------------------ #
    # Periodic maintenance                                                 #
    # ------------------------------------------------------------------ #

    def run_maintenance(self) -> dict:
        """Run periodic self-learning maintenance tasks.

        Called by the intelligence engine on its background thread.
        Returns a summary dict.
        """
        prune_insights = self._pruner.build_prune_insights()

        # Persist prune insights to the insights table
        persisted = 0
        for ins in prune_insights:
            try:
                from neurosync.intelligence.models import Insight

                insight = Insight(
                    id=ins["id"],
                    insight_type=ins["insight_type"],
                    category=ins["category"],
                    content=ins["content"],
                    confidence=ins["confidence"],
                    created_at=ins["created_at"],
                    updated_at=ins["updated_at"],
                    metadata=ins["metadata"],
                )
                self._db.upsert_insight(insight)
                persisted += 1
            except Exception as exc:
                logger.debug("Failed to persist prune insight: %s", exc)

        return {
            "prune_candidates": len(prune_insights),
            "insights_persisted": persisted,
        }
