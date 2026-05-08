"""Tests for the Cognitive Replay Engine — reasoning path capture and surfacing."""

import pytest

from neurosync.models import Episode, _new_id, _utcnow
from neurosync.replay import (
    CognitiveReplay,
    ReplayDetector,
    ReplayMatcher,
    ReplayStep,
    detect_replay_from_session,
)


class TestReplayStep:
    """Basic ReplayStep data model tests."""

    def test_to_dict_minimal(self):
        step = ReplayStep(hypothesis="pool exhaustion", outcome="dead_end")
        d = step.to_dict()
        assert d["hypothesis"] == "pool exhaustion"
        assert d["outcome"] == "dead_end"
        assert "signal" not in d
        assert "duration_hint" not in d

    def test_to_dict_full(self):
        step = ReplayStep(
            hypothesis="race condition", outcome="root_cause",
            signal="concurrent writes to shared map", duration_hint="quick"
        )
        d = step.to_dict()
        assert d["signal"] == "concurrent writes to shared map"
        assert d["duration_hint"] == "quick"

    def test_from_dict(self):
        d = {"hypothesis": "test", "outcome": "partial", "signal": "x"}
        step = ReplayStep.from_dict(d)
        assert step.hypothesis == "test"
        assert step.outcome == "partial"
        assert step.signal == "x"

    def test_from_dict_missing_fields(self):
        step = ReplayStep.from_dict({})
        assert step.hypothesis == ""
        assert step.outcome == "dead_end"


class TestCognitiveReplay:
    """CognitiveReplay data model tests."""

    def test_to_dict_and_back(self):
        replay = CognitiveReplay(
            session_id="sess1",
            strategy_type="elimination",
            problem_signature="connection timeout under load",
            steps=[
                ReplayStep(hypothesis="DNS resolution", outcome="dead_end", signal="DNS fine"),
                ReplayStep(hypothesis="pool exhaustion", outcome="root_cause", signal="pool size=5, threads=20"),
            ],
            shortcut="Skip: DNS resolution → Go directly to: pool exhaustion",
            domains=["concurrency", "database-access"],
            files_involved=["src/db/pool.py"],
        )
        d = replay.to_dict()
        restored = CognitiveReplay.from_dict(d)
        assert restored.strategy_type == "elimination"
        assert len(restored.steps) == 2
        assert restored.steps[0].outcome == "dead_end"
        assert restored.steps[1].outcome == "root_cause"
        assert restored.shortcut == replay.shortcut
        assert restored.domains == ["concurrency", "database-access"]

    def test_human_readable(self):
        replay = CognitiveReplay(
            strategy_type="elimination",
            problem_signature="timeout in auth service",
            steps=[
                ReplayStep(hypothesis="network latency", outcome="dead_end"),
                ReplayStep(hypothesis="token refresh", outcome="dead_end"),
                ReplayStep(hypothesis="mutex deadlock", outcome="root_cause", signal="thread dump shows lock contention"),
            ],
            shortcut="Skip network and token, go to mutex",
        )
        text = replay.human_readable()
        assert "elimination" in text
        assert "network latency" in text
        assert "mutex deadlock" in text
        assert "thread dump" in text

    def test_human_readable_empty(self):
        replay = CognitiveReplay(steps=[])
        text = replay.human_readable()
        assert "elimination" in text


class TestReplayDetector:
    """Detector identifies reasoning chains from episode sequences."""

    def _make_episode(self, content, event_type="debugging", **kwargs):
        return Episode(
            id=_new_id(),
            session_id="test-session",
            timestamp=_utcnow(),
            event_type=event_type,
            content=content,
            **kwargs,
        )

    def test_detects_elimination_chain(self):
        episodes = [
            self._make_episode(
                "Checked DNS resolution — not the issue, all lookups resolving in <5ms",
                event_type="debugging",
            ),
            self._make_episode(
                "Investigated connection pool — didn't help, pool stats show available connections",
                event_type="frustration",
            ),
            self._make_episode(
                "Found it — race condition in session handler, two threads writing to shared map",
                event_type="correction",
                reasoning="Concurrent access without lock",
            ),
        ]
        detector = ReplayDetector()
        replay = detector.detect(episodes)
        assert replay is not None
        assert replay.strategy_type == "elimination"
        assert len(replay.steps) >= 2
        assert any(s.outcome == "dead_end" for s in replay.steps)
        assert any(s.outcome == "root_cause" for s in replay.steps)
        assert replay.shortcut != ""

    def test_no_detection_without_dead_ends(self):
        episodes = [
            self._make_episode("Fixed the bug by adding a null check", event_type="correction"),
            self._make_episode("Also fixed the related timeout", event_type="correction"),
        ]
        detector = ReplayDetector()
        replay = detector.detect(episodes)
        assert replay is None

    def test_no_detection_without_resolution(self):
        episodes = [
            self._make_episode("Tried A — not the issue", event_type="frustration"),
            self._make_episode("Tried B — still failing", event_type="frustration"),
            self._make_episode("Tried C — no effect", event_type="frustration"),
        ]
        detector = ReplayDetector()
        replay = detector.detect(episodes)
        assert replay is None

    def test_minimum_steps_required(self):
        episodes = [
            self._make_episode("Found the root cause", event_type="correction"),
        ]
        detector = ReplayDetector(min_steps=2)
        replay = detector.detect(episodes)
        assert replay is None

    def test_max_steps_capped(self):
        episodes = [
            self._make_episode("Tried option 1 — dead end", event_type="debugging"),
            self._make_episode("Tried option 2 — dead end", event_type="debugging"),
            self._make_episode("Tried option 3 — dead end", event_type="debugging"),
            self._make_episode("Found the root cause — config file was wrong", event_type="correction"),
            self._make_episode("Tried option 5 — dead end", event_type="debugging"),
            self._make_episode("Tried option 6 — dead end", event_type="debugging"),
        ]
        detector = ReplayDetector(max_steps=4)
        replay = detector.detect(episodes)
        assert replay is not None
        assert len(replay.steps) <= 4

    def test_non_debugging_episodes_filtered(self):
        episodes = [
            self._make_episode("Committed code changes", event_type="file_change"),
            self._make_episode("Started new feature", event_type="decision"),
        ]
        detector = ReplayDetector()
        replay = detector.detect(episodes)
        assert replay is None

    def test_collects_domains_and_files(self):
        episodes = [
            self._make_episode(
                "Checked the cache layer — dead end",
                event_type="debugging",
                domains=["caching"],
                files_touched=["src/cache.py"],
            ),
            self._make_episode(
                "Found it — race condition in the lock",
                event_type="correction",
                domains=["concurrency"],
                files_touched=["src/lock.py"],
            ),
        ]
        detector = ReplayDetector()
        replay = detector.detect(episodes)
        assert replay is not None
        assert "caching" in replay.domains
        assert "concurrency" in replay.domains
        assert "src/cache.py" in replay.files_involved

    def test_strategy_bisection(self):
        episodes = [
            self._make_episode(
                "Checked the whole auth module — didn't help, not the issue",
                event_type="debugging",
            ),
            self._make_episode(
                "Narrowed further to token validation — getting closer but still failing",
                event_type="debugging",
            ),
            self._make_episode(
                "Found it — token expiry calculation off by one",
                event_type="correction",
            ),
        ]
        detector = ReplayDetector()
        replay = detector.detect(episodes)
        assert replay is not None

    def test_hypothesis_extraction(self):
        episodes = [
            self._make_episode(
                "Investigated connection pooling but it wasn't the issue",
                event_type="debugging",
            ),
            self._make_episode(
                "Suspected memory leak but ruled out after profiling",
                event_type="frustration",
            ),
            self._make_episode(
                "Root cause was the serialization layer — buffer overflow",
                event_type="correction",
                reasoning="Buffer size hardcoded to 1024",
            ),
        ]
        detector = ReplayDetector()
        replay = detector.detect(episodes)
        assert replay is not None
        # Should extract hypotheses from patterns
        hypotheses = [s.hypothesis for s in replay.steps]
        assert any("connection pooling" in h or "pooling" in h for h in hypotheses)


class TestDetectReplayFromSession:
    """Test the convenience function."""

    def _make_episode(self, content, event_type="debugging", **kwargs):
        return Episode(
            id=_new_id(),
            session_id="sess",
            timestamp=_utcnow(),
            event_type=event_type,
            content=content,
            **kwargs,
        )

    def test_returns_none_for_no_triggers(self):
        episodes = [
            self._make_episode("Added new API endpoint", event_type="decision"),
            self._make_episode("Wrote tests", event_type="file_change"),
        ]
        assert detect_replay_from_session(episodes) is None

    def test_detects_when_triggers_present(self):
        episodes = [
            self._make_episode("Tried restarting — didn't help", event_type="frustration"),
            self._make_episode("Checked logs — not the issue", event_type="debugging"),
            self._make_episode("Found the root cause — config was wrong", event_type="correction"),
        ]
        result = detect_replay_from_session(episodes)
        assert result is not None
        assert result.strategy_type in ("elimination", "bisection", "reversal")


class TestReplayMatcher:
    """Tests for finding relevant replays."""

    class FakeDB:
        def __init__(self, replays):
            self._replays = replays

        def list_replays(self, limit=50):
            return self._replays[:limit]

    def test_matches_by_domain(self):
        replay = CognitiveReplay(
            problem_signature="connection pool issue",
            domains=["concurrency", "database-access"],
            steps=[ReplayStep(hypothesis="pool size", outcome="root_cause")],
            confidence=0.8,
        )
        db = self.FakeDB([replay])
        matcher = ReplayMatcher(db)
        results = matcher.find_relevant(
            content="seeing timeout errors in database calls",
            domains=["database-access"],
        )
        assert len(results) == 1
        assert results[0].id == replay.id

    def test_matches_by_keywords(self):
        replay = CognitiveReplay(
            problem_signature="authentication token expiry race condition causing timeout",
            domains=["authentication"],
            steps=[
                ReplayStep(hypothesis="token refresh timing", outcome="root_cause"),
            ],
            confidence=0.9,
        )
        db = self.FakeDB([replay])
        matcher = ReplayMatcher(db)
        results = matcher.find_relevant(
            content="token expiry causing authentication timeout errors intermittently",
            domains=["authentication"],
        )
        assert len(results) >= 1

    def test_no_match_for_unrelated(self):
        replay = CognitiveReplay(
            problem_signature="CSS layout bug in flexbox",
            domains=["ui-layout"],
            steps=[ReplayStep(hypothesis="flex direction", outcome="root_cause")],
            confidence=0.8,
        )
        db = self.FakeDB([replay])
        matcher = ReplayMatcher(db)
        results = matcher.find_relevant(
            content="database migration failing on column type",
            domains=["database-access"],
        )
        assert len(results) == 0

    def test_respects_limit(self):
        replays = [
            CognitiveReplay(
                problem_signature=f"issue {i}",
                domains=["concurrency"],
                steps=[ReplayStep(hypothesis=f"h{i}", outcome="root_cause")],
                confidence=0.8,
            )
            for i in range(10)
        ]
        db = self.FakeDB(replays)
        matcher = ReplayMatcher(db)
        results = matcher.find_relevant(
            content="concurrency problem with threads",
            domains=["concurrency"],
            limit=2,
        )
        assert len(results) <= 2

    def test_confidence_affects_ranking(self):
        low_conf = CognitiveReplay(
            problem_signature="pool timeout",
            domains=["database-access"],
            steps=[ReplayStep(hypothesis="pool", outcome="root_cause")],
            confidence=0.2,
        )
        high_conf = CognitiveReplay(
            problem_signature="pool exhaustion",
            domains=["database-access"],
            steps=[ReplayStep(hypothesis="pool size", outcome="root_cause")],
            confidence=0.9,
        )
        db = self.FakeDB([low_conf, high_conf])
        matcher = ReplayMatcher(db)
        results = matcher.find_relevant(
            content="database pool timeout",
            domains=["database-access"],
            limit=2,
        )
        assert len(results) == 2
        assert results[0].confidence > results[1].confidence


class TestReplayPersistence:
    """Test DB persistence of replays (integration with Database)."""

    @pytest.fixture
    def db(self, tmp_path):
        from neurosync.config import NeuroSyncConfig

        config = NeuroSyncConfig(data_dir=str(tmp_path))
        from neurosync.db import Database

        return Database(config)

    def test_save_and_get(self, db):
        replay = CognitiveReplay(
            session_id="s1",
            strategy_type="elimination",
            problem_signature="auth timeout",
            steps=[
                ReplayStep(hypothesis="DNS", outcome="dead_end", signal="DNS OK"),
                ReplayStep(hypothesis="token refresh", outcome="root_cause", signal="expired"),
            ],
            shortcut="Skip DNS, go to token refresh",
            domains=["authentication"],
            files_involved=["src/auth.py"],
            source_episode_ids=["ep1", "ep2"],
        )
        db.save_replay(replay)
        loaded = db.get_replay(replay.id)
        assert loaded is not None
        assert loaded.strategy_type == "elimination"
        assert loaded.problem_signature == "auth timeout"
        assert len(loaded.steps) == 2
        assert loaded.steps[0].hypothesis == "DNS"
        assert loaded.steps[1].outcome == "root_cause"
        assert loaded.shortcut == "Skip DNS, go to token refresh"
        assert loaded.domains == ["authentication"]
        assert loaded.files_involved == ["src/auth.py"]

    def test_list_replays(self, db):
        for i in range(5):
            replay = CognitiveReplay(
                session_id=f"s{i}",
                strategy_type="elimination",
                problem_signature=f"issue {i}",
                steps=[ReplayStep(hypothesis=f"h{i}", outcome="root_cause")],
                confidence=0.5 + i * 0.1,
            )
            db.save_replay(replay)
        replays = db.list_replays(limit=3)
        assert len(replays) == 3
        # Should be ordered by confidence descending
        assert replays[0].confidence >= replays[1].confidence

    def test_count_replays(self, db):
        assert db.count_replays() == 0
        db.save_replay(CognitiveReplay(
            session_id="s1", steps=[ReplayStep(hypothesis="x", outcome="root_cause")],
        ))
        assert db.count_replays() == 1

    def test_increment_surfaced(self, db):
        replay = CognitiveReplay(
            session_id="s1",
            steps=[ReplayStep(hypothesis="x", outcome="root_cause")],
        )
        db.save_replay(replay)
        db.increment_replay_surfaced(replay.id)
        db.increment_replay_surfaced(replay.id)
        loaded = db.get_replay(replay.id)
        assert loaded.times_surfaced == 2

    def test_mark_helpful(self, db):
        replay = CognitiveReplay(
            session_id="s1",
            steps=[ReplayStep(hypothesis="x", outcome="root_cause")],
            confidence=0.5,
        )
        db.save_replay(replay)
        db.mark_replay_helpful(replay.id)
        loaded = db.get_replay(replay.id)
        assert loaded.times_helpful == 1
        assert loaded.confidence == pytest.approx(0.6, abs=0.01)

    def test_schema_version_10(self, db):
        stats = db.stats()
        assert stats["schema_version"] == 11
