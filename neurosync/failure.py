"""Failure modeling: record failures, extract from corrections, proactive warnings."""

from __future__ import annotations

import re
from typing import Any, Optional

from neurosync.db import Database
from neurosync.models import FailureRecord
from neurosync.vectorstore import VectorStore

# Regex for parsing correction episode content
_CORRECTION_RE = re.compile(
    r"CORRECTION:\s*Was told '(.+?)' but correct (?:answer )?is '(.+?)'",
    re.DOTALL,
)


class FailureModel:
    """Records, deduplicates, and queries failure patterns."""

    def __init__(self, db: Database, vectorstore: Optional[VectorStore] = None) -> None:
        self._db = db
        self._vs = vectorstore

    # --- Recording ---

    def record_failure(
        self,
        what_failed: str,
        why_failed: str = "",
        what_worked: str = "",
        category: str = "approach",
        project: str = "",
        context: str = "",
        source_episode_id: str = "",
        severity: int = 3,
    ) -> FailureRecord:
        """Record a failure, deduplicating against existing records.

        If a similar failure exists (vector distance < 0.3), increments
        its occurrence_count instead of creating a new record.
        """
        # Check for duplicate via vector search
        query_text = f"{what_failed} {why_failed}".strip()
        if query_text and self._vs:
            existing = self._vs.search_failures(query_text, n_results=3)
            for match in existing:
                if match.get("distance", 1.0) < 0.3:
                    try:
                        record_id = int(match["id"])
                    except (ValueError, TypeError, KeyError):
                        continue
                    self._db.increment_failure_occurrence(record_id)
                    record = self._db.get_failure_record(record_id)
                    if record:
                        return record

        record = FailureRecord(
            what_failed=what_failed,
            why_failed=why_failed,
            what_worked=what_worked,
            category=category,
            project=project,
            context=context,
            source_episode_id=source_episode_id,
            severity=severity,
        )
        self._db.save_failure_record(record)
        if self._vs:
            self._vs.add_failure(record)
        return record

    def extract_from_correction(self, episode_id: str) -> Optional[FailureRecord]:
        """Extract a failure record from a correction episode.

        Parses "CORRECTION: Was told 'X' but correct is 'Y'" format.
        """
        episode = self._db.get_episode(episode_id)
        if not episode:
            return None
        match = _CORRECTION_RE.search(episode.content)
        if not match:
            return None
        what_failed = match.group(1).strip()
        what_worked = match.group(2).strip()
        session = self._db.get_session(episode.session_id)
        project = session.project if session else ""
        return self.record_failure(
            what_failed=what_failed,
            why_failed="Corrected by user",
            what_worked=what_worked,
            category="assumption",
            project=project,
            source_episode_id=episode_id,
            severity=4,
        )

    def extract_from_debugging(self, episode_id: str) -> Optional[FailureRecord]:
        """Extract a failure record from a debugging episode."""
        episode = self._db.get_episode(episode_id)
        if not episode or episode.event_type != "debugging":
            return None
        session = self._db.get_session(episode.session_id)
        project = session.project if session else ""
        return self.record_failure(
            what_failed=episode.content,
            why_failed=episode.reasoning or "",
            category="approach",
            project=project,
            source_episode_id=episode_id,
            severity=3,
        )

    # --- Querying ---

    def check_for_warnings(
        self,
        context: str,
        project: str = "",
        threshold: float = 0.4,
    ) -> list[dict[str, Any]]:
        """Check if current context matches any known failures.

        Returns proactive warnings with remediation suggestions.
        """
        if not context.strip() or not self._vs:
            return []
        where = {"project": project} if project else None
        results = self._vs.search_failures(context, n_results=5, where=where)
        warnings: list[dict[str, Any]] = []
        for result in results:
            if result.get("distance", 1.0) > threshold:
                continue
            meta = result.get("metadata", {})
            warnings.append(
                {
                    "warning": result.get("document", ""),
                    "what_worked": meta.get("what_worked", ""),
                    "severity": meta.get("severity", 3),
                    "distance": result.get("distance", 0.0),
                }
            )
        return warnings

    def get_anti_patterns(
        self,
        project: Optional[str] = None,
        category: Optional[str] = None,
        min_severity: int = 1,
    ) -> list[FailureRecord]:
        return self._db.list_failure_records(
            project=project,
            category=category,
            min_severity=min_severity,
        )

    def search_failures(self, query: str, n_results: int = 5) -> list[dict[str, Any]]:
        if not self._vs:
            return []
        return self._vs.search_failures(query, n_results=n_results)

    def detect_recurring_failures(self, min_occurrences: int = 2) -> list[FailureRecord]:
        """Find failures that have occurred multiple times."""
        all_failures = self._db.list_failure_records(limit=500)
        return [f for f in all_failures if f.occurrence_count >= min_occurrences]

    def get_project_failure_summary(self, project: str) -> dict[str, Any]:
        """Summary of failures for a project."""
        failures = self._db.list_failure_records(project=project)
        by_category: dict[str, int] = {}
        total_occurrences = 0
        for f in failures:
            by_category[f.category] = by_category.get(f.category, 0) + 1
            total_occurrences += f.occurrence_count
        return {
            "project": project,
            "total_failures": len(failures),
            "total_occurrences": total_occurrences,
            "by_category": by_category,
        }
