"""Tests for signals.py — signal weight calculations."""

from __future__ import annotations

from neurosync.signals import (
    compute_composite_weight,
    compute_correction_signal,
    compute_depth_signal,
    compute_duration_signal,
    compute_episode_signals,
    compute_explicit_signal,
    compute_repetition_signal,
    compute_surprise_signal,
)


class TestSignals:
    def test_correction_signal(self):
        s1 = compute_correction_signal(1)
        assert s1.multiplier == 2.0
        s3 = compute_correction_signal(3)
        assert s3.multiplier == 8.0
        s10 = compute_correction_signal(10)
        assert s10.multiplier == 1000.0  # capped

    def test_depth_signal(self):
        s0 = compute_depth_signal([])
        assert s0.multiplier == 1.0
        s1 = compute_depth_signal(["service"])
        assert s1.multiplier == 1.0
        s3 = compute_depth_signal(["service", "dao", "inventory"])
        assert s3.multiplier == 3.0

    def test_depth_signal_unknown_layers(self):
        s = compute_depth_signal(["unknown_layer", "another"])
        assert s.multiplier == 1.0  # no known layers

    def test_surprise_signal(self):
        s_yes = compute_surprise_signal(True)
        assert s_yes.multiplier == 3.0
        s_no = compute_surprise_signal(False)
        assert s_no.multiplier == 1.0

    def test_repetition_signal(self):
        s0 = compute_repetition_signal(0)
        assert s0.multiplier == 1.0
        s1 = compute_repetition_signal(1)
        assert s1.multiplier == 1.0
        s2 = compute_repetition_signal(2)
        assert s2.multiplier == 5.0

    def test_duration_signal(self):
        s = compute_duration_signal(300, 600)
        assert 0.1 <= s.multiplier <= 5.0
        s_zero = compute_duration_signal(0, 0)
        assert s_zero.multiplier >= 0.1

    def test_explicit_signal(self):
        s = compute_explicit_signal()
        assert s.multiplier == 10.0

    def test_composite_weight(self):
        from neurosync.signals import SignalResult
        signals = [
            SignalResult("CORRECTION", 1.0, 4.0),
            SignalResult("DEPTH", 2.0, 2.0),
            SignalResult("EXPLICIT", 1.0, 10.0),
        ]
        weight = compute_composite_weight(signals)
        assert weight == 80.0

    def test_composite_weight_capped(self):
        from neurosync.signals import SignalResult
        signals = [
            SignalResult("A", 1.0, 100.0),
            SignalResult("B", 1.0, 100.0),
        ]
        weight = compute_composite_weight(signals, max_weight=1000.0)
        assert weight == 1000.0

    def test_compute_episode_signals(self):
        signals, weight = compute_episode_signals(
            event_type="correction",
            layers_touched=["service", "dao"],
            correction_count=2,
            is_explicit=True,
        )
        assert len(signals) >= 2
        assert weight > 1.0
        types = {s.signal_type for s in signals}
        assert "CORRECTION" in types
        assert "EXPLICIT" in types

    def test_compute_episode_signals_minimal(self):
        signals, weight = compute_episode_signals(
            event_type="decision",
            layers_touched=[],
        )
        assert weight == 1.0
