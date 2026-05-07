"""Full recall pipeline: context assembly, winner-take-all, user knowledge filter."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

from neurosync.db import Database
from neurosync.models import Theory
from neurosync.semantic import SemanticMemory
from neurosync.user_model import UserModel
from neurosync.vectorstore import VectorStore
from neurosync.working import build_recall_query, estimate_tokens, format_theory_result

# How quickly theories decay in relevance. Half-life = 30 days (λ = ln2/30).
# A theory confirmed today scores 1.0; one from 30 days ago scores 0.5 on this axis.
_RECENCY_HALFLIFE_DAYS = 30.0


def _recency_factor(theory: Theory) -> float:
    """Exponential recency weight: e^(-days_old * ln2 / 30)."""
    ts = theory.last_confirmed or theory.first_observed
    if not ts:
        return 0.5
    try:
        last = datetime.fromisoformat(ts)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        days_old = max(0.0, (datetime.now(timezone.utc) - last).total_seconds() / 86400.0)
        return math.exp(-days_old * math.log(2) / _RECENCY_HALFLIFE_DAYS)
    except (ValueError, OSError):
        return 0.5


# Threshold in seconds: if the gap between the previous session's last episode
# and now is below this, we treat the current call as a resumption.
_RESUMPTION_GAP_SECONDS = 4 * 3600  # 4 hours


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

        # Get user's familiar topics for filtering
        familiar: set[str] = set()
        if self._user_model:
            familiar = self._user_model.get_familiar_topics(threshold=0.9, project=project)

        # --- Primary theory fetch (vector or SQLite fallback) ---
        if self._vs:
            theory_results = self._vs.search_theories(query, n_results=10, active_only=True)
        else:
            theory_results = []

        # Fix #4 — SQLite fallback when ChromaDB unavailable
        if not theory_results:
            theory_results = self._sqlite_fallback_theories(project)

        # Score with recency-weighted formula (Fix #1)
        scored: list[tuple[float, Theory, dict[str, Any]]] = []
        for result in theory_results:
            theory = self._db.get_theory(result["id"])
            if not theory or not theory.active:
                continue
            # Fix #8 — use word-boundary matching instead of substring for familiarity
            if self._user_knows(theory, familiar):
                continue
            distance = result.get("distance", 0.0)
            recency = _recency_factor(theory)
            # Fix #1 — multiply score by recency so stale theories rank lower
            score = theory.confidence * recency / (1.0 + distance)
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
            if self._semantic:
                self._semantic.record_application(top_theory.id)

            # Fix #6 — token-budget driven loop, not a hard position cutoff at 4
            for score, theory, _ in scored[1:]:
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

        # Fix #5 — resumption detection: auto-surface last session context
        # when session gap < 4 hours on the same project/branch, even without handoff
        resumption: Optional[dict[str, Any]] = None
        if project and tokens_used < max_tokens:
            resumption = self._detect_resumption(project, branch, max_tokens - tokens_used)
            if resumption:
                tokens_used += estimate_tokens(resumption.get("content", ""))

        # Continuation episodes (explicit handoff)
        continuation: Optional[dict[str, Any]] = None
        if project and not resumption:
            if self._vs:
                cont_results = self._vs.search_episodes(
                    f"{project} continuation unfinished work",
                    n_results=3,
                    where={"$and": [{"project": project}, {"event_type": "continuation"}]},
                )
            else:
                cont_results = []
            if not cont_results:
                # SQLite fallback for continuation
                cont_eps = self._db.list_episodes(event_type="continuation", limit=5)
                cont_results = [
                    {"id": ep.id, "document": ep.content, "metadata": {"event_type": "continuation"}}
                    for ep in cont_eps
                    if not project or self._episode_matches_project(ep, project)
                ]
            for cr in cont_results:
                continuation = {
                    "id": cr["id"],
                    "content": cr.get("document", ""),
                }
                tokens_used += estimate_tokens(cr.get("document", ""))
                break

        # Recent episodes
        recent: list[dict[str, Any]] = []
        if project:
            if self._vs:
                episode_results = self._vs.search_episodes(
                    query, n_results=5, where={"project": project}
                )
            else:
                episode_results = []
            if not episode_results:
                # SQLite fallback for recent episodes
                all_eps = self._db.list_episodes(limit=20)
                episode_results = [
                    {
                        "id": ep.id,
                        "document": ep.content,
                        "distance": 0.0,
                        "metadata": {"event_type": ep.event_type},
                    }
                    for ep in all_eps
                    if not project or self._episode_matches_project(ep, project)
                ][:5]
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

        # Cross-project theory discovery
        cross_project: list[dict[str, Any]] = []
        if project and tokens_used < max_tokens:
            cross_project = self._discover_cross_project_theories(
                query, project, max_tokens - tokens_used, scored
            )
            for cp in cross_project:
                tokens_used += estimate_tokens(cp.get("content", ""))

        result = {
            "primary": primary,
            "supporting": supporting,
            "recent_episodes": recent,
            "continuation": continuation,
            "parent_theory": parent_theory,
            "cross_project_theories": cross_project,
            "tokens_used": tokens_used,
            "theories_considered": len(theory_results),
            "theories_filtered_by_familiarity": len(theory_results) - len(scored),
        }
        if resumption:
            result["resumption"] = resumption
        return result

    # ------------------------------------------------------------------
    # Fix #4 — SQLite fallback when ChromaDB unavailable
    # ------------------------------------------------------------------

    def _sqlite_fallback_theories(self, project: str = "") -> list[dict[str, Any]]:
        """Return top theories from SQLite ordered by confidence × recency.

        This ensures recall returns something useful in degraded mode instead
        of silent empty results.
        """
        try:
            theories = self._db.list_theories(active_only=True, limit=20)
            if project:
                # Prefer project-scoped, then domain/craft
                project_theories = [t for t in theories if t.scope_qualifier == project]
                other_theories = [t for t in theories if t.scope_qualifier != project]
                theories = project_theories + other_theories
            return [
                {"id": t.id, "distance": 1.0 - t.confidence}
                for t in theories[:10]
            ]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Fix #5 — Resumption detection
    # ------------------------------------------------------------------

    def _detect_resumption(
        self, project: str, branch: str, remaining_tokens: int
    ) -> Optional[dict[str, Any]]:
        """Detect if this is a short-gap resumption and surface last session's episodes.

        If the most recent session for this project ended within _RESUMPTION_GAP_SECONDS
        and was not a clean handoff, surface its last 3 episodes as resumption context
        at top priority — without requiring neurosync_handoff to have been called.
        """
        try:
            sessions = self._db.list_sessions(project=project, limit=5)
            if not sessions:
                return None
            # Find the most recently ended session
            for session in sessions:
                if not session.ended_at:
                    continue
                try:
                    ended = datetime.fromisoformat(session.ended_at)
                    if ended.tzinfo is None:
                        ended = ended.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    continue
                gap_seconds = (datetime.now(timezone.utc) - ended).total_seconds()
                if gap_seconds > _RESUMPTION_GAP_SECONDS:
                    continue
                # This is a recent session — check if it had a handoff
                handoff_eps = self._db.list_episodes(
                    session_id=session.id, event_type="continuation", limit=1
                )
                if handoff_eps:
                    # Already handled by continuation search — skip
                    continue
                # Surface the last 3 non-trivial episodes from this session
                recent_eps = self._db.list_episodes(session_id=session.id, limit=10)
                meaningful = [
                    ep for ep in recent_eps
                    if ep.event_type not in ("observed",) and ep.content.strip()
                ][:3]
                if not meaningful:
                    continue
                parts = [f"[{ep.event_type}] {ep.content[:200]}" for ep in meaningful]
                content = (
                    f"Resuming session from {int(gap_seconds // 60)} min ago "
                    f"(branch: {session.branch or branch}):\n" + "\n".join(parts)
                )
                if estimate_tokens(content) > remaining_tokens:
                    return None
                return {
                    "id": session.id,
                    "content": content,
                    "gap_minutes": int(gap_seconds // 60),
                    "branch": session.branch or branch,
                }
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Fix #11 — Cross-project with transfer_reasoning
    # ------------------------------------------------------------------

    def _discover_cross_project_theories(
        self,
        query: str,
        current_project: str,
        remaining_tokens: int,
        already_scored: list,
    ) -> list[dict[str, Any]]:
        """Find relevant theories from other projects or broader scopes.

        Adds transfer_reasoning so the LLM understands why a theory from
        another project is being surfaced.
        """
        if remaining_tokens <= 0:
            return []

        already_ids = {s[1].id for s in already_scored}

        if self._vs:
            results = self._vs.search_theories(query, n_results=15, active_only=True)
        else:
            results = self._sqlite_fallback_theories()

        cross_project: list[dict[str, Any]] = []
        tokens_used = 0

        for result in results:
            if result["id"] in already_ids:
                continue
            theory = self._db.get_theory(result["id"])
            if not theory or not theory.active:
                continue
            if theory.scope == "project" and theory.scope_qualifier == current_project:
                continue
            if theory.scope in ("domain", "craft") or (
                theory.scope == "project" and theory.scope_qualifier != current_project
            ):
                cost = estimate_tokens(theory.content)
                if tokens_used + cost > remaining_tokens:
                    break
                distance = result.get("distance", 0.0)
                if distance > 0.6:
                    continue
                score = theory.confidence * _recency_factor(theory) / (1.0 + distance)
                entry = format_theory_result(theory, score)
                entry["source_project"] = theory.scope_qualifier
                entry["cross_project"] = True
                # Fix #11 — add reasoning for why this cross-project theory surfaced
                entry["transfer_reasoning"] = _build_transfer_reasoning(theory, current_project)
                cross_project.append(entry)
                tokens_used += cost
                if len(cross_project) >= 3:
                    break

        return cross_project

    # ------------------------------------------------------------------
    # Fix #8 — word-boundary familiarity matching
    # ------------------------------------------------------------------

    @staticmethod
    def _user_knows(theory: Theory, familiar_topics: set[str]) -> bool:
        """Suppress over-familiar theories using word-boundary matching.

        Old implementation used substring containment, which caused 'auth' to
        suppress theories about 'authentication', 'authorization', 'OAuth' etc.
        Now requires a whole-word match so only genuinely redundant theories
        are suppressed.
        """
        content_lower = theory.content.lower()
        for topic in familiar_topics:
            # Build a word-boundary pattern; fall back to substring on regex error
            try:
                if re.search(r'\b' + re.escape(topic.lower()) + r'\b', content_lower):
                    return True
            except re.error:
                if topic.lower() in content_lower:
                    return True
        return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _episode_matches_project(self, ep: Any, project: str) -> bool:
        """Check if an episode belongs to the given project via its session."""
        try:
            session = self._db.get_session(ep.session_id)
            return session is not None and session.project == project
        except Exception:
            return False

    def format_for_context(self, recall_result: dict[str, Any]) -> str:
        """Format recall result as a readable context string for injection.

        Public API for non-MCP integrations (e.g., direct Python usage, custom
        hooks, or embedding recall context into prompts programmatically).
        Not called by the MCP server itself, which returns structured JSON.
        """
        parts: list[str] = []

        resumption = recall_result.get("resumption")
        if resumption:
            parts.append("## Resuming Previous Session")
            parts.append(resumption["content"])
            parts.append("")

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
    def _empty_result() -> dict[str, Any]:
        return {
            "primary": None,
            "supporting": [],
            "recent_episodes": [],
            "continuation": None,
            "resumption": None,
            "parent_theory": None,
            "cross_project_theories": [],
            "tokens_used": 0,
            "theories_considered": 0,
            "theories_filtered_by_familiarity": 0,
        }


def _build_transfer_reasoning(theory: Theory, current_project: str) -> str:
    """Explain why a cross-project theory is relevant."""
    if theory.scope == "craft":
        return "craft-level pattern (applies across all projects)"
    if theory.scope == "domain":
        domain = theory.scope_qualifier or "shared domain"
        return f"domain '{domain}' — same conceptual area as current work"
    if theory.scope == "project":
        src = theory.scope_qualifier or "another project"
        return f"learned in '{src}' — semantically similar to current context in '{current_project}'"
    return "cross-project relevance detected via semantic similarity"
