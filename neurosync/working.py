"""Layer 3: Working memory — utility functions for recall context assembly."""

from __future__ import annotations

from typing import Any

from neurosync.models import Theory


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
