"""Event Flow Analyzer — mines event_type sequences for workflow patterns and stuck detection."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional

from neurosync.db import Database
from neurosync.intelligence.analyzers.base import BaseAnalyzer
from neurosync.intelligence.models import Insight
from neurosync.vectorstore import VectorStore

_LEARNING_CYCLE = ("frustration", "debugging", "correction", "discovery")
_NEGATIVE_TERMINAL = {"frustration", "correction"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _insight_id(prefix: str, key: str) -> str:
    return hashlib.sha256(f"{prefix}:{key}".encode()).hexdigest()[:24]


class EventFlowAnalyzer(BaseAnalyzer):
    """Analyzes event_type sequences within sessions to detect workflow patterns."""

    interval_seconds = 3600
    max_runtime_ms = 5000

    def name(self) -> str:
        return "event_flows"

    def analyze(self, db: Database, vs: Optional[VectorStore]) -> list[Insight]:
        episodes = db.list_episodes_lightweight(
            columns=["session_id", "event_type", "timestamp"],
            limit=3000,
        )
        if len(episodes) < 30:
            return []

        # Group by session, ordered by timestamp
        session_sequences: dict[str, list[str]] = defaultdict(list)
        session_raw: dict[str, list[dict]] = defaultdict(list)
        for ep in episodes:
            sid = ep.get("session_id", "")
            if sid and ep.get("event_type"):
                session_raw[sid].append(ep)

        for sid, eps in session_raw.items():
            sorted_eps = sorted(eps, key=lambda e: e.get("timestamp", ""))
            session_sequences[sid] = [e["event_type"] for e in sorted_eps]

        if len(session_sequences) < 5:
            return []

        insights: list[Insight] = []
        insights.extend(self._analyze_learning_cycles(session_sequences))
        insights.extend(self._analyze_stuck_patterns(session_sequences))
        insights.extend(self._analyze_markov_patterns(session_sequences))
        return insights

    def _analyze_learning_cycles(
        self, session_sequences: dict[str, list[str]]
    ) -> list[Insight]:
        """Detect frustration→debugging→correction→discovery (positive learning cycle)."""
        cycle_sessions = 0
        total_sessions = len(session_sequences)

        for seq in session_sequences.values():
            if self._contains_subsequence(seq, list(_LEARNING_CYCLE)):
                cycle_sessions += 1

        if cycle_sessions < 3:
            return []

        rate = cycle_sessions / total_sessions
        if rate < 0.1:
            return []

        confidence = min(0.85, 0.3 + (cycle_sessions / 30))
        now = _utcnow()
        content = (
            f"Learning cycles detected in {cycle_sessions}/{total_sessions} sessions "
            f"({rate * 100:.0f}%): frustration → debugging → correction → discovery. "
            f"This pattern indicates active learning — positive signal."
        )

        return [
            Insight(
                id=_insight_id("event_flow", "learning_cycle"),
                insight_type="event_flow",
                category="learning_cycle",
                content=content,
                confidence=confidence,
                created_at=now,
                updated_at=now,
                metadata={
                    "cycle_sessions": cycle_sessions,
                    "total_sessions": total_sessions,
                    "rate": round(rate, 3),
                },
            )
        ]

    def _analyze_stuck_patterns(
        self, session_sequences: dict[str, list[str]]
    ) -> list[Insight]:
        """Detect sessions where same event_type repeats 3+ times without progression."""
        stuck_events: Counter = Counter()
        stuck_sessions = 0

        for seq in session_sequences.values():
            session_stuck = False
            for i in range(len(seq) - 2):
                if seq[i] == seq[i + 1] == seq[i + 2]:
                    event = seq[i]
                    if event in _NEGATIVE_TERMINAL:
                        stuck_events[event] += 1
                        session_stuck = True
            if session_stuck:
                stuck_sessions += 1

        if not stuck_events or stuck_sessions < 2:
            return []

        most_common_event, count = stuck_events.most_common(1)[0]
        total_sessions = len(session_sequences)
        stuck_rate = stuck_sessions / total_sessions
        confidence = min(0.8, 0.3 + (stuck_sessions / 20))
        now = _utcnow()

        content = (
            f"Stuck patterns detected: '{most_common_event}' repeats 3+ times without "
            f"progression in {stuck_sessions}/{total_sessions} sessions. "
            f"Consider breaking down the task or seeking a different approach."
        )

        return [
            Insight(
                id=_insight_id("event_flow", "stuck_pattern"),
                insight_type="event_flow",
                category="stuck_detection",
                content=content,
                confidence=confidence,
                created_at=now,
                updated_at=now,
                metadata={
                    "most_common_stuck_event": most_common_event,
                    "stuck_sessions": stuck_sessions,
                    "stuck_rate": round(stuck_rate, 3),
                    "all_stuck_events": dict(stuck_events.most_common(5)),
                },
            )
        ]

    def _analyze_markov_patterns(
        self, session_sequences: dict[str, list[str]]
    ) -> list[Insight]:
        """Build first-order Markov transition matrix and surface dominant workflow pattern."""
        transition_counts: dict[str, Counter] = defaultdict(Counter)

        for seq in session_sequences.values():
            for i in range(len(seq) - 1):
                transition_counts[seq[i]][seq[i + 1]] += 1

        # Find strongest transitions (>= 0.4 probability, >= 5 observations)
        strong_transitions: list[tuple[str, str, float, int]] = []
        for from_event, to_counts in transition_counts.items():
            total = sum(to_counts.values())
            if total < 5:
                continue
            for to_event, count in to_counts.items():
                prob = count / total
                if prob >= 0.4:
                    strong_transitions.append((from_event, to_event, prob, count))

        if len(strong_transitions) < 2:
            return []

        strong_transitions.sort(key=lambda x: (-x[2], -x[3]))
        top = strong_transitions[:3]

        # Build a readable workflow description from the top transitions
        transition_strs = [
            f"{a} → {b} ({prob * 100:.0f}%)" for a, b, prob, _ in top
        ]
        total_obs = sum(t[3] for t in top)
        confidence = min(0.8, 0.3 + (total_obs / 100))
        now = _utcnow()

        content = (
            f"Personal workflow pattern: {'; '.join(transition_strs)}. "
            f"Based on {len(session_sequences)} sessions."
        )

        return [
            Insight(
                id=_insight_id("event_flow", "markov_workflow"),
                insight_type="event_flow",
                category="workflow_pattern",
                content=content,
                confidence=confidence,
                created_at=now,
                updated_at=now,
                metadata={
                    "strong_transitions": [
                        {"from": a, "to": b, "probability": round(prob, 3), "count": cnt}
                        for a, b, prob, cnt in top
                    ],
                    "total_sessions": len(session_sequences),
                },
            )
        ]

    @staticmethod
    def _contains_subsequence(seq: list[str], subseq: list[str]) -> bool:
        """Check if subseq appears (in order, not necessarily contiguous) in seq."""
        it = iter(seq)
        return all(any(item == s for item in it) for s in subseq)
