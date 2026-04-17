"""Tests for db.py — SQLite database operations."""

from __future__ import annotations

from neurosync.models import (
    Contradiction,
    Episode,
    Session,
    Signal,
    Theory,
    UserKnowledge,
)


class TestDatabase:
    def test_schema_initialized(self, db):
        stats = db.stats()
        assert stats["schema_version"] == 1
        assert stats["sessions"] == 0

    def test_save_and_get_session(self, db):
        session = Session(project="test-project", branch="main")
        db.save_session(session)
        loaded = db.get_session(session.id)
        assert loaded is not None
        assert loaded.project == "test-project"
        assert loaded.branch == "main"

    def test_list_sessions(self, db):
        db.save_session(Session(project="proj-a"))
        db.save_session(Session(project="proj-b"))
        db.save_session(Session(project="proj-a"))
        all_sessions = db.list_sessions()
        assert len(all_sessions) == 3
        proj_a = db.list_sessions(project="proj-a")
        assert len(proj_a) == 2

    def test_save_and_get_episode(self, db):
        session = Session()
        db.save_session(session)
        episode = Episode(
            session_id=session.id,
            event_type="decision",
            content="Chose REST over GraphQL",
            files_touched=["api.py"],
            layers_touched=["service"],
        )
        db.save_episode(episode)
        loaded = db.get_episode(episode.id)
        assert loaded is not None
        assert loaded.content == "Chose REST over GraphQL"
        assert loaded.files_touched == ["api.py"]
        assert loaded.signal_weight == 1.0

    def test_list_episodes_with_filters(self, db):
        session = Session()
        db.save_session(session)
        db.save_episode(Episode(session_id=session.id, event_type="decision", content="d1"))
        db.save_episode(Episode(session_id=session.id, event_type="correction", content="c1"))
        db.save_episode(Episode(session_id=session.id, event_type="decision", content="d2", consolidated=1))
        all_eps = db.list_episodes()
        assert len(all_eps) == 3
        decisions = db.list_episodes(event_type="decision")
        assert len(decisions) == 2
        pending = db.list_episodes(consolidated=0)
        assert len(pending) == 2

    def test_count_episodes(self, db):
        session = Session()
        db.save_session(session)
        db.save_episode(Episode(session_id=session.id, content="a"))
        db.save_episode(Episode(session_id=session.id, content="b"))
        assert db.count_episodes() == 2
        assert db.count_episodes(consolidated=0) == 2

    def test_mark_episodes_consolidated(self, db):
        session = Session()
        db.save_session(session)
        ep1 = Episode(session_id=session.id, content="a")
        ep2 = Episode(session_id=session.id, content="b")
        db.save_episode(ep1)
        db.save_episode(ep2)
        db.mark_episodes_consolidated([ep1.id], "2024-01-01T00:00:00")
        loaded = db.get_episode(ep1.id)
        assert loaded.consolidated == 1
        loaded2 = db.get_episode(ep2.id)
        assert loaded2.consolidated == 0

    def test_save_and_get_signal(self, db):
        session = Session()
        db.save_session(session)
        ep = Episode(session_id=session.id, content="test")
        db.save_episode(ep)
        signal = Signal(episode_id=ep.id, signal_type="CORRECTION", raw_value=2.0, multiplier=4.0)
        db.save_signal(signal)
        signals = db.get_signals_for_episode(ep.id)
        assert len(signals) == 1
        assert signals[0].signal_type == "CORRECTION"
        assert signals[0].multiplier == 4.0

    def test_save_and_get_theory(self, db):
        theory = Theory(content="Always use type hints", scope="craft", confidence=0.8)
        db.save_theory(theory)
        loaded = db.get_theory(theory.id)
        assert loaded is not None
        assert loaded.content == "Always use type hints"
        assert loaded.confidence == 0.8
        assert loaded.active is True

    def test_list_theories(self, db):
        db.save_theory(Theory(content="t1", scope="craft", active=True))
        db.save_theory(Theory(content="t2", scope="project", scope_qualifier="proj-a", active=True))
        db.save_theory(Theory(content="t3", scope="craft", active=False))
        active = db.list_theories(active_only=True)
        assert len(active) == 2
        all_t = db.list_theories(active_only=False)
        assert len(all_t) == 3
        project = db.list_theories(scope="project")
        assert len(project) == 1

    def test_save_and_list_contradictions(self, db):
        theory = Theory(content="test theory")
        db.save_theory(theory)
        session = Session()
        db.save_session(session)
        ep = Episode(session_id=session.id, content="contradicts")
        db.save_episode(ep)
        c = Contradiction(theory_id=theory.id, episode_id=ep.id, description="Wrong!")
        db.save_contradiction(c)
        assert c.id is not None
        contras = db.list_contradictions(theory_id=theory.id)
        assert len(contras) == 1
        assert db.count_contradictions(unresolved_only=True) == 1

    def test_user_knowledge_crud(self, db):
        uk = UserKnowledge(topic="pytest", project="neurosync", familiarity=0.7)
        db.save_user_knowledge(uk)
        assert uk.id is not None
        loaded = db.get_user_knowledge("pytest", "neurosync")
        assert loaded.familiarity == 0.7
        loaded.familiarity = 0.9
        db.save_user_knowledge(loaded)
        reloaded = db.get_user_knowledge("pytest", "neurosync")
        assert reloaded.familiarity == 0.9

    def test_stats(self, db):
        stats = db.stats()
        assert "sessions" in stats
        assert "episodes" in stats
        assert "theories" in stats
        assert "contradictions" in stats
        assert stats["episodes"]["total"] == 0
