"""Causal graph: construction from episodes/theories, forward/backward queries."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any, Optional

from neurosync.db import Database
from neurosync.models import CausalLink, _utcnow
from neurosync.vectorstore import VectorStore

# Keywords for classifying causal mechanism
_MECHANISM_KEYWORDS: dict[str, list[re.Pattern[str]]] = {
    "preventing": [re.compile(r"prevent", re.IGNORECASE), re.compile(r"block", re.IGNORECASE)],
    "enabling": [re.compile(r"enabl", re.IGNORECASE), re.compile(r"allow", re.IGNORECASE)],
    "triggering": [re.compile(r"trigger", re.IGNORECASE), re.compile(r"caus(?:e[sd]?|ing)", re.IGNORECASE)],
    "modulating": [re.compile(r"modulat", re.IGNORECASE), re.compile(r"amplif", re.IGNORECASE)],
    "correlating": [re.compile(r"correlat", re.IGNORECASE), re.compile(r"associat", re.IGNORECASE)],
}


class CausalGraph:
    """Builds and queries a causal graph from episodes and theories."""

    def __init__(self, db: Database, vectorstore: Optional[VectorStore] = None) -> None:
        self._db = db
        self._vs = vectorstore

    # --- Construction ---

    def _classify_mechanism(self, text: str) -> str:
        """Classify mechanism type from text content."""
        for mechanism, patterns in _MECHANISM_KEYWORDS.items():
            for rx in patterns:
                if rx.search(text):
                    return mechanism
        return "direct"

    def extract_link_from_episode(self, episode_id: str) -> Optional[CausalLink]:
        """Extract a causal link from an episode with cause/effect fields."""
        episode = self._db.get_episode(episode_id)
        if not episode or not episode.cause or not episode.effect:
            return None
        reasoning = episode.reasoning or ""
        mechanism = self._classify_mechanism(reasoning + " " + episode.content)
        session = self._db.get_session(episode.session_id)
        project = session.project if session else ""
        link = CausalLink(
            cause_text=episode.cause,
            effect_text=episode.effect,
            mechanism=mechanism,
            mechanism_detail=reasoning,
            source_episode_ids=[episode_id],
            project=project,
        )
        return self.save_link(link)

    def extract_links_from_theory(self, theory_id: str) -> list[CausalLink]:
        """Extract causal links from a causal theory (When X, then Y because Z)."""
        theory = self._db.get_theory(theory_id)
        if not theory:
            return []
        # Parse "When X, then Y because Z" patterns
        match = re.match(
            r"When\s+(.+?),\s+then\s+(.+?)(?:\s+because\s+(.+))?$",
            theory.content,
            re.IGNORECASE | re.DOTALL,
        )
        if not match:
            return []
        cause = match.group(1).strip()
        effect = match.group(2).strip()
        reasoning = (match.group(3) or "").strip()
        mechanism = self._classify_mechanism(reasoning + " " + theory.content)
        link = CausalLink(
            cause_text=cause,
            effect_text=effect,
            mechanism=mechanism,
            mechanism_detail=reasoning,
            source_theory_id=theory_id,
            project=theory.scope_qualifier,
        )
        return [self.save_link(link)]

    def save_link(self, link: CausalLink) -> CausalLink:
        """Save a causal link, deduplicating by cause+effect text match."""
        # Check for existing link with same cause and effect
        existing = self._db.list_causal_links(
            cause_text=link.cause_text, effect_text=link.effect_text,
        )
        if existing:
            dup = existing[0]
            self._db.increment_causal_observation(dup.id)
            # Merge source episodes
            loaded = self._db.get_causal_link(dup.id)
            if loaded:
                new_eps = set(loaded.source_episode_ids) | set(link.source_episode_ids)
                loaded.source_episode_ids = list(new_eps)
                loaded.updated_at = _utcnow()
                self._db.save_causal_link(loaded)
                return loaded
        return self._db.save_causal_link(link)

    def strengthen_link(self, link_id: int, episode_id: str) -> None:
        """Increment observation count and add source episode."""
        self._db.increment_causal_observation(link_id)
        link = self._db.get_causal_link(link_id)
        if link and episode_id not in link.source_episode_ids:
            link.source_episode_ids.append(episode_id)
            link.updated_at = _utcnow()
            self._db.save_causal_link(link)

    # --- Forward/backward queries ---

    def get_effects_of(self, cause_text: str, max_depth: int = 1) -> list[CausalLink]:
        """Get direct (and optionally transitive) effects of a cause."""
        results: list[CausalLink] = []
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(cause_text, 0)])

        while queue:
            current_cause, depth = queue.popleft()
            if depth >= max_depth:
                continue
            if current_cause in visited:
                continue
            visited.add(current_cause)
            links = self._db.list_causal_links(cause_text=current_cause)
            for link in links:
                results.append(link)
                queue.append((link.effect_text, depth + 1))
        return results

    def get_causes_of(self, effect_text: str, max_depth: int = 1) -> list[CausalLink]:
        """Get direct (and optionally transitive) causes of an effect."""
        results: list[CausalLink] = []
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(effect_text, 0)])

        while queue:
            current_effect, depth = queue.popleft()
            if depth >= max_depth:
                continue
            if current_effect in visited:
                continue
            visited.add(current_effect)
            links = self._db.list_causal_links(effect_text=current_effect)
            for link in links:
                results.append(link)
                queue.append((link.cause_text, depth + 1))
        return results

    def get_causal_chain(
        self, start: str, end: str, max_depth: int = 5
    ) -> Optional[list[CausalLink]]:
        """Find a causal chain from start to end using BFS."""
        queue: deque[tuple[str, list[CausalLink]]] = deque([(start, [])])
        visited: set[str] = set()

        while queue:
            current, path = queue.popleft()
            if len(path) >= max_depth:
                continue
            if current in visited:
                continue
            visited.add(current)
            links = self._db.list_causal_links(cause_text=current)
            for link in links:
                new_path = path + [link]
                if link.effect_text == end:
                    return new_path
                queue.append((link.effect_text, new_path))
        return None

    def get_causal_neighborhood(self, text: str, radius: int = 2) -> dict[str, Any]:
        """Get upstream causes + downstream effects + links around a concept."""
        upstream = self.get_causes_of(text, max_depth=radius)
        downstream = self.get_effects_of(text, max_depth=radius)
        return {
            "concept": text,
            "upstream": [self._link_summary(link) for link in upstream],
            "downstream": [self._link_summary(link) for link in downstream],
        }

    # --- Analysis ---

    def detect_chains(self, min_length: int = 3) -> list[list[CausalLink]]:
        """Find long causal chains in the graph."""
        all_links = self._db.list_causal_links(limit=500)
        # Build adjacency list
        adj: dict[str, list[CausalLink]] = defaultdict(list)
        for link in all_links:
            adj[link.cause_text].append(link)

        chains: list[list[CausalLink]] = []
        for start in adj:
            # DFS to find chains
            stack: list[tuple[str, list[CausalLink]]] = [(start, [])]
            visited: set[str] = set()
            while stack:
                node, path = stack.pop()
                if node in visited:
                    if len(path) >= min_length:
                        chains.append(path)
                    continue
                visited.add(node)
                if node in adj:
                    for link in adj[node]:
                        new_path = path + [link]
                        stack.append((link.effect_text, new_path))
                elif len(path) >= min_length:
                    chains.append(path)
        return chains

    def find_common_causes(self, effects: list[str]) -> list[CausalLink]:
        """Find causes shared by multiple effects (root cause analysis)."""
        if not effects:
            return []
        cause_counts: dict[str, int] = defaultdict(int)
        cause_links: dict[str, CausalLink] = {}
        for effect in effects:
            links = self._db.list_causal_links(effect_text=effect)
            seen_causes: set[str] = set()
            for link in links:
                if link.cause_text not in seen_causes:
                    seen_causes.add(link.cause_text)
                    cause_counts[link.cause_text] += 1
                    cause_links[link.cause_text] = link
        # Return causes shared by 2+ effects
        return [
            cause_links[cause]
            for cause, count in cause_counts.items()
            if count >= 2
        ]

    # --- Batch construction ---

    def build_from_episodes(self, limit: int = 500) -> dict[str, Any]:
        """Build causal links from episodes with cause/effect fields."""
        episodes = self._db.list_episodes(limit=limit)
        created = 0
        for ep in episodes:
            if ep.cause and ep.effect:
                self.extract_link_from_episode(ep.id)
                created += 1
        return {"links_created": created}

    def build_from_theories(self, limit: int = 100) -> dict[str, Any]:
        """Build causal links from causal theories."""
        theories = self._db.list_theories(active_only=True, limit=limit)
        created = 0
        for theory in theories:
            if theory.content.lower().startswith("when "):
                links = self.extract_links_from_theory(theory.id)
                created += len(links)
        return {"links_created": created}

    @staticmethod
    def _link_summary(link: CausalLink) -> dict[str, Any]:
        return {
            "id": link.id,
            "cause": link.cause_text,
            "effect": link.effect_text,
            "mechanism": link.mechanism,
            "strength": link.strength,
            "observations": link.observation_count,
        }
