"""Signal Predictor Analyzer — mines signal combinations that predict theory creation."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from typing import Optional

from neurosync.db import Database
from neurosync.intelligence.analyzers.base import BaseAnalyzer
from neurosync.intelligence.models import Insight
from neurosync.vectorstore import VectorStore

_KNOWN_SIGNALS = {
    "CORRECTION", "EXPLICIT", "REPETITION", "SURPRISE",
    "INTUITION", "DEPTH", "DURATION", "PASSIVE",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _insight_id(prefix: str, key: str) -> str:
    return hashlib.sha256(f"{prefix}:{key}".encode()).hexdigest()[:24]


class SignalPredictorAnalyzer(BaseAnalyzer):
    """Analyzes which signal combinations predict theory creation (lift ratios)."""

    interval_seconds = 7200  # every 2 hours
    max_runtime_ms = 5000

    def name(self) -> str:
        return "signal_predictor"

    def analyze(self, db: Database, vs: Optional[VectorStore]) -> list[Insight]:
        # Collect episodes with their signals
        episodes = db.list_episodes_lightweight(
            columns=["id", "event_type"],
            limit=3000,
        )
        if len(episodes) < 30:
            return []

        # Gather signal types per episode via the thread-safe public API
        signal_rows = db.list_signals_lightweight(limit=10000)
        episode_signals: dict[str, set[str]] = defaultdict(set)
        for row in signal_rows:
            episode_signals[row["episode_id"]].add(row["signal_type"].upper())

        if not episode_signals:
            return []

        # Gather which episodes are source for theories
        theories = db.list_theories(active_only=False, limit=500)
        theory_episode_ids: set[str] = set()
        for theory in theories:
            for eid in (theory.source_episodes or []):
                theory_episode_ids.add(eid)

        if len(theory_episode_ids) < 5:
            return []

        episode_ids = [ep["id"] for ep in episodes if ep.get("id")]
        total_episodes = len(episode_ids)
        base_rate = len(theory_episode_ids) / total_episodes if total_episodes > 0 else 0

        if base_rate == 0:
            return []

        # Build signal combo → (theory_count, total_count) mapping
        combo_theory: Counter = Counter()
        combo_total: Counter = Counter()

        for eid in episode_ids:
            sigs = frozenset(episode_signals.get(eid, set()) & _KNOWN_SIGNALS)
            if not sigs:
                continue
            is_theory_source = eid in theory_episode_ids

            # Singles
            for sig in sigs:
                combo_total[sig] += 1
                if is_theory_source:
                    combo_theory[sig] += 1

            # Pairs
            sorted_sigs = sorted(sigs)
            for a, b in combinations(sorted_sigs, 2):
                key = f"{a}+{b}"
                combo_total[key] += 1
                if is_theory_source:
                    combo_theory[key] += 1

        if not combo_total:
            return []

        # Compute lift = P(theory|combo) / base_rate
        lifts: list[tuple[str, float, int, int]] = []
        for combo, total in combo_total.items():
            if total < 5:
                continue
            theory_count = combo_theory.get(combo, 0)
            conditional_rate = theory_count / total
            lift = conditional_rate / base_rate
            if lift >= 1.5:
                lifts.append((combo, lift, theory_count, total))

        if not lifts:
            return []

        lifts.sort(key=lambda x: (-x[1], -x[2]))
        top = lifts[:5]

        insights: list[Insight] = []
        now = _utcnow()
        total_theories = len(theory_episode_ids)

        for combo, lift, theory_count, total in top:
            confidence = min(0.85, 0.3 + (total / 50))
            content = (
                f"Episodes with [{combo}] signals are {lift:.1f}x more likely to become theories "
                f"({theory_count}/{total} episodes → {theory_count/total*100:.0f}% vs "
                f"base rate {base_rate*100:.0f}%)."
            )
            insights.append(
                Insight(
                    id=_insight_id("signal_predictor", combo),
                    insight_type="signal_predictor",
                    category="theory_prediction",
                    content=content,
                    confidence=confidence,
                    created_at=now,
                    updated_at=now,
                    metadata={
                        "combo": combo,
                        "lift": round(lift, 2),
                        "theory_count": theory_count,
                        "total_count": total,
                        "base_rate": round(base_rate, 4),
                        "total_theories_used": total_theories,
                    },
                )
            )

        return insights
