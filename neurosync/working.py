"""Layer 3: Working memory — utility functions for recall context assembly."""

from __future__ import annotations

from typing import Any, Optional

from neurosync.models import Theory

_encoder: Optional[Any] = None
_encoder_loaded: bool = False


def _get_encoder() -> Optional[Any]:
    """Lazy-load tiktoken encoder (cl100k_base). Returns None if unavailable."""
    global _encoder, _encoder_loaded
    if _encoder_loaded:
        return _encoder
    _encoder_loaded = True
    try:
        import tiktoken

        _encoder = tiktoken.get_encoding("cl100k_base")
    except (ImportError, Exception):
        _encoder = None
    return _encoder


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
    """Estimate token count using tiktoken (cl100k_base) with char-based fallback."""
    enc = _get_encoder()
    if enc is not None:
        return max(1, len(enc.encode(text)))
    return max(1, len(text) // 4)
