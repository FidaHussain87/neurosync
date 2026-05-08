"""NeuroSync Intelligence Layer — background analysis engine that mines stored data for patterns."""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from neurosync.db import Database
from neurosync.intelligence.analyzers.base import BaseAnalyzer
from neurosync.intelligence.models import Insight
from neurosync.intelligence.surfacer import InsightSurfacer
from neurosync.logging import get_logger
from neurosync.vectorstore import VectorStore

logger = get_logger("intelligence")


class IntelligenceEngine:
    """Orchestrates background analyzers and surfaces insights via MCP responses."""

    def __init__(
        self,
        db: Database,
        vs: Optional[VectorStore] = None,
        run_interval: int = 60,
    ) -> None:
        self._db = db
        self._vs = vs
        self._run_interval = run_interval
        self._analyzers: list[BaseAnalyzer] = []
        self._last_run: dict[str, float] = {}
        self._shutdown = False
        self._lock = threading.Lock()
        self._surfacer = InsightSurfacer(db)
        self._surfaced_this_session: set[str] = set()
        self._register_default_analyzers()

    def _register_default_analyzers(self) -> None:
        from neurosync.intelligence.analyzers.event_flows import EventFlowAnalyzer
        from neurosync.intelligence.analyzers.file_network import FileNetworkAnalyzer
        from neurosync.intelligence.analyzers.learning_velocity import LearningVelocityAnalyzer
        from neurosync.intelligence.analyzers.signal_predictor import SignalPredictorAnalyzer
        from neurosync.intelligence.analyzers.work_patterns import WorkPatternAnalyzer

        self._analyzers.append(WorkPatternAnalyzer())
        self._analyzers.append(FileNetworkAnalyzer())
        self._analyzers.append(EventFlowAnalyzer())
        self._analyzers.append(SignalPredictorAnalyzer())
        self._analyzers.append(LearningVelocityAnalyzer())

    def register_analyzer(self, analyzer: BaseAnalyzer) -> None:
        self._analyzers.append(analyzer)

    def run_loop(self) -> None:
        """Background loop: runs analyzers on their intervals. Call from daemon thread."""
        while not self._shutdown:
            self._tick()
            time.sleep(self._run_interval)

    _EXPIRY_CHECK_INTERVAL = 86400  # check for expired insights once per day

    def _tick(self) -> None:
        """Single pass: check and run due analyzers, clean expired insights."""
        now = time.time()

        # Periodic expiry cleanup
        with self._lock:
            last_expiry = self._last_run.get("_expiry_cleanup", 0)
        if now - last_expiry >= self._EXPIRY_CHECK_INTERVAL:
            self._cleanup_expired_insights()
            with self._lock:
                self._last_run["_expiry_cleanup"] = now

        for analyzer in self._analyzers:
            name = analyzer.name()
            with self._lock:
                last = self._last_run.get(name, 0)
            if now - last < analyzer.interval_seconds:
                continue
            try:
                start = time.time()
                insights = analyzer.analyze(self._db, self._vs)
                elapsed_ms = (time.time() - start) * 1000
                if elapsed_ms > analyzer.max_runtime_ms:
                    logger.warning(
                        "Analyzer %s exceeded time limit (%.0fms > %dms)",
                        name,
                        elapsed_ms,
                        analyzer.max_runtime_ms,
                    )
                self._store_insights(insights)
                with self._lock:
                    self._last_run[name] = now
                if insights:
                    logger.debug("Analyzer %s produced %d insights", name, len(insights))
            except Exception:
                logger.warning("Analyzer %s failed", name, exc_info=True)
                with self._lock:
                    self._last_run[name] = now

    def _cleanup_expired_insights(self) -> None:
        """Remove insights past their expires_at timestamp."""
        try:
            removed = self._db.delete_expired_insights()
            if removed > 0:
                logger.debug("Cleaned up %d expired insights", removed)
        except Exception:
            logger.debug("Expired insight cleanup failed", exc_info=True)

    def _store_insights(self, insights: list[Insight]) -> None:
        """Persist insights to database (upsert by id)."""
        for insight in insights:
            self._db.upsert_insight(insight)

    def run_once(self) -> dict[str, Any]:
        """Run all analyzers immediately (for CLI/testing). Returns summary."""
        results: dict[str, Any] = {}
        for analyzer in self._analyzers:
            name = analyzer.name()
            try:
                insights = analyzer.analyze(self._db, self._vs)
                self._store_insights(insights)
                results[name] = {"insights_produced": len(insights)}
            except Exception as e:
                results[name] = {"error": str(e)}
        return results

    _MAX_SURFACED_TRACKING = 500

    def get_relevant_insights(
        self,
        project: str = "",
        context: str = "",
        limit: int = 2,
    ) -> list[dict[str, Any]]:
        """Get insights to surface in MCP response. Fast (<10ms, reads from table)."""
        with self._lock:
            exclude = self._surfaced_this_session.copy()
        insights = self._surfacer.select(
            project=project,
            context=context,
            limit=limit,
            exclude_ids=exclude,
        )
        with self._lock:
            for ins in insights:
                self._surfaced_this_session.add(ins["id"])
            # Evict oldest entries when cap exceeded (preserves recent dedup)
            if len(self._surfaced_this_session) > self._MAX_SURFACED_TRACKING:
                excess = len(self._surfaced_this_session) - self._MAX_SURFACED_TRACKING
                it = iter(self._surfaced_this_session)
                to_remove = [next(it) for _ in range(excess)]
                self._surfaced_this_session -= set(to_remove)
        for ins in insights:
            self._db.increment_insight_surfaced(ins["id"])
        return insights

    def get_proactive_warnings(
        self,
        project: str = "",
        session_start: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """Get warning-type insights for record responses."""
        with self._lock:
            exclude = self._surfaced_this_session.copy()
        return self._surfacer.select_warnings(
            project=project,
            session_start=session_start,
            exclude_ids=exclude,
        )

    def get_developer_profile(self) -> dict[str, Any]:
        """Get computed developer profile for status response."""
        rows = self._db.list_developer_profile()
        return {r["profile_key"]: r["profile_value"] for r in rows}

    def get_stats(self) -> dict[str, Any]:
        """Intelligence health metrics."""
        total_insights = self._db.count_insights()
        with self._lock:
            last_runs = {
                name: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
                for name, ts in self._last_run.items()
            }
        return {
            "analyzers_active": len(self._analyzers),
            "total_insights": total_insights,
            "last_runs": last_runs,
        }

    def reset_session(self) -> None:
        """Reset per-session state (call on new session start)."""
        with self._lock:
            self._surfaced_this_session.clear()

    def shutdown(self) -> None:
        """Signal background loop to stop."""
        self._shutdown = True
