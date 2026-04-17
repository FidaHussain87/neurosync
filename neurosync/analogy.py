"""Analogical reasoning: structural fingerprinting, combined search, multi-hop."""

from __future__ import annotations

import re
from typing import Any, Optional

from neurosync.db import Database
from neurosync.vectorstore import VectorStore

# Structural pattern library — compiled regex for each structural category
STRUCTURAL_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "race_condition": [
        re.compile(r"race\s+condition", re.IGNORECASE),
        re.compile(r"concurrent", re.IGNORECASE),
        re.compile(r"TOCTOU", re.IGNORECASE),
        re.compile(r"deadlock", re.IGNORECASE),
        re.compile(r"mutex|semaphore", re.IGNORECASE),
    ],
    "caching": [
        re.compile(r"cache\s+invalidat", re.IGNORECASE),
        re.compile(r"stale\s+cache", re.IGNORECASE),
        re.compile(r"TTL", re.IGNORECASE),
        re.compile(r"memoiz", re.IGNORECASE),
        re.compile(r"cache\s+miss", re.IGNORECASE),
    ],
    "retry_logic": [
        re.compile(r"retry", re.IGNORECASE),
        re.compile(r"backoff", re.IGNORECASE),
        re.compile(r"idempoten", re.IGNORECASE),
        re.compile(r"circuit\s+breaker", re.IGNORECASE),
    ],
    "configuration": [
        re.compile(r"config", re.IGNORECASE),
        re.compile(r"env\s+var", re.IGNORECASE),
        re.compile(r"feature\s+flag", re.IGNORECASE),
        re.compile(r"settings?\s+file", re.IGNORECASE),
    ],
    "api_contract": [
        re.compile(r"API\s+version", re.IGNORECASE),
        re.compile(r"breaking\s+change", re.IGNORECASE),
        re.compile(r"backward.?compat", re.IGNORECASE),
        re.compile(r"deprecat", re.IGNORECASE),
    ],
    "auth_permission": [
        re.compile(r"auth", re.IGNORECASE),
        re.compile(r"permission", re.IGNORECASE),
        re.compile(r"RBAC", re.IGNORECASE),
        re.compile(r"token\s+expir", re.IGNORECASE),
        re.compile(r"credential", re.IGNORECASE),
    ],
    "data_consistency": [
        re.compile(r"eventual\s+consist", re.IGNORECASE),
        re.compile(r"stale\s+data", re.IGNORECASE),
        re.compile(r"replicat", re.IGNORECASE),
        re.compile(r"sync\s+conflict", re.IGNORECASE),
    ],
    "resource_lifecycle": [
        re.compile(r"cleanup", re.IGNORECASE),
        re.compile(r"(?:resource\s+)?leak", re.IGNORECASE),
        re.compile(r"orphan", re.IGNORECASE),
        re.compile(r"finaliz", re.IGNORECASE),
    ],
    "error_handling": [
        re.compile(r"error\s+handl", re.IGNORECASE),
        re.compile(r"exception", re.IGNORECASE),
        re.compile(r"fallback", re.IGNORECASE),
        re.compile(r"graceful\s+degrad", re.IGNORECASE),
    ],
    "naming_convention": [
        re.compile(r"naming\s+conv", re.IGNORECASE),
        re.compile(r"snake_?case", re.IGNORECASE),
        re.compile(r"hungarian", re.IGNORECASE),
        re.compile(r"camel_?case", re.IGNORECASE),
    ],
}


class StructuralFingerprint:
    """A set of structural pattern labels detected in text content."""

    def __init__(self, patterns: Optional[list[str]] = None) -> None:
        self.patterns: frozenset[str] = frozenset(patterns or [])

    def similarity(self, other: StructuralFingerprint) -> float:
        """Jaccard similarity: |A∩B| / |A∪B|."""
        if not self.patterns and not other.patterns:
            return 0.0
        intersection = self.patterns & other.patterns
        union = self.patterns | other.patterns
        if not union:
            return 0.0
        return len(intersection) / len(union)

    def to_string(self) -> str:
        return ",".join(sorted(self.patterns))

    @classmethod
    def from_string(cls, s: str) -> StructuralFingerprint:
        if not s or not s.strip():
            return cls([])
        return cls(s.split(","))

    def __repr__(self) -> str:
        return f"StructuralFingerprint({sorted(self.patterns)})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StructuralFingerprint):
            return NotImplemented
        return self.patterns == other.patterns


class AnalogyEngine:
    """Find structural analogies across episodes and theories."""

    def __init__(self, db: Database, vectorstore: Optional[VectorStore] = None) -> None:
        self._db = db
        self._vs = vectorstore

    def fingerprint(self, content: str) -> StructuralFingerprint:
        """Compute structural fingerprint from content text."""
        matched: list[str] = []
        for category, regexes in STRUCTURAL_PATTERNS.items():
            for rx in regexes:
                if rx.search(content):
                    matched.append(category)
                    break
        return StructuralFingerprint(matched)

    def find_analogies(
        self,
        query: str,
        n_results: int = 5,
        structural_weight: float = 0.4,
        semantic_weight: float = 0.6,
    ) -> list[dict[str, Any]]:
        """Combined structural + semantic search.

        score = semantic_weight * (1 - cosine_dist) + structural_weight * jaccard
        """
        query_fp = self.fingerprint(query)

        if not self._vs:
            return []

        # Semantic search for candidates
        theory_results = self._vs.search_theories(query, n_results=n_results * 2)
        episode_results = self._vs.search_episodes(query, n_results=n_results * 2)

        scored: list[tuple[float, dict[str, Any]]] = []
        for result in theory_results + episode_results:
            cosine_dist = result.get("distance", 1.0)
            semantic_score = 1.0 - min(cosine_dist, 1.0)

            # Get structural fingerprint from metadata or content
            fp_str = result.get("metadata", {}).get("structural_fingerprint", "")
            if fp_str:
                result_fp = StructuralFingerprint.from_string(fp_str)
            else:
                result_fp = self.fingerprint(result.get("document", ""))

            structural_score = query_fp.similarity(result_fp)
            combined = semantic_weight * semantic_score + structural_weight * structural_score

            scored.append((combined, {
                "id": result["id"],
                "content": result.get("document", ""),
                "distance": cosine_dist,
                "structural_similarity": structural_score,
                "combined_score": round(combined, 4),
                "fingerprint": result_fp.to_string(),
                "metadata": result.get("metadata", {}),
            }))

        # Sort by combined score descending, deduplicate by id
        scored.sort(key=lambda x: x[0], reverse=True)
        seen: set[str] = set()
        results: list[dict[str, Any]] = []
        for _, item in scored:
            if item["id"] not in seen:
                seen.add(item["id"])
                results.append(item)
                if len(results) >= n_results:
                    break
        return results

    def multi_hop_search(
        self,
        query: str,
        max_hops: int = 2,
        n_per_hop: int = 5,
    ) -> list[dict[str, Any]]:
        """Multi-hop analogical search: search -> use top result as new query -> repeat.

        Returns deduplicated results across all hops.
        """
        all_results: list[dict[str, Any]] = []
        seen: set[str] = set()
        current_query = query

        for _hop in range(max_hops):
            hop_results = self.find_analogies(current_query, n_results=n_per_hop)
            for result in hop_results:
                if result["id"] not in seen:
                    seen.add(result["id"])
                    all_results.append(result)

            # Use top result's content as next query
            if hop_results:
                current_query = hop_results[0].get("content", query)
            else:
                break

        return all_results

    def cross_project_analogies(
        self,
        query: str,
        current_project: str,
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Find analogies from OTHER projects (not the current one)."""
        results = self.find_analogies(query, n_results=n_results * 2)
        filtered: list[dict[str, Any]] = []
        for result in results:
            project = result.get("metadata", {}).get("project", "")
            scope_qualifier = result.get("metadata", {}).get("scope_qualifier", "")
            # Include if from a different project or no project (craft-level)
            if project != current_project and scope_qualifier != current_project:
                filtered.append(result)
                if len(filtered) >= n_results:
                    break
        return filtered
