"""Tests for working.py — Layer 3 working memory."""

from __future__ import annotations


class TestWorkingMemory:
    def test_empty_recall(self, working):
        result = working.recall()
        assert result["primary"] is None
        assert result["supporting"] == []
        assert result["recent_episodes"] == []

    def test_recall_with_theories(self, working, semantic, episodic):
        semantic.create_theory(
            content="Always use WAL mode in SQLite for concurrent reads",
            scope="craft",
            confidence=0.9,
        )
        semantic.create_theory(
            content="Use pytest fixtures for test isolation",
            scope="craft",
            confidence=0.7,
        )
        result = working.recall(context="SQLite database setup")
        assert result["primary"] is not None
        assert result["tokens_used"] > 0

    def test_recall_with_token_budget(self, working, semantic):
        for i in range(5):
            semantic.create_theory(
                content=f"Theory number {i} with some longer content to test token budgeting behavior",
                scope="craft",
                confidence=0.5 + i * 0.1,
            )
        result = working.recall(context="theory", max_tokens=50)
        # Should respect token budget
        assert result["tokens_used"] <= 60  # Small buffer for estimation

    def test_recall_filters_familiar_topics(self, working, semantic):
        semantic.create_theory(
            content="Python list comprehensions are faster than map/filter",
            scope="craft",
            confidence=0.9,
        )
        # With familiar topic filter
        result = working.recall(
            context="Python performance",
            user_familiar_topics={"python list comprehensions"},
        )
        # Theory should be filtered out
        if result["primary"]:
            assert "list comprehensions" not in result["primary"]["content"].lower()

    def test_build_query(self):
        from neurosync.working import WorkingMemory
        q = WorkingMemory._build_query("proj", "main", "fix bug")
        assert "project:proj" in q
        assert "branch:main" in q
        assert "fix bug" in q

    def test_estimate_tokens(self):
        from neurosync.working import WorkingMemory
        assert WorkingMemory._estimate_tokens("hello world") >= 1
        assert WorkingMemory._estimate_tokens("") == 1
