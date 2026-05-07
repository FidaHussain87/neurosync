"""Tests for Predictive Pre-emption — trajectory inference and mistake prediction."""

import pytest

from neurosync.models import Episode, FailureRecord, _new_id, _utcnow
from neurosync.preemption import (
    PreemptionEngine,
    Trajectory,
    parse_branch_intent,
    predict_files,
    predict_mistakes,
    score_relevance,
)


class TestBranchIntent:
    """Test branch name parsing."""

    def test_fix_branch(self):
        result = parse_branch_intent("fix/auth-timeout")
        assert result["type"] == "debugging"
        assert result["area"] == "auth"
        assert result.get("keyword") == "timeout"

    def test_feature_branch(self):
        result = parse_branch_intent("feature/payment-integration")
        assert result["type"] == "feature"
        assert result["area"] == "payment"

    def test_refactor_branch(self):
        result = parse_branch_intent("refactor/db-layer")
        assert result["type"] == "refactor"
        assert result["area"] == "db"

    def test_empty_branch(self):
        result = parse_branch_intent("")
        assert result == {}

    def test_unknown_format(self):
        result = parse_branch_intent("main")
        assert result.get("type", "") == ""

    def test_hotfix_branch(self):
        result = parse_branch_intent("hotfix/critical-bug")
        assert result["type"] == "debugging"


class TestPredictFiles:
    """Test file co-occurrence prediction."""

    class FakeDB:
        def __init__(self, episodes):
            self._episodes = episodes

        def list_episodes(self, limit=100, **kwargs):
            return self._episodes[:limit]

    def test_predicts_cooccurring_files(self):
        episodes = [
            Episode(id=_new_id(), files_touched=["src/auth.py", "src/tokens.py"]),
            Episode(id=_new_id(), files_touched=["src/auth.py", "src/tokens.py"]),
            Episode(id=_new_id(), files_touched=["src/auth.py", "src/tokens.py"]),
            Episode(id=_new_id(), files_touched=["src/auth.py", "src/other.py"]),
        ]
        db = self.FakeDB(episodes)
        results = predict_files(["src/auth.py"], db, limit=5)
        # tokens.py should be top prediction (3 co-occurrences)
        assert len(results) > 0
        files = [f for f, _ in results]
        assert "src/tokens.py" in files

    def test_excludes_current_files(self):
        episodes = [
            Episode(id=_new_id(), files_touched=["a.py", "b.py"]),
        ]
        db = self.FakeDB(episodes)
        results = predict_files(["a.py", "b.py"], db)
        files = [f for f, _ in results]
        assert "a.py" not in files
        assert "b.py" not in files

    def test_empty_input(self):
        db = self.FakeDB([])
        results = predict_files([], db)
        assert results == []


class TestPredictMistakes:
    """Test mistake prediction from failure records."""

    class FakeDB:
        def __init__(self, failures):
            self._failures = failures

        def list_failure_records(self, project=None, limit=100, **kwargs):
            return self._failures[:limit]

    def test_predicts_from_file_match(self):
        failures = [
            FailureRecord(
                what_failed="Race condition in auth handler",
                why_failed="No lock",
                what_worked="Added mutex",
                context="src/auth.py",
                occurrence_count=8,  # P = 8/13 ≈ 0.62
            ),
        ]
        db = self.FakeDB(failures)
        results = predict_mistakes(
            predicted_files=["src/auth.py"],
            predicted_domains=[],
            db=db,
        )
        assert len(results) >= 1
        assert results[0][1] > 0.3  # probability above threshold

    def test_no_prediction_for_low_occurrence(self):
        failures = [
            FailureRecord(
                what_failed="One-off issue",
                why_failed="Rare",
                what_worked="Workaround",
                context="src/rare.py",
                occurrence_count=1,  # P = 1/6 ≈ 0.17
            ),
        ]
        db = self.FakeDB(failures)
        results = predict_mistakes(
            predicted_files=["src/rare.py"],
            predicted_domains=[],
            db=db,
        )
        assert len(results) == 0

    def test_empty_inputs(self):
        db = self.FakeDB([])
        results = predict_mistakes([], [], db)
        assert results == []


class TestScoreRelevance:
    """Test relevance scoring."""

    def test_full_domain_overlap(self):
        traj = Trajectory(
            predicted_files=[],
            predicted_domains=["concurrency", "database-access"],
        )
        score = score_relevance(
            item_domains=["concurrency"],
            item_files=[],
            trajectory=traj,
        )
        assert score > 0.3

    def test_full_file_overlap(self):
        traj = Trajectory(
            predicted_files=["src/auth.py", "src/tokens.py"],
            predicted_domains=[],
        )
        score = score_relevance(
            item_domains=[],
            item_files=["src/auth.py"],
            trajectory=traj,
        )
        assert score > 0.3

    def test_no_overlap(self):
        traj = Trajectory(
            predicted_files=["src/auth.py"],
            predicted_domains=["authentication"],
        )
        score = score_relevance(
            item_domains=["deployment"],
            item_files=["infra/docker.yml"],
            trajectory=traj,
        )
        assert score == 0.0

    def test_empty_trajectory(self):
        traj = Trajectory()
        score = score_relevance(["concurrency"], ["src/lock.py"], traj)
        assert score == 0.0


class TestPreemptionEngine:
    """Integration tests for the PreemptionEngine."""

    class FakeDB:
        def list_episodes(self, limit=100, **kwargs):
            return [
                Episode(id=_new_id(), files_touched=["src/auth.py", "src/tokens.py"]),
                Episode(id=_new_id(), files_touched=["src/auth.py", "src/session.py"]),
            ]

        def list_failure_records(self, project=None, limit=100, **kwargs):
            return [
                FailureRecord(
                    what_failed="Token expiry not handled",
                    why_failed="Missing refresh logic",
                    what_worked="Added token refresh middleware",
                    context="src/tokens.py",
                    category="api_misuse",
                    occurrence_count=6,
                ),
            ]

    def test_infer_trajectory(self):
        db = self.FakeDB()
        engine = PreemptionEngine(db)
        traj = engine.infer_trajectory(
            project="myapp",
            branch="fix/auth-timeout",
            current_files=["src/auth.py"],
        )
        assert isinstance(traj, Trajectory)
        assert "src/tokens.py" in traj.predicted_files or "src/session.py" in traj.predicted_files

    def test_preemptive_context(self):
        db = self.FakeDB()
        engine = PreemptionEngine(db)
        traj = engine.infer_trajectory(
            project="myapp",
            branch="fix/auth-timeout",
            current_files=["src/auth.py"],
        )
        ctx = engine.get_preemptive_context(traj, project="myapp")
        assert "predicted_files" in ctx
        assert "warnings" in ctx
