"""File Network Analyzer — mines files_touched for co-occurrence and volatility."""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from typing import Optional

from neurosync.db import Database
from neurosync.intelligence.analyzers.base import BaseAnalyzer
from neurosync.intelligence.models import Insight
from neurosync.vectorstore import VectorStore


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _insight_id(prefix: str, key: str) -> str:
    return hashlib.sha256(f"{prefix}:{key}".encode()).hexdigest()[:24]


def _short_path(path: str) -> str:
    """Shorten path for display (last 2 components)."""
    parts = path.replace("\\", "/").split("/")
    return "/".join(parts[-2:]) if len(parts) > 2 else path


VOLATILITY_WEIGHTS: dict[str, int] = {
    "correction": 3,
    "debugging": 2,
    "frustration": 2,
    "file_change": 1,
    "decision": 1,
    "discovery": 1,
}


class FileNetworkAnalyzer(BaseAnalyzer):
    """Analyzes file co-occurrence patterns and volatility hotspots."""

    interval_seconds = 7200  # every 2 hours
    max_runtime_ms = 5000

    def name(self) -> str:
        return "file_network"

    def analyze(self, db: Database, vs: Optional[VectorStore]) -> list[Insight]:
        episodes = db.list_episodes_lightweight(
            columns=["files_touched", "event_type"],
            limit=2000,
        )
        if len(episodes) < 10:
            return []

        insights: list[Insight] = []
        insights.extend(self._analyze_co_occurrence(episodes))
        insights.extend(self._analyze_volatility(episodes))
        return insights

    def _analyze_co_occurrence(self, episodes: list[dict]) -> list[Insight]:
        """Find files that always change together."""
        file_occurrences: Counter = Counter()
        pair_occurrences: Counter = Counter()

        for ep in episodes:
            files = ep.get("files_touched") or []
            if isinstance(files, str):
                try:
                    files = json.loads(files)
                except (json.JSONDecodeError, TypeError):
                    files = []
            if not files or len(files) < 2:
                if files:
                    for f in files:
                        file_occurrences[f] += 1
                continue

            normalized = sorted({f.strip() for f in files if f.strip()})
            for f in normalized:
                file_occurrences[f] += 1

            for a, b in combinations(normalized[:20], 2):
                pair_occurrences[(a, b)] += 1

        if not pair_occurrences:
            return []

        # Compute Jaccard index for pairs with 3+ co-occurrences
        strong_pairs: list[tuple[str, str, float, int]] = []
        for (a, b), count in pair_occurrences.items():
            if count < 3:
                continue
            union = file_occurrences[a] + file_occurrences[b] - count
            jaccard = count / union if union > 0 else 0
            if jaccard >= 0.3:
                strong_pairs.append((a, b, jaccard, count))

        if not strong_pairs:
            return []

        strong_pairs.sort(key=lambda x: (-x[2], -x[3]))
        top_pairs = strong_pairs[:5]

        now = _utcnow()
        insights: list[Insight] = []

        for a, b, jaccard, count in top_pairs:
            a_short = _short_path(a)
            b_short = _short_path(b)
            content = (
                f"{a_short} and {b_short} always change together "
                f"({count} co-occurrences, Jaccard={jaccard:.2f}). "
                f"Hidden dependency detected."
            )
            confidence = min(0.9, 0.3 + (count / 20))
            insights.append(
                Insight(
                    id=_insight_id("file_network", f"cooccur_{a}_{b}"),
                    insight_type="file_network",
                    category="co_occurrence",
                    content=content,
                    confidence=confidence,
                    evidence=[a, b],
                    created_at=now,
                    updated_at=now,
                    metadata={
                        "file_a": a,
                        "file_b": b,
                        "jaccard": round(jaccard, 3),
                        "count": count,
                    },
                )
            )

        return insights

    def _analyze_volatility(self, episodes: list[dict]) -> list[Insight]:
        """Find files that appear frequently in correction/debugging episodes."""
        file_volatility: Counter = Counter()
        file_total: Counter = Counter()

        for ep in episodes:
            files = ep.get("files_touched") or []
            if isinstance(files, str):
                try:
                    files = json.loads(files)
                except (json.JSONDecodeError, TypeError):
                    files = []
            if not files:
                continue

            weight = VOLATILITY_WEIGHTS.get(ep.get("event_type", ""), 0)
            for f in files:
                f = f.strip()
                if not f:
                    continue
                file_total[f] += 1
                if weight > 0:
                    file_volatility[f] += weight

        if not file_volatility:
            return []

        # Normalize: volatility_score = weighted_corrections / total_occurrences
        volatility_scores: dict[str, float] = {}
        for f, vol in file_volatility.items():
            total = file_total.get(f, 1)
            if total >= 3:
                volatility_scores[f] = vol / total

        if not volatility_scores:
            return []

        # Find hotspots: top files by volatility score with minimum occurrences
        all_scores = list(volatility_scores.values())
        if len(all_scores) < 3:
            return []

        mean_vol = statistics.mean(all_scores)
        std_vol = statistics.stdev(all_scores) if len(all_scores) > 1 else 0
        threshold = mean_vol + std_vol

        hotspots = [
            (f, score, file_total[f])
            for f, score in volatility_scores.items()
            if score >= threshold and file_total[f] >= 3
        ]
        hotspots.sort(key=lambda x: -x[1])

        if not hotspots:
            return []

        now = _utcnow()
        insights: list[Insight] = []

        for f, score, total in hotspots[:3]:
            f_short = _short_path(f)
            corrections = file_volatility.get(f, 0)
            content = (
                f"{f_short} is a volatility hotspot "
                f"(volatility score: {score:.1f}, {total} total touches, "
                f"{corrections} weighted corrections). Extra care recommended."
            )
            confidence = min(0.85, 0.3 + (total / 30))
            insights.append(
                Insight(
                    id=_insight_id("file_network", f"volatile_{f}"),
                    insight_type="file_network",
                    category="volatility",
                    content=content,
                    confidence=confidence,
                    evidence=[f],
                    created_at=now,
                    updated_at=now,
                    metadata={
                        "file": f,
                        "volatility_score": round(score, 2),
                        "total_touches": total,
                        "weighted_corrections": corrections,
                    },
                )
            )

        return insights
