"""Cognitive Lensing Protocol: transform verbose knowledge into minimal-token imperative lenses."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neurosync.models import Episode, FailureRecord, Theory


# --- Regex patterns for imperative extraction ---

_NEGATION_RE = re.compile(
    r"\b(never|don'?t|do not|must not|should not|shouldn'?t|avoid|prohibit)\b",
    re.IGNORECASE,
)

_REQUIREMENT_RE = re.compile(
    r"\b(must|always|require|shall|need to|have to|mandatory)\b",
    re.IGNORECASE,
)

_PREFERENCE_RE = re.compile(
    r"\b(prefer|better to|should|recommend|favor|opt for|default to)\b",
    re.IGNORECASE,
)

_WARNING_RE = re.compile(
    r"\b(warning|caution|careful|beware|watch out|risky|danger|pitfall)\b",
    re.IGNORECASE,
)

# Patterns indicating project-specific content
_PROJECT_SPECIFIC_RE = re.compile(
    r"(/[\w/]+\.\w+|[\w_]+\.py|[\w_]+\.ts|[\w_]+\.pm|src/|lib/|tests?/|config/)",
    re.IGNORECASE,
)

# Patterns indicating common/generic best practices
_COMMON_PRACTICE_RE = re.compile(
    r"\b(validate input|use transactions?|handle errors?|write tests?|"
    r"add logging|use type hints?|follow conventions?|keep it simple|DRY|SOLID)\b",
    re.IGNORECASE,
)

# Extract action from content
_ACTION_EXTRACT_RE = re.compile(
    r"(?:should|must|always|never|prefer|avoid|default to)\s+(.+?)(?:\.|$|;|\n)",
    re.IGNORECASE,
)

# Extract context/trigger from content
_CONTEXT_EXTRACT_RE = re.compile(
    r"(?:when|if|for|in|during|while|after|before)\s+(.+?)(?:,|:|;|\s+(?:should|must|always|never|prefer|avoid))",
    re.IGNORECASE,
)


# --- Data Models ---


@dataclass
class Lens:
    """A minimal-token behavioral modification unit."""

    id: str
    context: str
    imperative: str
    confidence: float
    scope: str
    source_type: str
    token_cost: int
    behavioral_impact: float
    prior_alignment: float

    def format(self) -> str:
        """Format as compact lens string."""
        if self.scope:
            return f"{self.context} -> {self.imperative} | {self.scope}"
        return f"{self.context} -> {self.imperative}"


@dataclass
class LensSet:
    """Optimized set of lenses for a given token budget."""

    lenses: list[Lens] = field(default_factory=list)
    drift_warnings: list[str] = field(default_factory=list)
    total_tokens: int = 0
    total_impact: float = 0.0
    budget_used: float = 0.0


# --- Token Estimation ---


def estimate_lens_tokens(text: str) -> int:
    """Rough token estimate: 1 token ~ 4 chars for imperative format."""
    return max(1, len(text) // 4)


# --- Epistemic Delta Encoding ---


def compute_prior_alignment(theory: Theory) -> float:
    """Compute how much this theory aligns with LLM priors.

    High value = LLM already knows this (don't waste tokens).
    Low value = LLM's default is wrong (MUST surface).
    """
    total = theory.confirmation_count + theory.contradiction_count
    if total == 0:
        return 0.5
    return 1.0 - (theory.contradiction_count / max(total, 1))


def is_llm_prior_novel(theory: Theory) -> float:
    """Estimate how much this deviates from typical LLM behavior.

    Returns 0.0 (completely novel to LLM) to 1.0 (LLM already knows this).
    """
    content = theory.content

    # High contradiction count = LLM keeps getting it wrong
    if theory.contradiction_count >= 3:
        return 0.1

    # Common best practice the LLM already knows (check first — strongest signal)
    if _COMMON_PRACTICE_RE.search(content):
        return 0.8

    # Contains NEVER/ALWAYS overrides = likely project-specific
    if _NEGATION_RE.search(content) or _REQUIREMENT_RE.search(content):
        # If also project-specific, even more novel
        if _PROJECT_SPECIFIC_RE.search(content):
            return 0.2
        return 0.3

    # Contains project-specific file paths or names
    if _PROJECT_SPECIFIC_RE.search(content):
        return 0.2

    # Default: moderate novelty
    return 0.5


# --- Imperative Compression ---


def _extract_verb(content: str) -> str:
    """Determine the imperative verb from content."""
    if _NEGATION_RE.search(content):
        return "NEVER"
    if _REQUIREMENT_RE.search(content):
        return "MUST"
    if _WARNING_RE.search(content):
        return "AVOID"
    if _PREFERENCE_RE.search(content):
        return "PREFER"
    return "DEFAULT"


def _extract_action(content: str) -> str:
    """Extract the core action from verbose content."""
    match = _ACTION_EXTRACT_RE.search(content)
    if match:
        action = match.group(1).strip()
        # Truncate to reasonable length
        if len(action) > 80:
            action = action[:77] + "..."
        return action
    # Fallback: use first sentence, truncated
    first_sentence = content.split(".")[0].strip()
    if len(first_sentence) > 80:
        first_sentence = first_sentence[:77] + "..."
    return first_sentence


def _extract_context(content: str) -> str:
    """Extract the trigger context from content."""
    match = _CONTEXT_EXTRACT_RE.search(content)
    if match:
        ctx = match.group(1).strip()
        if len(ctx) > 40:
            ctx = ctx[:37] + "..."
        return ctx
    return "general"


def _extract_scope(theory: Theory) -> str:
    """Extract scope from theory metadata."""
    if theory.scope_qualifier:
        return theory.scope_qualifier
    return theory.scope


def compress_theory(theory: Theory) -> Lens:
    """Transform a verbose theory into a minimal imperative lens."""
    verb = _extract_verb(theory.content)
    action = _extract_action(theory.content)
    context = _extract_context(theory.content)
    scope = _extract_scope(theory)
    imperative = f"{verb} {action}"
    prior = compute_prior_alignment(theory)
    novelty = is_llm_prior_novel(theory)

    # Behavioral impact: higher when novel and high confidence
    p_mistake = 1.0 - theory.confidence
    cost = 3.0 * (1.0 + math.log(max(theory.application_count, 1)))
    impact = p_mistake * cost * (1.0 - prior)

    lens_text = f"{context} -> {imperative}"
    if scope and scope not in ("craft", "project", "domain"):
        lens_text += f" | {scope}"

    return Lens(
        id=theory.id,
        context=context,
        imperative=imperative,
        confidence=theory.confidence,
        scope=scope,
        source_type="theory",
        token_cost=estimate_lens_tokens(lens_text),
        behavioral_impact=impact,
        prior_alignment=novelty,
    )


def compress_failure(failure: FailureRecord) -> Lens:
    """Transform a failure record into a NEVER/AVOID lens."""
    what_failed = failure.what_failed
    if len(what_failed) > 60:
        what_failed = what_failed[:57] + "..."

    if failure.what_worked:
        what_worked = failure.what_worked
        if len(what_worked) > 60:
            what_worked = what_worked[:57] + "..."
        imperative = f"NEVER {what_failed}; PREFER {what_worked}"
    else:
        imperative = f"AVOID {what_failed}"

    context = failure.context or failure.category
    if len(context) > 40:
        context = context[:37] + "..."

    scope = failure.project or "general"

    # Failures are always novel (LLM doesn't know project failures)
    prior = 0.2

    # Impact: severity * log(occurrences) * novelty
    cost = failure.severity * (1.0 + math.log(max(failure.occurrence_count, 1)))
    p_mistake = 0.7  # failures have high recurrence probability
    impact = p_mistake * cost * (1.0 - prior)

    lens_text = f"{context} -> {imperative}"
    if scope != "general":
        lens_text += f" | {scope}"

    return Lens(
        id=str(failure.id) if failure.id is not None else "",
        context=context,
        imperative=imperative,
        confidence=0.8,
        scope=scope,
        source_type="failure",
        token_cost=estimate_lens_tokens(lens_text),
        behavioral_impact=impact,
        prior_alignment=prior,
    )


def compress_correction(content: str, what_wrong: str, what_right: str) -> Lens:
    """Transform a correction into a NEVER/MUST lens pair."""
    if len(what_wrong) > 50:
        what_wrong = what_wrong[:47] + "..."
    if len(what_right) > 50:
        what_right = what_right[:47] + "..."

    imperative = f"NEVER {what_wrong}; MUST {what_right}"
    context = _extract_context(content) if content else "general"

    lens_text = f"{context} -> {imperative}"

    # Corrections are maximally novel — LLM was explicitly wrong
    prior = 0.1

    # High impact: corrections are the strongest signal
    impact = 0.9 * 4.0 * (1.0 - prior)

    return Lens(
        id="",
        context=context,
        imperative=imperative,
        confidence=0.9,
        scope="project",
        source_type="correction",
        token_cost=estimate_lens_tokens(lens_text),
        behavioral_impact=impact,
        prior_alignment=prior,
    )


# --- Information Density Maximization ---


def optimize_lens_set(
    candidates: list[Lens],
    token_budget: int = 80,
    max_lenses: int = 10,
) -> LensSet:
    """Greedy fractional knapsack: select lenses maximizing impact per token.

    Sorts by beta/tau ratio (behavioral_impact / token_cost),
    fills until budget exhausted.
    """
    if not candidates:
        return LensSet()

    # Sort by impact-per-token ratio descending
    scored = sorted(
        candidates,
        key=lambda lens: lens.behavioral_impact / max(lens.token_cost, 1),
        reverse=True,
    )

    selected: list[Lens] = []
    total_tokens = 0
    total_impact = 0.0

    for lens in scored:
        if len(selected) >= max_lenses:
            break
        if total_tokens + lens.token_cost > token_budget:
            continue
        selected.append(lens)
        total_tokens += lens.token_cost
        total_impact += lens.behavioral_impact

    budget_used = total_tokens / max(token_budget, 1)

    return LensSet(
        lenses=selected,
        drift_warnings=[],
        total_tokens=total_tokens,
        total_impact=total_impact,
        budget_used=budget_used,
    )


# --- Drift Warnings ---


def detect_drift_warnings(
    theories: list[Theory],
    corrections: list[Episode] | None = None,
) -> list[str]:
    """Detect patterns where LLM defaults conflict with developer truth."""
    warnings: list[str] = []

    # Theories with high contradiction count
    for theory in theories:
        if theory.contradiction_count >= 2:
            action = _extract_action(theory.content)
            warnings.append(
                f"you default to contradicting: {action} "
                f"(contradicted {theory.contradiction_count}x)"
            )

    # Corrections that repeat
    if corrections:
        correction_texts: dict[str, int] = {}
        for ep in corrections:
            key = ep.content[:80]
            correction_texts[key] = correction_texts.get(key, 0) + 1
        for text, count in correction_texts.items():
            if count >= 2:
                short = text[:60] + "..." if len(text) > 60 else text
                warnings.append(f"repeated correction ({count}x): {short}")

    return warnings


# --- Full Pipeline ---


class CognitiveLens:
    """Main pipeline: theories + corrections + failures -> optimized LensSet."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def generate_lens_set(
        self,
        theories: list[Theory],
        failures: list[FailureRecord] | None = None,
        corrections: list[Episode] | None = None,
        token_budget: int = 80,
        context: str = "",
        files: list[str] | None = None,
        domains: list[str] | None = None,
    ) -> LensSet:
        """Full pipeline: compress -> score -> optimize -> return."""
        candidates: list[Lens] = []

        # Compress theories
        for theory in theories:
            if not theory.active:
                continue
            lens = compress_theory(theory)
            # Context filtering: boost relevance if matching files/domains
            if files and theory.scope_qualifier and any(
                theory.scope_qualifier in f for f in files
            ):
                lens.behavioral_impact *= 1.5
            candidates.append(lens)

        # Compress failures
        if failures:
            for failure in failures:
                lens = compress_failure(failure)
                # Boost if failure context matches current context
                if context and failure.context and context in failure.context:
                    lens.behavioral_impact *= 1.3
                candidates.append(lens)

        # Compress corrections
        if corrections:
            for episode in corrections:
                if episode.event_type != "correction":
                    continue
                # Parse correction format
                what_wrong, what_right = self._parse_correction(episode.content)
                if what_wrong or what_right:
                    lens = compress_correction(episode.content, what_wrong, what_right)
                    lens.id = episode.id
                    candidates.append(lens)

        # Filter out high prior_alignment lenses (LLM already knows)
        candidates = [c for c in candidates if c.prior_alignment < 0.75]

        # Optimize selection within budget
        lens_set = optimize_lens_set(candidates, token_budget, max_lenses=10)

        # Detect drift warnings
        lens_set.drift_warnings = detect_drift_warnings(theories, corrections)

        return lens_set

    @staticmethod
    def _parse_correction(content: str) -> tuple[str, str]:
        """Parse correction episode content into (what_wrong, what_right)."""
        # Format: "CORRECTION: Was told 'X' but correct is 'Y'"
        match = re.search(
            r"Was told '(.+?)' but correct (?:answer )?is '(.+?)'",
            content,
            re.DOTALL,
        )
        if match:
            return match.group(1).strip(), match.group(2).strip()

        # Fallback: "wrong: X / right: Y" style
        match = re.search(
            r"wrong:\s*(.+?)(?:\s*/\s*|\s+right:\s*)(.+?)(?:\.|$)",
            content,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip(), match.group(2).strip()

        # Last resort: use entire content as what_wrong
        if content:
            return content[:100], ""
        return "", ""
