"""Forgetting engine: Ebbinghaus retention, spaced repetition, active pruning."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

from neurosync.db import Database
from neurosync.models import Episode, Theory, _utcnow
from neurosync.vectorstore import VectorStore

# Episode types that must never be pruned
_PROTECTED_TYPES = frozenset({"correction", "continuation", "explicit"})


class ForgettingEngine:
    """Manages memory retention using Ebbinghaus curves and spaced repetition."""

    def __init__(self, db: Database, vectorstore: Optional[VectorStore] = None) -> None:
        self._db = db
        self._vs = vectorstore

    # --- Episode retention (Ebbinghaus) ---

    def compute_episode_stability(self, episode: Episode) -> float:
        """Compute memory stability S for an episode.

        S = base * weight_factor * quality_factor * 2^reinforcements
        Higher stability = slower forgetting.
        """
        base = 7.0  # 7 days base stability
        weight_factor = min(episode.signal_weight, 10.0) / 2.0
        quality = episode.quality_score if episode.quality_score is not None else 3
        quality_factor = max(0.5, quality / 7.0)
        reinforcement_factor = 2 ** min(episode.reinforcement_count, 10)
        return base * weight_factor * quality_factor * reinforcement_factor

    def compute_episode_retention(self, episode: Episode) -> float:
        """Compute retention R = e^(-t/S) where t is days since creation.

        Returns a value between 0.0 (forgotten) and 1.0 (fresh).
        """
        now = datetime.now(timezone.utc)
        created = datetime.fromisoformat(episode.timestamp)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = max(0, (now - created).total_seconds() / 86400.0)
        stability = self.compute_episode_stability(episode)
        if stability <= 0:
            return 0.0
        return math.exp(-age_days / stability)

    def reinforce_episode(self, episode_id: str) -> None:
        """Mark an episode as reinforced (recalled), extending its retention."""
        episode = self._db.get_episode(episode_id)
        if not episode:
            return
        self._db.update_episode_access(
            episode_id,
            reinforcement_count=episode.reinforcement_count + 1,
            last_accessed=_utcnow(),
        )

    # --- Active pruning ---

    def prune_low_value_episodes(
        self,
        retention_threshold: float = 0.1,
        max_prune: int = 100,
    ) -> int:
        """Prune low-retention consolidated episodes from vectorstore.

        Never prunes corrections, continuations, or explicit episodes.
        Only prunes consolidated (state=1) episodes with quality < 5.
        """
        candidates = self._db.list_episodes_for_pruning(
            min_age_days=7,
            consolidated=1,
            limit=max_prune * 3,
        )
        pruned_ids: list[str] = []
        for episode in candidates:
            if len(pruned_ids) >= max_prune:
                break
            if episode.event_type in _PROTECTED_TYPES:
                continue
            if episode.quality_score is not None and episode.quality_score >= 5:
                continue
            retention = self.compute_episode_retention(episode)
            if retention < retention_threshold:
                pruned_ids.append(episode.id)

        if pruned_ids:
            self._db.mark_episodes_decayed(pruned_ids)
            if self._vs:
                self._vs.remove_episodes(pruned_ids)
        return len(pruned_ids)

    # --- Theory Ebbinghaus decay (replaces linear decay) ---

    def apply_ebbinghaus_theory_decay(self, base_grace_days: int = 30) -> int:
        """Apply Ebbinghaus-style decay to theories.

        stability = grace * (1 + log2(confirmations + applications + 1))
        confidence *= e^(-overdue / stability)
        """
        now = datetime.now(timezone.utc)
        theories = self._db.list_theories(active_only=True, limit=1000)
        affected = 0
        for theory in theories:
            if not theory.last_confirmed:
                continue
            last = datetime.fromisoformat(theory.last_confirmed)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            days_since = (now - last).days
            if days_since <= base_grace_days:
                continue
            # Stability grows with usage
            usage = theory.confirmation_count + theory.application_count + 1
            stability = base_grace_days * (1.0 + math.log2(max(usage, 1)))
            overdue = days_since - base_grace_days
            decay_factor = math.exp(-overdue / stability)
            theory.confidence = max(0.0, theory.confidence * decay_factor)
            if theory.confidence <= 0.05:
                theory.active = False
                if self._vs:
                    self._vs.remove_theory(theory.id)
            else:
                if self._vs:
                    self._vs.add_theory(theory)
            self._db.save_theory(theory)
            affected += 1
        return affected

    def refresh_theory_on_application(self, theory: Theory) -> Theory:
        """Extend a theory's effective grace period by updating last_confirmed."""
        theory.last_confirmed = _utcnow()
        self._db.save_theory(theory)
        if self._vs:
            self._vs.add_theory(theory)
        return theory

    # --- Batch operation ---

    def run_forgetting_pass(self, active_project: str = "") -> dict[str, Any]:
        """Run a complete forgetting pass: prune episodes + decay theories."""
        pruned = self.prune_low_value_episodes()
        decayed = self.apply_ebbinghaus_theory_decay()
        return {
            "episodes_pruned": pruned,
            "theories_decayed": decayed,
        }
