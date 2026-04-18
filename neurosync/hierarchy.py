"""Hierarchical theory abstraction: graph traversal, semantic parents, merging."""

from __future__ import annotations

from typing import Any, Optional

from neurosync.db import Database
from neurosync.models import Theory, _new_id, _utcnow
from neurosync.vectorstore import VectorStore


class TheoryHierarchy:
    """Manages the theory parent-child hierarchy."""

    def __init__(self, db: Database, vectorstore: Optional[VectorStore] = None) -> None:
        self._db = db
        self._vs = vectorstore

    # --- Traversal ---

    def get_depth(self, theory_id: str) -> int:
        """Compute depth by walking parent chain."""
        depth = 0
        current = self._db.get_theory(theory_id)
        visited: set[str] = set()
        while current and current.parent_theory_id and current.parent_theory_id not in visited:
            visited.add(current.id)
            depth += 1
            current = self._db.get_theory(current.parent_theory_id)
        return depth

    def get_ancestors(self, theory_id: str, max_depth: int = 5) -> list[Theory]:
        """Get ancestor chain from immediate parent up to root."""
        ancestors: list[Theory] = []
        current = self._db.get_theory(theory_id)
        visited: set[str] = set()
        while current and current.parent_theory_id and len(ancestors) < max_depth:
            if current.parent_theory_id in visited:
                break
            visited.add(current.id)
            parent = self._db.get_theory(current.parent_theory_id)
            if parent:
                ancestors.append(parent)
            current = parent
        return ancestors

    def get_children(self, theory_id: str) -> list[Theory]:
        """Get direct children of a theory."""
        return self._db.list_children_of_theory(theory_id)

    def get_subtree(self, theory_id: str, max_depth: int = 3) -> dict[str, Any]:
        """Get the full subtree rooted at theory_id."""
        theory = self._db.get_theory(theory_id)
        if not theory:
            return {}
        return self._build_subtree(theory, 0, max_depth)

    def _build_subtree(self, theory: Theory, depth: int, max_depth: int) -> dict[str, Any]:
        node: dict[str, Any] = {
            "id": theory.id,
            "content": theory.content,
            "scope": theory.scope,
            "confidence": theory.confidence,
            "depth": depth,
        }
        if depth < max_depth:
            children = self._db.list_children_of_theory(theory.id)
            node["children"] = [
                self._build_subtree(child, depth + 1, max_depth)
                for child in children
            ]
        else:
            node["children"] = []
        return node

    # --- Semantic parent detection ---

    def find_semantic_parent(
        self, theory_id: str, distance_threshold: float = 0.35
    ) -> Optional[Theory]:
        """Find a broader theory that could be the parent.

        A parent candidate must:
        - Be semantically similar (distance < threshold)
        - Have more source_episodes (broader)
        - Have higher or equal confirmation_count
        """
        if not self._vs:
            return None
        theory = self._db.get_theory(theory_id)
        if not theory:
            return None
        results = self._vs.search_theories(theory.content, n_results=10, active_only=True)
        for result in results:
            if result["id"] == theory_id:
                continue
            if result.get("distance", 1.0) >= distance_threshold:
                continue
            candidate = self._db.get_theory(result["id"])
            if not candidate or not candidate.active:
                continue
            # Parent should be broader: more source episodes or higher confirmation
            if (len(candidate.source_episodes) > len(theory.source_episodes)
                    and candidate.confirmation_count >= theory.confirmation_count):
                return candidate
        return None

    # --- Promotion and merging ---

    def promote_to_parent(
        self,
        child_ids: list[str],
        parent_content: str,
        scope: str = "craft",
    ) -> Optional[Theory]:
        """Create a new abstract parent theory and assign children to it."""
        if not child_ids or not parent_content.strip():
            return None
        # Collect source episodes from all children
        all_sources: list[str] = []
        for cid in child_ids:
            child = self._db.get_theory(cid)
            if child:
                all_sources.extend(child.source_episodes)
        parent = Theory(
            id=_new_id(),
            content=parent_content,
            scope=scope,
            confidence=0.5,
            source_episodes=list(set(all_sources)),
            first_observed=_utcnow(),
            hierarchy_depth=0,
        )
        self._db.save_theory(parent)
        if self._vs:
            self._vs.add_theory(parent)
        # Dual-write: junction table
        for ep_id in parent.source_episodes:
            self._db.add_theory_episode(parent.id, ep_id)
        # Set children's parent
        for cid in child_ids:
            child = self._db.get_theory(cid)
            if child:
                child.parent_theory_id = parent.id
                child.hierarchy_depth = 1
                self._db.save_theory(child)
        return parent

    def merge_theories(self, theory_ids: list[str]) -> Optional[Theory]:
        """Merge multiple theories into one, keeping the highest-confidence survivor.

        Other theories are superseded.
        """
        if len(theory_ids) < 2:
            return None
        theories = [self._db.get_theory(tid) for tid in theory_ids]
        theories = [t for t in theories if t is not None]
        if len(theories) < 2:
            return None
        # Pick highest-confidence as survivor
        theories.sort(key=lambda t: t.confidence, reverse=True)
        survivor = theories[0]
        # Merge source episodes from all
        all_sources: set[str] = set(survivor.source_episodes)
        for t in theories[1:]:
            all_sources.update(t.source_episodes)
            t.active = False
            t.superseded_by = survivor.id
            self._db.save_theory(t)
            if self._vs:
                self._vs.remove_theory(t.id)
        survivor.source_episodes = list(all_sources)
        self._db.save_theory(survivor)
        if self._vs:
            self._vs.add_theory(survivor)
        # Dual-write: junction table
        for ep_id in survivor.source_episodes:
            self._db.add_theory_episode(survivor.id, ep_id)
        return survivor

    def detect_merge_candidates(
        self, distance_threshold: float = 0.15
    ) -> list[tuple[str, str]]:
        """Find pairs of theories that are near-duplicates."""
        if not self._vs:
            return []
        theories = self._db.list_theories(active_only=True, limit=200)
        candidates: list[tuple[str, str]] = []
        seen_pairs: set[frozenset[str]] = set()
        for theory in theories:
            if not theory.content.strip():
                continue
            results = self._vs.search_theories(theory.content, n_results=5, active_only=True)
            for result in results:
                if result["id"] == theory.id:
                    continue
                pair = frozenset({theory.id, result["id"]})
                if pair in seen_pairs:
                    continue
                if result.get("distance", 1.0) < distance_threshold:
                    candidates.append((theory.id, result["id"]))
                    seen_pairs.add(pair)
        return candidates

    # --- Graph-aware recall ---

    def graph_aware_recall(
        self,
        theory: Theory,
        max_ancestors: int = 2,
        max_children: int = 3,
    ) -> dict[str, Any]:
        """Get hierarchy context for a theory: ancestors, children, siblings."""
        ancestors = self.get_ancestors(theory.id, max_depth=max_ancestors)
        children = self.get_children(theory.id)[:max_children]
        # Siblings: other children of same parent
        siblings: list[Theory] = []
        if theory.parent_theory_id:
            all_siblings = self.get_children(theory.parent_theory_id)
            siblings = [s for s in all_siblings if s.id != theory.id][:3]
        return {
            "ancestors": [self._theory_summary(t) for t in ancestors],
            "children": [self._theory_summary(t) for t in children],
            "siblings": [self._theory_summary(t) for t in siblings],
        }

    @staticmethod
    def _theory_summary(theory: Theory) -> dict[str, Any]:
        return {
            "id": theory.id,
            "content": theory.content[:200],
            "scope": theory.scope,
            "confidence": theory.confidence,
        }
