"""Tests for forgetting.py — Ebbinghaus retention, spaced repetition, pruning."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from neurosync.forgetting import ForgettingEngine
from neurosync.models import Episode, Session, Theory, _utcnow


def _make_episode(session_id: str, **kwargs) -> Episode:
    defaults = {
        "session_id": session_id,
        "content": "test episode content for retention",
        "event_type": "decision",
        "signal_weight": 1.0,
        "quality_score": 3,
        "consolidated": 0,
        "reinforcement_count": 0,
    }
    defaults.update(kwargs)
    return Episode(**defaults)


class TestForgettingEngine:
    def _setup(self, db, vectorstore):
        session = Session(project="test")
        db.save_session(session)
        engine = ForgettingEngine(db, vectorstore)
        return session, engine

    def test_retention_fresh(self, db, vectorstore):
        """A just-created episode should have retention close to 1.0."""
        session, engine = self._setup(db, vectorstore)
        ep = _make_episode(session.id)
        db.save_episode(ep)
        retention = engine.compute_episode_retention(ep)
        assert retention > 0.95

    def test_retention_old(self, db, vectorstore):
        """An old episode with no reinforcement should have low retention."""
        session, engine = self._setup(db, vectorstore)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        ep = _make_episode(session.id, timestamp=old_ts)
        db.save_episode(ep)
        retention = engine.compute_episode_retention(ep)
        assert retention < 0.3

    def test_retention_reinforced(self, db, vectorstore):
        """Reinforced episodes should retain better than unreinforced ones."""
        session, engine = self._setup(db, vectorstore)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        ep_no_reinforce = _make_episode(session.id, timestamp=old_ts, reinforcement_count=0)
        ep_reinforced = _make_episode(session.id, timestamp=old_ts, reinforcement_count=3)
        r_no = engine.compute_episode_retention(ep_no_reinforce)
        r_yes = engine.compute_episode_retention(ep_reinforced)
        assert r_yes > r_no

    def test_stability_by_weight(self, db, vectorstore):
        """Higher signal_weight should increase stability."""
        session, engine = self._setup(db, vectorstore)
        ep_low = _make_episode(session.id, signal_weight=1.0)
        ep_high = _make_episode(session.id, signal_weight=8.0)
        s_low = engine.compute_episode_stability(ep_low)
        s_high = engine.compute_episode_stability(ep_high)
        assert s_high > s_low

    def test_stability_by_quality(self, db, vectorstore):
        """Higher quality_score should increase stability."""
        session, engine = self._setup(db, vectorstore)
        ep_low_q = _make_episode(session.id, quality_score=1)
        ep_high_q = _make_episode(session.id, quality_score=6)
        s_low = engine.compute_episode_stability(ep_low_q)
        s_high = engine.compute_episode_stability(ep_high_q)
        assert s_high > s_low

    def test_reinforce_increments(self, db, vectorstore):
        """reinforce_episode should increment the reinforcement_count."""
        session, engine = self._setup(db, vectorstore)
        ep = _make_episode(session.id)
        db.save_episode(ep)
        assert ep.reinforcement_count == 0
        engine.reinforce_episode(ep.id)
        loaded = db.get_episode(ep.id)
        assert loaded.reinforcement_count == 1
        assert loaded.last_accessed is not None

    def test_prune_low_value(self, db, vectorstore):
        """Old consolidated low-quality episodes should be pruned."""
        session, engine = self._setup(db, vectorstore)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        ep = _make_episode(
            session.id, timestamp=old_ts, consolidated=1,
            quality_score=2, event_type="decision",
        )
        db.save_episode(ep)
        vectorstore.add_episode(ep, project="test")
        pruned = engine.prune_low_value_episodes(retention_threshold=0.5)
        assert pruned == 1
        loaded = db.get_episode(ep.id)
        assert loaded.consolidated == 2  # decayed

    def test_prune_never_corrections(self, db, vectorstore):
        """Correction episodes must never be pruned."""
        session, engine = self._setup(db, vectorstore)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        ep = _make_episode(
            session.id, timestamp=old_ts, consolidated=1,
            quality_score=1, event_type="correction",
        )
        db.save_episode(ep)
        vectorstore.add_episode(ep, project="test")
        pruned = engine.prune_low_value_episodes(retention_threshold=0.9)
        assert pruned == 0

    def test_prune_never_continuations(self, db, vectorstore):
        """Continuation episodes must never be pruned."""
        session, engine = self._setup(db, vectorstore)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        ep = _make_episode(
            session.id, timestamp=old_ts, consolidated=1,
            quality_score=1, event_type="continuation",
        )
        db.save_episode(ep)
        vectorstore.add_episode(ep, project="test")
        pruned = engine.prune_low_value_episodes(retention_threshold=0.9)
        assert pruned == 0

    def test_ebbinghaus_decay(self, db, vectorstore):
        """Theories past grace period should lose confidence via Ebbinghaus curve."""
        session, engine = self._setup(db, vectorstore)
        old_confirmed = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        theory = Theory(
            content="old pattern theory",
            confidence=0.8,
            confirmation_count=1,
            last_confirmed=old_confirmed,
        )
        db.save_theory(theory)
        vectorstore.add_theory(theory)
        affected = engine.apply_ebbinghaus_theory_decay(base_grace_days=30)
        assert affected == 1
        loaded = db.get_theory(theory.id)
        assert loaded.confidence < 0.8

    def test_refresh_on_application(self, db, vectorstore):
        """Refreshing a theory should update its last_confirmed timestamp."""
        session, engine = self._setup(db, vectorstore)
        old_confirmed = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        theory = Theory(
            content="theory to refresh",
            confidence=0.7,
            last_confirmed=old_confirmed,
        )
        db.save_theory(theory)
        vectorstore.add_theory(theory)
        refreshed = engine.refresh_theory_on_application(theory)
        assert refreshed.last_confirmed != old_confirmed

    def test_run_forgetting_pass(self, db, vectorstore):
        """run_forgetting_pass should return summary stats."""
        session, engine = self._setup(db, vectorstore)
        result = engine.run_forgetting_pass()
        assert "episodes_pruned" in result
        assert "theories_decayed" in result
        assert result["episodes_pruned"] >= 0
        assert result["theories_decayed"] >= 0
