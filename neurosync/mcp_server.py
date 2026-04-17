"""MCP JSON-RPC 2.0 stdio server — 9 tools for NeuroSync memory system."""

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
from neurosync.semantic import SemanticMemory
from neurosync.vectorstore import VectorStore
from neurosync.version import __version__
from neurosync.working import WorkingMemory

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
                "project": {"type": "string", "description": "Project name (auto-detected from git if omitted)"},
                "branch": {"type": "string", "description": "Branch name (auto-detected from git if omitted)"},
                "context": {"type": "string", "description": "Additional context for retrieval"},
                "max_tokens": {"type": "integer", "description": "Max output tokens (default 500)", "default": 500},
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
                            "effect": {"type": "string", "description": "What resulted from this event"},
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
                "type": {"type": "string", "description": "Event type (default: explicit)", "default": "explicit"},
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
                "scope": {"type": "string", "enum": ["all", "episodes", "theories"], "default": "all"},
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
                "accomplished": {"type": "string", "description": "What was accomplished this session"},
                "remaining": {"type": "string", "description": "What still needs to be done"},
                "next_step": {"type": "string", "description": "Concrete next step for the next session"},
                "blockers": {"type": "string", "description": "Any blockers or open questions"},
            },
            "required": ["goal", "accomplished", "remaining", "next_step"],
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
_working: Optional[WorkingMemory] = None
_analogy: Optional[AnalogyEngine] = None
_causal: Optional[CausalGraph] = None
_failure: Optional[FailureModel] = None
_forgetting: Optional[ForgettingEngine] = None
_hierarchy: Optional[TheoryHierarchy] = None
_current_session_id: Optional[str] = None
_correction_count: int = 0
_git_observer: Optional[GitObserver] = None


def _init() -> None:
    global _config, _db, _vs, _episodic, _semantic, _working
    global _analogy, _causal, _failure, _forgetting, _hierarchy
    if _db is not None:
        return

    config = NeuroSyncConfig.load()
    config.ensure_dirs()
    configure_logging()

    # Database is essential — failure here is fatal
    db = Database(config)

    # VectorStore is optional — failure means degraded mode
    vs = None
    try:
        vs = VectorStore(config)
    except Exception:
        logger.warning("ChromaDB unavailable, running in degraded mode (no vector search)", exc_info=True)

    # Build engines — they accept Optional[VectorStore]
    episodic = EpisodicMemory(db, vs)
    semantic = SemanticMemory(db, vs)
    working = WorkingMemory(db, vs)
    analogy = AnalogyEngine(db, vs) if vs else None
    causal = CausalGraph(db, vs)
    failure = FailureModel(db, vs)
    forgetting = ForgettingEngine(db, vs)
    hierarchy = TheoryHierarchy(db, vs)

    # Atomic commit — all or nothing
    _config = config
    _db = db
    _vs = vs
    _episodic = episodic
    _semantic = semantic
    _working = working
    _analogy = analogy
    _causal = causal
    _failure = failure
    _forgetting = forgetting
    _hierarchy = hierarchy


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


def _try_auto_consolidate() -> Optional[dict]:
    """Run auto-consolidation if enabled and threshold is met. Returns result or None."""
    if _config and _config.auto_consolidation_enabled and _db and _vs and _episodic and _semantic:
        return maybe_consolidate(
            _db, _vs, _episodic, _semantic,
            threshold=_config.auto_consolidation_threshold,
            min_episodes=_config.consolidation_min_episodes,
        )
    return None


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def handle_recall(params: dict[str, Any]) -> dict[str, Any]:
    _require_init(_working, _failure, _hierarchy)
    git_info = detect_git_info()
    project = params.get("project") or git_info.get("project", "")
    branch = params.get("branch") or git_info.get("branch", "")
    context = params.get("context", "")
    max_tokens = params.get("max_tokens", 500)
    result = _working.recall(
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
        episode = _episodic.record_episode(
            session_id=session_id,
            event_type=event_type,
            content=event.get("content", ""),
            files_touched=event.get("files", []),
            layers_touched=event.get("layers", []),
            cause=event.get("cause", ""),
            effect=event.get("effect", ""),
            reasoning=event.get("reasoning", ""),
            importance=event.get("importance", 0),
        )
        recorded.append(episode.id)
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


def handle_remember(params: dict[str, Any]) -> dict[str, Any]:
    _require_init(_episodic)
    content = params.get("content", "")
    event_type = params.get("type", "explicit")
    if not content.strip():
        return {"error": "Content is required"}
    session_id = _ensure_session()
    episode = _episodic.record_explicit(
        session_id=session_id,
        content=content,
        event_type=event_type,
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
            return {"mode": "analogy", "results": [], "warning": "Analogy engine unavailable (no vector search)"}
        analogies = _analogy.find_analogies(query, n_results=limit)
        return {"mode": "analogy", "results": analogies}

    if mode == "causal":
        neighborhood = _causal.get_causal_neighborhood(query)
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
    global _correction_count
    _require_init(_episodic, _semantic, _failure)
    wrong = params.get("wrong", "")
    right = params.get("right", "")
    theory_id = params.get("theory_id")
    if not wrong.strip() or not right.strip():
        return {"error": "Both 'wrong' and 'right' are required"}
    _correction_count += 1
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
    auto_result = _try_auto_consolidate()
    if auto_result:
        result["auto_consolidation"] = auto_result
    return _add_protocol_hint("neurosync_correct", result)


def handle_status(params: dict[str, Any]) -> dict[str, Any]:
    _require_init(_db, _vs)
    db_stats = _db.stats()
    vs_stats = _vs.stats()
    return {
        "version": __version__,
        "database": db_stats,
        "vectorstore": vs_stats,
        "current_session": _current_session_id,
        "correction_count": _correction_count,
        "causal_links": _db.count_causal_links(),
        "failure_records": _db.count_failure_records(),
    }


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
    return _add_protocol_hint("neurosync_handoff", {
        "episode_id": episode.id,
        "signal_weight": episode.signal_weight,
        "message": "Handoff recorded. Next session will see this as continuation context.",
    })


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
        return _success_response(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {
                "name": "neurosync",
                "version": __version__,
            },
        })

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
            return _success_response(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
            })
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("Error in %s: %s", tool_name, tb)
            return _success_response(req_id, {
                "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                "isError": True,
            })

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
