"""Tests for working.py — utility functions for recall context assembly."""

from __future__ import annotations

from neurosync.models import Theory
from neurosync.working import build_recall_query, estimate_tokens, format_theory_result


class TestBuildRecallQuery:
    def test_full_query(self):
        q = build_recall_query("proj", "main", "fix bug")
        assert "project:proj" in q
        assert "branch:main" in q
        assert "fix bug" in q

    def test_project_only(self):
        q = build_recall_query("proj", "", "")
        assert q == "project:proj"

    def test_empty(self):
        q = build_recall_query("", "", "")
        assert q == ""

    def test_context_only(self):
        q = build_recall_query("", "", "some context")
        assert q == "some context"


class TestEstimateTokens:
    def test_nonempty(self):
        assert estimate_tokens("hello world") >= 1

    def test_empty(self):
        assert estimate_tokens("") == 1

    def test_long_text(self):
        text = "a" * 400
        result = estimate_tokens(text)
        assert result >= 1
        assert result <= 400

    def test_proportional(self):
        short = estimate_tokens("hello")
        long = estimate_tokens("hello " * 100)
        assert long > short

    def test_fallback_when_tiktoken_unavailable(self):
        import neurosync.working as w

        old_encoder = w._encoder
        old_loaded = w._encoder_loaded
        w._encoder = None
        w._encoder_loaded = True
        try:
            assert estimate_tokens("a" * 400) == 100
        finally:
            w._encoder = old_encoder
            w._encoder_loaded = old_loaded


class TestFormatTheoryResult:
    def test_format(self):
        theory = Theory(
            content="Always use WAL mode",
            scope="craft",
            scope_qualifier="sqlite",
            confidence=0.85,
            validation_status="confirmed",
            application_count=3,
        )
        result = format_theory_result(theory, 0.7123456)
        assert result["content"] == "Always use WAL mode"
        assert result["scope"] == "craft"
        assert result["scope_qualifier"] == "sqlite"
        assert result["confidence"] == 0.85
        assert result["score"] == 0.7123
        assert result["validation_status"] == "confirmed"
        assert result["application_count"] == 3
        assert "id" in result
