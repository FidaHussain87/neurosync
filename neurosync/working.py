"""Layer 3: Working memory — context-aware recall with winner-take-all activation."""

from __future__ import annotations

from typing import Any, Optional

from neurosync.db import Database
from neurosync.models import Theory
from neurosync.vectorstore import VectorStore


def build_recall_query(project: str, branch: str, context: str) -> str:
    """Build a query string from project, branch, and context."""
    parts = []
    if project:
        parts.append(f"project:{project}")
    if branch:
        parts.append(f"branch:{branch}")
    if context:
        parts.append(context)
    return " ".join(parts)


def format_theory_result(theory: Theory, score: float) -> dict[str, Any]:
    """Format a theory object into a recall result dict."""
    return {
        "id": theory.id,
        "content": theory.content,
        "scope": theory.scope,
        "scope_qualifier": theory.scope_qualifier,
        "confidence": theory.confidence,
        "score": round(score, 4),
        "validation_status": theory.validation_status,
        "application_count": theory.application_count,
    }


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return max(1, len(text) // 4)


class WorkingMemory:
    """Assembles context-relevant recall from theories and episodes (Layer 3)."""

    def __init__(self, db: Database, vectorstore: Optional[VectorStore] = None) -> None:
        self._db = db
        self._vs = vectorstore

    def recall(
        self,
        project: str = "",
        branch: str = "",
        context: str = "",
        max_tokens: int = 500,
        user_familiar_topics: Optional[set[str]] = None,
    ) -> dict[str, Any]:
        """Build a recall context for the current session.

        Returns a structured dict with primary theory, supporting theories,
        and recent episode context, all within the token budget.
        """
        query = build_recall_query(project, branch, context)
        if not query.strip():
            return {"primary": None, "supporting": [], "recent_episodes": [], "tokens_used": 0}

        if not self._vs:
            return {"primary": None, "supporting": [], "recent_episodes": [], "tokens_used": 0}

        # Retrieve candidate theories
        theory_results = self._vs.search_theories(query, n_results=10, active_only=True)

        # Winner-take-all: score = confidence / (1 + distance)
        scored = []
        for result in theory_results:
            theory = self._db.get_theory(result["id"])
            if not theory or not theory.active:
                continue
            # Filter by user familiarity — suppress if user already knows this well
            if user_familiar_topics and self._is_familiar(theory, user_familiar_topics):
                continue
            distance = result.get("distance", 0.0)
            score = theory.confidence / (1.0 + distance)
            scored.append((score, theory, result))

        scored.sort(key=lambda x: x[0], reverse=True)

        primary: Optional[dict[str, Any]] = None
        supporting: list[dict[str, Any]] = []
        tokens_used = 0

        if scored:
            # Winner: highest-scoring theory
            top_score, top_theory, top_result = scored[0]
            primary = format_theory_result(top_theory, top_score)
            tokens_used += estimate_tokens(top_theory.content)

            # Supporting: next 2-3 theories within token budget
            for score, theory, _result in scored[1:4]:
                cost = estimate_tokens(theory.content)
                if tokens_used + cost > max_tokens:
                    break
                supporting.append(format_theory_result(theory, score))
                tokens_used += cost

        # Fetch parent theory context for primary
        parent_theory: Optional[dict[str, Any]] = None
        if primary and scored:
            top_theory = scored[0][1]
            if top_theory.parent_theory_id:
                parent = self._db.get_theory(top_theory.parent_theory_id)
                if parent and parent.active:
                    parent_theory = format_theory_result(parent, 0.0)
                    tokens_used += estimate_tokens(parent.content)

        # Search for continuation episodes from same project
        continuation: Optional[dict[str, Any]] = None
        if project:
            cont_results = self._vs.search_episodes(
                "CONTINUATION", n_results=3, where={"project": project}
            )
            for cr in cont_results:
                meta = cr.get("metadata", {})
                if meta.get("event_type") == "continuation":
                    continuation = {
                        "id": cr["id"],
                        "content": cr.get("document", ""),
                    }
                    tokens_used += estimate_tokens(cr.get("document", ""))
                    break

        # Recent episodes from same project/branch
        recent_episodes: list[dict[str, Any]] = []
        if project:
            episode_results = self._vs.search_episodes(
                query, n_results=5, where={"project": project}
            )
            for ep in episode_results:
                cost = estimate_tokens(ep.get("document", ""))
                if tokens_used + cost > max_tokens:
                    break
                recent_episodes.append(
                    {
                        "id": ep["id"],
                        "content": ep.get("document", ""),
                        "event_type": ep.get("metadata", {}).get("event_type", ""),
                        "distance": ep.get("distance", 0.0),
                    }
                )
                tokens_used += cost

        return {
            "primary": primary,
            "supporting": supporting,
            "recent_episodes": recent_episodes,
            "continuation": continuation,
            "parent_theory": parent_theory,
            "tokens_used": tokens_used,
        }

    @staticmethod
    def _is_familiar(theory: Theory, familiar_topics: set[str]) -> bool:
        """Check if theory content overlaps significantly with familiar topics."""
        content_lower = theory.content.lower()
        return any(topic.lower() in content_lower for topic in familiar_topics)
