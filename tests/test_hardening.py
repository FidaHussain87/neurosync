"""Tests for production hardening: atomic init, vectorstore safety, degraded mode."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from neurosync.models import Episode, Session, Theory


# --- Phase 6: Atomic Server Initialization ---


class TestAtomicInit:
    def test_init_survives_chromadb_failure(self, config):
        """If VectorStore constructor throws, _init should still complete in degraded mode."""
        from neurosync.db import Database

        db = Database(config)
        db.close()

        import neurosync.mcp_server as srv
        # Reset server state
        srv._db = None
        srv._vs = None
        srv._config = None

        with patch("neurosync.mcp_server.VectorStore", side_effect=RuntimeError("ChromaDB broken")):
            srv._init()
            # DB should be initialized
            assert srv._db is not None
            # VectorStore should be None (degraded)
            assert srv._vs is None
            # Engines that don't require vs should still work
            assert srv._episodic is not None
            assert srv._semantic is not None
            assert srv._causal is not None
            # Analogy requires vs, so should be None
            assert srv._analogy is None

        # Cleanup
        srv._db.close()
        srv._db = None
        srv._vs = None
        srv._config = None

    def test_init_atomic_on_db_failure(self, config):
        """If Database constructor throws, globals should remain None."""
        import neurosync.mcp_server as srv
        srv._db = None
        srv._vs = None
        srv._config = None

        with patch("neurosync.mcp_server.Database", side_effect=RuntimeError("SQLite broken")):
            with pytest.raises(RuntimeError):
                srv._init()
            # Nothing should have been assigned
            assert srv._db is None
            assert srv._vs is None


# --- Phase 7: VectorStore Hardening ---


class TestVectorStoreHardening:
    def test_truncation_long_content(self, vectorstore):
        """Content longer than MAX_EMBED_CHARS should be truncated."""
        from neurosync.vectorstore import MAX_EMBED_CHARS

        long_text = "x" * (MAX_EMBED_CHARS + 1000)
        result = vectorstore._safe_document(long_text)
        assert len(result) == MAX_EMBED_CHARS

    def test_truncation_short_content(self, vectorstore):
        """Short content should pass through unchanged."""
        short_text = "hello world"
        result = vectorstore._safe_document(short_text)
        assert result == short_text

    def test_search_returns_empty_on_error(self, config):
        """If ChromaDB query fails, search methods should return empty list."""
        from unittest.mock import MagicMock

        from neurosync.vectorstore import VectorStore

        vs = VectorStore(config)
        # Replace with a mock that raises
        vs._episodes = MagicMock()
        vs._episodes.count.side_effect = RuntimeError("ChromaDB corrupt")
        result = vs.search_episodes("test query")
        assert result == []

    def test_search_theories_returns_empty_on_error(self, config):
        from neurosync.vectorstore import VectorStore
        from unittest.mock import MagicMock

        vs = VectorStore(config)
        vs._theories = MagicMock()
        vs._theories.count.side_effect = RuntimeError("ChromaDB corrupt")
        result = vs.search_theories("test query")
        assert result == []

    def test_search_failures_returns_empty_on_error(self, config):
        from neurosync.vectorstore import VectorStore
        from unittest.mock import MagicMock

        vs = VectorStore(config)
        vs._failures = MagicMock()
        vs._failures.count.side_effect = RuntimeError("ChromaDB corrupt")
        result = vs.search_failures("test query")
        assert result == []


# --- Phase 8: Degraded Mode in Memory Layers ---


class TestDegradedMode:
    def test_episodic_record_without_vectorstore(self, db):
        """EpisodicMemory should record episodes to SQLite even without VectorStore."""
        from neurosync.episodic import EpisodicMemory

        episodic = EpisodicMemory(db, vectorstore=None)
        session = episodic.start_session(project="test")
        episode = episodic.record_episode(
            session_id=session.id,
            event_type="decision",
            content="Test without vector store",
        )
        assert episode.id is not None
        loaded = episodic.get_episode(episode.id)
        assert loaded is not None
        assert loaded.content == "Test without vector store"

    def test_episodic_search_without_vectorstore(self, db):
        """Search should return empty when vectorstore is None."""
        from neurosync.episodic import EpisodicMemory

        episodic = EpisodicMemory(db, vectorstore=None)
        results = episodic.search("anything")
        assert results == []

    def test_episodic_decay_without_vectorstore(self, db):
        """decay_episodes should still mark in SQLite without vectorstore."""
        from neurosync.episodic import EpisodicMemory

        episodic = EpisodicMemory(db, vectorstore=None)
        session = episodic.start_session()
        ep = episodic.record_episode(session_id=session.id, event_type="decision", content="test")
        # Should not raise
        episodic.decay_episodes([ep.id])

    def test_retrieval_recall_without_vectorstore(self, db):
        """RetrievalPipeline.recall should return empty result without vectorstore."""
        from neurosync.retrieval import RetrievalPipeline

        pipeline = RetrievalPipeline(db, vectorstore=None)
        result = pipeline.recall(project="test", context="anything")
        assert result["primary"] is None
        assert result["supporting"] == []

    def test_semantic_create_without_vectorstore(self, db):
        """SemanticMemory should create theories in SQLite without vectorstore."""
        from neurosync.semantic import SemanticMemory

        semantic = SemanticMemory(db, vectorstore=None)
        theory = semantic.create_theory(content="Test theory", scope="craft")
        assert theory.id is not None
        loaded = semantic.get_theory(theory.id)
        assert loaded is not None
        assert loaded.content == "Test theory"

    def test_semantic_search_without_vectorstore(self, db):
        from neurosync.semantic import SemanticMemory

        semantic = SemanticMemory(db, vectorstore=None)
        results = semantic.search("anything")
        assert results == []

    def test_semantic_retire_without_vectorstore(self, db):
        from neurosync.semantic import SemanticMemory

        semantic = SemanticMemory(db, vectorstore=None)
        theory = semantic.create_theory(content="Retire me")
        retired = semantic.retire_theory(theory.id)
        assert retired is not None
        assert retired.active is False

    def test_consolidation_without_vectorstore(self, db):
        """ConsolidationEngine should work (single cluster) without vectorstore."""
        from neurosync.consolidation import ConsolidationEngine
        from neurosync.episodic import EpisodicMemory
        from neurosync.semantic import SemanticMemory

        episodic = EpisodicMemory(db, vectorstore=None)
        semantic = SemanticMemory(db, vectorstore=None)
        session = episodic.start_session(project="test")
        for i in range(6):
            episodic.record_episode(
                session_id=session.id,
                event_type="decision",
                content=f"Decision {i}: chose approach {i}",
            )
        engine = ConsolidationEngine(db, None, episodic, semantic, min_episodes=3)
        result = engine.run(dry_run=True)
        assert "episodes_processed" in result
        assert result["episodes_processed"] >= 6

    def test_failure_model_without_vectorstore(self, db):
        from neurosync.failure import FailureModel

        fm = FailureModel(db, vectorstore=None)
        record = fm.record_failure(what_failed="test failure", why_failed="test reason")
        assert record.id is not None
        # Search should return empty
        results = fm.search_failures("test")
        assert results == []
        # Warnings should return empty
        warnings = fm.check_for_warnings("test context")
        assert warnings == []

    def test_hierarchy_without_vectorstore(self, db):
        from neurosync.hierarchy import TheoryHierarchy
        from neurosync.semantic import SemanticMemory

        semantic = SemanticMemory(db, vectorstore=None)
        hierarchy = TheoryHierarchy(db, vectorstore=None)
        t1 = semantic.create_theory(content="Parent theory")
        t2 = semantic.create_theory(content="Child theory")
        # find_semantic_parent should return None without vs
        parent = hierarchy.find_semantic_parent(t2.id)
        assert parent is None
        # detect_merge_candidates should return empty
        candidates = hierarchy.detect_merge_candidates()
        assert candidates == []
        # promote_to_parent should still work (SQLite only)
        promoted = hierarchy.promote_to_parent([t2.id], "Abstract parent")
        assert promoted is not None

    def test_forgetting_without_vectorstore(self, db):
        from neurosync.episodic import EpisodicMemory
        from neurosync.forgetting import ForgettingEngine

        episodic = EpisodicMemory(db, vectorstore=None)
        forgetting = ForgettingEngine(db, vectorstore=None)
        # Should not raise
        result = forgetting.run_forgetting_pass()
        assert "episodes_pruned" in result
        assert "theories_decayed" in result

    def test_retrieval_without_vectorstore(self, db):
        from neurosync.retrieval import RetrievalPipeline

        pipeline = RetrievalPipeline(db, vectorstore=None)
        result = pipeline.recall(project="test", context="anything")
        assert result["primary"] is None
        assert result["theories_considered"] == 0
