"""Tests for the Cognitive Lensing Protocol — minimal-token knowledge compression."""

import pytest

from neurosync.lensing import (
    CognitiveLens,
    Lens,
    LensSet,
    compress_correction,
    compress_failure,
    compress_theory,
    compute_prior_alignment,
    detect_drift_warnings,
    estimate_lens_tokens,
    is_llm_prior_novel,
    optimize_lens_set,
)
from neurosync.models import Episode, FailureRecord, Theory, _new_id


class TestEpistemicDelta:
    """Tests for prior alignment and novelty estimation."""

    def test_high_contradiction_low_alignment(self):
        theory = Theory(
            content="Always use threading.Lock",
            contradiction_count=5,
            confirmation_count=2,
        )
        pa = compute_prior_alignment(theory)
        assert pa < 0.5

    def test_high_confirmation_high_alignment(self):
        theory = Theory(
            content="Validate all user input",
            contradiction_count=0,
            confirmation_count=10,
        )
        pa = compute_prior_alignment(theory)
        assert pa > 0.8

    def test_novel_project_specific(self):
        theory = Theory(
            content="In src/auth/handler.py always use PKCE flow",
            metadata={"scope": "project"},
        )
        novelty = is_llm_prior_novel(theory)
        assert novelty < 0.5  # Low = novel to LLM

    def test_common_practice_not_novel(self):
        theory = Theory(
            content="Always validate input and handle errors properly",
        )
        novelty = is_llm_prior_novel(theory)
        assert novelty > 0.6  # High = LLM already knows this

    def test_never_override_is_novel(self):
        theory = Theory(
            content="Never use setTimeout for retry logic",
        )
        novelty = is_llm_prior_novel(theory)
        assert novelty < 0.5


class TestImperativeCompression:
    """Tests for theory/failure/correction compression into lenses."""

    def test_compress_theory_negation(self):
        theory = Theory(
            id="t1",
            content="Never throw exceptions in this codebase, always return Result types",
            confidence=0.9,
            scope_qualifier="payments",
        )
        lens = compress_theory(theory)
        assert lens.id == "t1"
        assert "NEVER" in lens.imperative
        assert lens.confidence == 0.9

    def test_compress_theory_requirement(self):
        theory = Theory(
            id="t2",
            content="Must use transactions for all database writes in the order service",
            confidence=0.85,
        )
        lens = compress_theory(theory)
        assert "MUST" in lens.imperative

    def test_compress_failure(self):
        failure = FailureRecord(
            id=1,
            what_failed="Used mocks for DB tests",
            why_failed="Mock/prod divergence caused undetected migration bug",
            what_worked="Integration tests with real DB",
            severity=4,
            occurrence_count=3,
        )
        lens = compress_failure(failure)
        assert "AVOID" in lens.imperative or "NEVER" in lens.imperative
        assert lens.source_type == "failure"
        assert lens.behavioral_impact > 0

    def test_compress_correction(self):
        lens = compress_correction(
            content="Was told X but correct is Y",
            what_wrong="using threading.Lock",
            what_right="use asyncio.Lock instead",
        )
        assert "NEVER" in lens.imperative or "MUST" in lens.imperative
        assert lens.source_type == "correction"

    def test_token_estimation(self):
        assert estimate_lens_tokens("NEVER throw") > 0
        assert estimate_lens_tokens("a" * 40) > estimate_lens_tokens("short")
        assert estimate_lens_tokens("") == 1


class TestOptimization:
    """Tests for knapsack-based lens selection."""

    def test_respects_budget(self):
        lenses = [
            Lens(id=f"l{i}", context="ctx", imperative=f"MUST do thing {i}",
                 confidence=0.8, scope="", source_type="theory",
                 token_cost=10, behavioral_impact=float(i),
                 prior_alignment=0.3)
            for i in range(10)
        ]
        result = optimize_lens_set(lenses, token_budget=30, max_lenses=10)
        assert result.total_tokens <= 30

    def test_selects_highest_impact(self):
        low = Lens(id="low", context="", imperative="x", confidence=0.5,
                   scope="", source_type="theory", token_cost=10,
                   behavioral_impact=0.1, prior_alignment=0.3)
        high = Lens(id="high", context="", imperative="y", confidence=0.9,
                    scope="", source_type="theory", token_cost=10,
                    behavioral_impact=5.0, prior_alignment=0.1)
        result = optimize_lens_set([low, high], token_budget=15)
        assert len(result.lenses) == 1
        assert result.lenses[0].id == "high"

    def test_empty_candidates(self):
        result = optimize_lens_set([], token_budget=80)
        assert result.lenses == []
        assert result.total_tokens == 0

    def test_max_lenses_cap(self):
        lenses = [
            Lens(id=f"l{i}", context="", imperative="x", confidence=0.8,
                 scope="", source_type="theory", token_cost=1,
                 behavioral_impact=1.0, prior_alignment=0.3)
            for i in range(20)
        ]
        result = optimize_lens_set(lenses, token_budget=1000, max_lenses=5)
        assert len(result.lenses) <= 5


class TestDriftWarnings:
    """Tests for detecting systematic LLM blind spots."""

    def test_detects_high_contradiction_theory(self):
        theories = [
            Theory(content="Use asyncio.Lock not threading.Lock",
                   contradiction_count=4, confirmation_count=2, active=True),
        ]
        warnings = detect_drift_warnings(theories)
        assert len(warnings) >= 1

    def test_no_warnings_for_stable_theories(self):
        theories = [
            Theory(content="Use type hints", contradiction_count=0,
                   confirmation_count=10, active=True),
        ]
        warnings = detect_drift_warnings(theories)
        assert len(warnings) == 0


class TestCognitiveLensPipeline:
    """Integration tests for the full pipeline."""

    def test_full_pipeline(self):
        theories = [
            Theory(id="t1", content="Never use eval() for config parsing",
                   confidence=0.9, contradiction_count=3, confirmation_count=8, active=True),
            Theory(id="t2", content="Must wrap DB calls in transactions",
                   confidence=0.8, contradiction_count=0, confirmation_count=5, active=True),
        ]

        class FakeDB:
            pass

        engine = CognitiveLens(FakeDB())
        result = engine.generate_lens_set(theories=theories, token_budget=80)
        assert isinstance(result, LensSet)
        assert result.total_tokens <= 80
        assert result.total_tokens > 0

    def test_pipeline_filters_high_prior(self):
        theories = [
            Theory(id="t1", content="Always validate input before processing",
                   confidence=0.9, contradiction_count=0, confirmation_count=20, active=True),
        ]

        class FakeDB:
            pass

        engine = CognitiveLens(FakeDB())
        result = engine.generate_lens_set(theories=theories, token_budget=80)
        # Common practice + high confirmation = high prior alignment = filtered
        assert len(result.lenses) == 0

    def test_pipeline_includes_corrections(self):
        theories: list[Theory] = []
        corrections = [
            Episode(
                id="ep1", event_type="correction",
                content="CORRECTION: Was told 'use print debugging' but correct answer is 'use proper logging with structlog'",
            ),
        ]

        class FakeDB:
            pass

        engine = CognitiveLens(FakeDB())
        result = engine.generate_lens_set(
            theories=theories, corrections=corrections, token_budget=80
        )
        assert len(result.lenses) >= 1
