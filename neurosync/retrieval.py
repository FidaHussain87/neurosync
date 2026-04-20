"""Full recall pipeline: context assembly, winner-take-all, user knowledge filter."""

from __future__ import annotations

from typing import Any, Optional

from neurosync.db import Database
from neurosync.models import Theory
from neurosync.semantic import SemanticMemory
from neurosync.user_model import UserModel
from neurosync.vectorstore import VectorStore
from neurosync.working import build_recall_query, estimate_tokens, format_theory_result


class RetrievalPipeline:
    """Assembles complete recall context using all memory layers."""

    def __init__(
        self,
        db: Database,
        vectorstore: Optional[VectorStore] = None,
        user_model: Optional[UserModel] = None,
        semantic: Optional[SemanticMemory] = None,
    ) -> None:
        self._db = db
        self._vs = vectorstore
        self._user_model = user_model
        self._semantic = semantic

    def recall(
        self,
        project: str = "",
        branch: str = "",
        context: str = "",
        max_tokens: int = 500,
    ) -> dict[str, Any]:
        """Full recall pipeline with winner-take-all and user filtering."""
        query = build_recall_query(project, branch, context)
        if not query.strip():
            return self._empty_result()

        if not self._vs:
            return self._empty_result()

        # Get user's familiar topics for filtering
        familiar: set[str] = set()
        if self._user_model:
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
            primary = format_theory_result(top_theory, top_score)
            tokens_used += estimate_tokens(top_theory.content)
            # Track application
            if self._semantic:
                self._semantic.record_application(top_theory.id)

            # 2-3 supporting theories
            for score, theory, _ in scored[1:4]:
                cost = estimate_tokens(theory.content)
                if tokens_used + cost > max_tokens:
                    break
                supporting.append(format_theory_result(theory, score))
                tokens_used += cost

        # Parent theory context
        parent_theory: Optional[dict[str, Any]] = None
        if primary and scored:
            top_theory = scored[0][1]
            if top_theory.parent_theory_id:
                parent = self._db.get_theory(top_theory.parent_theory_id)
                if parent and parent.active:
                    parent_theory = format_theory_result(parent, 0.0)
                    tokens_used += estimate_tokens(parent.content)

        # Continuation episodes
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

        # Recent episodes
        recent: list[dict[str, Any]] = []
        if project:
            episode_results = self._vs.search_episodes(
                query, n_results=5, where={"project": project}
            )
            for ep in episode_results:
                cost = estimate_tokens(ep.get("document", ""))
                if tokens_used + cost > max_tokens:
                    break
                recent.append(
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
            "recent_episodes": recent,
            "continuation": continuation,
            "parent_theory": parent_theory,
            "tokens_used": tokens_used,
            "theories_considered": len(theory_results),
            "theories_filtered_by_familiarity": len(theory_results) - len(scored),
        }

    def format_for_context(self, recall_result: dict[str, Any]) -> str:
        """Format recall result as a readable context string for injection."""
        parts: list[str] = []

        continuation = recall_result.get("continuation")
        if continuation:
            parts.append("## Continuation from Previous Session")
            parts.append(continuation["content"])
            parts.append("")

        primary = recall_result.get("primary")
        if primary:
            status = primary.get("validation_status", "unvalidated")
            parts.append(
                f"## Primary Insight (confidence: {primary['confidence']:.0%}, status: {status})"
            )
            parts.append(primary["content"])
            parts.append("")

        parent = recall_result.get("parent_theory")
        if parent:
            parts.append("## Parent Context")
            parts.append(parent["content"])
            parts.append("")

        supporting = recall_result.get("supporting", [])
        if supporting:
            parts.append("## Supporting Context")
            for theory in supporting:
                status = theory.get("validation_status", "unvalidated")
                parts.append(f"- [{theory['scope']}|{status}] {theory['content']}")
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
    def _user_knows(theory: Theory, familiar_topics: set[str]) -> bool:
        content_lower = theory.content.lower()
        return any(topic.lower() in content_lower for topic in familiar_topics)

    @staticmethod
    def _empty_result() -> dict[str, Any]:
        return {
            "primary": None,
            "supporting": [],
            "recent_episodes": [],
            "continuation": None,
            "parent_theory": None,
            "tokens_used": 0,
            "theories_considered": 0,
            "theories_filtered_by_familiarity": 0,
        }
