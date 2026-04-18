"""Offline consolidation engine: cluster -> extract -> MDL prune -> merge/create theories."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from neurosync.analogy import AnalogyEngine
from neurosync.db import Database
from neurosync.episodic import EpisodicMemory
from neurosync.logging import get_logger
from neurosync.models import Episode, Theory
from neurosync.semantic import SemanticMemory
from neurosync.vectorstore import VectorStore

logger = get_logger("consolidation")


def maybe_consolidate(
    db: Database,
    vs: Optional[VectorStore],
    episodic: EpisodicMemory,
    semantic: SemanticMemory,
    threshold: int = 20,
    min_episodes: int = 5,
) -> Optional[dict[str, Any]]:
    """Auto-consolidate if unconsolidated episode count exceeds threshold.

    Returns consolidation result dict, or None if below threshold or on error.
    This function must never raise — it is called as a side effect of write operations.
    """
    try:
        pending = db.count_episodes(consolidated=0)
        if pending < threshold or pending < min_episodes:
            return None
        engine = ConsolidationEngine(
            db, vs, episodic, semantic, min_episodes=min_episodes,
        )
        return engine.run()
    except Exception:
        logger.warning("Auto-consolidation failed", exc_info=True)
        return None


class ConsolidationEngine:
    """Clusters unconsolidated episodes and extracts theories."""

    def __init__(
        self,
        db: Database,
        vectorstore: Optional[VectorStore],
        episodic: EpisodicMemory,
        semantic: SemanticMemory,
        min_episodes: int = 5,
        similarity_threshold: float = 0.8,
        mdl_threshold: float = 5.0,
    ) -> None:
        self._db = db
        self._vs = vectorstore
        self._episodic = episodic
        self._semantic = semantic
        self._analogy = AnalogyEngine(db)
        self._min_episodes = min_episodes
        self._similarity_threshold = similarity_threshold
        self._mdl_threshold = mdl_threshold

    def run(
        self, project: Optional[str] = None, dry_run: bool = False
    ) -> dict[str, Any]:
        """Run full consolidation pipeline."""
        # 1. Gather unconsolidated episodes
        episodes = self._episodic.get_unconsolidated_episodes(limit=500)
        if project:
            episodes = [
                ep for ep in episodes
                if self._episode_project(ep) == project
            ]
        if len(episodes) < self._min_episodes:
            return {
                "message": f"Not enough episodes ({len(episodes)}/{self._min_episodes})",
                "pending_episodes": len(episodes),
                "theories_created": 0,
                "theories_confirmed": 0,
            }

        # 2. Cluster by semantic similarity
        clusters = self._cluster_episodes(episodes)

        # 3-6. Process each cluster
        theories_created = 0
        theories_confirmed = 0
        consolidated_ids: list[str] = []
        candidates: list[dict[str, Any]] = []

        for cluster in clusters:
            if len(cluster) < 2:
                continue

            # Extract candidate theory
            candidate = self._extract_candidate(cluster)
            if not candidate:
                continue

            # MDL prune
            if not self._passes_mdl(candidate, cluster):
                continue

            if dry_run:
                candidates.append({
                    "content": candidate,
                    "episode_count": len(cluster),
                    "scope": self._classify_scope(cluster),
                })
                continue

            # Check for existing matching theory
            existing = self._find_matching_theory(candidate)
            if existing:
                # Confirm existing theory
                for ep in cluster:
                    self._semantic.confirm_theory(existing.id, episode_id=ep.id)
                theories_confirmed += 1
            else:
                # Create new theory
                scope, qualifier = self._classify_scope(cluster), self._scope_qualifier(cluster)
                new_theory = self._semantic.create_theory(
                    content=candidate,
                    scope=scope,
                    scope_qualifier=qualifier,
                    confidence=0.5,
                    source_episodes=[ep.id for ep in cluster],
                )
                theories_created += 1
                # Auto-compute structural fingerprint
                fp = self._analogy.fingerprint(candidate)
                if fp.patterns:
                    new_theory.structural_fingerprint = fp.to_string()
                    self._db.save_theory(new_theory)
                    self._db.set_entity_fingerprints(new_theory.id, "theory", list(fp.patterns))
                # Auto-link to related theories
                self._link_new_theory(new_theory.id)
                # Check for parent relationship
                self._check_parent_theory(new_theory.id, cluster)

            consolidated_ids.extend(ep.id for ep in cluster)

        # 7. Mark episodes consolidated
        if not dry_run and consolidated_ids:
            unique_ids = list(set(consolidated_ids))
            self._episodic.mark_consolidated(unique_ids)

        # 8. Apply confidence decay
        decayed = 0
        if not dry_run:
            decayed = self._semantic.apply_confidence_decay()

        result: dict[str, Any] = {
            "episodes_processed": len(episodes),
            "clusters_found": len(clusters),
            "theories_created": theories_created,
            "theories_confirmed": theories_confirmed,
            "episodes_consolidated": len(set(consolidated_ids)),
            "theories_decayed": decayed,
        }
        if dry_run:
            result["dry_run"] = True
            result["candidates"] = candidates
        return result

    def _cluster_episodes(self, episodes: list[Episode]) -> list[list[Episode]]:
        """Cluster episodes by semantic similarity using single-linkage grouping."""
        if not episodes:
            return []
        if not self._vs:
            # Without vector search, put all episodes in one cluster
            return [episodes]

        # Get embeddings from ChromaDB via search
        # Build adjacency: for each episode, find its neighbors
        episode_map = {ep.id: ep for ep in episodes}
        adjacency: dict[str, set[str]] = defaultdict(set)

        for ep in episodes:
            if not ep.content.strip():
                continue
            neighbors = self._vs.search_episodes(
                ep.content,
                n_results=min(len(episodes), 20),
            )
            for neighbor in neighbors:
                nid = neighbor["id"]
                dist = neighbor.get("distance", 1.0)
                if nid != ep.id and nid in episode_map and dist < self._similarity_threshold:
                    adjacency[ep.id].add(nid)
                    adjacency[nid].add(ep.id)

        # Single-linkage clustering via union-find
        parent: dict[str, str] = {ep.id: ep.id for ep in episodes}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for eid, neighbors in adjacency.items():
            for nid in neighbors:
                union(eid, nid)

        # Group by root
        groups: dict[str, list[Episode]] = defaultdict(list)
        for ep in episodes:
            root = find(ep.id)
            groups[root].append(ep)

        return list(groups.values())

    def _extract_candidate(self, cluster: list[Episode]) -> Optional[str]:
        """Extract a candidate theory from a cluster of episodes.

        Strategy: if causal episodes exist, compose a causal theory.
        Otherwise, pick the most concise episode content as the theory basis.
        """
        if not cluster:
            return None

        # Separate causal vs non-causal episodes
        causal_eps = [ep for ep in cluster if ep.cause and ep.effect]

        if causal_eps:
            # Compose causal theory from highest-weight causal episode
            sorted_causal = sorted(
                causal_eps,
                key=lambda ep: (-ep.signal_weight, len(ep.content)),
            )
            best = sorted_causal[0]
            reasoning = best.reasoning or ""
            if reasoning:
                content = f"When {best.cause}, then {best.effect} because {reasoning}"
            else:
                content = f"When {best.cause}, then {best.effect}"
            return content

        # Fallback: use highest-weighted, most concise episode
        sorted_eps = sorted(
            cluster,
            key=lambda ep: (-ep.signal_weight, len(ep.content)),
        )
        best = sorted_eps[0]
        content = best.content.strip()
        if not content:
            return None

        # If all episodes share a common event type, note it
        types = {ep.event_type for ep in cluster}
        if len(types) == 1:
            common_type = types.pop()
            if common_type != "decision":
                content = f"[{common_type}] {content}"

        return content

    def _passes_mdl(self, candidate: str, cluster: list[Episode]) -> bool:
        """MDL pruning: reject if description_length / coverage is too high."""
        desc_len = len(candidate)
        total_content_len = sum(len(ep.content) for ep in cluster)
        if total_content_len == 0:
            return False
        ratio = desc_len / max(total_content_len, 1)
        return ratio < self._mdl_threshold

    def _find_matching_theory(self, candidate: str) -> Optional[Theory]:
        """Check if candidate matches an existing active theory (cosine < 0.5)."""
        if not self._vs:
            return None
        results = self._vs.search_theories(candidate, n_results=3, active_only=True)
        for result in results:
            if result.get("distance", 1.0) < 0.5:
                theory = self._db.get_theory(result["id"])
                if theory and theory.active:
                    return theory
        return None

    def _classify_scope(self, cluster: list[Episode]) -> str:
        """Determine scope: project (single project), domain (shared domain), craft (general)."""
        projects: set[str] = set()
        for ep in cluster:
            session = self._db.get_session(ep.session_id)
            if session and session.project:
                projects.add(session.project)
        if len(projects) == 1:
            return "project"
        if len(projects) > 1:
            return "domain"
        return "craft"

    def _scope_qualifier(self, cluster: list[Episode]) -> str:
        """Get the scope qualifier (e.g., project name)."""
        projects: set[str] = set()
        for ep in cluster:
            session = self._db.get_session(ep.session_id)
            if session and session.project:
                projects.add(session.project)
        if len(projects) == 1:
            return projects.pop()
        return ""

    def _link_new_theory(self, theory_id: str) -> None:
        """After creating a theory, find and link related theories."""
        related = self._semantic.find_related_theories(
            theory_id, distance_threshold=0.4
        )
        if related:
            self._semantic.link_theories(
                theory_id, [t.id for t in related]
            )

    def _check_parent_theory(
        self, theory_id: str, cluster: list[Episode]
    ) -> None:
        """If new theory's source episodes are a superset of another theory's, set parent."""
        theory = self._db.get_theory(theory_id)
        if not theory:
            return
        cluster_episode_ids = {ep.id for ep in cluster}
        # Check existing theories for subset relationships
        existing_theories = self._db.list_theories(active_only=True, limit=100)
        for existing in existing_theories:
            if existing.id == theory_id:
                continue
            if not existing.source_episodes:
                continue
            existing_set = set(existing.source_episodes)
            if existing_set and existing_set.issubset(cluster_episode_ids):
                self._semantic.set_parent_theory(existing.id, theory_id)

    def _episode_project(self, episode: Episode) -> str:
        session = self._db.get_session(episode.session_id)
        return session.project if session else ""
