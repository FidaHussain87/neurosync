"""Tests for vectorstore.py — ChromaDB operations."""

from __future__ import annotations

from neurosync.models import Episode, Theory


class TestVectorStore:
    def test_initial_stats(self, vectorstore):
        stats = vectorstore.stats()
        assert stats["episodes"] == 0
        assert stats["theories"] == 0

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
