"""Tests for failure.py — failure recording, extraction, proactive warnings."""

from __future__ import annotations

from neurosync.failure import FailureModel
from neurosync.models import Episode, FailureRecord, Session


class TestFailureModel:
    def _setup(self, db, vectorstore):
        session = Session(project="test-proj")
        db.save_session(session)
        model = FailureModel(db, vectorstore)
        return session, model

    def test_record_failure_basic(self, db, vectorstore):
        session, model = self._setup(db, vectorstore)
        rec = model.record_failure(
            what_failed="Used global state",
            why_failed="Thread safety issues",
            what_worked="Use dependency injection",
            category="approach",
            severity=4,
        )
        assert rec.id is not None
        assert rec.what_failed == "Used global state"
        assert rec.why_failed == "Thread safety issues"

    def test_deduplication(self, db, vectorstore):
        """Recording a similar failure should increment occurrence_count."""
        session, model = self._setup(db, vectorstore)
        rec1 = model.record_failure(
            what_failed="Used global mutable state for configuration",
            why_failed="Race conditions in threads",
        )
        rec2 = model.record_failure(
            what_failed="Used global mutable state for configuration",
            why_failed="Race conditions in concurrent access",
        )
        # Should have incremented the same record
        loaded = db.get_failure_record(rec1.id)
        assert loaded.occurrence_count >= 1

    def test_extract_from_correction(self, db, vectorstore):
        """Should extract failure from CORRECTION episode format."""
        session, model = self._setup(db, vectorstore)
        ep = Episode(
            session_id=session.id,
            event_type="correction",
            content="CORRECTION: Was told 'use eval for dynamic code' but correct is 'use ast.literal_eval for safe parsing'",
        )
        db.save_episode(ep)
        rec = model.extract_from_correction(ep.id)
        assert rec is not None
        assert "eval" in rec.what_failed
        assert "ast.literal_eval" in rec.what_worked
        assert rec.category == "assumption"

    def test_extract_from_correction_no_match(self, db, vectorstore):
        """Non-correction-format episodes should return None."""
        session, model = self._setup(db, vectorstore)
        ep = Episode(
            session_id=session.id,
            event_type="decision",
            content="Chose to use PostgreSQL",
        )
        db.save_episode(ep)
        rec = model.extract_from_correction(ep.id)
        assert rec is None

    def test_extract_from_debugging(self, db, vectorstore):
        """Should extract failure from debugging episodes."""
        session, model = self._setup(db, vectorstore)
        ep = Episode(
            session_id=session.id,
            event_type="debugging",
            content="Connection pool exhausted under load",
            reasoning="Max pool size was too small for concurrent requests",
        )
        db.save_episode(ep)
        rec = model.extract_from_debugging(ep.id)
        assert rec is not None
        assert "Connection pool" in rec.what_failed

    def test_check_warnings_match(self, db, vectorstore):
        """Warnings should be returned when context matches a failure."""
        session, model = self._setup(db, vectorstore)
        model.record_failure(
            what_failed="Used eval() for parsing user input",
            why_failed="Security vulnerability: code injection",
            what_worked="Use ast.literal_eval() or json.loads()",
            severity=5,
        )
        warnings = model.check_for_warnings("about to use eval for parsing", threshold=0.8)
        assert len(warnings) >= 1
        assert warnings[0]["severity"] == 5

    def test_check_warnings_no_match(self, db, vectorstore):
        """No warnings for completely unrelated context."""
        session, model = self._setup(db, vectorstore)
        model.record_failure(
            what_failed="Used eval() for parsing user input",
            why_failed="Security vulnerability",
        )
        # Very strict threshold to ensure no false matches
        warnings = model.check_for_warnings(
            "Setting up CI/CD pipeline for deployment", threshold=0.1,
        )
        assert len(warnings) == 0

    def test_anti_patterns(self, db, vectorstore):
        session, model = self._setup(db, vectorstore)
        model.record_failure(what_failed="f1", category="approach", severity=3)
        model.record_failure(what_failed="f2", category="tooling", severity=2)
        results = model.get_anti_patterns(category="approach")
        assert len(results) == 1

    def test_by_category(self, db, vectorstore):
        session, model = self._setup(db, vectorstore)
        model.record_failure(what_failed="Used global mutable state in production", category="approach")
        model.record_failure(what_failed="Wrong version of Node.js installed", category="tooling")
        model.record_failure(what_failed="Forgot to validate user input boundaries", category="approach")
        approach = model.get_anti_patterns(category="approach")
        assert len(approach) == 2

    def test_recurring(self, db, vectorstore):
        """detect_recurring_failures should find high-occurrence failures."""
        session, model = self._setup(db, vectorstore)
        rec = model.record_failure(what_failed="common mistake one two three four five")
        db.increment_failure_occurrence(rec.id)
        db.increment_failure_occurrence(rec.id)
        model.record_failure(what_failed="rare unique failure only happens once ever")
        recurring = model.detect_recurring_failures(min_occurrences=3)
        assert len(recurring) == 1
        assert recurring[0].what_failed == "common mistake one two three four five"

    def test_search_failures(self, db, vectorstore):
        session, model = self._setup(db, vectorstore)
        model.record_failure(
            what_failed="Cache invalidation caused stale data",
            why_failed="TTL not set correctly",
        )
        results = model.search_failures("cache stale data")
        assert len(results) >= 1

    def test_project_summary(self, db, vectorstore):
        session, model = self._setup(db, vectorstore)
        model.record_failure(what_failed="f1", category="approach", project="proj-a")
        model.record_failure(what_failed="f2", category="tooling", project="proj-a")
        summary = model.get_project_failure_summary("proj-a")
        assert summary["project"] == "proj-a"
        assert summary["total_failures"] == 2
        assert "approach" in summary["by_category"]
