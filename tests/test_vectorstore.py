"""Tests for vectorstore.py — ChromaDB operations."""

from __future__ import annotations

from neurosync.models import Episode, Theory


class TestVectorStore:
    def test_initial_stats(self, vectorstore):
        stats = vectorstore.stats()
        assert stats["episodes"] == 0
        assert stats["theories"] == 0
        assert stats["failures"] == 0

    def test_add_and_search_episode(self, vectorstore):
        ep = Episode(
            id="ep-001",
            session_id="s1",
            content="Implemented REST API endpoint for user authentication",
            event_type="decision",
        )
        vectorstore.add_episode(ep, project="myproject")
        assert vectorstore.stats()["episodes"] == 1
        results = vectorstore.search_episodes("authentication API", n_results=5)
        assert len(results) >= 1
        assert results[0]["id"] == "ep-001"

    def test_add_empty_episode_skipped(self, vectorstore):
        ep = Episode(id="ep-empty", session_id="s1", content="   ")
        vectorstore.add_episode(ep)
        assert vectorstore.stats()["episodes"] == 0

    def test_remove_episodes(self, vectorstore):
        ep = Episode(id="ep-rm", session_id="s1", content="Remove me")
        vectorstore.add_episode(ep)
        assert vectorstore.stats()["episodes"] == 1
        vectorstore.remove_episodes(["ep-rm"])
        assert vectorstore.stats()["episodes"] == 0

    def test_remove_nonexistent_episode(self, vectorstore):
        vectorstore.remove_episodes(["nonexistent-id"])

    def test_add_and_search_theory(self, vectorstore):
        theory = Theory(
            id="th-001",
            content="Always validate user input at service boundaries",
            scope="craft",
            confidence=0.8,
        )
        vectorstore.add_theory(theory)
        assert vectorstore.stats()["theories"] == 1
        results = vectorstore.search_theories("input validation", n_results=5)
        assert len(results) >= 1
        assert results[0]["id"] == "th-001"

    def test_remove_theory(self, vectorstore):
        theory = Theory(id="th-rm", content="Remove this theory")
        vectorstore.add_theory(theory)
        vectorstore.remove_theory("th-rm")
        assert vectorstore.stats()["theories"] == 0

    def test_search_empty_collection(self, vectorstore):
        assert vectorstore.search_episodes("anything") == []
        assert vectorstore.search_theories("anything") == []

    def test_reset(self, vectorstore):
        vectorstore.add_episode(Episode(id="e1", session_id="s1", content="test"))
        vectorstore.add_theory(Theory(id="t1", content="test theory"))
        vectorstore.reset()
        assert vectorstore.stats()["episodes"] == 0
        assert vectorstore.stats()["theories"] == 0

    def test_episode_causal_metadata(self, vectorstore):
        ep = Episode(
            id="ep-causal", session_id="s1",
            content="Applied theory because context matched",
            cause="context matched", quality_score=5,
        )
        vectorstore.add_episode(ep, project="test")
        results = vectorstore.search_episodes("theory context", n_results=1)
        assert len(results) >= 1
        meta = results[0]["metadata"]
        assert meta.get("has_causal") == 1
        assert meta.get("quality_score") == 5

    def test_theory_validation_metadata(self, vectorstore):
        theory = Theory(
            id="th-val", content="Validated theory content",
            validation_status="confirmed", application_count=3,
        )
        vectorstore.add_theory(theory)
        results = vectorstore.search_theories("validated theory", n_results=1)
        assert len(results) >= 1
        meta = results[0]["metadata"]
        assert meta.get("validation_status") == "confirmed"
        assert meta.get("application_count") == 3

    def test_add_episode_with_fingerprint(self, vectorstore):
        """Fingerprint should be stored in ChromaDB episode metadata."""
        ep = Episode(
            id="ep-fp", session_id="s1",
            content="Cache invalidation caused stale data",
            structural_fingerprint="caching,data_consistency",
        )
        vectorstore.add_episode(ep, project="test")
        results = vectorstore.search_episodes("cache invalidation", n_results=1)
        assert len(results) >= 1
        meta = results[0]["metadata"]
        assert meta.get("structural_fingerprint") == "caching,data_consistency"

    def test_add_theory_with_fingerprint(self, vectorstore):
        """Fingerprint should be stored in ChromaDB theory metadata."""
        theory = Theory(
            id="th-fp", content="Retry logic with exponential backoff",
            structural_fingerprint="retry_logic",
        )
        vectorstore.add_theory(theory)
        results = vectorstore.search_theories("retry backoff", n_results=1)
        assert len(results) >= 1
        meta = results[0]["metadata"]
        assert meta.get("structural_fingerprint") == "retry_logic"
