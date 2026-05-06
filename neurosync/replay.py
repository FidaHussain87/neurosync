"""Cognitive Replay Engine — captures reasoning paths, not just conclusions.

Records the hypothesis→test→eliminate→realize chains developers follow when
debugging. When a structurally similar problem appears, surfaces the reasoning
*strategy* that worked — enabling "skip to step N" instead of re-deriving.

Zero LLM. Detection is event-flow-based (frustration→debugging→correction
triggers capture). Storage is ~300 bytes per replay skeleton.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from neurosync.models import Episode, _new_id, _utcnow

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

STEP_OUTCOMES = frozenset({"dead_end", "partial", "root_cause", "workaround"})

STRATEGY_TYPES = frozenset(
    {
        "elimination",  # tried A, B, C — C was it
        "bisection",  # narrowed via divide-and-conquer
        "analogy",  # recognized pattern from past problem
        "escalation",  # simple → complex hypotheses
        "reversal",  # assumption inversion led to answer
    }
)


@dataclass
class ReplayStep:
    """One hypothesis in a reasoning chain."""

    hypothesis: str = ""
    outcome: str = "dead_end"  # dead_end | partial | root_cause | workaround
    signal: str = ""  # what evidence confirmed/eliminated this
    duration_hint: str = ""  # "quick" | "long" — how much time was spent

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"hypothesis": self.hypothesis, "outcome": self.outcome}
        if self.signal:
            d["signal"] = self.signal
        if self.duration_hint:
            d["duration_hint"] = self.duration_hint
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ReplayStep:
        return cls(
            hypothesis=d.get("hypothesis", ""),
            outcome=d.get("outcome", "dead_end"),
            signal=d.get("signal", ""),
            duration_hint=d.get("duration_hint", ""),
        )


@dataclass
class CognitiveReplay:
    """A reasoning path skeleton — the strategy that solved a problem."""

    id: str = field(default_factory=_new_id)
    session_id: str = ""
    strategy_type: str = "elimination"
    problem_signature: str = ""  # compact description for matching
    steps: list[ReplayStep] = field(default_factory=list)
    shortcut: str = ""  # "skip to step N" advice for next time
    domains: list[str] = field(default_factory=list)
    files_involved: list[str] = field(default_factory=list)
    source_episode_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utcnow)
    times_surfaced: int = 0
    times_helpful: int = 0  # user confirmed it helped
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "strategy_type": self.strategy_type,
            "problem_signature": self.problem_signature,
            "steps": [s.to_dict() for s in self.steps],
            "shortcut": self.shortcut,
            "domains": self.domains,
            "files_involved": self.files_involved,
            "source_episode_ids": self.source_episode_ids,
            "created_at": self.created_at,
            "times_surfaced": self.times_surfaced,
            "times_helpful": self.times_helpful,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CognitiveReplay:
        return cls(
            id=d.get("id", _new_id()),
            session_id=d.get("session_id", ""),
            strategy_type=d.get("strategy_type", "elimination"),
            problem_signature=d.get("problem_signature", ""),
            steps=[ReplayStep.from_dict(s) for s in d.get("steps", [])],
            shortcut=d.get("shortcut", ""),
            domains=d.get("domains", []),
            files_involved=d.get("files_involved", []),
            source_episode_ids=d.get("source_episode_ids", []),
            created_at=d.get("created_at", _utcnow()),
            times_surfaced=d.get("times_surfaced", 0),
            times_helpful=d.get("times_helpful", 0),
            confidence=d.get("confidence", 0.5),
        )

    def human_readable(self) -> str:
        """Format replay as concise advice."""
        lines = [f"Strategy: {self.strategy_type}"]
        if self.problem_signature:
            lines.append(f"Problem: {self.problem_signature}")
        dead_ends = [s for s in self.steps if s.outcome == "dead_end"]
        root = [s for s in self.steps if s.outcome == "root_cause"]
        if dead_ends:
            skips = ", ".join(s.hypothesis for s in dead_ends)
            lines.append(f"Skip: {skips} (dead ends last time)")
        if root:
            lines.append(f"Jump to: {root[0].hypothesis}")
            if root[0].signal:
                lines.append(f"Look for: {root[0].signal}")
        if self.shortcut:
            lines.append(f"Shortcut: {self.shortcut}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Replay detection — identifies reasoning chains from episode sequences
# ---------------------------------------------------------------------------

# Patterns in episode content that indicate hypothesis testing
_HYPOTHESIS_PATTERNS = [
    re.compile(r"(?:tried|checked|investigated|looked at|examined)\s+(.{10,80})", re.I),
    re.compile(r"(?:thought it was|suspected|hypothesis:?)\s+(.{10,80})", re.I),
    re.compile(r"(?:maybe|could be|might be)\s+(.{10,80})", re.I),
]

_DEAD_END_PATTERNS = [
    re.compile(r"(?:not the issue|dead end|ruled out|wasn't|wasn't it|not that)", re.I),
    re.compile(r"(?:didn't help|no effect|still failing|same error)", re.I),
    re.compile(r"(?:red herring|wrong direction|doesn't explain)", re.I),
]

_ROOT_CAUSE_PATTERNS = [
    re.compile(r"(?:root cause|found it|actual issue|the real problem|turned out)", re.I),
    re.compile(r"(?:fixed by|solution was|resolved by|the fix)", re.I),
    re.compile(r"(?:because|realized|discovered that)", re.I),
]

_TRIGGER_EVENT_TYPES = frozenset({"debugging", "frustration", "correction"})


class ReplayDetector:
    """Detects replay-worthy reasoning chains from session episodes."""

    def __init__(self, min_steps: int = 2, max_steps: int = 8) -> None:
        self._min_steps = min_steps
        self._max_steps = max_steps

    def detect(self, episodes: list[Episode]) -> Optional[CognitiveReplay]:
        """Analyze a sequence of episodes for a reasoning chain.

        Returns a CognitiveReplay if the sequence contains:
        - At least min_steps hypotheses
        - At least one dead end AND one root cause/fix
        """
        if len(episodes) < self._min_steps:
            return None

        # Filter to debugging-related episodes
        relevant = [
            ep for ep in episodes
            if ep.event_type in _TRIGGER_EVENT_TYPES
            or self._has_hypothesis_language(ep.content)
        ]
        if len(relevant) < self._min_steps:
            return None

        steps: list[ReplayStep] = []
        source_ids: list[str] = []
        all_files: list[str] = []
        all_domains: list[str] = []

        for ep in relevant[: self._max_steps]:
            step = self._episode_to_step(ep)
            if step:
                steps.append(step)
                source_ids.append(ep.id)
                all_files.extend(ep.files_touched)
                all_domains.extend(ep.domains)

        if len(steps) < self._min_steps:
            return None

        # Must have at least one dead end and one resolution
        has_dead_end = any(s.outcome == "dead_end" for s in steps)
        has_resolution = any(s.outcome in ("root_cause", "workaround") for s in steps)
        if not (has_dead_end and has_resolution):
            return None

        strategy = self._infer_strategy(steps)
        signature = self._build_signature(steps, relevant)
        shortcut = self._build_shortcut(steps)

        return CognitiveReplay(
            session_id=episodes[0].session_id if episodes else "",
            strategy_type=strategy,
            problem_signature=signature,
            steps=steps,
            shortcut=shortcut,
            domains=list(dict.fromkeys(all_domains)),  # dedupe preserving order
            files_involved=list(dict.fromkeys(all_files)),
            source_episode_ids=source_ids,
        )

    def _episode_to_step(self, ep: Episode) -> Optional[ReplayStep]:
        """Convert an episode into a ReplayStep."""
        hypothesis = self._extract_hypothesis(ep.content)
        if not hypothesis:
            hypothesis = ep.content[:100]

        outcome = self._classify_outcome(ep)
        signal = ""
        if ep.reasoning:
            signal = ep.reasoning[:120]
        elif ep.effect:
            signal = ep.effect[:120]

        return ReplayStep(
            hypothesis=hypothesis,
            outcome=outcome,
            signal=signal,
        )

    def _extract_hypothesis(self, content: str) -> str:
        """Extract the hypothesis being tested from content."""
        for pattern in _HYPOTHESIS_PATTERNS:
            m = pattern.search(content)
            if m:
                return m.group(1).strip().rstrip(".,;")
        return ""

    def _classify_outcome(self, ep: Episode) -> str:
        """Determine if episode represents dead end or root cause."""
        content = f"{ep.content} {ep.reasoning} {ep.effect}"

        if ep.event_type == "correction":
            return "root_cause"

        for p in _ROOT_CAUSE_PATTERNS:
            if p.search(content):
                return "root_cause"

        for p in _DEAD_END_PATTERNS:
            if p.search(content):
                return "dead_end"

        if ep.event_type == "frustration":
            return "dead_end"

        return "partial"

    def _has_hypothesis_language(self, content: str) -> bool:
        """Check if content contains hypothesis-testing language."""
        return (
            any(p.search(content) for p in _HYPOTHESIS_PATTERNS)
            or any(p.search(content) for p in _DEAD_END_PATTERNS)
            or any(p.search(content) for p in _ROOT_CAUSE_PATTERNS)
        )

    def _infer_strategy(self, steps: list[ReplayStep]) -> str:
        """Infer the strategy type from the step pattern."""
        outcomes = [s.outcome for s in steps]

        # Elimination: multiple dead ends then root cause
        dead_ends = outcomes.count("dead_end")
        if dead_ends >= 2:
            return "elimination"

        # Bisection: partials narrowing down
        partials = outcomes.count("partial")
        if partials >= 2:
            return "bisection"

        # Reversal: root cause early after a single wrong assumption
        if len(outcomes) >= 2 and outcomes[0] == "dead_end" and outcomes[-1] == "root_cause":
            return "reversal"

        return "elimination"

    def _build_signature(self, steps: list[ReplayStep], episodes: list[Episode]) -> str:
        """Build a compact problem signature for future matching."""
        root_step = next((s for s in steps if s.outcome == "root_cause"), None)
        if root_step:
            return root_step.hypothesis[:120]
        # Fallback: use first episode's content
        if episodes:
            return episodes[0].content[:120]
        return ""

    def _build_shortcut(self, steps: list[ReplayStep]) -> str:
        """Generate the skip-to advice."""
        dead_ends = [s.hypothesis for s in steps if s.outcome == "dead_end"]
        root = next((s for s in steps if s.outcome == "root_cause"), None)

        parts: list[str] = []
        if dead_ends:
            parts.append(f"Skip: {', '.join(dead_ends[:3])}")
        if root:
            parts.append(f"Go directly to: {root.hypothesis}")
        return " → ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Replay matching — finds relevant replays for current problem
# ---------------------------------------------------------------------------


class ReplayMatcher:
    """Finds relevant past replays for a current problem context."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def find_relevant(
        self,
        content: str,
        domains: Optional[list[str]] = None,
        files: Optional[list[str]] = None,
        limit: int = 2,
    ) -> list[CognitiveReplay]:
        """Find replays matching current problem context.

        Scoring: domain match (×2) + file overlap (×1.5) + keyword overlap (×1).
        """
        all_replays = self._db.list_replays(limit=50)
        if not all_replays:
            return []

        content_lower = content.lower()
        content_words = set(re.findall(r"\b\w{4,}\b", content_lower))
        domains_set = set(domains or [])
        files_set = set(files or [])

        scored: list[tuple[float, CognitiveReplay]] = []
        for replay in all_replays:
            score = self._score_relevance(
                replay, content_words, domains_set, files_set
            )
            if score > 0.3:
                scored.append((score, replay))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:limit]]

    def _score_relevance(
        self,
        replay: CognitiveReplay,
        content_words: set[str],
        domains: set[str],
        files: set[str],
    ) -> float:
        score = 0.0

        # Domain overlap (strongest signal)
        replay_domains = set(replay.domains)
        if domains and replay_domains:
            overlap = len(domains & replay_domains) / max(len(domains), 1)
            score += overlap * 2.0

        # File overlap
        replay_files = set(replay.files_involved)
        if files and replay_files:
            overlap = len(files & replay_files) / max(len(files), 1)
            score += overlap * 1.5

        # Keyword overlap with problem signature + step hypotheses
        replay_text = replay.problem_signature.lower()
        for step in replay.steps:
            replay_text += " " + step.hypothesis.lower()
        replay_words = set(re.findall(r"\b\w{4,}\b", replay_text))
        if content_words and replay_words:
            overlap = len(content_words & replay_words) / max(len(content_words), 1)
            score += overlap * 1.0

        # Confidence boost
        score *= replay.confidence

        return score


# ---------------------------------------------------------------------------
# Session-level replay capture (integrates with record flow)
# ---------------------------------------------------------------------------


def detect_replay_from_session(episodes: list[Episode]) -> Optional[CognitiveReplay]:
    """Convenience: run detection on a session's episodes.

    Call this at session end (during neurosync_record) when the session
    contains debugging/frustration/correction episodes.
    """
    trigger_types = _TRIGGER_EVENT_TYPES
    has_trigger = any(ep.event_type in trigger_types for ep in episodes)
    if not has_trigger:
        return None

    # Sort by timestamp for correct ordering
    sorted_eps = sorted(episodes, key=lambda e: e.timestamp)
    detector = ReplayDetector()
    return detector.detect(sorted_eps)
