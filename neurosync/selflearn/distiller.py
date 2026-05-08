"""Imperative distiller: compresses verbose theories to minimal actionable rules."""

from __future__ import annotations

import hashlib
import re
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from neurosync.logging import get_logger

if TYPE_CHECKING:
    from neurosync.db import Database

logger = get_logger("selflearn.distiller")

# Regex patterns to extract imperative sentences from theory text.
# Ordered by specificity — more explicit imperatives first.
_IMPERATIVE_PATTERNS: list[re.Pattern[str]] = [
    # "Always X" / "Never Y" / "Do X" / "Don't X" / "Use X" / "Avoid X"
    re.compile(
        r"(?:^|\.\s+|\n)"
        r"((?:Always|Never|Do\b|Don't|Avoid|Use\b|Prefer|Ensure|"
        r"Return|Raise|Set|Call|Check|Verify|Handle|Keep|Make sure)[^.!?\n]{10,120})",
        re.IGNORECASE,
    ),
    # Sentences containing "must", "should", "must not"
    re.compile(
        r"(?:^|\.\s+|\n)"
        r"([^.!?\n]{5,120}(?:\bmust\b|\bshould\b|\bmust not\b)[^.!?\n]{0,80})",
        re.IGNORECASE,
    ),
    # "X → Y" causal rules
    re.compile(r"([^\n.!?]{5,80}→[^\n.!?]{5,80})"),
]

# Minimum Jaccard word-overlap required between distilled and original.
# Jaccard(A, B) = |A ∩ B| / |A ∪ B| on word sets.
_MIN_SIMILARITY = 0.15  # distilled text must share ≥15% vocabulary with source

# Maximum characters in distilled output (~80 tokens ≈ 320 chars at 4 chars/token)
_MAX_DISTILLED_CHARS = 320


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _distilled_id(theory_id: str) -> str:
    ts = _utcnow()
    return hashlib.sha256(f"distilled:{theory_id}:{ts}".encode()).hexdigest()[:24]


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: 4 characters per token."""
    return max(1, len(text) // 4)


def _extract_imperatives(text: str) -> list[str]:
    """Extract imperative sentences from theory content using regex patterns."""
    candidates: list[str] = []
    seen: set[str] = set()

    for pattern in _IMPERATIVE_PATTERNS:
        for m in pattern.finditer(text):
            sentence = m.group(1).strip().rstrip(".,;")
            # Normalise whitespace
            sentence = re.sub(r"\s+", " ", sentence)
            key = sentence.lower()[:60]
            if key not in seen and len(sentence) >= 15:
                seen.add(key)
                candidates.append(sentence)

    return candidates


def _compress_to_budget(sentences: list[str], max_chars: int) -> str:
    """Greedily join extracted sentences until char budget exhausted."""
    parts: list[str] = []
    used = 0
    for s in sentences:
        entry = s if not parts else f" | {s}"
        if used + len(entry) > max_chars and parts:
            break
        parts.append(s)
        used += len(entry)
    return " | ".join(parts)


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Compute Jaccard similarity on lowercase word sets."""
    words_a = set(re.findall(r"\b\w{3,}\b", text_a.lower()))
    words_b = set(re.findall(r"\b\w{3,}\b", text_b.lower()))
    if not words_a or not words_b:
        return 0.0
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    return intersection / union if union > 0 else 0.0


class Distiller:
    """Compresses verbose theory text to minimal imperative format.

    Process:
    1. Extract imperative sentences via regex.
    2. Compress to ≤ _MAX_DISTILLED_CHARS greedily.
    3. Validate Jaccard word-overlap ≥ _MIN_SIMILARITY with original.
    4. If overlap too low or no imperatives found, fall back to first sentence.
    5. Store in distilled_knowledge table.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        # Prevents concurrent threads from re-distilling the same theory simultaneously
        self._distill_lock = threading.Lock()

    def distill_theory(self, theory_id: str, content: str) -> dict | None:
        """Distill a theory and persist it. Returns the distilled record or None.

        Returns None if:
        - Content is already short enough (≤ _MAX_DISTILLED_CHARS).
        - Similarity validation fails with no valid fallback.
        """
        original_tokens = _estimate_tokens(content)

        # Already compact — no distillation needed
        if len(content) <= _MAX_DISTILLED_CHARS:
            return None

        imperatives = _extract_imperatives(content)

        if imperatives:
            distilled = _compress_to_budget(imperatives, _MAX_DISTILLED_CHARS)
        else:
            # Fallback: take the first sentence
            first = re.split(r"[.!?]", content)[0].strip()
            distilled = first[:_MAX_DISTILLED_CHARS]

        if not distilled:
            return None

        # Validate word-overlap similarity
        similarity = _jaccard_similarity(content, distilled)
        if similarity < _MIN_SIMILARITY:
            # Overlap too low — try a longer fallback (first 2 sentences)
            sentences = re.split(r"[.!?]", content)
            fallback = ". ".join(s.strip() for s in sentences[:2] if s.strip())[:_MAX_DISTILLED_CHARS]
            if fallback and fallback != distilled:
                similarity2 = _jaccard_similarity(content, fallback)
                if similarity2 >= _MIN_SIMILARITY:
                    distilled = fallback
                    similarity = similarity2
                else:
                    logger.debug(
                        "Distillation rejected for theory %s (similarity %.2f < %.2f)",
                        theory_id,
                        similarity2,
                        _MIN_SIMILARITY,
                    )
                    return None
            else:
                return None

        distilled_tokens = _estimate_tokens(distilled)
        compression_ratio = (
            1.0 - distilled_tokens / original_tokens if original_tokens > 0 else 0.0
        )
        did = _distilled_id(theory_id)

        self._db.insert_distilled(
            distilled_id=did,
            source_theory_id=theory_id,
            distilled_content=distilled,
            original_tokens=original_tokens,
            distilled_tokens=distilled_tokens,
            compression_ratio=round(compression_ratio, 4),
            similarity_score=round(similarity, 4),
            distilled_at=_utcnow(),
        )

        return {
            "id": did,
            "source_theory_id": theory_id,
            "distilled_content": distilled,
            "original_tokens": original_tokens,
            "distilled_tokens": distilled_tokens,
            "compression_ratio": round(compression_ratio, 4),
            "similarity_score": round(similarity, 4),
        }

    def get_or_distill(self, theory_id: str, content: str) -> str:
        """Return distilled content if available and active, otherwise distill and return.

        Falls back to the original content if distillation is not possible.
        Thread-safe: the lock prevents two threads from simultaneously distilling
        the same theory and writing duplicate entries.
        """
        # Fast path: already distilled (no lock needed for read-only check)
        existing = self._db.get_distilled_for_theory(theory_id)
        if existing and existing.get("active"):
            self._db.increment_distilled_recall(existing["id"], positive=True)
            return existing["distilled_content"]

        # Slow path: needs distillation — serialize to prevent concurrent duplicates
        with self._distill_lock:
            # Re-check under lock (another thread may have distilled while we waited)
            existing = self._db.get_distilled_for_theory(theory_id)
            if existing and existing.get("active"):
                self._db.increment_distilled_recall(existing["id"], positive=True)
                return existing["distilled_content"]

            result = self.distill_theory(theory_id, content)
            if result:
                return result["distilled_content"]
        return content

