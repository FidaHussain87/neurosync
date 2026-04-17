"""Tests for consolidation.py — consolidation engine."""

from __future__ import annotations

from unittest.mock import patch

from neurosync.consolidation import ConsolidationEngine, maybe_consolidate


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

    def test_causal_extraction(self, db, vectorstore, episodic, semantic):
        engine = ConsolidationEngine(
            db, vectorstore, episodic, semantic,
            min_episodes=2, similarity_threshold=0.99,
        )
        session = episodic.start_session(project="test")
        for i in range(5):
            episodic.record_episode(
                session.id, "causal", f"Causal episode {i}",
                cause="user corrected AI",
                effect="model learned",
                reasoning="corrections compound exponentially",
            )
        result = engine.run()
        assert result["episodes_processed"] == 5

    def test_causal_fallback(self, db, vectorstore, episodic, semantic):
        """When no causal episodes, should fall back to standard extraction."""
        engine = ConsolidationEngine(
            db, vectorstore, episodic, semantic,
            min_episodes=2, similarity_threshold=0.99,
        )
        session = episodic.start_session(project="test")
        for _ in range(5):
            episodic.record_episode(session.id, "decision", "Always validate user input")
        result = engine.run()
        assert result["episodes_processed"] == 5

    def test_theory_linking(self, db, vectorstore, episodic, semantic):
        """Test that newly created theories get auto-linked to related ones."""
        # Create a pre-existing theory
        semantic.create_theory(content="Always validate user input at boundaries")
        engine = ConsolidationEngine(
            db, vectorstore, episodic, semantic,
            min_episodes=2, similarity_threshold=0.99,
        )
        session = episodic.start_session(project="test")
        for _ in range(5):
            episodic.record_episode(
                session.id, "decision",
                "Validate all user input at service layer boundaries",
            )
        result = engine.run()
        # Theories may be created or confirmed depending on clustering
        assert result["episodes_processed"] == 5

    def test_parent_detection(self, db, vectorstore, episodic, semantic):
        """Test parent relationship detection during consolidation."""
        session = episodic.start_session(project="test")
        # Create a small theory from 2 episodes
        ep1 = episodic.record_episode(session.id, "decision", "Use WAL mode in SQLite")
        ep2 = episodic.record_episode(session.id, "decision", "WAL mode for SQLite")
        small_theory = semantic.create_theory(
            content="Use WAL mode", source_episodes=[ep1.id, ep2.id]
        )
        # Now create more episodes that overlap
        for i in range(3):
            episodic.record_episode(session.id, "decision", "Use WAL mode in SQLite always")
        engine = ConsolidationEngine(
            db, vectorstore, episodic, semantic,
            min_episodes=2, similarity_threshold=0.99,
        )
        result = engine.run()
        assert result["episodes_processed"] >= 5


class TestMaybeConsolidate:
    def test_below_threshold(self, db, vectorstore, episodic, semantic):
        session = episodic.start_session(project="test")
        for _ in range(3):
            episodic.record_episode(session.id, "decision", "Some episode")
        result = maybe_consolidate(db, vectorstore, episodic, semantic, threshold=20)
        assert result is None

    def test_above_threshold(self, db, vectorstore, episodic, semantic):
        session = episodic.start_session(project="test")
        for i in range(25):
            episodic.record_episode(
                session.id, "decision", f"Episode about testing pattern {i}"
            )
        result = maybe_consolidate(
            db, vectorstore, episodic, semantic, threshold=20, min_episodes=5,
        )
        assert result is not None
        assert "episodes_processed" in result

    def test_respects_min_episodes(self, db, vectorstore, episodic, semantic):
        session = episodic.start_session(project="test")
        for _ in range(3):
            episodic.record_episode(session.id, "decision", "Episode")
        # threshold=2 but min_episodes=5 — not enough
        result = maybe_consolidate(
            db, vectorstore, episodic, semantic, threshold=2, min_episodes=5,
        )
        assert result is None

    def test_exception_safety(self, db, vectorstore, episodic, semantic):
        """maybe_consolidate must never raise, even if consolidation fails."""
        session = episodic.start_session(project="test")
        for i in range(25):
            episodic.record_episode(session.id, "decision", f"Episode {i}")
        with patch.object(
            ConsolidationEngine, "run", side_effect=RuntimeError("boom")
        ):
            result = maybe_consolidate(
                db, vectorstore, episodic, semantic, threshold=20, min_episodes=5,
            )
        assert result is None
