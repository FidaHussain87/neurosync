"""Offline consolidation engine: cluster -> extract -> MDL prune -> merge/create theories."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
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
            db,
            vs,
            episodic,
            semantic,
            min_episodes=min_episodes,
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
        mdl_threshold: float = 0.7,
    ) -> None:
        self._db = db
        self._vs = vectorstore
        self._episodic = episodic
        self._semantic = semantic
        self._analogy = AnalogyEngine(db)
        self._min_episodes = min_episodes
        self._similarity_threshold = similarity_threshold
        self._mdl_threshold = mdl_threshold

    def run(self, project: Optional[str] = None, dry_run: bool = False) -> dict[str, Any]:
        """Run full consolidation pipeline."""
        # 1. Gather unconsolidated episodes
        episodes = self._episodic.get_unconsolidated_episodes(limit=500)
        if project:
            episodes = [ep for ep in episodes if self._episode_project(ep) == project]
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
                candidates.append(
                    {
                        "content": candidate,
                        "episode_count": len(cluster),
                        "scope": self._classify_scope(cluster),
                    }
                )
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

        # 8. Confidence decay is handled by ForgettingEngine.run_forgetting_pass()
        # which is called after consolidation in mcp_server._try_auto_consolidate().
        # This avoids competing linear vs Ebbinghaus decay systems.
        decayed = 0

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

        Uses multi-strategy extraction (all local, no LLM):
        1. Causal episodes → merge causes/effects into generalized causal theory
        2. Multi-episode → extract shared keywords via TF-IDF and compose summary
        3. Fallback → highest-weight episode with type annotation
        """
        if not cluster:
            return None

        # Strategy 1: Causal episodes — merge multiple causes/effects
        causal_eps = [ep for ep in cluster if ep.cause and ep.effect]
        if causal_eps:
            return self._extract_causal_theory(causal_eps)

        # Strategy 2: Multi-episode keyword extraction and summary
        if len(cluster) >= 3:
            keyword_theory = self._extract_keyword_theory(cluster)
            if keyword_theory:
                return keyword_theory

        # Strategy 3: Fallback — highest-weight, most concise episode
        sorted_eps = sorted(
            cluster,
            key=lambda ep: (-ep.signal_weight, len(ep.content)),
        )
        best = sorted_eps[0]
        content = best.content.strip()
        if not content:
            return None

        # Annotate with shared event type if uniform
        types = {ep.event_type for ep in cluster}
        if len(types) == 1:
            common_type = types.pop()
            if common_type != "decision":
                content = f"[{common_type}] {content}"

        return content

    def _extract_causal_theory(self, causal_eps: list[Episode]) -> str:
        """Merge multiple causal episodes into a generalized theory.

        If multiple episodes share similar causes, combine their effects.
        Otherwise, use the highest-weight causal episode.
        """
        sorted_causal = sorted(
            causal_eps,
            key=lambda ep: (-ep.signal_weight, len(ep.content)),
        )
        best = sorted_causal[0]
        reasoning = best.reasoning or ""

        if len(causal_eps) >= 2:
            # Collect all unique effects
            effects = []
            seen_effects: set[str] = set()
            for ep in sorted_causal:
                effect_lower = ep.effect.strip().lower()
                if effect_lower not in seen_effects:
                    seen_effects.add(effect_lower)
                    effects.append(ep.effect.strip())

            if len(effects) > 1:
                # Multiple effects from similar cause — merge
                effects_text = "; ".join(effects[:3])
                if reasoning:
                    return f"When {best.cause}, then {effects_text} because {reasoning}"
                return f"When {best.cause}, then {effects_text}"

        # Single causal pattern
        if reasoning:
            return f"When {best.cause}, then {best.effect} because {reasoning}"
        return f"When {best.cause}, then {best.effect}"

    def _extract_keyword_theory(self, cluster: list[Episode]) -> Optional[str]:
        """Extract shared themes from cluster using TF-IDF-like keyword scoring.

        Pure local computation — no LLM calls.
        """
        # Tokenize each episode's content
        stop_words = frozenset(
            {
                "the",
                "a",
                "an",
                "is",
                "are",
                "was",
                "were",
                "be",
                "been",
                "being",
                "have",
                "has",
                "had",
                "do",
                "does",
                "did",
                "will",
                "would",
                "could",
                "should",
                "may",
                "might",
                "shall",
                "can",
                "need",
                "to",
                "of",
                "in",
                "for",
                "on",
                "with",
                "at",
                "by",
                "from",
                "as",
                "into",
                "through",
                "during",
                "before",
                "after",
                "above",
                "below",
                "between",
                "and",
                "or",
                "but",
                "if",
                "then",
                "else",
                "when",
                "while",
                "so",
                "that",
                "this",
                "these",
                "those",
                "it",
                "its",
                "not",
                "no",
                "nor",
                "only",
                "own",
                "same",
                "than",
                "too",
                "very",
                "just",
                "because",
                "about",
                "up",
            }
        )

        def tokenize(text: str) -> list[str]:
            words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())
            return [w for w in words if len(w) > 2 and w not in stop_words]

        # Document frequency: how many episodes contain each word
        doc_freq: Counter = Counter()
        doc_tokens: list[list[str]] = []
        for ep in cluster:
            tokens = tokenize(ep.content)
            doc_tokens.append(tokens)
            unique_tokens = set(tokens)
            for t in unique_tokens:
                doc_freq[t] += 1

        n_docs = len(cluster)
        if n_docs < 2:
            return None

        # TF-IDF score: words that appear in multiple (but not all) documents are most informative
        # Also weight by signal_weight of containing episodes
        keyword_scores: Counter = Counter()
        for i, tokens in enumerate(doc_tokens):
            tf: Counter = Counter(tokens)
            ep_weight = cluster[i].signal_weight
            for word, count in tf.items():
                df = doc_freq[word]
                if df < 2:
                    continue  # Must appear in at least 2 episodes
                # IDF that peaks for words in ~half the documents
                idf = math.log(n_docs / df) + 0.5
                keyword_scores[word] += count * idf * min(ep_weight, 5.0)

        top_keywords = [w for w, _ in keyword_scores.most_common(8)]
        if len(top_keywords) < 2:
            return None

        # Find the most representative episode (highest overlap with top keywords)
        best_ep = max(
            cluster,
            key=lambda ep: (
                sum(1 for kw in top_keywords if kw in ep.content.lower()),
                ep.signal_weight,
            ),
        )

        # Compose theory: keywords as topic + representative content
        theme = ", ".join(top_keywords[:5])
        # Use shared event type if uniform
        types = {ep.event_type for ep in cluster}
        type_prefix = ""
        if len(types) == 1:
            t = types.pop()
            if t != "decision":
                type_prefix = f"[{t}] "

        # Truncate representative content to be concise
        rep_content = best_ep.content.strip()
        if len(rep_content) > 200:
            # Find sentence boundary near 200 chars
            boundary = rep_content.rfind(". ", 100, 250)
            rep_content = rep_content[: boundary + 1] if boundary > 0 else rep_content[:200] + "..."

        return f"{type_prefix}{rep_content} (themes: {theme})"

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
        related = self._semantic.find_related_theories(theory_id, distance_threshold=0.4)
        if related:
            self._semantic.link_theories(theory_id, [t.id for t in related])

    def _check_parent_theory(self, theory_id: str, cluster: list[Episode]) -> None:
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
