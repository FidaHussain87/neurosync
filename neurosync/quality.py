"""Episode quality scoring — feedback loop for episode content quality."""

from __future__ import annotations

import re
from typing import Optional

# Patterns indicating causal language
_CAUSAL_PATTERNS = re.compile(
    r"\b(because|so that|therefore|since|as a result|due to|in order to|caused by|leads to)\b",
    re.IGNORECASE,
)

# Patterns indicating decision/reasoning language
_REASONING_PATTERNS = re.compile(
    r"\b(decided|chose|instead of|opted for|preferred|trade-?off|alternative|approach)\b",
    re.IGNORECASE,
)

# Patterns indicating file/module references
_FILE_PATTERNS = re.compile(
    r"(\w+\.py\b|\w+\.pm\b|\w+\.pl\b|\w+\.t\b|\w+::\w+)",
)

# Patterns indicating activity log (low quality)
_ACTIVITY_LOG_PATTERNS = re.compile(
    r"^(Edited|Changed|Modified|Updated|Created|Deleted|Removed|Added|Moved|Renamed)\b",
)


def score_episode_quality(content: str) -> int:
    """Score episode content quality from 0-7.

    Higher scores indicate more useful episodes for consolidation.
    """
    score = 0

    # Has causal language (+2)
    if _CAUSAL_PATTERNS.search(content):
        score += 2

    # Has file/module references (+1)
    if _FILE_PATTERNS.search(content):
        score += 1

    # Content length checks
    content_len = len(content)
    if content_len > 50:
        score += 1
    if content_len > 200:
        score += 1
    # Penalize verbosity
    if content_len > 500:
        score -= 1

    # Has decision/reasoning language (+1)
    if _REASONING_PATTERNS.search(content):
        score += 1

    # Is NOT activity log (+1)
    if not _ACTIVITY_LOG_PATTERNS.match(content.strip()):
        score += 1

    return max(0, score)


def quality_warning(score: int, threshold: int = 3) -> Optional[str]:
    """Return a warning message if quality is below threshold, else None."""
    if score >= threshold:
        return None
    return (
        f"Episode quality score {score}/{threshold}. "
        "Tip: Include causal language (because, so that), "
        "file references, and reasoning — not just activity descriptions."
    )
