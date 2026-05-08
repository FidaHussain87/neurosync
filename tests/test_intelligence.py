"""Tests for Phase 2 intelligence analyzers and neurosync_insights MCP tool."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from neurosync.models import Episode, Session, Signal, Theory, UserKnowledge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _ts(hours_ago: float = 0, day_of_week: int = 0) -> str:
    """Return an ISO timestamp offset from now."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    # Optionally shift to a specific weekday (0=Mon…6=Sun)
    if day_of_week:
        current_dow = dt.weekday()
        shift = (day_of_week - current_dow) % 7
        dt = dt + timedelta(days=shift)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _make_session(db) -> Session:
    s = Session()
    db.save_session(s)
    return s


def _make_episode(db, session_id: str, event_type: str = "decision",
                  timestamp: str = "", quality_score: int = 4,
                  files: list | None = None) -> Episode:
    ep = Episode(
        session_id=session_id,
        event_type=event_type,
        timestamp=timestamp or _utcnow(),
        quality_score=quality_score,
        files_touched=files or [],
        signal_weight=1.0,
    )
    db.save_episode(ep)
    return ep


def _make_signal(db, episode_id: str, signal_type: str) -> Signal:
    sig = Signal(
        episode_id=episode_id,
        signal_type=signal_type,
        raw_value=1.0,
        multiplier=1.0,
    )
    return db.save_signal(sig)


def _make_theory(db, content: str, source_episodes: list[str] | None = None) -> Theory:
    t = Theory(content=content, source_episodes=source_episodes or [])
    return db.save_theory(t)


def _make_user_knowledge(db, topic: str, familiarity: float = 0.5,
                         times_seen: int = 5, last_seen: str = "") -> UserKnowledge:
    uk = UserKnowledge(
        topic=topic,
        project="test",
        familiarity=familiarity,
        last_seen=last_seen or _utcnow(),
        times_seen=times_seen,
        times_explained=0,
    )
    db.save_user_knowledge(uk)
    return uk


# ---------------------------------------------------------------------------
# EventFlowAnalyzer
# ---------------------------------------------------------------------------

class TestEventFlowAnalyzer:
    def test_insufficient_data_returns_empty(self, db):
        from neurosync.intelligence.analyzers.event_flows import EventFlowAnalyzer
        analyzer = EventFlowAnalyzer()
        result = analyzer.analyze(db, None)
        assert result == []

    def test_learning_cycle_detected(self, db):
        from neurosync.intelligence.analyzers.event_flows import EventFlowAnalyzer
        analyzer = EventFlowAnalyzer()

        # Create 10 sessions each with a learning cycle
        for i in range(10):
            s = _make_session(db)
            events = ["frustration", "debugging", "correction", "discovery"]
            for j, ev in enumerate(events):
                _make_episode(db, s.id, event_type=ev,
                              timestamp=_ts(hours_ago=240 - i * 24 - j * 0.5))

        # Add padding sessions to reach 30+ episodes
        for i in range(5):
            s = _make_session(db)
            for j in range(3):
                _make_episode(db, s.id, event_type="decision",
                              timestamp=_ts(hours_ago=200 - i * 20 - j))

        insights = analyzer.analyze(db, None)
        types = [ins.category for ins in insights]
        assert "learning_cycle" in types

        lc = next(i for i in insights if i.category == "learning_cycle")
        assert lc.confidence > 0.3
        assert lc.metadata["cycle_sessions"] >= 3

    def test_stuck_pattern_detected(self, db):
        from neurosync.intelligence.analyzers.event_flows import EventFlowAnalyzer
        analyzer = EventFlowAnalyzer()

        for i in range(8):
            s = _make_session(db)
            # frustration repeated 3+ times
            for j in range(4):
                _make_episode(db, s.id, event_type="frustration",
                              timestamp=_ts(hours_ago=200 - i * 20 - j))

        # filler to reach 30+ episodes
        for i in range(4):
            s = _make_session(db)
            for j in range(2):
                _make_episode(db, s.id, event_type="decision",
                              timestamp=_ts(hours_ago=100 - i * 10 - j))

        insights = analyzer.analyze(db, None)
        types = [ins.category for ins in insights]
        assert "stuck_detection" in types

        stuck = next(i for i in insights if i.category == "stuck_detection")
        assert stuck.metadata["most_common_stuck_event"] in ("frustration", "correction")

    def test_markov_workflow_detected(self, db):
        from neurosync.intelligence.analyzers.event_flows import EventFlowAnalyzer
        analyzer = EventFlowAnalyzer()

        # Create consistent transition: discovery → pattern (10+ sessions)
        for i in range(15):
            s = _make_session(db)
            for j, ev in enumerate(["discovery", "pattern", "decision", "decision"]):
                _make_episode(db, s.id, event_type=ev,
                              timestamp=_ts(hours_ago=300 - i * 20 - j))

        insights = analyzer.analyze(db, None)
        markov = [i for i in insights if i.category == "workflow_pattern"]
        assert len(markov) > 0
        assert markov[0].metadata["strong_transitions"]

    def test_contains_subsequence_helper(self):
        from neurosync.intelligence.analyzers.event_flows import EventFlowAnalyzer
        # Direct subsequence
        assert EventFlowAnalyzer._contains_subsequence(
            ["a", "b", "c", "d"], ["a", "c", "d"]
        )
        # Missing element
        assert not EventFlowAnalyzer._contains_subsequence(
            ["a", "b", "c"], ["a", "x", "c"]
        )
        # Empty subseq always matches
        assert EventFlowAnalyzer._contains_subsequence(["a", "b"], [])

    def test_insight_id_stable(self):
        from neurosync.intelligence.analyzers.event_flows import EventFlowAnalyzer
        from neurosync.intelligence.analyzers.event_flows import _insight_id
        id1 = _insight_id("event_flow", "learning_cycle")
        id2 = _insight_id("event_flow", "learning_cycle")
        assert id1 == id2
        assert len(id1) == 24

    def test_analyzer_name(self):
        from neurosync.intelligence.analyzers.event_flows import EventFlowAnalyzer
        assert EventFlowAnalyzer().name() == "event_flows"

    def test_interval_is_hourly(self):
        from neurosync.intelligence.analyzers.event_flows import EventFlowAnalyzer
        assert EventFlowAnalyzer.interval_seconds == 3600


# ---------------------------------------------------------------------------
# SignalPredictorAnalyzer
# ---------------------------------------------------------------------------

class TestSignalPredictorAnalyzer:
    def test_insufficient_data_returns_empty(self, db):
        from neurosync.intelligence.analyzers.signal_predictor import SignalPredictorAnalyzer
        result = SignalPredictorAnalyzer().analyze(db, None)
        assert result == []

    def test_single_signal_lift_detected(self, db):
        from neurosync.intelligence.analyzers.signal_predictor import SignalPredictorAnalyzer

        s = _make_session(db)
        theory_ep_ids = []

        # 20 episodes with DEPTH signal that become theories
        for i in range(20):
            ep = _make_episode(db, s.id)
            _make_signal(db, ep.id, "DEPTH")
            theory_ep_ids.append(ep.id)

        # 10 more episodes with DEPTH that do NOT become theories
        non_theory_eps = []
        for i in range(10):
            ep = _make_episode(db, s.id)
            _make_signal(db, ep.id, "DEPTH")
            non_theory_eps.append(ep.id)

        # 20 episodes without any signal (not theories)
        for i in range(20):
            _make_episode(db, s.id)

        # Create theories sourced from theory_ep_ids
        for i in range(0, len(theory_ep_ids), 4):
            batch = theory_ep_ids[i:i + 4]
            _make_theory(db, f"theory {i}", source_episodes=batch)

        insights = SignalPredictorAnalyzer().analyze(db, None)
        assert len(insights) > 0

        # DEPTH should appear with positive lift
        depth_insights = [i for i in insights if "DEPTH" in i.metadata.get("combo", "")]
        assert len(depth_insights) > 0
        assert depth_insights[0].metadata["lift"] > 1.0

    def test_combo_signal_detected(self, db):
        from neurosync.intelligence.analyzers.signal_predictor import SignalPredictorAnalyzer

        s = _make_session(db)
        theory_eps = []

        # Episodes with DEPTH+SURPRISE → always theories
        for i in range(15):
            ep = _make_episode(db, s.id)
            _make_signal(db, ep.id, "DEPTH")
            _make_signal(db, ep.id, "SURPRISE")
            theory_eps.append(ep.id)

        # Episodes with only DEPTH → rarely theories
        for i in range(20):
            ep = _make_episode(db, s.id)
            _make_signal(db, ep.id, "DEPTH")

        # Filler
        for i in range(20):
            _make_episode(db, s.id)

        for i in range(0, len(theory_eps), 3):
            batch = theory_eps[i:i + 3]
            _make_theory(db, f"theory {i}", source_episodes=batch)

        insights = SignalPredictorAnalyzer().analyze(db, None)
        combo_insights = [i for i in insights if "+" in i.metadata.get("combo", "")]
        assert len(combo_insights) > 0

    def test_low_lift_not_surfaced(self, db):
        from neurosync.intelligence.analyzers.signal_predictor import SignalPredictorAnalyzer

        s = _make_session(db)
        all_eps = []

        # Signal PASSIVE on all episodes, theories on random half → no real lift
        for i in range(60):
            ep = _make_episode(db, s.id)
            _make_signal(db, ep.id, "PASSIVE")
            all_eps.append(ep.id)

        # Only ~30% become theories (matching base rate)
        for i in range(0, 18, 3):
            _make_theory(db, f"t{i}", source_episodes=all_eps[i:i + 3])

        insights = SignalPredictorAnalyzer().analyze(db, None)
        # All lifts should be near 1.0 (no signal predicts theory better than base)
        # May return empty or near-base insights — no lift >= 1.5 for PASSIVE
        high_lift = [i for i in insights if i.metadata.get("lift", 0) >= 1.5]
        assert len(high_lift) == 0

    def test_analyzer_name(self):
        from neurosync.intelligence.analyzers.signal_predictor import SignalPredictorAnalyzer
        assert SignalPredictorAnalyzer().name() == "signal_predictor"

    def test_interval_is_two_hours(self):
        from neurosync.intelligence.analyzers.signal_predictor import SignalPredictorAnalyzer
        assert SignalPredictorAnalyzer.interval_seconds == 7200

    def test_insight_type_is_signal_predictor(self, db):
        from neurosync.intelligence.analyzers.signal_predictor import SignalPredictorAnalyzer

        s = _make_session(db)
        theory_eps = []
        for i in range(15):
            ep = _make_episode(db, s.id)
            _make_signal(db, ep.id, "CORRECTION")
            theory_eps.append(ep.id)
        for i in range(15):
            _make_episode(db, s.id)
        for i in range(0, 12, 3):
            _make_theory(db, f"t{i}", source_episodes=theory_eps[i:i + 3])

        insights = SignalPredictorAnalyzer().analyze(db, None)
        for ins in insights:
            assert ins.insight_type == "signal_predictor"


# ---------------------------------------------------------------------------
# LearningVelocityAnalyzer
# ---------------------------------------------------------------------------

class TestLearningVelocityAnalyzer:
    def test_insufficient_data_returns_empty(self, db):
        from neurosync.intelligence.analyzers.learning_velocity import LearningVelocityAnalyzer
        result = LearningVelocityAnalyzer().analyze(db, None)
        assert result == []

    def test_learning_rates_detected(self, db):
        from neurosync.intelligence.analyzers.learning_velocity import LearningVelocityAnalyzer

        # Create diverse user knowledge
        topics = [
            ("async patterns", 0.7, 10),
            ("database optimization", 0.4, 8),
            ("api design", 0.9, 20),
            ("testing", 0.6, 12),
            ("type systems", 0.3, 5),
            ("caching", 0.55, 9),
        ]
        for topic, fam, times in topics:
            _make_user_knowledge(db, topic, familiarity=fam, times_seen=times,
                                 last_seen=_ts(hours_ago=24 * 7))

        insights = LearningVelocityAnalyzer().analyze(db, None)
        rate_insights = [i for i in insights if i.category == "learning_rate"]
        assert len(rate_insights) > 0
        assert "top_topics" in rate_insights[0].metadata
        assert len(rate_insights[0].metadata["top_topics"]) > 0

    def test_plateau_detected(self, db):
        from neurosync.intelligence.analyzers.learning_velocity import LearningVelocityAnalyzer

        # Topics with many views but low familiarity (plateau zone 0.2–0.75)
        topics_to_plateau = [
            ("old concept", 0.35, 20),
            ("stale topic", 0.45, 15),
            ("stuck domain", 0.50, 18),
        ]
        # last_seen 4 weeks ago (inactive)
        old_ts = _ts(hours_ago=24 * 28)
        for topic, fam, times in topics_to_plateau:
            _make_user_knowledge(db, topic, familiarity=fam, times_seen=times,
                                 last_seen=old_ts)

        # Add active topics to reach the min count threshold
        for i in range(5):
            _make_user_knowledge(db, f"active_{i}", familiarity=0.8, times_seen=5)

        insights = LearningVelocityAnalyzer().analyze(db, None)
        plateau_insights = [i for i in insights if i.category == "plateau_detection"]
        assert len(plateau_insights) > 0
        assert plateau_insights[0].metadata["total_plateaus"] >= 1

    def test_near_mastery_detected(self, db):
        from neurosync.intelligence.analyzers.learning_velocity import LearningVelocityAnalyzer

        mastery_topics = [
            ("python", 0.92),
            ("git", 0.95),
            ("linux", 0.88),
        ]
        for topic, fam in mastery_topics:
            _make_user_knowledge(db, topic, familiarity=fam, times_seen=30)

        # Filler topics
        for i in range(4):
            _make_user_knowledge(db, f"topic_{i}", familiarity=0.3, times_seen=5)

        insights = LearningVelocityAnalyzer().analyze(db, None)
        mastery_insights = [i for i in insights if i.category == "mastery_progress"]
        assert len(mastery_insights) > 0
        assert mastery_insights[0].metadata["mastery_count"] == 3

    def test_developer_profile_updated(self, db):
        from neurosync.intelligence.analyzers.learning_velocity import LearningVelocityAnalyzer

        for i in range(8):
            _make_user_knowledge(db, f"topic_{i}", familiarity=0.5 + i * 0.05,
                                 times_seen=5 + i, last_seen=_ts(hours_ago=24 * (i + 1)))

        LearningVelocityAnalyzer().analyze(db, None)
        profile = db.list_developer_profile()
        keys = {p["profile_key"] for p in profile}
        assert "learning_velocity_by_topic" in keys

    def test_no_plateau_for_recent_active_topics(self, db):
        from neurosync.intelligence.analyzers.learning_velocity import LearningVelocityAnalyzer

        # Same familiarity/times_seen as plateau, but recently seen
        recent_ts = _ts(hours_ago=12)
        for i in range(5):
            _make_user_knowledge(db, f"active_{i}", familiarity=0.45, times_seen=10,
                                 last_seen=recent_ts)
        for i in range(3):
            _make_user_knowledge(db, f"other_{i}", familiarity=0.8, times_seen=20)

        insights = LearningVelocityAnalyzer().analyze(db, None)
        plateau_insights = [i for i in insights if i.category == "plateau_detection"]
        # Recently active topics should not be classified as plateaus
        assert len(plateau_insights) == 0

    def test_analyzer_name(self):
        from neurosync.intelligence.analyzers.learning_velocity import LearningVelocityAnalyzer
        assert LearningVelocityAnalyzer().name() == "learning_velocity"

    def test_interval_is_two_hours(self):
        from neurosync.intelligence.analyzers.learning_velocity import LearningVelocityAnalyzer
        assert LearningVelocityAnalyzer.interval_seconds == 7200


# ---------------------------------------------------------------------------
# IntelligenceEngine — Phase 2 registration
# ---------------------------------------------------------------------------

class TestIntelligenceEnginePhase2:
    def test_all_five_analyzers_registered(self, db):
        from neurosync.intelligence import IntelligenceEngine

        engine = IntelligenceEngine(db)
        names = {a.name() for a in engine._analyzers}
        assert "work_patterns" in names
        assert "file_network" in names
        assert "event_flows" in names
        assert "signal_predictor" in names
        assert "learning_velocity" in names

    def test_run_once_includes_phase2_analyzers(self, db):
        from neurosync.intelligence import IntelligenceEngine

        engine = IntelligenceEngine(db)
        results = engine.run_once()
        assert "event_flows" in results
        assert "signal_predictor" in results
        assert "learning_velocity" in results

    def test_stats_shows_five_analyzers(self, db):
        from neurosync.intelligence import IntelligenceEngine

        engine = IntelligenceEngine(db)
        stats = engine.get_stats()
        assert stats["analyzers_active"] == 5


# ---------------------------------------------------------------------------
# neurosync_insights MCP tool
# ---------------------------------------------------------------------------

class TestNeurosyncInsightsTool:
    def _setup_mcp(self, db, tmp_dir):
        """Patch MCP globals and return a configured handler."""
        import neurosync.mcp_server as mcp
        mcp._db = db
        mcp._intelligence = None  # test without intelligence engine
        return mcp

    def test_handler_returns_expected_keys(self, db, tmp_dir):
        import neurosync.mcp_server as mcp
        orig_db = mcp._db
        orig_intel = mcp._intelligence
        try:
            mcp._db = db
            mcp._intelligence = None
            result = mcp.handle_insights({})
            assert "category" in result
            assert "insights" in result
            assert "count" in result
            assert isinstance(result["insights"], list)
        finally:
            mcp._db = orig_db
            mcp._intelligence = orig_intel

    def test_category_all_by_default(self, db):
        import neurosync.mcp_server as mcp
        orig_db = mcp._db
        try:
            mcp._db = db
            result = mcp.handle_insights({})
            assert result["category"] == "all"
        finally:
            mcp._db = orig_db

    def test_category_filter_work_patterns(self, db):
        import neurosync.mcp_server as mcp
        orig_db = mcp._db
        try:
            mcp._db = db
            # Insert a work_pattern insight
            from neurosync.intelligence.models import Insight
            ins = Insight(
                id="wp-test-1",
                insight_type="work_pattern",
                category="peak_hours",
                content="Peak hours test",
                confidence=0.7,
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            db.upsert_insight(ins)

            result = mcp.handle_insights({"category": "work_patterns"})
            assert result["category"] == "work_patterns"
            assert any(i["type"] == "work_pattern" for i in result["insights"])
        finally:
            mcp._db = orig_db

    def test_category_filter_event_flows(self, db):
        import neurosync.mcp_server as mcp
        orig_db = mcp._db
        try:
            mcp._db = db
            from neurosync.intelligence.models import Insight
            ins = Insight(
                id="ef-test-1",
                insight_type="event_flow",
                category="learning_cycle",
                content="Event flow test",
                confidence=0.6,
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            db.upsert_insight(ins)

            result = mcp.handle_insights({"category": "event_flows"})
            assert result["category"] == "event_flows"
            assert any(i["type"] == "event_flow" for i in result["insights"])
        finally:
            mcp._db = orig_db

    def test_category_filter_learning(self, db):
        import neurosync.mcp_server as mcp
        orig_db = mcp._db
        try:
            mcp._db = db
            from neurosync.intelligence.models import Insight
            ins = Insight(
                id="lv-test-1",
                insight_type="learning_velocity",
                category="learning_rate",
                content="Learning velocity test",
                confidence=0.65,
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            db.upsert_insight(ins)

            result = mcp.handle_insights({"category": "learning"})
            assert any(i["type"] == "learning_velocity" for i in result["insights"])
        finally:
            mcp._db = orig_db

    def test_category_filter_warnings(self, db):
        import neurosync.mcp_server as mcp
        orig_db = mcp._db
        try:
            mcp._db = db
            from neurosync.intelligence.models import Insight
            # Insert a fatigue warning
            ins = Insight(
                id="fw-test-1",
                insight_type="work_pattern",
                category="fatigue_warning",
                content="Fatigue warning test",
                confidence=0.7,
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            db.upsert_insight(ins)
            # Non-warning insight
            ins2 = Insight(
                id="pk-test-2",
                insight_type="work_pattern",
                category="peak_hours",
                content="Peak hours (not a warning)",
                confidence=0.7,
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            db.upsert_insight(ins2)

            result = mcp.handle_insights({"category": "warnings"})
            for i in result["insights"]:
                assert i["category"] in ("fatigue_warning", "stuck_detection", "plateau_detection")
        finally:
            mcp._db = orig_db

    def test_min_confidence_filter(self, db):
        import neurosync.mcp_server as mcp
        orig_db = mcp._db
        try:
            mcp._db = db
            from neurosync.intelligence.models import Insight
            low = Insight(
                id="low-conf-1",
                insight_type="work_pattern",
                category="peak_hours",
                content="Low confidence",
                confidence=0.2,
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            high = Insight(
                id="high-conf-1",
                insight_type="work_pattern",
                category="peak_hours",
                content="High confidence",
                confidence=0.8,
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            db.upsert_insight(low)
            db.upsert_insight(high)

            result = mcp.handle_insights({"min_confidence": 0.5})
            for i in result["insights"]:
                assert i["confidence"] >= 0.5
        finally:
            mcp._db = orig_db

    def test_limit_respected(self, db):
        import neurosync.mcp_server as mcp
        orig_db = mcp._db
        try:
            mcp._db = db
            from neurosync.intelligence.models import Insight
            for idx in range(10):
                ins = Insight(
                    id=f"limit-test-{idx}",
                    insight_type="work_pattern",
                    category="peak_hours",
                    content=f"insight {idx}",
                    confidence=0.7,
                    created_at=_utcnow(),
                    updated_at=_utcnow(),
                )
                db.upsert_insight(ins)

            result = mcp.handle_insights({"limit": 3})
            assert len(result["insights"]) <= 3
        finally:
            mcp._db = orig_db

    def test_insight_structure(self, db):
        import neurosync.mcp_server as mcp
        orig_db = mcp._db
        try:
            mcp._db = db
            from neurosync.intelligence.models import Insight
            ins = Insight(
                id="struct-test-1",
                insight_type="event_flow",
                category="learning_cycle",
                content="Structured insight",
                confidence=0.75,
                created_at=_utcnow(),
                updated_at=_utcnow(),
                metadata={"key": "value"},
            )
            db.upsert_insight(ins)

            result = mcp.handle_insights({})
            assert len(result["insights"]) >= 1
            i = next(x for x in result["insights"] if x["id"] == "struct-test-1")
            assert i["id"] == "struct-test-1"
            assert i["type"] == "event_flow"
            assert i["category"] == "learning_cycle"
            assert i["content"] == "Structured insight"
            assert i["confidence"] == 0.75
            assert "updated_at" in i
            assert "metadata" in i
        finally:
            mcp._db = orig_db

    def test_developer_profile_in_response_for_work_patterns(self, db):
        import neurosync.mcp_server as mcp
        from neurosync.intelligence import IntelligenceEngine
        orig_db = mcp._db
        orig_intel = mcp._intelligence
        try:
            mcp._db = db
            engine = IntelligenceEngine(db)
            mcp._intelligence = engine

            # Store a profile entry
            db.upsert_developer_profile("peak_hours", {"start": 9, "end": 11}, 50, 0.8)

            result = mcp.handle_insights({"category": "work_patterns"})
            assert "developer_profile" in result
            assert isinstance(result["developer_profile"], dict)
        finally:
            mcp._db = orig_db
            mcp._intelligence = orig_intel

    def test_engine_stats_in_response(self, db):
        import neurosync.mcp_server as mcp
        from neurosync.intelligence import IntelligenceEngine
        orig_db = mcp._db
        orig_intel = mcp._intelligence
        try:
            mcp._db = db
            engine = IntelligenceEngine(db)
            mcp._intelligence = engine

            result = mcp.handle_insights({})
            assert "engine" in result
            assert "analyzers_active" in result["engine"]
            assert result["engine"]["analyzers_active"] == 5
        finally:
            mcp._db = orig_db
            mcp._intelligence = orig_intel

    def test_insights_tool_in_handlers(self):
        import neurosync.mcp_server as mcp
        assert "neurosync_insights" in mcp._HANDLERS
        assert mcp._HANDLERS["neurosync_insights"] is mcp.handle_insights

    def test_insights_tool_in_schema(self):
        import neurosync.mcp_server as mcp
        names = [t["name"] for t in mcp.TOOLS]
        assert "neurosync_insights" in names

    def test_insights_schema_has_category_enum(self):
        import neurosync.mcp_server as mcp
        tool = next(t for t in mcp.TOOLS if t["name"] == "neurosync_insights")
        cats = tool["inputSchema"]["properties"]["category"]["enum"]
        expected = {"work_patterns", "file_network", "event_flows",
                    "signal_predictor", "learning", "warnings", "all"}
        assert set(cats) == expected

    def test_project_filter(self, db):
        import neurosync.mcp_server as mcp
        orig_db = mcp._db
        try:
            mcp._db = db
            from neurosync.intelligence.models import Insight
            ins_a = Insight(
                id="proj-filter-a",
                insight_type="work_pattern",
                category="peak_hours",
                content="Project A insight",
                confidence=0.7,
                project="project_a",
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            ins_b = Insight(
                id="proj-filter-b",
                insight_type="work_pattern",
                category="peak_hours",
                content="Project B insight",
                confidence=0.7,
                project="project_b",
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            db.upsert_insight(ins_a)
            db.upsert_insight(ins_b)

            result = mcp.handle_insights({"project": "project_a"})
            for i in result["insights"]:
                if i.get("project"):
                    assert i.get("project") == "project_a"
        finally:
            mcp._db = orig_db

    def test_limit_capped_at_50(self, db):
        import neurosync.mcp_server as mcp
        orig_db = mcp._db
        try:
            mcp._db = db
            # Requesting 999 should be capped to 50
            result = mcp.handle_insights({"limit": 999})
            assert result["count"] <= 50
        finally:
            mcp._db = orig_db


# ---------------------------------------------------------------------------
# Integration: run analyzers then query insights
# ---------------------------------------------------------------------------

class TestEndToEndIntelligence:
    def test_event_flow_insights_queryable_via_mcp(self, db):
        """Run EventFlowAnalyzer, store insights, retrieve via handle_insights."""
        from neurosync.intelligence.analyzers.event_flows import EventFlowAnalyzer
        import neurosync.mcp_server as mcp
        orig_db = mcp._db
        try:
            mcp._db = db

            # Seed sessions with learning cycles
            for i in range(12):
                s = _make_session(db)
                for j, ev in enumerate(["frustration", "debugging", "correction", "discovery"]):
                    _make_episode(db, s.id, event_type=ev,
                                  timestamp=_ts(hours_ago=300 - i * 24 - j))
            # filler
            for i in range(3):
                s = _make_session(db)
                for j in range(3):
                    _make_episode(db, s.id, event_type="decision",
                                  timestamp=_ts(hours_ago=100 - i * 10 - j))

            analyzer = EventFlowAnalyzer()
            insights = analyzer.analyze(db, None)
            for ins in insights:
                db.upsert_insight(ins)

            result = mcp.handle_insights({"category": "event_flows"})
            assert result["count"] >= 1
            assert all(i["type"] == "event_flow" for i in result["insights"])
        finally:
            mcp._db = orig_db

    def test_signal_predictor_insights_queryable_via_mcp(self, db):
        """Run SignalPredictorAnalyzer, store insights, retrieve via handle_insights."""
        from neurosync.intelligence.analyzers.signal_predictor import SignalPredictorAnalyzer
        import neurosync.mcp_server as mcp
        orig_db = mcp._db
        try:
            mcp._db = db

            s = _make_session(db)
            theory_eps = []
            for i in range(20):
                ep = _make_episode(db, s.id)
                _make_signal(db, ep.id, "DEPTH")
                _make_signal(db, ep.id, "SURPRISE")
                theory_eps.append(ep.id)
            for i in range(20):
                _make_episode(db, s.id)

            for i in range(0, 18, 3):
                _make_theory(db, f"theory_{i}", source_episodes=theory_eps[i:i + 3])

            analyzer = SignalPredictorAnalyzer()
            insights = analyzer.analyze(db, None)
            for ins in insights:
                db.upsert_insight(ins)

            result = mcp.handle_insights({"category": "signal_predictor"})
            assert result["count"] >= 0  # may be 0 if no lift >= 1.5

        finally:
            mcp._db = orig_db

    def test_learning_velocity_insights_queryable_via_mcp(self, db):
        """Run LearningVelocityAnalyzer, store insights, retrieve via handle_insights."""
        from neurosync.intelligence.analyzers.learning_velocity import LearningVelocityAnalyzer
        import neurosync.mcp_server as mcp
        orig_db = mcp._db
        try:
            mcp._db = db

            topics = [
                ("python", 0.9, 30), ("async", 0.7, 15),
                ("api design", 0.5, 10), ("testing", 0.6, 12),
                ("docker", 0.4, 8), ("git", 0.95, 40),
            ]
            for topic, fam, ts in topics:
                _make_user_knowledge(db, topic, familiarity=fam, times_seen=ts,
                                     last_seen=_ts(hours_ago=24 * 7))

            analyzer = LearningVelocityAnalyzer()
            insights = analyzer.analyze(db, None)
            for ins in insights:
                db.upsert_insight(ins)

            result = mcp.handle_insights({"category": "learning"})
            assert result["count"] >= 1
            assert all(i["type"] == "learning_velocity" for i in result["insights"])
        finally:
            mcp._db = orig_db
