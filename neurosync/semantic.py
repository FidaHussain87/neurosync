"""Layer 2: Semantic memory — theory CRUD, confidence management, superseding."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from neurosync.db import Database
from neurosync.models import Contradiction, Theory, _utcnow
from neurosync.vectorstore import VectorStore


class SemanticMemory:
    """Manages theories and contradictions (Layer 2)."""

    def __init__(self, db: Database, vectorstore: Optional[VectorStore] = None) -> None:
        self._db = db
        self._vs = vectorstore

    # --- Theory CRUD ---

    def create_theory(
        self,
        content: str,
        scope: str = "craft",
        scope_qualifier: str = "",
        confidence: float = 0.5,
        source_episodes: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Theory:
        theory = Theory(
            content=content,
            scope=scope,
            scope_qualifier=scope_qualifier,
            confidence=confidence,
            source_episodes=source_episodes or [],
            metadata=metadata or {},
        )
        self._db.save_theory(theory)
        if self._vs:
            self._vs.add_theory(theory)
        # Dual-write: junction table
        for ep_id in theory.source_episodes:
            self._db.add_theory_episode(theory.id, ep_id)
        return theory

    def get_theory(self, theory_id: str) -> Optional[Theory]:
        return self._db.get_theory(theory_id)

    def list_theories(
        self,
        active_only: bool = True,
        scope: Optional[str] = None,
        project: Optional[str] = None,
        limit: int = 50,
    ) -> list[Theory]:
        return self._db.list_theories(
            active_only=active_only, scope=scope, project=project, limit=limit
        )

    def confirm_theory(self, theory_id: str, episode_id: str = "") -> Optional[Theory]:
        """Increase confidence when an episode confirms a theory."""
        theory = self._db.get_theory(theory_id)
        if not theory:
            return None
        theory.confirmation_count += 1
        theory.last_confirmed = _utcnow()
        # Confidence grows asymptotically toward 1.0
        theory.confidence = min(
            1.0,
            theory.confidence + (1.0 - theory.confidence) * 0.1,
        )
        if episode_id and episode_id not in theory.source_episodes:
            theory.source_episodes.append(episode_id)
        # Dual-write: junction table
        if episode_id:
            self._db.add_theory_episode(theory_id, episode_id)
        # Update validation status
        if theory.contradiction_count > 0:
            theory.validation_status = "mixed"
        else:
            theory.validation_status = "confirmed"
        self._db.save_theory(theory)
        if self._vs:
            self._vs.add_theory(theory)
        return theory

    def contradict_theory(
        self,
        theory_id: str,
        episode_id: str,
        description: str,
    ) -> Optional[Contradiction]:
        """Record a contradiction and decrease theory confidence."""
        theory = self._db.get_theory(theory_id)
        if not theory:
            return None
        theory.contradiction_count += 1
        theory.confidence = max(0.0, theory.confidence - 0.15)
        # Update validation status
        if theory.confirmation_count > 0:
            theory.validation_status = "mixed"
        else:
            theory.validation_status = "contradicted"
        self._db.save_theory(theory)
        if self._vs:
            self._vs.add_theory(theory)
        contradiction = Contradiction(
            theory_id=theory_id,
            episode_id=episode_id,
            description=description,
        )
        return self._db.save_contradiction(contradiction)

    def link_theories(
        self, theory_id: str, related_ids: list[str]
    ) -> Optional[Theory]:
        """Link theories bidirectionally."""
        theory = self._db.get_theory(theory_id)
        if not theory:
            return None
        for rid in related_ids:
            if rid not in theory.related_theories:
                theory.related_theories.append(rid)
            # Bidirectional: add reverse link
            related = self._db.get_theory(rid)
            if related and theory_id not in related.related_theories:
                related.related_theories.append(theory_id)
                self._db.save_theory(related)
            # Dual-write: junction table (bidirectional)
            self._db.add_theory_relation(theory_id, rid)
            self._db.add_theory_relation(rid, theory_id)
        self._db.save_theory(theory)
        return theory

    def set_parent_theory(
        self, child_id: str, parent_id: str
    ) -> Optional[Theory]:
        """Set a parent-child relationship between theories."""
        child = self._db.get_theory(child_id)
        if not child:
            return None
        child.parent_theory_id = parent_id
        self._db.save_theory(child)
        return child

    def record_application(self, theory_id: str) -> Optional[Theory]:
        """Track when a theory is applied during recall."""
        theory = self._db.get_theory(theory_id)
        if not theory:
            return None
        theory.last_applied = _utcnow()
        theory.application_count += 1
        self._db.save_theory(theory)
        return theory

    def find_related_theories(
        self, theory_id: str, distance_threshold: float = 0.4
    ) -> list[Theory]:
        """Find semantically related theories via vector search."""
        if not self._vs:
            return []
        theory = self._db.get_theory(theory_id)
        if not theory:
            return []
        results = self._vs.search_theories(
            theory.content, n_results=10, active_only=True
        )
        related: list[Theory] = []
        for result in results:
            if result["id"] == theory_id:
                continue
            if result.get("distance", 1.0) < distance_threshold:
                t = self._db.get_theory(result["id"])
                if t and t.active:
                    related.append(t)
        return related

    def supersede_theory(self, old_id: str, new_id: str) -> None:
        """Mark a theory as superseded by another."""
        old = self._db.get_theory(old_id)
        if old:
            old.active = False
            old.superseded_by = new_id
            self._db.save_theory(old)
            if self._vs:
                self._vs.remove_theory(old_id)

    def retire_theory(self, theory_id: str) -> Optional[Theory]:
        """Manually deactivate a theory."""
        theory = self._db.get_theory(theory_id)
        if not theory:
            return None
        theory.active = False
        self._db.save_theory(theory)
        if self._vs:
            self._vs.remove_theory(theory_id)
        return theory

    def apply_confidence_decay(self, decay_days: int = 30, decay_rate: float = 0.01) -> int:
        """Decay confidence on theories not confirmed recently. Returns count affected."""
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
            if days_since > decay_days:
                overdue = days_since - decay_days
                theory.confidence = max(0.0, theory.confidence - overdue * decay_rate)
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

    # --- Contradictions ---

    def list_contradictions(
        self,
        theory_id: Optional[str] = None,
        unresolved_only: bool = False,
    ) -> list[Contradiction]:
        return self._db.list_contradictions(
            theory_id=theory_id, unresolved_only=unresolved_only
        )

    # --- Search ---

    def search(
        self, query: str, n_results: int = 10, active_only: bool = True
    ) -> list[dict[str, Any]]:
        if not self._vs:
            return []
        return self._vs.search_theories(query, n_results=n_results, active_only=active_only)
