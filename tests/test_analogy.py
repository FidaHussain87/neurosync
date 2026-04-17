"""Tests for analogy.py — structural fingerprinting, combined search, multi-hop."""

from __future__ import annotations

from neurosync.analogy import AnalogyEngine, StructuralFingerprint
from neurosync.models import Episode, Session, Theory


class TestStructuralFingerprint:
    def test_fingerprint_race_condition(self):
        fp = StructuralFingerprint(["race_condition"])
        assert "race_condition" in fp.patterns

    def test_fingerprint_caching(self):
        fp = StructuralFingerprint(["caching"])
        assert "caching" in fp.patterns

    def test_fingerprint_empty(self):
        fp = StructuralFingerprint([])
        assert len(fp.patterns) == 0

    def test_fingerprint_multiple(self):
        fp = StructuralFingerprint(["caching", "retry_logic"])
        assert len(fp.patterns) == 2

    def test_similarity_identical(self):
        fp1 = StructuralFingerprint(["caching", "retry_logic"])
        fp2 = StructuralFingerprint(["caching", "retry_logic"])
        assert fp1.similarity(fp2) == 1.0

    def test_similarity_disjoint(self):
        fp1 = StructuralFingerprint(["caching"])
        fp2 = StructuralFingerprint(["auth_permission"])
        assert fp1.similarity(fp2) == 0.0

    def test_similarity_partial(self):
        fp1 = StructuralFingerprint(["caching", "retry_logic"])
        fp2 = StructuralFingerprint(["caching", "error_handling"])
        sim = fp1.similarity(fp2)
        # Jaccard: {caching} / {caching, retry_logic, error_handling} = 1/3
        assert abs(sim - 1.0 / 3.0) < 0.01

    def test_similarity_both_empty(self):
        fp1 = StructuralFingerprint([])
        fp2 = StructuralFingerprint([])
        assert fp1.similarity(fp2) == 0.0

    def test_to_string_roundtrip(self):
        fp = StructuralFingerprint(["caching", "retry_logic"])
        s = fp.to_string()
        restored = StructuralFingerprint.from_string(s)
        assert fp == restored

    def test_from_string_empty(self):
        fp = StructuralFingerprint.from_string("")
        assert len(fp.patterns) == 0


class TestAnalogyEngine:
    def _setup(self, db, vectorstore):
        session = Session(project="test")
        db.save_session(session)
        engine = AnalogyEngine(db, vectorstore)
        return session, engine

    def test_fingerprint_detects_caching(self, db, vectorstore):
        _, engine = self._setup(db, vectorstore)
        fp = engine.fingerprint("The stale cache caused TTL issues in the system")
        assert "caching" in fp.patterns

    def test_fingerprint_detects_retry(self, db, vectorstore):
        _, engine = self._setup(db, vectorstore)
        fp = engine.fingerprint("Added exponential backoff retry logic for API calls")
        assert "retry_logic" in fp.patterns

    def test_fingerprint_detects_multiple(self, db, vectorstore):
        _, engine = self._setup(db, vectorstore)
        fp = engine.fingerprint("Cache invalidation with retry backoff on API version change")
        assert "caching" in fp.patterns
        assert "retry_logic" in fp.patterns

    def test_fingerprint_no_match(self, db, vectorstore):
        _, engine = self._setup(db, vectorstore)
        fp = engine.fingerprint("Simple variable assignment in loop")
        assert len(fp.patterns) == 0

    def test_find_analogies_combined(self, db, vectorstore):
        """find_analogies should return results with combined scores."""
        session, engine = self._setup(db, vectorstore)
        # Add some theories with different structural patterns
        t1 = Theory(content="Cache invalidation is hard, TTL must be managed carefully")
        t2 = Theory(content="Retry with exponential backoff for flaky API calls")
        t3 = Theory(content="Simple variable naming conventions")
        db.save_theory(t1)
        db.save_theory(t2)
        db.save_theory(t3)
        vectorstore.add_theory(t1)
        vectorstore.add_theory(t2)
        vectorstore.add_theory(t3)
        results = engine.find_analogies("stale cache TTL problems", n_results=3)
        assert len(results) > 0
        assert all("combined_score" in r for r in results)

    def test_multi_hop(self, db, vectorstore):
        """multi_hop_search should return deduplicated results across hops."""
        session, engine = self._setup(db, vectorstore)
        t1 = Theory(content="Cache invalidation requires careful TTL management")
        t2 = Theory(content="TTL expiry leads to stale data consistency issues")
        db.save_theory(t1)
        db.save_theory(t2)
        vectorstore.add_theory(t1)
        vectorstore.add_theory(t2)
        results = engine.multi_hop_search("cache problems", max_hops=2, n_per_hop=3)
        ids = [r["id"] for r in results]
        # No duplicates
        assert len(ids) == len(set(ids))

    def test_cross_project(self, db, vectorstore):
        """cross_project_analogies should exclude the current project."""
        session, engine = self._setup(db, vectorstore)
        t1 = Theory(content="Cache TTL patterns in storage", scope="project", scope_qualifier="proj-a")
        t2 = Theory(content="Cache TTL patterns in DNS", scope="project", scope_qualifier="proj-b")
        db.save_theory(t1)
        db.save_theory(t2)
        vectorstore.add_theory(t1)
        vectorstore.add_theory(t2)
        results = engine.cross_project_analogies("cache TTL", current_project="proj-a", n_results=5)
        for r in results:
            assert r.get("metadata", {}).get("scope_qualifier", "") != "proj-a"
