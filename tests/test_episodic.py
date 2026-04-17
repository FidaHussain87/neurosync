"""Tests for episodic.py — Layer 1 episodic memory."""

from __future__ import annotations


class TestEpisodicMemory:
    def test_start_session(self, episodic):
        session = episodic.start_session(project="test", branch="main")
        assert session.project == "test"
        assert session.branch == "main"
        assert session.id

    def test_end_session(self, episodic):
        session = episodic.start_session(project="test")
        ended = episodic.end_session(session.id, summary="Done", duration_seconds=3600)
        assert ended.summary == "Done"
        assert ended.duration_seconds == 3600
        assert ended.ended_at is not None

    def test_end_nonexistent_session(self, episodic):
        assert episodic.end_session("nonexistent") is None

    def test_record_episode(self, episodic):
        session = episodic.start_session(project="test")
        episode = episodic.record_episode(
            session_id=session.id,
            event_type="decision",
            content="Chose SQLite over PostgreSQL",
            files_touched=["db.py"],
            layers_touched=["dao"],
        )
        assert episode.id
        assert episode.content == "Chose SQLite over PostgreSQL"
        assert episode.signal_weight == 1.0
        loaded = episodic.get_episode(episode.id)
        assert loaded is not None

    def test_record_explicit(self, episodic):
        session = episodic.start_session()
        episode = episodic.record_explicit(session.id, "Always use WAL mode")
        assert episode.signal_weight == 10.0
        assert episode.event_type == "explicit"

    def test_record_correction(self, episodic):
        session = episodic.start_session()
        ep1 = episodic.record_correction(session.id, "use mock()", "use redefine()", 1)
        assert ep1.signal_weight == 2.0
        ep2 = episodic.record_correction(session.id, "wrong again", "correct", 3)
        assert ep2.signal_weight == 8.0

    def test_list_episodes(self, episodic):
        session = episodic.start_session()
        episodic.record_episode(session.id, "decision", "d1")
        episodic.record_episode(session.id, "correction", "c1")
        all_eps = episodic.list_episodes(session_id=session.id)
        assert len(all_eps) == 2

    def test_get_unconsolidated_episodes(self, episodic):
        session = episodic.start_session()
        episodic.record_episode(session.id, "decision", "d1")
        episodic.record_episode(session.id, "decision", "d2")
        unconsolidated = episodic.get_unconsolidated_episodes()
        assert len(unconsolidated) == 2

    def test_mark_consolidated(self, episodic):
        session = episodic.start_session()
        ep = episodic.record_episode(session.id, "decision", "test")
        episodic.mark_consolidated([ep.id])
        loaded = episodic.get_episode(ep.id)
        assert loaded.consolidated == 1

    def test_decay_episodes(self, episodic):
        session = episodic.start_session()
        ep = episodic.record_episode(session.id, "decision", "will decay")
        episodic.decay_episodes([ep.id])
        loaded = episodic.get_episode(ep.id)
        assert loaded.consolidated == 2

    def test_search(self, episodic):
        session = episodic.start_session(project="myproj")
        episodic.record_episode(session.id, "decision", "Implemented OAuth2 authentication flow")
        results = episodic.search("authentication", project="myproj")
        assert len(results) >= 1
