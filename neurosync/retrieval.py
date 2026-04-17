"""Full recall pipeline: context assembly, winner-take-all, user knowledge filter."""

from __future__ import annotations

from typing import Any, Optional

from neurosync.db import Database
from neurosync.models import Theory
from neurosync.user_model import UserModel
from neurosync.vectorstore import VectorStore


class RetrievalPipeline:
    """Assembles complete recall context using all memory layers."""

    def __init__(
        self,
        db: Database,
        vectorstore: VectorStore,
        user_model: UserModel,
    ) -> None:
        self._db = db
        self._vs = vectorstore
        self._user_model = user_model

    def recall(
        self,
        project: str = "",
        branch: str = "",
        context: str = "",
        max_tokens: int = 500,
    ) -> dict[str, Any]:
        """Full recall pipeline with winner-take-all and user filtering."""
        query = self._build_query(project, branch, context)
        if not query.strip():
            return self._empty_result()

        # Get user's familiar topics for filtering
        familiar = self._user_model.get_familiar_topics(threshold=0.9, project=project)

        # 1. Query theory collection
        theory_results = self._vs.search_theories(query, n_results=10, active_only=True)

        # 2. Score with winner-take-all
        scored: list[tuple[float, Theory, dict[str, Any]]] = []
        for result in theory_results:
            theory = self._db.get_theory(result["id"])
            if not theory or not theory.active:
                continue
            # Filter: suppress theories the user already knows well
            if self._user_knows(theory, familiar):
                continue
            distance = result.get("distance", 0.0)
            score = theory.confidence / (1.0 + distance)
            scored.append((score, theory, result))

        scored.sort(key=lambda x: x[0], reverse=True)

        tokens_used = 0
        primary: Optional[dict[str, Any]] = None
        supporting: list[dict[str, Any]] = []

        # Winner: single primary prediction
        if scored:
            top_score, top_theory, _ = scored[0]
            primary = self._format_theory(top_theory, top_score)
            tokens_used += self._estimate_tokens(top_theory.content)

            # 2-3 supporting theories
            for score, theory, _ in scored[1:4]:
                cost = self._estimate_tokens(theory.content)
                if tokens_used + cost > max_tokens:
                    break
                supporting.append(self._format_theory(theory, score))
                tokens_used += cost

        # Recent episodes
        recent: list[dict[str, Any]] = []
        if project:
            episode_results = self._vs.search_episodes(
                query, n_results=5, where={"project": project}
            )
            for ep in episode_results:
                cost = self._estimate_tokens(ep.get("document", ""))
                if tokens_used + cost > max_tokens:
                    break
                recent.append({
                    "id": ep["id"],
                    "content": ep.get("document", ""),
                    "event_type": ep.get("metadata", {}).get("event_type", ""),
                    "distance": ep.get("distance", 0.0),
                })
                tokens_used += cost

        return {
            "primary": primary,
            "supporting": supporting,
            "recent_episodes": recent,
            "tokens_used": tokens_used,
            "theories_considered": len(theory_results),
            "theories_filtered_by_familiarity": len(theory_results) - len(scored),
        }

    def format_for_context(self, recall_result: dict[str, Any]) -> str:
        """Format recall result as a readable context string for injection."""
        parts: list[str] = []
        primary = recall_result.get("primary")
        if primary:
            parts.append(f"## Primary Insight (confidence: {primary['confidence']:.0%})")
            parts.append(primary["content"])
            parts.append("")

        supporting = recall_result.get("supporting", [])
        if supporting:
            parts.append("## Supporting Context")
            for theory in supporting:
                parts.append(f"- [{theory['scope']}] {theory['content']}")
            parts.append("")

        recent = recall_result.get("recent_episodes", [])
        if recent:
            parts.append("## Recent Episodes")
            for ep in recent:
                parts.append(f"- [{ep['event_type']}] {ep['content'][:150]}")
            parts.append("")

        if not parts:
            return "No memories yet."
        return "\n".join(parts)

    @staticmethod
    def _build_query(project: str, branch: str, context: str) -> str:
        parts = []
        if project:
            parts.append(f"project:{project}")
        if branch:
            parts.append(f"branch:{branch}")
        if context:
            parts.append(context)
        return " ".join(parts)

    @staticmethod
    def _format_theory(theory: Theory, score: float) -> dict[str, Any]:
        return {
            "id": theory.id,
            "content": theory.content,
            "scope": theory.scope,
            "scope_qualifier": theory.scope_qualifier,
            "confidence": theory.confidence,
            "score": round(score, 4),
        }

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)

    @staticmethod
    def _user_knows(theory: Theory, familiar_topics: set[str]) -> bool:
        content_lower = theory.content.lower()
        return any(topic.lower() in content_lower for topic in familiar_topics)

    @staticmethod
    def _empty_result() -> dict[str, Any]:
        return {
            "primary": None,
            "supporting": [],
            "recent_episodes": [],
            "tokens_used": 0,
            "theories_considered": 0,
            "theories_filtered_by_familiarity": 0,
        }
