"""Tests for semantic.py — Layer 2 semantic memory."""

from __future__ import annotations

from neurosync.models import Episode, Session


class TestSemanticMemory:
    def test_create_theory(self, semantic):
        theory = semantic.create_theory(
            content="Validate inputs at service layer boundaries",
            scope="craft",
            confidence=0.6,
        )
        assert theory.id
        assert theory.confidence == 0.6
        assert theory.active is True

    def test_get_theory(self, semantic):
        theory = semantic.create_theory(content="Test theory")
        loaded = semantic.get_theory(theory.id)
        assert loaded is not None
        assert loaded.content == "Test theory"

    def test_list_theories(self, semantic):
        semantic.create_theory(content="t1", scope="craft")
        semantic.create_theory(content="t2", scope="project", scope_qualifier="proj-a")
        theories = semantic.list_theories()
        assert len(theories) == 2
        project_theories = semantic.list_theories(scope="project")
        assert len(project_theories) == 1

    def test_confirm_theory(self, semantic):
        theory = semantic.create_theory(content="test", confidence=0.5)
        confirmed = semantic.confirm_theory(theory.id, episode_id="ep1")
        assert confirmed.confirmation_count == 1
        assert confirmed.confidence > 0.5
        assert confirmed.last_confirmed is not None

    def test_contradict_theory(self, semantic, db):
        theory = semantic.create_theory(content="test", confidence=0.8)
        session = Session()
        db.save_session(session)
        ep = Episode(session_id=session.id, content="contradiction")
        db.save_episode(ep)
        contradiction = semantic.contradict_theory(theory.id, ep.id, "This is wrong")
        assert contradiction is not None
        assert contradiction.description == "This is wrong"
        loaded = semantic.get_theory(theory.id)
        assert loaded.confidence < 0.8
        assert loaded.contradiction_count == 1

    def test_supersede_theory(self, semantic):
        old = semantic.create_theory(content="old pattern")
        new = semantic.create_theory(content="new pattern")
        semantic.supersede_theory(old.id, new.id)
        loaded = semantic.get_theory(old.id)
        assert loaded.active is False
        assert loaded.superseded_by == new.id

    def test_retire_theory(self, semantic):
        theory = semantic.create_theory(content="to retire")
        retired = semantic.retire_theory(theory.id)
        assert retired.active is False
        loaded = semantic.get_theory(theory.id)
        assert loaded.active is False

    def test_retire_nonexistent(self, semantic):
        assert semantic.retire_theory("nonexistent") is None

    def test_search(self, semantic):
        semantic.create_theory(content="Always use WAL mode for SQLite concurrency")
        results = semantic.search("SQLite concurrency")
        assert len(results) >= 1

    def test_confidence_decay(self, semantic):
        # Create a theory with old last_confirmed date
        theory = semantic.create_theory(content="stale theory", confidence=0.7)
        theory.last_confirmed = "2020-01-01T00:00:00+00:00"
        from neurosync.db import Database
        semantic._db.save_theory(theory)
        affected = semantic.apply_confidence_decay(decay_days=30, decay_rate=0.01)
        assert affected >= 1
        loaded = semantic.get_theory(theory.id)
        assert loaded.confidence < 0.7
