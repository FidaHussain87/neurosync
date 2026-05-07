"""Tests for Reflexive Calibration Network — epistemic self-awareness for LLMs."""

from neurosync.calibration import (
    AccuracyTracker,
    CalibrationReport,
    DomainAccuracy,
    FailurePrecursor,
    ReflexiveCalibrationEngine,
    calibrate_confidence,
    compute_hazard_rate,
    detect_failure_precursors,
    isotonic_regression,
)
from neurosync.models import Episode, Theory, _new_id, _utcnow


class TestDomainAccuracy:
    """Tests for per-domain accuracy tracking."""

    def test_initial_accuracy_is_prior(self):
        da = DomainAccuracy(domain="testing")
        assert da.accuracy == 0.5
        assert da.confidence_band == "low"

    def test_accuracy_computation(self):
        da = DomainAccuracy(domain="auth", total_assertions=10, corrections=3)
        assert da.accuracy == 0.7

    def test_high_accuracy(self):
        da = DomainAccuracy(domain="api", total_assertions=20, corrections=1)
        assert da.accuracy == 0.95
        assert da.confidence_band == "high"

    def test_low_accuracy(self):
        da = DomainAccuracy(domain="concurrency", total_assertions=10, corrections=5)
        assert da.accuracy == 0.5
        assert da.confidence_band == "low"

    def test_unreliable(self):
        da = DomainAccuracy(domain="x", total_assertions=10, corrections=6)
        assert da.confidence_band == "unreliable"

    def test_recent_accuracy(self):
        da = DomainAccuracy(
            domain="test",
            last_5_outcomes=[True, True, False, True, False],
        )
        assert da.recent_accuracy == 0.6

    def test_brier_score_perfect(self):
        da = DomainAccuracy(domain="x", total_assertions=10, corrections=0)
        assert da.brier_score == 0.0

    def test_brier_score_bad(self):
        da = DomainAccuracy(domain="x", total_assertions=10, corrections=8)
        # accuracy = 0.2, p = 0.2
        # Brier = (2*(1-0.2)^2 + 8*0.2^2)/10 = (2*0.64 + 8*0.04)/10 = 0.16
        # This is actually well-calibrated (low Brier) — the system accurately
        # knows it's bad at this domain. High Brier requires miscalibration.
        assert abs(da.brier_score - 0.16) < 0.01

    def test_brier_score_miscalibrated(self):
        # System that claims ~50% accuracy but is actually much worse
        # total=10, corrections=9, accuracy=0.1, p=0.1
        # Brier = (1*(1-0.1)^2 + 9*0.1^2)/10 = (0.81 + 0.09)/10 = 0.09
        # Even this is low because Brier measures forecast vs outcome:
        # predicting p=0.1 when you get correct only 10% is well-calibrated!
        # Brier is ONLY high when predictions are wrong.
        # For a proper miscalibration test: system predicts 80% but gets 20%:
        # We can't create that scenario with DomainAccuracy since it uses
        # actual accuracy as its prediction. This verifies the formula is correct.
        da = DomainAccuracy(domain="x", total_assertions=10, corrections=5)
        # accuracy = 0.5, Brier = (5*0.25 + 5*0.25)/10 = 0.25
        assert abs(da.brier_score - 0.25) < 0.01


class TestIsotonicRegression:
    """Tests for PAVA isotonic calibration."""

    def test_empty_input(self):
        assert isotonic_regression([]) == []

    def test_already_monotone(self):
        points = [(0.2, 0.1), (0.5, 0.5), (0.8, 0.9)]
        result = isotonic_regression(points)
        assert len(result) == 3
        # Should preserve monotonicity
        values = [r[1] for r in result]
        for i in range(len(values) - 1):
            assert values[i] <= values[i + 1]

    def test_violation_pooled(self):
        # Point at 0.5 has higher outcome than point at 0.7 — violation
        points = [(0.3, 0.3), (0.5, 0.8), (0.7, 0.4), (0.9, 0.9)]
        result = isotonic_regression(points)
        values = [r[1] for r in result]
        # Must be monotonically non-decreasing
        for i in range(len(values) - 1):
            assert values[i] <= values[i + 1]

    def test_single_point(self):
        result = isotonic_regression([(0.5, 0.7)])
        assert len(result) == 1
        assert result[0] == (0.5, 0.7)

    def test_all_same_predicted(self):
        points = [(0.5, 0.3), (0.5, 0.7), (0.5, 0.5)]
        result = isotonic_regression(points)
        assert len(result) == 3


class TestCalibrateConfidence:
    """Tests for confidence calibration mapping."""

    def test_no_curve_returns_claimed(self):
        assert calibrate_confidence(0.8, []) == 0.8

    def test_interpolation(self):
        curve = [(0.0, 0.0), (0.5, 0.3), (1.0, 0.8)]
        # At 0.25: interpolate between (0.0, 0.0) and (0.5, 0.3) → 0.15
        result = calibrate_confidence(0.25, curve)
        assert abs(result - 0.15) < 0.01

    def test_extrapolation_below(self):
        curve = [(0.3, 0.2), (0.7, 0.6)]
        result = calibrate_confidence(0.1, curve)
        assert result == 0.2  # Clamps to first point

    def test_extrapolation_above(self):
        curve = [(0.3, 0.2), (0.7, 0.6)]
        result = calibrate_confidence(0.9, curve)
        assert result == 0.6  # Clamps to last point

    def test_exact_point(self):
        curve = [(0.0, 0.0), (0.5, 0.4), (1.0, 0.9)]
        result = calibrate_confidence(0.5, curve)
        assert abs(result - 0.4) < 0.01


class TestHazardRate:
    """Tests for instantaneous failure risk computation."""

    def test_no_assertions_uses_baseline(self):
        h = compute_hazard_rate(0, 0, 30.0)
        assert h.hazard_rate == 0.1  # default baseline
        assert h.fatigue_factor == 1.0

    def test_high_correction_rate(self):
        h = compute_hazard_rate(3, 5, 60.0)
        assert h.hazard_rate == 0.6

    def test_fatigue_factor_short_session(self):
        h = compute_hazard_rate(1, 10, 60.0)
        assert h.fatigue_factor == 1.0

    def test_fatigue_factor_long_session(self):
        h = compute_hazard_rate(1, 10, 150.0)
        # 150 - 90 = 60 min overtime → fatigue = 1.0 + 0.5 * (60/60) = 1.5
        assert h.fatigue_factor == 1.5
        # Hazard adjusted: 0.1 * 1.5 = 0.15
        assert abs(h.hazard_rate - 0.15) < 0.01

    def test_fatigue_compounds_with_corrections(self):
        h = compute_hazard_rate(4, 10, 180.0)
        # base hazard: 0.4, fatigue: 1.0 + 0.5 * (90/60) = 1.75
        assert h.fatigue_factor == 1.75
        assert abs(h.hazard_rate - 0.7) < 0.01


class TestFailurePrecursors:
    """Tests for failure pattern detection."""

    def test_empty_episodes(self):
        assert detect_failure_precursors([]) == []

    def test_no_corrections_no_precursors(self):
        episodes = [
            Episode(id=_new_id(), event_type="discovery", domains=["testing"]),
            Episode(id=_new_id(), event_type="discovery", domains=["testing"]),
        ]
        assert detect_failure_precursors(episodes) == []

    def test_detects_high_correction_domain(self):
        episodes = []
        # 4 corrections in "concurrency"
        for _ in range(4):
            episodes.append(Episode(
                id=_new_id(), event_type="correction", domains=["concurrency"],
            ))
        # 2 successful in "concurrency"
        for _ in range(2):
            episodes.append(Episode(
                id=_new_id(), event_type="discovery", domains=["concurrency"],
            ))
        # 5 successful in other domains (baseline)
        for _ in range(5):
            episodes.append(Episode(
                id=_new_id(), event_type="discovery", domains=["testing"],
            ))

        precursors = detect_failure_precursors(episodes, min_observations=3)
        assert len(precursors) >= 1
        # Concurrency should be flagged (4/6 = 67% correction rate)
        domains_found = [p.pattern_domains for p in precursors]
        assert ["concurrency"] in domains_found

    def test_respects_min_observations(self):
        episodes = [
            Episode(id=_new_id(), event_type="correction", domains=["rare"]),
            Episode(id=_new_id(), event_type="correction", domains=["rare"]),
        ]
        # Only 2 observations, below min_observations=3
        precursors = detect_failure_precursors(episodes, min_observations=3)
        rare_precursors = [p for p in precursors if "rare" in p.pattern_domains]
        assert len(rare_precursors) == 0

    def test_domain_pair_detection(self):
        episodes = []
        # Corrections happen when concurrency + database co-occur
        for _ in range(4):
            episodes.append(Episode(
                id=_new_id(), event_type="correction",
                domains=["concurrency", "database-access"],
            ))
        # No corrections in each domain alone
        for _ in range(10):
            episodes.append(Episode(
                id=_new_id(), event_type="discovery", domains=["concurrency"],
            ))
        for _ in range(10):
            episodes.append(Episode(
                id=_new_id(), event_type="discovery", domains=["database-access"],
            ))

        precursors = detect_failure_precursors(episodes, min_observations=3)
        # The pair should have higher correction rate than individuals
        pair_precursors = [
            p for p in precursors
            if set(p.pattern_domains) == {"concurrency", "database-access"}
        ]
        assert len(pair_precursors) >= 1
        assert pair_precursors[0].correction_rate == 1.0  # 4/4


class TestAccuracyTracker:
    """Tests for the accuracy tracking system."""

    def test_record_correct(self):
        tracker = AccuracyTracker()
        tracker.record_assertion(["testing"], was_correct=True)
        da = tracker.get_domain("testing")
        assert da.total_assertions == 1
        assert da.corrections == 0
        assert da.accuracy == 1.0

    def test_record_incorrect(self):
        tracker = AccuracyTracker()
        tracker.record_assertion(["testing"], was_correct=False)
        da = tracker.get_domain("testing")
        assert da.corrections == 1

    def test_multi_domain_assertion(self):
        tracker = AccuracyTracker()
        tracker.record_assertion(["auth", "concurrency"], was_correct=False)
        assert tracker.get_domain("auth").corrections == 1
        assert tracker.get_domain("concurrency").corrections == 1

    def test_build_from_episodes(self):
        episodes = [
            Episode(id=_new_id(), event_type="correction", domains=["auth"]),
            Episode(id=_new_id(), event_type="discovery", domains=["auth"]),
            Episode(id=_new_id(), event_type="discovery", domains=["auth"]),
        ]
        tracker = AccuracyTracker()
        tracker.build_from_episodes(episodes)
        da = tracker.get_domain("auth")
        assert da.total_assertions == 3
        assert da.corrections == 1
        assert abs(da.accuracy - 0.667) < 0.01

    def test_build_from_theories(self):
        theories = [
            Theory(
                id="t1", content="x", scope_qualifier="testing",
                confirmation_count=8, contradiction_count=2, active=True,
            ),
        ]
        tracker = AccuracyTracker()
        tracker.build_from_theories(theories)
        da = tracker.get_domain("testing")
        assert da.total_assertions == 10
        assert da.corrections == 2

    def test_mean_accuracy(self):
        tracker = AccuracyTracker()
        # Domain A: 80% accuracy (needs >= 3 observations)
        for _ in range(8):
            tracker.record_assertion(["a"], was_correct=True)
        for _ in range(2):
            tracker.record_assertion(["a"], was_correct=False)
        # Domain B: 60% accuracy
        for _ in range(6):
            tracker.record_assertion(["b"], was_correct=True)
        for _ in range(4):
            tracker.record_assertion(["b"], was_correct=False)
        assert abs(tracker.mean_accuracy - 0.7) < 0.01

    def test_worst_domain(self):
        tracker = AccuracyTracker()
        for _ in range(9):
            tracker.record_assertion(["good"], was_correct=True)
        tracker.record_assertion(["good"], was_correct=False)
        for _ in range(3):
            tracker.record_assertion(["bad"], was_correct=True)
        for _ in range(7):
            tracker.record_assertion(["bad"], was_correct=False)
        name, acc = tracker.worst_domain
        assert name == "bad"
        assert abs(acc - 0.3) < 1e-9


class TestReflexiveCalibrationEngine:
    """Integration tests for the full RCN pipeline."""

    class FakeDB:
        def __init__(self, episodes=None, theories=None):
            self._episodes = episodes or []
            self._theories = theories or []

        def list_episodes(self, limit=1000, **kwargs):
            return self._episodes[:limit]

        def list_theories(self, limit=500, **kwargs):
            return self._theories[:limit]

    def test_calibrate_empty_db(self):
        engine = ReflexiveCalibrationEngine(self.FakeDB())
        report = engine.calibrate()
        assert isinstance(report, CalibrationReport)
        assert report.doubt_level == "none"

    def test_calibrate_with_corrections(self):
        episodes = []
        # 5 corrections in concurrency
        for _ in range(5):
            episodes.append(Episode(
                id=_new_id(), event_type="correction", domains=["concurrency"],
            ))
        # 5 successes in concurrency
        for _ in range(5):
            episodes.append(Episode(
                id=_new_id(), event_type="discovery", domains=["concurrency"],
            ))

        engine = ReflexiveCalibrationEngine(self.FakeDB(episodes=episodes))
        report = engine.calibrate(context_domains=["concurrency"])
        assert report.mean_accuracy <= 0.6
        assert report.doubt_level in ("moderate", "severe")
        assert report.should_verify is True

    def test_to_dict_format(self):
        engine = ReflexiveCalibrationEngine(self.FakeDB())
        report = engine.calibrate()
        d = report.to_dict()
        assert "mean_accuracy" in d
        assert "doubt_level" in d
        assert "should_verify" in d

    def test_format_injection_empty_when_safe(self):
        engine = ReflexiveCalibrationEngine(self.FakeDB())
        report = engine.calibrate()
        assert report.format_injection() == ""

    def test_format_injection_with_warnings(self):
        episodes = []
        for _ in range(8):
            episodes.append(Episode(
                id=_new_id(), event_type="correction", domains=["auth"],
            ))
        for _ in range(2):
            episodes.append(Episode(
                id=_new_id(), event_type="discovery", domains=["auth"],
            ))

        engine = ReflexiveCalibrationEngine(self.FakeDB(episodes=episodes))
        report = engine.calibrate(context_domains=["auth"])
        injection = report.format_injection()
        assert len(injection) > 0

    def test_record_outcome_updates_model(self):
        engine = ReflexiveCalibrationEngine(self.FakeDB())
        engine.initialize()
        engine.record_outcome(["testing"], was_correct=False)
        engine.record_outcome(["testing"], was_correct=False)
        engine.record_outcome(["testing"], was_correct=True)
        da = engine._tracker.get_domain("testing")
        assert da.total_assertions == 3
        assert da.corrections == 2

    def test_get_domain_report(self):
        episodes = []
        for _ in range(5):
            episodes.append(Episode(
                id=_new_id(), event_type="correction", domains=["auth"],
            ))
        for _ in range(15):
            episodes.append(Episode(
                id=_new_id(), event_type="discovery", domains=["auth"],
            ))

        engine = ReflexiveCalibrationEngine(self.FakeDB(episodes=episodes))
        engine.initialize()
        report = engine.get_domain_report()
        assert "auth" in report
        assert report["auth"]["accuracy"] == 0.75
        assert report["auth"]["corrections"] == 5

    def test_calibration_curve_from_theories(self):
        # Theories need varying confidence (spread > 0.1) and ≥3 observations each
        theories = [
            Theory(id=f"t{i}", content=f"theory {i}",
                   confidence=0.3 + i * 0.07,  # 0.3, 0.37, 0.44, ..., 0.93
                   confirmation_count=5 + i,
                   contradiction_count=max(1, 5 - i),
                   active=True)
            for i in range(10)
        ]
        engine = ReflexiveCalibrationEngine(self.FakeDB(theories=theories))
        engine.initialize()
        # Should have built a calibration curve (spread = 0.63 > 0.1)
        assert len(engine._calibration_curve) >= 1

    def test_high_fatigue_triggers_warning(self):
        engine = ReflexiveCalibrationEngine(self.FakeDB())
        report = engine.calibrate(session_duration_minutes=180.0, session_corrections=2, session_assertions=5)
        # Long session + corrections should trigger fatigue warning
        assert report.hazard.fatigue_factor > 1.0
