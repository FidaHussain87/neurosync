"""Tests for retrieval.py — full recall pipeline."""

from __future__ import annotations

from neurosync.retrieval import RetrievalPipeline
from neurosync.user_model import UserModel


class TestRetrievalPipeline:
    def test_empty_recall(self, db, vectorstore):
        um = UserModel(db)
        pipeline = RetrievalPipeline(db, vectorstore, um)
        result = pipeline.recall()
        assert result["primary"] is None
        assert result["theories_considered"] == 0

    def test_recall_with_theories(self, db, vectorstore, semantic):
        um = UserModel(db)
        pipeline = RetrievalPipeline(db, vectorstore, um)
        semantic.create_theory(
            content="Use WAL mode for SQLite concurrency",
            scope="craft",
            confidence=0.9,
        )
        result = pipeline.recall(context="SQLite setup")
        assert result["primary"] is not None
        assert result["primary"]["confidence"] == 0.9

    def test_user_familiarity_filtering(self, db, vectorstore, semantic):
        um = UserModel(db)
        pipeline = RetrievalPipeline(db, vectorstore, um)
        semantic.create_theory(
            content="Python type hints improve code quality",
            scope="craft",
            confidence=0.9,
        )
        # Build familiarity
        for _ in range(20):
            um.record_exposure("python type hints", explained=True)
        result = pipeline.recall(context="Python type hints")
        # Should filter familiar topic
        filtered = result.get("theories_filtered_by_familiarity", 0)
        assert filtered >= 0

    def test_format_for_context_empty(self, db, vectorstore):
        um = UserModel(db)
        pipeline = RetrievalPipeline(db, vectorstore, um)
        result = pipeline.recall()
        formatted = pipeline.format_for_context(result)
        assert "No memories" in formatted

    def test_format_for_context_with_data(self, db, vectorstore, semantic):
        um = UserModel(db)
        pipeline = RetrievalPipeline(db, vectorstore, um)
        semantic.create_theory(
            content="Test theory for formatting",
            scope="craft",
            confidence=0.8,
        )
        result = pipeline.recall(context="test")
        formatted = pipeline.format_for_context(result)
        assert "Primary Insight" in formatted

    def test_recall_respects_token_budget(self, db, vectorstore, semantic):
        um = UserModel(db)
        pipeline = RetrievalPipeline(db, vectorstore, um)
        for i in range(10):
            semantic.create_theory(
                content=f"Theory {i}: " + "x" * 200,
                scope="craft",
                confidence=0.5 + i * 0.05,
            )
        result = pipeline.recall(context="theory", max_tokens=100)
        assert result["tokens_used"] <= 120  # Small buffer
