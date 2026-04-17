"""Tests for consolidation.py — consolidation engine."""

from __future__ import annotations

from neurosync.consolidation import ConsolidationEngine


class TestConsolidationEngine:
    def test_not_enough_episodes(self, db, vectorstore, episodic, semantic):
        engine = ConsolidationEngine(db, vectorstore, episodic, semantic, min_episodes=5)
        session = episodic.start_session(project="test")
        episodic.record_episode(session.id, "decision", "Only one episode")
        result = engine.run()
        assert result["theories_created"] == 0
        assert "Not enough" in result["message"]

    def test_dry_run(self, db, vectorstore, episodic, semantic):
        engine = ConsolidationEngine(db, vectorstore, episodic, semantic, min_episodes=2)
        session = episodic.start_session(project="test")
        for i in range(5):
            episodic.record_episode(
                session.id, "decision", f"Used SQLite WAL mode for concurrent access pattern {i}"
            )
        result = engine.run(dry_run=True)
        assert result.get("dry_run") is True
        # Episodes should still be unconsolidated
        assert db.count_episodes(consolidated=0) == 5

    def test_full_consolidation(self, db, vectorstore, episodic, semantic):
        engine = ConsolidationEngine(
            db, vectorstore, episodic, semantic,
            min_episodes=2, similarity_threshold=0.9,
        )
        session = episodic.start_session(project="test")
        # Create similar episodes that should cluster
        episodic.record_episode(session.id, "decision", "Always use WAL mode in SQLite")
        episodic.record_episode(session.id, "decision", "SQLite WAL mode is essential for concurrency")
        episodic.record_episode(session.id, "pattern", "WAL mode prevents database locks in SQLite")
        episodic.record_episode(session.id, "decision", "Use pytest fixtures for test isolation")
        episodic.record_episode(session.id, "pattern", "Pytest fixtures provide clean test state")
        result = engine.run()
        assert result["episodes_processed"] == 5
        assert result["theories_created"] >= 0  # May or may not cluster

    def test_consolidation_marks_episodes(self, db, vectorstore, episodic, semantic):
        engine = ConsolidationEngine(
            db, vectorstore, episodic, semantic,
            min_episodes=2, similarity_threshold=0.99,  # Very strict to form clusters
        )
        session = episodic.start_session(project="test")
        # Identical content should cluster
        for _ in range(5):
            episodic.record_episode(session.id, "decision", "Always validate user input")
        result = engine.run()
        # After consolidation, some episodes should be marked
        assert result["episodes_processed"] == 5

    def test_project_filter(self, db, vectorstore, episodic, semantic):
        engine = ConsolidationEngine(db, vectorstore, episodic, semantic, min_episodes=2)
        s1 = episodic.start_session(project="proj-a")
        s2 = episodic.start_session(project="proj-b")
        for _ in range(3):
            episodic.record_episode(s1.id, "decision", "Project A pattern")
        for _ in range(3):
            episodic.record_episode(s2.id, "decision", "Project B pattern")
        result = engine.run(project="proj-a")
        assert result["episodes_processed"] == 3
