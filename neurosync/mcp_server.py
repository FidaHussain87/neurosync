"""MCP JSON-RPC 2.0 stdio server — 8 tools for NeuroSync memory system."""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Optional

from neurosync.config import NeuroSyncConfig, detect_git_info
from neurosync.db import Database
from neurosync.episodic import EpisodicMemory
from neurosync.models import EPISODE_TYPES
from neurosync.semantic import SemanticMemory
from neurosync.vectorstore import VectorStore
from neurosync.working import WorkingMemory

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
            "with events that happened during the session."
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
            "Use when the user says 'remember this' or equivalent."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "What to remember"},
                "type": {"type": "string", "description": "Event type (default: explicit)", "default": "explicit"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "neurosync_query",
        "description": "Semantic search across episodes and/or theories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "scope": {"type": "string", "enum": ["all", "episodes", "theories"], "default": "all"},
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
        "description": "Browse, inspect, or retire theories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "detail", "retire"], "default": "list"},
                "scope": {"type": "string", "enum": ["project", "domain", "craft"]},
                "project": {"type": "string"},
                "theory_id": {"type": "string"},
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
]

# ---------------------------------------------------------------------------
# Server state
# ---------------------------------------------------------------------------

_config: Optional[NeuroSyncConfig] = None
_db: Optional[Database] = None
_vs: Optional[VectorStore] = None
_episodic: Optional[EpisodicMemory] = None
_semantic: Optional[SemanticMemory] = None
_working: Optional[WorkingMemory] = None
_current_session_id: Optional[str] = None
_correction_count: int = 0


def _init() -> None:
    global _config, _db, _vs, _episodic, _semantic, _working
    if _db is not None:
        return
    _config = NeuroSyncConfig.load()
    _config.ensure_dirs()
    _db = Database(_config)
    _vs = VectorStore(_config)
    _episodic = EpisodicMemory(_db, _vs)
    _semantic = SemanticMemory(_db, _vs)
    _working = WorkingMemory(_db, _vs)


def _ensure_session(project: str = "", branch: str = "") -> str:
    global _current_session_id
    if _current_session_id:
        return _current_session_id
    assert _episodic is not None
    git_info = detect_git_info()
    project = project or git_info.get("project", "")
    branch = branch or git_info.get("branch", "")
    session = _episodic.start_session(project=project, branch=branch)
    _current_session_id = session.id
    return session.id


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def handle_recall(params: dict[str, Any]) -> dict[str, Any]:
    assert _working is not None
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
        return {"message": "No memories yet. Start working and record episodes to build memory."}
    return result


def handle_record(params: dict[str, Any]) -> dict[str, Any]:
    assert _episodic is not None
    events = params.get("events", [])
    summary = params.get("session_summary", "")
    project = params.get("project", "")
    branch = params.get("branch", "")
    session_id = _ensure_session(project=project, branch=branch)
    recorded = []
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
        )
        recorded.append(episode.id)
    # Handle explicit_remember items
    for item in params.get("explicit_remember", []):
        episode = _episodic.record_explicit(session_id=session_id, content=item)
        recorded.append(episode.id)
    if summary:
        _episodic.end_session(session_id, summary=summary)
    return {
        "session_id": session_id,
        "episodes_recorded": len(recorded),
        "episode_ids": recorded,
    }


def handle_remember(params: dict[str, Any]) -> dict[str, Any]:
    assert _episodic is not None
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
    return {
        "episode_id": episode.id,
        "signal_weight": episode.signal_weight,
        "message": f"Remembered with signal weight {episode.signal_weight}",
    }


def handle_query(params: dict[str, Any]) -> dict[str, Any]:
    assert _episodic is not None and _semantic is not None
    query = params.get("query", "")
    scope = params.get("scope", "all")
    project = params.get("project")
    limit = params.get("limit", 10)
    if not query.strip():
        return {"error": "Query is required"}
    results: dict[str, Any] = {}
    if scope in ("all", "episodes"):
        results["episodes"] = _episodic.search(query, n_results=limit, project=project)
    if scope in ("all", "theories"):
        results["theories"] = _semantic.search(query, n_results=limit)
    return results


def handle_correct(params: dict[str, Any]) -> dict[str, Any]:
    global _correction_count
    assert _episodic is not None and _semantic is not None
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
    return result


def handle_status(params: dict[str, Any]) -> dict[str, Any]:
    assert _db is not None and _vs is not None
    db_stats = _db.stats()
    vs_stats = _vs.stats()
    return {
        "database": db_stats,
        "vectorstore": vs_stats,
        "current_session": _current_session_id,
        "correction_count": _correction_count,
    }


def handle_theories(params: dict[str, Any]) -> dict[str, Any]:
    assert _semantic is not None
    action = params.get("action", "list")
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
                }
                for t in theories
            ],
            "count": len(theories),
        }


def handle_consolidate(params: dict[str, Any]) -> dict[str, Any]:
    # Full implementation in Phase 2 — for now return status of unconsolidated episodes
    assert _episodic is not None and _db is not None
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
    # Phase 2 will implement full consolidation
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


_HANDLERS = {
    "neurosync_recall": handle_recall,
    "neurosync_record": handle_record,
    "neurosync_remember": handle_remember,
    "neurosync_query": handle_query,
    "neurosync_correct": handle_correct,
    "neurosync_status": handle_status,
    "neurosync_theories": handle_theories,
    "neurosync_consolidate": handle_consolidate,
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
                "version": "0.1.0",
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
            sys.stderr.write(f"Error in {tool_name}: {tb}\n")
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
    sys.stderr.write("NeuroSync MCP server starting on stdio...\n")
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
