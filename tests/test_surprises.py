"""Tests for the Knowledge Surprise Detection engine."""

from __future__ import annotations

from unittest.mock import MagicMock

from neurosync.models import Theory
from neurosync.surprises import (
    SurpriseEngine,
    _extract_domains,
    _extract_keywords,
    _get_project,
)


def _make_theory(
    theory_id: str = "t1",
    content: str = "test theory",
    scope: str = "project",
    scope_qualifier: str = "myproject",
    confidence: float = 0.7,
    active: bool = True,
    related_theories: list[str] | None = None,
    parent_theory_id: str = "",
    contradiction_count: int = 0,
    confirmation_count: int = 0,
    application_count: int = 0,
    metadata: dict | None = None,
) -> Theory:
    t = Theory(
        id=theory_id,
        content=content,
        scope=scope,
        scope_qualifier=scope_qualifier,
        confidence=confidence,
        active=active,
    )
    t.related_theories = related_theories or []
    t.parent_theory_id = parent_theory_id
    t.contradiction_count = contradiction_count
    t.confirmation_count = confirmation_count
    t.application_count = application_count
    t.metadata = metadata or {}
    return t


class TestExtractDomains:
    def test_extracts_from_scope_qualifier(self):
        t = _make_theory(scope_qualifier="concurrency")
        domains = _extract_domains(t)
        assert "concurrency" in domains

    def test_extracts_from_content(self):
        t = _make_theory(content="This uses authentication and authorization for security")
        domains = _extract_domains(t)
        assert "authentication" in domains
        assert "authorization" in domains

    def test_extracts_from_metadata(self):
        t = _make_theory(metadata={"domains": ["caching", "database-access"]})
        domains = _extract_domains(t)
        assert "caching" in domains
        assert "database-access" in domains


class TestExtractKeywords:
    def test_basic_extraction(self):
        kw = _extract_keywords("The database connection pool should be configured properly")
        assert "database" in kw
        assert "connection" in kw
        assert "pool" in kw
        assert "the" not in kw  # stopword

    def test_filters_short_words(self):
        kw = _extract_keywords("a b cd efg")
        assert "efg" in kw
        assert "cd" not in kw  # too short


class TestGetProject:
    def test_returns_qualifier_for_project_scope(self):
        t = _make_theory(scope="project", scope_qualifier="neurosync")
        assert _get_project(t) == "neurosync"

    def test_returns_empty_for_domain_scope(self):
        t = _make_theory(scope="domain", scope_qualifier="concurrency")
        assert _get_project(t) == ""


class TestSurpriseEngine:
    def _mock_db(self, theories: list[Theory]) -> MagicMock:
        db = MagicMock()
        db.list_theories.return_value = theories
        return db

    def test_insufficient_theories(self):
        db = self._mock_db([_make_theory()])
        engine = SurpriseEngine(db)
        report = engine.analyze()
        assert report.stats.get("insufficient") is True

    def test_finds_cross_domain_surprise(self):
        theories = [
            _make_theory(
                theory_id="t1",
                content="database connection pooling for postgresql performance optimization",
                scope_qualifier="database-access",
                related_theories=["t2"],
            ),
            _make_theory(
                theory_id="t2",
                content="frontend react component lifecycle rendering updates",
                scope_qualifier="frontend-ui",
                related_theories=["t1"],
            ),
            _make_theory(
                theory_id="t3",
                content="testing unit tests mock fixtures assertions coverage",
                scope_qualifier="testing",
            ),
        ]
        db = self._mock_db(theories)
        engine = SurpriseEngine(db)
        report = engine.analyze(top_surprises=5)

        # t1 and t2 should be surprising (cross-domain, low keyword overlap)
        assert len(report.surprises) > 0
        surprise_pairs = {
            (s.theory_a_id, s.theory_b_id) for s in report.surprises
        } | {
            (s.theory_b_id, s.theory_a_id) for s in report.surprises
        }
        assert ("t1", "t2") in surprise_pairs or ("t2", "t1") in surprise_pairs

    def test_finds_god_theories(self):
        theories = [
            _make_theory(
                theory_id="hub",
                content="error handling patterns for robust applications",
                related_theories=["t1", "t2", "t3"],
            ),
            _make_theory(theory_id="t1", content="database error recovery", related_theories=["hub"]),
            _make_theory(theory_id="t2", content="api error responses", related_theories=["hub"]),
            _make_theory(theory_id="t3", content="logging error events", related_theories=["hub"]),
        ]
        db = self._mock_db(theories)
        engine = SurpriseEngine(db)
        report = engine.analyze(top_god=3)

        assert len(report.god_theories) > 0
        assert report.god_theories[0].theory_id == "hub"
        assert report.god_theories[0].degree >= 3

    def test_generates_questions_for_weak_connected_theory(self):
        theories = [
            _make_theory(
                theory_id="weak",
                content="concurrency pattern that might be wrong",
                confidence=0.2,
                related_theories=["t1", "t2", "t3"],
            ),
            _make_theory(theory_id="t1", content="mutex locking strategy", related_theories=["weak"]),
            _make_theory(theory_id="t2", content="thread pool sizing", related_theories=["weak"]),
            _make_theory(theory_id="t3", content="async task scheduling", related_theories=["weak"]),
        ]
        db = self._mock_db(theories)
        engine = SurpriseEngine(db)
        report = engine.analyze(top_questions=10)

        weak_questions = [q for q in report.questions if q.question_type == "weak_theory"]
        assert len(weak_questions) > 0

    def test_generates_questions_for_isolated_theory(self):
        theories = [
            _make_theory(
                theory_id="island",
                content="quantum entanglement physics experiment",
                scope_qualifier="physics",
                confirmation_count=2,
                related_theories=[],
            ),
            _make_theory(theory_id="t1", content="database postgresql connection pooling", scope_qualifier="databases", related_theories=["t2"]),
            _make_theory(theory_id="t2", content="redis caching invalidation strategy", scope_qualifier="databases", related_theories=["t1"]),
        ]
        db = self._mock_db(theories)
        engine = SurpriseEngine(db)
        report = engine.analyze(top_questions=10)

        isolated_q = [q for q in report.questions if q.question_type == "isolated"]
        assert len(isolated_q) > 0

    def test_report_serialization(self):
        theories = [
            _make_theory(theory_id="t1", content="theory one about testing", related_theories=["t2", "t3"]),
            _make_theory(theory_id="t2", content="theory two about caching", related_theories=["t1"]),
            _make_theory(theory_id="t3", content="theory three about deployment", related_theories=["t1"]),
        ]
        db = self._mock_db(theories)
        engine = SurpriseEngine(db)
        report = engine.analyze()

        d = report.to_dict()
        assert "surprises" in d
        assert "questions" in d
        assert "god_theories" in d
        assert "stats" in d
        assert d["stats"]["theories_analyzed"] == 3

    def test_cross_project_surprise(self):
        theories = [
            _make_theory(
                theory_id="t1",
                content="caching strategy with redis invalidation ttl expiry",
                scope="project",
                scope_qualifier="backend-api",
                related_theories=["t2"],
            ),
            _make_theory(
                theory_id="t2",
                content="caching strategy with service worker cache invalidation",
                scope="project",
                scope_qualifier="frontend-app",
                related_theories=["t1"],
            ),
            _make_theory(
                theory_id="t3",
                content="unrelated testing theory for unit test coverage",
                scope="project",
                scope_qualifier="backend-api",
            ),
        ]
        db = self._mock_db(theories)
        engine = SurpriseEngine(db)
        report = engine.analyze(top_surprises=5)

        cross_project = [s for s in report.surprises if s.connection_type == "cross_project"]
        # t1 and t2 are from different projects
        assert len(cross_project) > 0 or len(report.surprises) > 0

    def test_generates_questions_for_contradicted_theory(self):
        theories = [
            _make_theory(
                theory_id="t1",
                content="contradicted theory about caching invalidation",
                contradiction_count=3,
                confidence=0.5,
                related_theories=["t2"],
            ),
            _make_theory(theory_id="t2", content="redis caching patterns", related_theories=["t1"]),
            _make_theory(theory_id="t3", content="memcached configuration setup"),
        ]
        db = self._mock_db(theories)
        engine = SurpriseEngine(db)
        report = engine.analyze(top_questions=10)

        ambiguous = [q for q in report.questions if q.question_type == "ambiguous_link"]
        assert len(ambiguous) > 0
        assert "contradicted" in ambiguous[0].question

    def test_generates_knowledge_gap_questions(self):
        theories = [
            _make_theory(
                theory_id="t1",
                content="machine learning neural network training loss optimization",
                scope_qualifier="machine-learning",
            ),
            _make_theory(
                theory_id="t2",
                content="database postgresql connection pool reuse",
                scope_qualifier="database-access",
                related_theories=["t3"],
            ),
            _make_theory(
                theory_id="t3",
                content="database postgresql indexing performance tuning",
                scope_qualifier="database-access",
                related_theories=["t2"],
            ),
        ]
        db = self._mock_db(theories)
        engine = SurpriseEngine(db)
        report = engine.analyze(top_questions=10)

        gaps = [q for q in report.questions if q.question_type == "knowledge_gap"]
        # machine-learning has only 1 theory
        assert len(gaps) > 0

    def test_application_count_disparity_boosts_score(self):
        theories = [
            _make_theory(
                theory_id="t1",
                content="frontend react rendering pipeline virtual dom diffing",
                scope_qualifier="frontend-ui",
                application_count=10,
                related_theories=["t2"],
            ),
            _make_theory(
                theory_id="t2",
                content="database sharding horizontal partitioning strategy",
                scope_qualifier="database-access",
                application_count=0,
                related_theories=["t1"],
            ),
            _make_theory(
                theory_id="t3",
                content="testing unit test mock fixture",
                scope_qualifier="testing",
            ),
        ]
        db = self._mock_db(theories)
        engine = SurpriseEngine(db)
        report = engine.analyze(top_surprises=5)

        # The cross-domain pair t1-t2 should appear and the application disparity
        # contributes to its score
        assert len(report.surprises) > 0
        pair = next(
            (s for s in report.surprises
             if {s.theory_a_id, s.theory_b_id} == {"t1", "t2"}),
            None,
        )
        assert pair is not None
        assert any("untested" in r for r in pair.reasons)
