"""Work Pattern Analyzer — mines episode timestamps for productivity intelligence."""

from __future__ import annotations

import hashlib
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional

from neurosync.db import Database
from neurosync.intelligence.analyzers.base import BaseAnalyzer
from neurosync.intelligence.models import Insight
from neurosync.vectorstore import VectorStore


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _insight_id(prefix: str, key: str) -> str:
    return hashlib.sha256(f"{prefix}:{key}".encode()).hexdigest()[:24]


class WorkPatternAnalyzer(BaseAnalyzer):
    """Analyzes temporal patterns in episode creation."""

    interval_seconds = 3600  # hourly
    max_runtime_ms = 5000

    def name(self) -> str:
        return "work_patterns"

    def analyze(self, db: Database, vs: Optional[VectorStore]) -> list[Insight]:
        insights: list[Insight] = []

        episodes = db.list_episodes_lightweight(
            columns=["timestamp", "quality_score", "signal_weight", "event_type", "session_id"],
            limit=2000,
        )
        if len(episodes) < 20:
            return insights

        insights.extend(self._analyze_peak_hours(episodes, db))
        insights.extend(self._analyze_session_rhythm(episodes, db))
        insights.extend(self._analyze_day_of_week(episodes))

        return insights

    def _analyze_peak_hours(
        self, episodes: list[dict], db: Database
    ) -> list[Insight]:
        """Find hours with highest weighted quality."""
        hour_data: dict[int, list[float]] = defaultdict(list)

        for ep in episodes:
            ts = ep.get("timestamp", "")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            hour = dt.hour
            raw_quality = ep.get("quality_score")
            quality = min(max(raw_quality if raw_quality is not None else 3, 0), 7)
            weight = min(max(ep.get("signal_weight", 1.0), 0.0), 50.0)
            hour_data[hour].append(weight * quality)

        if len(hour_data) < 4:
            return []

        hour_avgs: dict[int, float] = {}
        hour_counts: dict[int, int] = {}
        for h, values in hour_data.items():
            if len(values) >= 3:
                hour_avgs[h] = statistics.mean(values)
                hour_counts[h] = len(values)

        if len(hour_avgs) < 4:
            return []

        all_avgs = list(hour_avgs.values())
        mean_quality = statistics.mean(all_avgs)
        if mean_quality == 0:
            return []
        std_quality = statistics.stdev(all_avgs) if len(all_avgs) > 1 else 0

        peak_threshold = mean_quality + 0.3 * std_quality
        peak_hours = sorted(
            [h for h, avg in hour_avgs.items() if avg >= peak_threshold],
            key=lambda h: hour_avgs[h],
            reverse=True,
        )

        if not peak_hours:
            return []

        best_hour = peak_hours[0]
        best_ratio = hour_avgs[best_hour] / mean_quality if mean_quality > 0 else 1.0

        # Find contiguous peak band
        peak_set = set(peak_hours[:4])
        start_h = min(peak_set)
        end_h = max(peak_set)

        total_observations = sum(hour_counts.get(h, 0) for h in peak_hours)
        confidence = min(0.95, 0.3 + (total_observations / 200))

        content = (
            f"Your peak productivity hours are {start_h}:00-{end_h + 1}:00 "
            f"({best_ratio:.1f}x quality vs average). "
            f"Based on {total_observations} episodes."
        )

        now = _utcnow()
        db.upsert_developer_profile(
            "peak_hours",
            {"start": start_h, "end": end_h + 1, "ratio": round(best_ratio, 2)},
            total_observations,
            confidence,
        )

        return [
            Insight(
                id=_insight_id("work_pattern", "peak_hours"),
                insight_type="work_pattern",
                category="peak_hours",
                content=content,
                confidence=confidence,
                evidence=[],
                created_at=now,
                updated_at=now,
                metadata={"peak_hours": peak_hours[:4], "ratio": round(best_ratio, 2)},
            )
        ]

    def _analyze_session_rhythm(
        self, episodes: list[dict], db: Database
    ) -> list[Insight]:
        """Detect average productive session length and fatigue patterns."""
        session_episodes: dict[str, list[dict]] = defaultdict(list)
        for ep in episodes:
            sid = ep.get("session_id", "")
            if sid:
                session_episodes[sid].append(ep)

        session_durations: list[float] = []
        fatigue_sessions: list[str] = []

        for sid, eps in session_episodes.items():
            if len(eps) < 3:
                continue
            timestamps = []
            for ep in eps:
                ts = ep.get("timestamp", "")
                if ts:
                    try:
                        timestamps.append(
                            datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        )
                    except (ValueError, AttributeError):
                        continue
            if len(timestamps) < 2:
                continue
            timestamps.sort()
            duration_min = (timestamps[-1] - timestamps[0]).total_seconds() / 60
            if duration_min < 5:
                continue
            session_durations.append(duration_min)

            # Check for quality decline (linear regression on quality scores)
            qualities = [
                ep.get("quality_score")
                for ep in sorted(eps, key=lambda e: e.get("timestamp", ""))
                if ep.get("quality_score") is not None
            ]
            if len(qualities) >= 4:
                slope = self._linear_slope(qualities)
                if slope < -0.3:
                    fatigue_sessions.append(sid)

        if len(session_durations) < 5:
            return []

        avg_duration = statistics.mean(session_durations)
        median_duration = statistics.median(session_durations)
        fatigue_rate = len(fatigue_sessions) / len(session_episodes) if session_episodes else 0

        insights: list[Insight] = []
        now = _utcnow()

        confidence = min(0.9, 0.3 + (len(session_durations) / 100))

        content = (
            f"Your typical productive session is {median_duration:.0f} minutes (median). "
            f"Quality decline detected in {fatigue_rate * 100:.0f}% of sessions."
        )

        db.upsert_developer_profile(
            "session_rhythm",
            {
                "avg_minutes": round(avg_duration, 1),
                "median_minutes": round(median_duration, 1),
                "fatigue_rate": round(fatigue_rate, 3),
            },
            len(session_durations),
            confidence,
        )

        insights.append(
            Insight(
                id=_insight_id("work_pattern", "session_rhythm"),
                insight_type="work_pattern",
                category="session_rhythm",
                content=content,
                confidence=confidence,
                created_at=now,
                updated_at=now,
                metadata={
                    "avg_minutes": round(avg_duration, 1),
                    "median_minutes": round(median_duration, 1),
                    "fatigue_rate": round(fatigue_rate, 3),
                    "sample_size": len(session_durations),
                },
            )
        )

        # Fatigue threshold insight
        if fatigue_rate > 0.2 and len(session_durations) >= 10:
            # Find duration threshold where fatigue becomes likely
            long_sessions = sorted(session_durations, reverse=True)
            fatigue_threshold = statistics.median(long_sessions[: len(long_sessions) // 3])

            fatigue_content = (
                f"Sessions longer than {fatigue_threshold:.0f} minutes show quality decline. "
                f"Consider taking breaks at that point."
            )
            db.upsert_developer_profile(
                "fatigue_threshold_minutes",
                round(fatigue_threshold, 1),
                len(session_durations),
                confidence,
            )
            insights.append(
                Insight(
                    id=_insight_id("work_pattern", "fatigue_threshold"),
                    insight_type="work_pattern",
                    category="fatigue_warning",
                    content=fatigue_content,
                    confidence=confidence * 0.9,
                    created_at=now,
                    updated_at=now,
                    metadata={"threshold_minutes": round(fatigue_threshold, 1)},
                )
            )

        return insights

    def _analyze_day_of_week(self, episodes: list[dict]) -> list[Insight]:
        """Find day-of-week patterns in corrections vs discoveries."""
        day_corrections: Counter = Counter()
        day_discoveries: Counter = Counter()
        day_total: Counter = Counter()

        for ep in episodes:
            ts = ep.get("timestamp", "")
            if not ts:
                continue
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            day = dt.strftime("%A")
            day_total[day] += 1
            if ep.get("event_type") == "correction":
                day_corrections[day] += 1
            elif ep.get("event_type") == "discovery":
                day_discoveries[day] += 1

        if sum(day_total.values()) < 50:
            return []

        # Find day with most corrections relative to total
        correction_rates: dict[str, float] = {}
        for day, total in day_total.items():
            if total >= 5:
                correction_rates[day] = day_corrections[day] / total

        if not correction_rates:
            return []

        worst_day = max(correction_rates, key=correction_rates.get)  # type: ignore[arg-type]
        best_day = min(correction_rates, key=correction_rates.get)  # type: ignore[arg-type]

        worst_rate = correction_rates[worst_day]
        best_rate = correction_rates[best_day]

        if worst_rate < 0.05 or (worst_rate / max(best_rate, 0.01)) < 1.5:
            return []

        now = _utcnow()
        ratio = worst_rate / max(best_rate, 0.01)
        confidence = min(0.85, 0.3 + (sum(day_total.values()) / 300))

        content = (
            f"{worst_day}s have {ratio:.1f}x more corrections than {best_day}s. "
            f"Consider extra review on {worst_day}s."
        )

        return [
            Insight(
                id=_insight_id("work_pattern", "day_of_week"),
                insight_type="work_pattern",
                category="day_of_week",
                content=content,
                confidence=confidence,
                created_at=now,
                updated_at=now,
                metadata={
                    "worst_day": worst_day,
                    "best_day": best_day,
                    "ratio": round(ratio, 2),
                },
            )
        ]

    @staticmethod
    def _linear_slope(values: list[float]) -> float:
        """Compute slope of linear fit (least-squares). Positive = improving."""
        n = len(values)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2
        y_mean = statistics.mean(values)
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        den = sum((i - x_mean) ** 2 for i in range(n))
        return num / den if den > 0 else 0.0
