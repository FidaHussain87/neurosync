"""MCP JSON-RPC 2.0 stdio server — 10 tools for NeuroSync memory system."""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Optional

from neurosync.analogy import AnalogyEngine
from neurosync.causal import CausalGraph
from neurosync.config import NeuroSyncConfig, detect_git_info
from neurosync.consolidation import maybe_consolidate
from neurosync.db import Database
from neurosync.episodic import EpisodicMemory
from neurosync.failure import FailureModel
from neurosync.forgetting import ForgettingEngine
from neurosync.git_observer import GitObserver
from neurosync.hierarchy import TheoryHierarchy
from neurosync.logging import configure_logging, get_logger
from neurosync.models import EPISODE_TYPES
from neurosync.quality import quality_warning
from neurosync.retrieval import RetrievalPipeline
from neurosync.semantic import SemanticMemory
from neurosync.user_model import UserModel
from neurosync.vectorstore import VectorStore
from neurosync.version import __version__

logger = get_logger("mcp_server")

# ---------------------------------------------------------------------------
# Protocol hints — contextual reminders appended to tool responses
# ---------------------------------------------------------------------------

_PROTOCOL_HINTS: dict[str, str] = {
    "neurosync_recall": (
        "Apply recalled theories as ground truth. Check for continuation episodes "
        "from previous sessions. If recall returns nothing, proceed carefully and "
        "record assumptions at session end."
    ),
    "neurosync_record": (
        "Write episodes as causal statements, not activity logs. Include cause, "
        "effect, and reasoning fields when possible. Use importance 1-5 for "
        "intuition signal."
    ),
    "neurosync_remember": (
        "Capture full context with reasoning. Include file paths and module names. "
        "Explain WHY, not just WHAT."
    ),
    "neurosync_correct": (
        "Each correction compounds (2^N). After recording, look for other places "
        "where the same default behavior might apply."
    ),
    "neurosync_handoff": (
        "Record a handoff at session end for multi-session tasks. Include specific "
        "next steps and any blockers."
    ),
}


def _build_protocol_hint(tool_name: str) -> Optional[str]:
    """Build dynamic protocol hint for a tool response."""
    parts: list[str] = []
    # Base hint
    base = _PROTOCOL_HINTS.get(tool_name)
    if base:
        parts.append(base)
    # Dynamic: pending episode count nudge
    if _db:
        try:
            pending = _db.count_episodes(consolidated=0)
            if pending > 30:
                parts.append(
                    f"Note: {pending} unconsolidated episodes pending. "
                    "Auto-consolidation will handle this, but you can also "
                    "run neurosync_consolidate manually."
                )
        except Exception:
            logger.debug("Failed to build protocol hint")
    # Dynamic: correction count awareness
    if _correction_count >= 3:
        parts.append(
            f"Session has {_correction_count} corrections so far. "
            "Look for patterns — the same default behavior may be wrong elsewhere."
        )
    return " ".join(parts) if parts else None


def _add_protocol_hint(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Append protocol hint to tool response if available."""
    hint = _build_protocol_hint(tool_name)
    if hint:
        result["_hint"] = hint
    return result


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "neurosync_recall",
        "description": (
            "Retrieve relevant theories and recent context for the current project/branch. "
            "Use at session start to load developer memory. Winner-take-all activation with "
            "token-budgeted output."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project name (auto-detected from git if omitted)",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch name (auto-detected from git if omitted)",
                },
                "context": {"type": "string", "description": "Additional context for retrieval"},
                "max_tokens": {
                    "type": "integer",
                    "description": "Max output tokens (default 500)",
                    "default": 500,
                },
            },
        },
    },
    {
        "name": "neurosync_record",
        "description": (
            "Record structured episodes from the current session. Call at session end "
            "with events that happened during the session. Include cause/effect/reasoning "
            "for causal episodes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "events": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": sorted(EPISODE_TYPES)},
                            "content": {"type": "string"},
                            "files": {"type": "array", "items": {"type": "string"}},
                            "layers": {"type": "array", "items": {"type": "string"}},
                            "cause": {"type": "string", "description": "What triggered this event"},
                            "effect": {
                                "type": "string",
                                "description": "What resulted from this event",
                            },
                            "reasoning": {"type": "string", "description": "Why this happened"},
                            "importance": {
                                "type": "integer",
                                "description": "Intuition rating 1-5 (0=none)",
                                "minimum": 0,
                                "maximum": 5,
                            },
                        },
                        "required": ["type", "content"],
                    },
                    "description": "Events to record",
                },
                "session_summary": {"type": "string", "description": "Summary of the session"},
                "project": {"type": "string"},
                "branch": {"type": "string"},
                "explicit_remember": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Things to explicitly remember (high signal weight)",
                },
            },
            "required": ["events"],
        },
    },
    {
        "name": "neurosync_remember",
        "description": (
            "Explicitly remember something important. Creates a high-weight episode. "
            "Use when the user says 'remember this' or equivalent. Include cause/effect "
            "for causal memories."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "What to remember"},
                "type": {
                    "type": "string",
                    "description": "Event type (default: explicit)",
                    "default": "explicit",
                },
                "cause": {"type": "string", "description": "What triggered this memory"},
                "effect": {"type": "string", "description": "What resulted"},
                "reasoning": {"type": "string", "description": "Why this matters"},
                "importance": {
                    "type": "integer",
                    "description": "Intuition rating 1-5 (0=none)",
                    "minimum": 0,
                    "maximum": 5,
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "neurosync_query",
        "description": "Search across episodes, theories, analogies, causal graph, or failures.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "scope": {
                    "type": "string",
                    "enum": ["all", "episodes", "theories"],
                    "default": "all",
                },
                "mode": {
                    "type": "string",
                    "enum": ["semantic", "analogy", "causal", "failures"],
                    "default": "semantic",
                    "description": "Search mode: semantic (default), analogy (structural+semantic), causal (cause/effect graph), failures (known anti-patterns)",
                },
                "project": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "neurosync_correct",
        "description": (
            "Record an AI mistake. Creates a correction episode with exponential weight (2^N). "
            "Optionally logs a contradiction against a matched theory."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "wrong": {"type": "string", "description": "What was wrong"},
                "right": {"type": "string", "description": "What is correct"},
                "theory_id": {"type": "string", "description": "Theory to contradict (optional)"},
            },
            "required": ["wrong", "right"],
        },
    },
    {
        "name": "neurosync_status",
        "description": "Health check — episode, theory, contradiction counts and ChromaDB sizes.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "neurosync_theories",
        "description": "Browse, inspect, retire, relate, or view hierarchy graph of theories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "detail", "retire", "relate", "graph"],
                    "default": "list",
                },
                "scope": {"type": "string", "enum": ["project", "domain", "craft"]},
                "project": {"type": "string"},
                "theory_id": {"type": "string"},
                "related_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Theory IDs to link (for relate action)",
                },
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "neurosync_consolidate",
        "description": (
            "Trigger the consolidation engine manually. Clusters episodes, extracts theories, "
            "and applies MDL pruning."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "dry_run": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "neurosync_handoff",
        "description": (
            "Record a cross-session handoff for multi-session tasks. Creates a "
            "high-weight continuation episode so the next session picks up where "
            "this one left off."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "Overall goal of the task"},
                "accomplished": {
                    "type": "string",
                    "description": "What was accomplished this session",
                },
                "remaining": {"type": "string", "description": "What still needs to be done"},
                "next_step": {
                    "type": "string",
                    "description": "Concrete next step for the next session",
                },
                "blockers": {"type": "string", "description": "Any blockers or open questions"},
            },
            "required": ["goal", "accomplished", "remaining", "next_step"],
        },
    },
    {
        "name": "neurosync_graph",
        "description": (
            "Query or sync the Neo4j knowledge graph. Requires neo4j extra: "
            "pip install neurosync[neo4j]. Actions: status (graph health), "
            "sync (SQLite -> Neo4j), prebuilt (list/run pre-built queries), "
            "query (run read-only Cypher)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["query", "sync", "prebuilt", "status"],
                    "description": "Action to perform",
                },
                "cypher": {
                    "type": "string",
                    "description": "Cypher query to execute (for 'query' action)",
                },
                "parameters": {
                    "type": "object",
                    "description": "Parameters for the Cypher query",
                },
                "prebuilt_name": {
                    "type": "string",
                    "description": "Name of a pre-built query to run (for 'prebuilt' action)",
                },
                "project": {
                    "type": "string",
                    "description": "Project filter for sync",
                },
            },
            "required": ["action"],
        },
    },
]

# ---------------------------------------------------------------------------
# Server state
# ---------------------------------------------------------------------------


def _require_init(*components: Any) -> None:
    """Raise RuntimeError if any server component is None (not yet initialized)."""
    for comp in components:
        if comp is None:
            raise RuntimeError("NeuroSync server not initialized. Call _init() first.")


_config: Optional[NeuroSyncConfig] = None
_db: Optional[Database] = None
_vs: Optional[VectorStore] = None
_episodic: Optional[EpisodicMemory] = None
_semantic: Optional[SemanticMemory] = None
_analogy: Optional[AnalogyEngine] = None
_causal: Optional[CausalGraph] = None
_failure: Optional[FailureModel] = None
_forgetting: Optional[ForgettingEngine] = None
_hierarchy: Optional[TheoryHierarchy] = None
_user_model: Optional[UserModel] = None
_retrieval: Optional[RetrievalPipeline] = None
_graph: Optional[Any] = None
_current_session_id: Optional[str] = None
_correction_count: int = 0
_correction_topics: list[str] = []  # Topics corrected this session (for targeted penalization)
_git_observer: Optional[GitObserver] = None


def _init() -> None:
    global _config, _db, _vs, _episodic, _semantic
    global _analogy, _causal, _failure, _forgetting, _hierarchy
    global _user_model, _retrieval
    if _db is not None:
        return

    config = NeuroSyncConfig.load()
    config.ensure_dirs()
    configure_logging()

    # Database is essential — failure here is fatal
    # Use PostgreSQL when configured, SQLite otherwise
    db: Any
    if config.db_backend == "postgresql":
        try:
            from neurosync.pg_db import PostgresDatabase

            db = PostgresDatabase(config)
            logger.info("Using PostgreSQL backend")
        except ImportError:
            logger.warning("psycopg2 not installed, falling back to SQLite")
            db = Database(config)
        except Exception:
            logger.warning("PostgreSQL connection failed, falling back to SQLite", exc_info=True)
            db = Database(config)
    else:
        db = Database(config)

    # VectorStore is optional — failure means degraded mode
    vs = None
    try:
        vs = VectorStore(config)
    except Exception:
        logger.warning(
            "ChromaDB unavailable, running in degraded mode (no vector search)", exc_info=True
        )

    # Build engines — they accept Optional[VectorStore]
    episodic = EpisodicMemory(db, vs)
    semantic = SemanticMemory(db, vs)
    analogy = AnalogyEngine(db, vs) if vs else None
    causal = CausalGraph(db, vs)
    failure = FailureModel(db, vs)
    forgetting = ForgettingEngine(db, vs)
    hierarchy = TheoryHierarchy(db, vs)
    user_model = UserModel(db)
    retrieval = RetrievalPipeline(db, vs, user_model=user_model, semantic=semantic)

    # Atomic commit — all or nothing
    _config = config
    _db = db
    _vs = vs
    _episodic = episodic
    _semantic = semantic
    _analogy = analogy
    _causal = causal
    _failure = failure
    _forgetting = forgetting
    _hierarchy = hierarchy
    _user_model = user_model
    _retrieval = retrieval


def _ensure_session(project: str = "", branch: str = "") -> str:
    global _current_session_id, _git_observer
    if _current_session_id:
        return _current_session_id
    _require_init(_episodic)
    git_info = detect_git_info()
    project = project or git_info.get("project", "")
    branch = branch or git_info.get("branch", "")
    session = _episodic.start_session(project=project, branch=branch)
    _current_session_id = session.id
    # Capture git baseline for passive observation
    if _git_observer is None:
        _git_observer = GitObserver()
        _git_observer.capture_baseline()
    return session.id


def _rotate_session() -> None:
    """End the current session and reset per-session state.

    Called at the start of handle_recall() because the protocol mandates
    "call recall at session start" — making it the natural session boundary.
    If no session exists yet (first call), this is a no-op.
    """
    global _current_session_id, _correction_count, _correction_topics, _git_observer
    if _current_session_id is None:
        return
    # Capture git delta and end the old session
    try:
        if _git_observer and _episodic:
            session_id = _current_session_id
            for event in _git_observer.capture_delta():
                _episodic.record_episode(
                    session_id=session_id,
                    event_type="observed",
                    content=event.get("content", ""),
                    files_touched=event.get("files", []),
                    layers_touched=event.get("layers", []),
                    signal_weight=event.get("signal_weight", 0.3),
                )
        if _episodic:
            _episodic.end_session(_current_session_id)
    except Exception:
        logger.debug("Error during session rotation cleanup", exc_info=True)
    # Reset per-session state
    _current_session_id = None
    _correction_count = 0
    _correction_topics = []
    _git_observer = None


def _get_graph():
    """Lazy-init GraphStore on first use."""
    global _graph
    if _graph is False:  # Previously failed — don't retry
        return None
    if _graph is not None:
        return _graph
    try:
        from neurosync.graph import GraphStore

        _graph = GraphStore(_config)
        return _graph
    except ImportError:
        logger.info("Neo4j driver not installed, graph features disabled")
        _graph = False  # sentinel: don't retry
        return None
    except Exception:
        logger.warning("Neo4j unavailable, graph features disabled", exc_info=True)
        _graph = False
        return None


def _try_auto_consolidate() -> Optional[dict]:
    """Run auto-consolidation if enabled and threshold is met. Returns result or None."""
    if _config and _config.auto_consolidation_enabled and _db and _episodic and _semantic:
        result = maybe_consolidate(
            _db,
            _vs,
            _episodic,
            _semantic,
            threshold=_config.auto_consolidation_threshold,
            min_episodes=_config.consolidation_min_episodes,
        )
        # Run forgetting pass after consolidation to prune stale episodes and decay theories
        if result and _forgetting:
            try:
                forget_result = _forgetting.run_forgetting_pass()
                result["forgetting"] = forget_result
            except Exception:
                logger.debug("Forgetting pass failed after consolidation", exc_info=True)
        # Auto-sync new theories to Neo4j graph if available
        if result:
            try:
                graph = _get_graph()
                if graph:
                    sync_result = graph.sync(_db)
                    result["graph_sync"] = sync_result
            except Exception:
                logger.debug("Graph sync failed after consolidation", exc_info=True)
        return result
    return None


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def handle_recall(params: dict[str, Any]) -> dict[str, Any]:
    _init()
    _rotate_session()
    _require_init(_retrieval, _failure, _hierarchy, _forgetting)
    git_info = detect_git_info()
    project = params.get("project") or git_info.get("project", "")
    branch = params.get("branch") or git_info.get("branch", "")
    context = params.get("context", "")
    max_tokens = params.get("max_tokens", 500)
    # Use RetrievalPipeline (includes UserModel filtering, parent context, continuations)
    result = _retrieval.recall(
        project=project,
        branch=branch,
        context=context,
        max_tokens=max_tokens,
    )
    if not result["primary"] and not result["recent_episodes"]:
        return _add_protocol_hint(
            "neurosync_recall",
            {"message": "No memories yet. Start working and record episodes to build memory."},
        )
    # Track user exposure to recalled theories (feeds UserModel familiarity)
    if _user_model and project:
        if result.get("primary"):
            _user_model.record_exposure(
                topic=result["primary"]["content"][:100],
                project=project,
                explained=False,
            )
        for sup in result.get("supporting", []):
            _user_model.record_exposure(
                topic=sup["content"][:100],
                project=project,
                explained=False,
            )
    # Refresh primary theory's retention (extends Ebbinghaus grace period)
    if result.get("primary") and _forgetting:
        primary_id = result["primary"].get("id", "")
        if primary_id:
            theory = _db.get_theory(primary_id)
            if theory:
                _forgetting.refresh_theory_on_application(theory)
    # Enrich with failure warnings
    query = f"{project} {branch} {context}".strip()
    if query:
        warnings = _failure.check_for_warnings(query, project=project, threshold=0.5)
        if warnings:
            result["warnings"] = warnings
    # Enrich with hierarchy context for primary theory
    if result.get("primary"):
        primary_id = result["primary"].get("id", "")
        if primary_id:
            theory = _db.get_theory(primary_id)
            if theory:
                hierarchy_ctx = _hierarchy.graph_aware_recall(theory)
                if hierarchy_ctx.get("ancestors") or hierarchy_ctx.get("children"):
                    result["hierarchy_context"] = hierarchy_ctx
    return _add_protocol_hint("neurosync_recall", result)


def handle_record(params: dict[str, Any]) -> dict[str, Any]:
    _require_init(_episodic)
    events = params.get("events", [])
    summary = params.get("session_summary", "")
    project = params.get("project", "")
    branch = params.get("branch", "")
    session_id = _ensure_session(project=project, branch=branch)
    recorded = []
    warnings: list[str] = []
    for event in events:
        event_type = event.get("type", "decision")
        if event_type not in EPISODE_TYPES:
            event_type = "decision"
        content = event.get("content", "")
        layers = event.get("layers", [])
        # Compute SURPRISE signal: check if content contradicts any existing theory
        contradicts = False
        if _vs and content.strip():
            try:
                similar = _vs.search_theories(content, n_results=3, active_only=True)
                for match in similar:
                    dist = match.get("distance", 1.0)
                    # Low distance = similar topic; check if content has contradiction language
                    if dist < 0.4 and _has_contradiction_language(content):
                        contradicts = True
                        break
            except Exception:
                pass
        # Compute REPETITION signal: check if user has explained this topic before
        times_explained = 0
        if _user_model and content.strip():
            topic_key = content[:100]
            uk = _db.get_user_knowledge(topic_key, project)
            if uk:
                times_explained = uk.times_explained
        episode = _episodic.record_episode(
            session_id=session_id,
            event_type=event_type,
            content=content,
            files_touched=event.get("files", []),
            layers_touched=layers,
            cause=event.get("cause", ""),
            effect=event.get("effect", ""),
            reasoning=event.get("reasoning", ""),
            importance=event.get("importance", 0),
            contradicts_theory=contradicts,
            times_explained=times_explained,
        )
        recorded.append(episode.id)
        # Track user exposure when they explain something
        if _user_model and project and content.strip():
            _user_model.record_exposure(
                topic=content[:100],
                project=project,
                explained=True,
            )
        # Check quality
        if episode.quality_score is not None:
            warn = quality_warning(episode.quality_score)
            if warn:
                warnings.append(f"Episode '{event.get('content', '')[:50]}...': {warn}")
    # Handle explicit_remember items
    for item in params.get("explicit_remember", []):
        episode = _episodic.record_explicit(session_id=session_id, content=item)
        recorded.append(episode.id)
    # Capture git delta — passive observed episodes
    observed_count = 0
    if _git_observer:
        for event in _git_observer.capture_delta():
            _episodic.record_episode(
                session_id=session_id,
                event_type="observed",
                content=event.get("content", ""),
                files_touched=event.get("files", []),
                layers_touched=event.get("layers", []),
                signal_weight=event.get("signal_weight", 0.3),
            )
            observed_count += 1
    if summary:
        _episodic.end_session(session_id, summary=summary)
    # Outcome-based confidence: if session had corrections, slightly reduce
    # confidence of theories that were recalled but led to mistakes
    if _correction_count > 0 and _semantic:
        _apply_outcome_confidence_adjustment()
    result: dict[str, Any] = {
        "session_id": session_id,
        "episodes_recorded": len(recorded),
        "episode_ids": recorded,
    }
    if observed_count > 0:
        result["observed_episodes"] = observed_count
    if warnings:
        result["quality_warnings"] = warnings
    # Auto-consolidation
    auto_result = _try_auto_consolidate()
    if auto_result:
        result["auto_consolidation"] = auto_result
    return _add_protocol_hint("neurosync_record", result)


def _has_contradiction_language(text: str) -> bool:
    """Check if text contains strong contradiction/correction indicators.

    Uses multi-word phrases and strong negation patterns to avoid false
    positives from common words like "instead" or "however" that appear
    in normal technical writing.
    """
    # Strong indicators: phrases that strongly imply contradiction
    strong_markers = (
        "but actually",
        "not true",
        "this is wrong",
        "was wrong",
        "is incorrect",
        "was incorrect",
        "doesn't work",
        "didn't work",
        "this is broken",
        "was broken",
        "should not have",
        "contrary to",
        "opposite of",
        "contradicts",
        "that's a mistake",
        "was a mistake",
        "corrected to",
        "the correct approach",
        "the right way",
        "not actually",
    )
    text_lower = text.lower()
    if any(m in text_lower for m in strong_markers):
        return True
    # Require at least 2 weak indicators to trigger (co-occurrence reduces false positives)
    weak_markers = (
        "actually",
        "incorrect",
        "wrong",
        "mistake",
        "corrected",
        "instead",
        "rather",
        "however",
        "contrary",
        "broken",
    )
    weak_count = sum(1 for m in weak_markers if m in text_lower)
    return weak_count >= 2


def _apply_outcome_confidence_adjustment() -> None:
    """Outcome-based confidence: reduce confidence of recently-applied theories
    only when the correction topic is relevant to the theory content.

    Uses Hebbian specificity: only weaken the activated pathway (theory whose
    content overlaps with the correction), not all active theories globally.
    """
    if not _semantic or not _db or not _correction_topics:
        return
    try:
        theories = _db.list_theories(active_only=True, limit=50)
        penalty = min(_correction_count * 0.02, 0.1)  # Cap at 10% reduction
        for theory in theories:
            if not theory.last_applied or theory.application_count <= 0:
                continue
            # Only penalize if the theory's content is relevant to a correction topic
            theory_lower = theory.content.lower()
            relevant = any(_topic_overlap(topic, theory_lower) for topic in _correction_topics)
            if relevant:
                theory.confidence = max(0.05, theory.confidence - penalty)
                _db.save_theory(theory)
    except Exception:
        logger.debug("Outcome confidence adjustment failed", exc_info=True)


def _topic_overlap(correction_text: str, theory_text: str) -> bool:
    """Check if a correction topic is semantically related to a theory.

    Uses keyword overlap: splits correction into significant words (3+ chars)
    and checks if at least 2 appear in the theory, or if the full correction
    phrase appears as a substring.
    """
    if correction_text in theory_text:
        return True
    words = [w for w in correction_text.split() if len(w) >= 3]
    if not words:
        return False
    matches = sum(1 for w in words if w in theory_text)
    # Require at least 2 keyword matches, or >40% overlap for short phrases
    threshold = min(2, max(1, len(words) * 4 // 10))
    return matches >= threshold


def handle_remember(params: dict[str, Any]) -> dict[str, Any]:
    _require_init(_episodic)
    content = params.get("content", "")
    event_type = params.get("type", "explicit")
    cause = params.get("cause", "")
    effect = params.get("effect", "")
    reasoning = params.get("reasoning", "")
    importance = params.get("importance", 0)
    if not content.strip():
        return {"error": "Content is required"}
    # Build enriched content with causal context if provided
    enriched = content
    if cause or effect:
        parts = []
        if cause:
            parts.append(f"Cause: {cause}")
        parts.append(content)
        if effect:
            parts.append(f"Effect: {effect}")
        if reasoning:
            parts.append(f"Reasoning: {reasoning}")
        enriched = " | ".join(parts)
    session_id = _ensure_session()
    episode = _episodic.record_explicit(
        session_id=session_id,
        content=enriched,
        event_type=event_type,
        importance=importance,
        cause=cause,
        effect=effect,
        reasoning=reasoning,
    )
    result: dict[str, Any] = {
        "episode_id": episode.id,
        "signal_weight": episode.signal_weight,
        "message": f"Remembered with signal weight {episode.signal_weight}",
    }
    auto_result = _try_auto_consolidate()
    if auto_result:
        result["auto_consolidation"] = auto_result
    return _add_protocol_hint("neurosync_remember", result)


def handle_query(params: dict[str, Any]) -> dict[str, Any]:
    _require_init(_episodic, _semantic, _causal, _failure)
    query = params.get("query", "")
    scope = params.get("scope", "all")
    mode = params.get("mode", "semantic")
    project = params.get("project")
    limit = params.get("limit", 10)
    if not query.strip():
        return {"error": "Query is required"}

    if mode == "analogy":
        if not _analogy:
            return {
                "mode": "analogy",
                "results": [],
                "warning": "Analogy engine unavailable (no vector search)",
            }
        analogies = _analogy.find_analogies(query, n_results=limit)
        return {"mode": "analogy", "results": analogies}

    if mode == "causal":
        neighborhood = _causal.get_causal_neighborhood(query, project=project)
        return {"mode": "causal", "results": neighborhood}

    if mode == "failures":
        failures = _failure.search_failures(query, n_results=limit)
        warnings = _failure.check_for_warnings(query, project=project or "")
        return {"mode": "failures", "results": failures, "warnings": warnings}

    # Default: semantic
    results: dict[str, Any] = {"mode": "semantic"}
    if scope in ("all", "episodes"):
        results["episodes"] = _episodic.search(query, n_results=limit, project=project)
    if scope in ("all", "theories"):
        results["theories"] = _semantic.search(query, n_results=limit)
    return results


def handle_correct(params: dict[str, Any]) -> dict[str, Any]:
    global _correction_count, _correction_topics
    _require_init(_episodic, _semantic, _failure)
    wrong = params.get("wrong", "")
    right = params.get("right", "")
    theory_id = params.get("theory_id")
    if not wrong.strip() or not right.strip():
        return {"error": "Both 'wrong' and 'right' are required"}
    _correction_count += 1
    # Track correction topics for targeted confidence adjustment
    _correction_topics.append(wrong.lower())
    _correction_topics.append(right.lower())
    session_id = _ensure_session()
    episode = _episodic.record_correction(
        session_id=session_id,
        wrong=wrong,
        right=right,
        correction_count=_correction_count,
    )
    result: dict[str, Any] = {
        "episode_id": episode.id,
        "signal_weight": episode.signal_weight,
        "correction_number": _correction_count,
    }
    if theory_id:
        contradiction = _semantic.contradict_theory(
            theory_id=theory_id,
            episode_id=episode.id,
            description=f"Corrected: {wrong} -> {right}",
        )
        if contradiction:
            result["contradiction_id"] = contradiction.id
    # Auto-extract failure record
    failure_rec = _failure.extract_from_correction(episode.id)
    if failure_rec:
        result["failure_record_id"] = failure_rec.id
    # Track correction in user model
    if _user_model:
        git_info = detect_git_info()
        proj = git_info.get("project", "")
        # Record the wrong thing as a correction topic (we were wrong about it)
        _user_model.record_correction_on_topic(topic=wrong[:100], project=proj)
        # Record the right thing as exposure (user now knows this)
        _user_model.record_exposure(topic=right[:100], project=proj, explained=True)
    auto_result = _try_auto_consolidate()
    if auto_result:
        result["auto_consolidation"] = auto_result
    return _add_protocol_hint("neurosync_correct", result)


def handle_status(params: dict[str, Any]) -> dict[str, Any]:
    # Only require _db — vectorstore and graph are optional (degraded mode)
    _require_init(_db)
    db_stats = _db.stats()
    vs_stats = _vs.stats() if _vs else {"healthy": False, "error": "ChromaDB unavailable"}
    result: dict[str, Any] = {
        "version": __version__,
        "database": db_stats,
        "vectorstore": vs_stats,
        "current_session": _current_session_id,
        "correction_count": _correction_count,
        "causal_links": _db.count_causal_links(),
        "failure_records": _db.count_failure_records(),
    }
    graph = _get_graph()
    if graph:
        try:
            result["graph"] = graph.stats()
            result["graph"]["healthy"] = True
        except Exception as e:
            result["graph"] = {"healthy": False, "error": str(e)}
    return result


def handle_theories(params: dict[str, Any]) -> dict[str, Any]:
    _require_init(_semantic, _hierarchy)
    action = params.get("action", "list")
    if action == "graph":
        theory_id = params.get("theory_id")
        if not theory_id:
            return {"error": "theory_id required for graph action"}
        subtree = _hierarchy.get_subtree(theory_id)
        if not subtree:
            return {"error": f"Theory {theory_id} not found"}
        return {"subtree": subtree}
    if action == "detail":
        theory_id = params.get("theory_id")
        if not theory_id:
            return {"error": "theory_id required for detail action"}
        theory = _semantic.get_theory(theory_id)
        if not theory:
            return {"error": f"Theory {theory_id} not found"}
        contradictions = _semantic.list_contradictions(theory_id=theory_id)
        return {
            "theory": {
                "id": theory.id,
                "content": theory.content,
                "scope": theory.scope,
                "scope_qualifier": theory.scope_qualifier,
                "confidence": theory.confidence,
                "confirmation_count": theory.confirmation_count,
                "contradiction_count": theory.contradiction_count,
                "first_observed": theory.first_observed,
                "last_confirmed": theory.last_confirmed,
                "active": theory.active,
                "source_episodes": theory.source_episodes,
                "validation_status": theory.validation_status,
                "application_count": theory.application_count,
                "parent_theory_id": theory.parent_theory_id,
                "related_theories": theory.related_theories,
            },
            "contradictions": [
                {"id": c.id, "description": c.description, "resolved_at": c.resolved_at}
                for c in contradictions
            ],
        }
    elif action == "retire":
        theory_id = params.get("theory_id")
        if not theory_id:
            return {"error": "theory_id required for retire action"}
        theory = _semantic.retire_theory(theory_id)
        if not theory:
            return {"error": f"Theory {theory_id} not found"}
        return {"message": f"Theory {theory_id} retired", "theory_id": theory_id}
    elif action == "relate":
        theory_id = params.get("theory_id")
        related_ids = params.get("related_ids", [])
        if not theory_id:
            return {"error": "theory_id required for relate action"}
        if not related_ids:
            return {"error": "related_ids required for relate action"}
        result = _semantic.link_theories(theory_id, related_ids)
        if not result:
            return {"error": f"Theory {theory_id} not found"}
        return {
            "message": f"Linked {len(related_ids)} theories to {theory_id}",
            "theory_id": theory_id,
            "related_theories": result.related_theories,
        }
    else:
        # list
        scope = params.get("scope")
        project = params.get("project")
        limit = params.get("limit", 20)
        theories = _semantic.list_theories(scope=scope, project=project, limit=limit)
        return {
            "theories": [
                {
                    "id": t.id,
                    "content": t.content[:200],
                    "scope": t.scope,
                    "confidence": t.confidence,
                    "active": t.active,
                    "validation_status": t.validation_status,
                }
                for t in theories
            ],
            "count": len(theories),
        }


def handle_consolidate(params: dict[str, Any]) -> dict[str, Any]:
    _require_init(_episodic, _db)
    dry_run = params.get("dry_run", False)
    pending = _db.count_episodes(consolidated=0)
    if pending < 5:
        return {
            "message": f"Not enough episodes to consolidate ({pending}/5 minimum)",
            "pending_episodes": pending,
        }
    if dry_run:
        return {
            "message": f"Dry run: {pending} episodes ready for consolidation",
            "pending_episodes": pending,
        }
    try:
        from neurosync.consolidation import ConsolidationEngine

        engine = ConsolidationEngine(_db, _vs, _episodic, _semantic)
        result = engine.run(project=params.get("project"), dry_run=False)
        # Run forgetting pass after manual consolidation
        if _forgetting:
            try:
                forget_result = _forgetting.run_forgetting_pass()
                result["forgetting"] = forget_result
            except Exception:
                logger.debug("Forgetting pass failed after consolidation", exc_info=True)
        return result
    except ImportError:
        return {
            "message": "Consolidation engine not yet available",
            "pending_episodes": pending,
        }


def handle_handoff(params: dict[str, Any]) -> dict[str, Any]:
    _require_init(_episodic)
    goal = params.get("goal", "")
    accomplished = params.get("accomplished", "")
    remaining = params.get("remaining", "")
    next_step = params.get("next_step", "")
    blockers = params.get("blockers", "")
    if not all([goal.strip(), accomplished.strip(), remaining.strip(), next_step.strip()]):
        return {"error": "goal, accomplished, remaining, and next_step are all required"}
    session_id = _ensure_session()
    episode = _episodic.record_continuation(
        session_id=session_id,
        goal=goal,
        accomplished=accomplished,
        remaining=remaining,
        next_step=next_step,
        blockers=blockers,
    )
    return _add_protocol_hint(
        "neurosync_handoff",
        {
            "episode_id": episode.id,
            "signal_weight": episode.signal_weight,
            "message": "Handoff recorded. Next session will see this as continuation context.",
        },
    )


def handle_graph(params: dict[str, Any]) -> dict[str, Any]:
    _require_init(_config)
    action = params.get("action", "status")
    graph = _get_graph()

    if not graph:
        return {
            "error": "Neo4j graph not available. Install with: pip install neurosync[neo4j] "
            "and ensure Neo4j is running.",
        }

    if action == "status":
        try:
            stats = graph.stats()
            stats["healthy"] = True
            return stats
        except Exception as e:
            return {"healthy": False, "error": str(e)}

    elif action == "prebuilt":
        prebuilt_name = params.get("prebuilt_name")
        if not prebuilt_name:
            # Return catalog
            catalog = graph.get_prebuilt_queries()
            return {
                "queries": {name: info["description"] for name, info in catalog.items()},
            }
        catalog = graph.get_prebuilt_queries()
        if prebuilt_name not in catalog:
            return {"error": f"Unknown pre-built query: {prebuilt_name}"}
        query_info = catalog[prebuilt_name]
        cypher = query_info["cypher"]
        query_params = params.get("parameters", {})
        results = graph.run_cypher(cypher, query_params)
        return {
            "query": prebuilt_name,
            "description": query_info["description"],
            "results": results,
        }

    elif action == "sync":
        _require_init(_db)
        project = params.get("project")
        result = graph.sync(_db, project=project)
        return result

    elif action == "query":
        cypher = params.get("cypher", "")
        if not cypher.strip():
            return {"error": "cypher parameter is required for query action"}
        from neurosync.graph import _is_write_query

        if _is_write_query(cypher):
            return {
                "error": "Write queries are not allowed via the MCP tool. "
                "Use sync action or Neo4j Browser for writes."
            }
        query_params = params.get("parameters", {})
        results = graph.run_cypher(cypher, query_params)
        return {"results": results}

    else:
        return {"error": f"Unknown action: {action}. Use: query, sync, prebuilt, status"}


_HANDLERS = {
    "neurosync_recall": handle_recall,
    "neurosync_record": handle_record,
    "neurosync_remember": handle_remember,
    "neurosync_query": handle_query,
    "neurosync_correct": handle_correct,
    "neurosync_status": handle_status,
    "neurosync_theories": handle_theories,
    "neurosync_consolidate": handle_consolidate,
    "neurosync_handoff": handle_handoff,
    "neurosync_graph": handle_graph,
}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 protocol over stdio
# ---------------------------------------------------------------------------


def _send(msg: dict[str, Any]) -> None:
    """Send a JSON-RPC message to stdout."""
    data = json.dumps(msg)
    sys.stdout.write(data + "\n")
    sys.stdout.flush()


def _error_response(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _success_response(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _handle_request(request: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Process a single JSON-RPC request."""
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "initialize":
        return _success_response(
            req_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "neurosync",
                    "version": __version__,
                },
            },
        )

    if method == "notifications/initialized":
        return None  # Notification, no response

    if method == "tools/list":
        return _success_response(req_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        handler = _HANDLERS.get(tool_name)
        if not handler:
            return _error_response(req_id, -32601, f"Unknown tool: {tool_name}")
        try:
            _init()
            result = handler(tool_args)
            return _success_response(
                req_id,
                {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                },
            )
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("Error in %s: %s", tool_name, tb)
            return _success_response(
                req_id,
                {
                    "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                    "isError": True,
                },
            )

    if method == "ping":
        return _success_response(req_id, {})

    # Unknown method
    if req_id is not None:
        return _error_response(req_id, -32601, f"Method not found: {method}")
    return None


def serve() -> None:
    """Run the MCP server on stdio."""
    configure_logging()
    logger.info("NeuroSync MCP server starting on stdio...")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            _send(_error_response(None, -32700, "Parse error"))
            continue
        response = _handle_request(request)
        if response is not None:
            _send(response)


if __name__ == "__main__":
    serve()
