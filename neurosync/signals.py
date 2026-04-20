"""Signal weight calculations — 8 signal types that compose into episode weights.

Active: CORRECTION, DEPTH, SURPRISE, REPETITION, EXPLICIT, INTUITION, PASSIVE.
Defined but unwired: DURATION (requires session-level timing data).
"""

from __future__ import annotations

from dataclasses import dataclass

# Architecture layers for DEPTH signal
KNOWN_LAYERS = frozenset({
    "inventory",
    "dao",
    "service",
    "ismr",
    "ism",
    "extcomm",
    "scanner",
    "endpoint",
    "ui",
    "config",
    "test",
})


@dataclass
class SignalResult:
    """Result of a signal weight computation."""

    signal_type: str
    raw_value: float
    multiplier: float


def compute_correction_signal(correction_count: int) -> SignalResult:
    """CORRECTION: User corrected AI N times in session. Weight = 2^N."""
    multiplier = min(2**correction_count, 1000.0)
    return SignalResult(
        signal_type="CORRECTION",
        raw_value=float(correction_count),
        multiplier=multiplier,
    )


def compute_depth_signal(layers_touched: list[str]) -> SignalResult:
    """DEPTH: Files touched across N architecture layers. Weight = N."""
    unique_layers = {layer.lower() for layer in layers_touched if layer.lower() in KNOWN_LAYERS}
    n = max(len(unique_layers), 1)
    return SignalResult(
        signal_type="DEPTH",
        raw_value=float(n),
        multiplier=float(n),
    )


def compute_surprise_signal(contradicts_theory: bool) -> SignalResult:
    """SURPRISE: Episode contradicts existing theory. Weight = x3."""
    multiplier = 3.0 if contradicts_theory else 1.0
    return SignalResult(
        signal_type="SURPRISE",
        raw_value=1.0 if contradicts_theory else 0.0,
        multiplier=multiplier,
    )


def compute_repetition_signal(times_explained: int) -> SignalResult:
    """REPETITION: User re-explained something from past session. Weight = x5."""
    multiplier = 5.0 if times_explained > 1 else 1.0
    return SignalResult(
        signal_type="REPETITION",
        raw_value=float(times_explained),
        multiplier=multiplier,
    )


def compute_duration_signal(
    topic_duration_seconds: float, session_duration_seconds: float
) -> SignalResult:
    """DURATION: Time spent on topic vs session total. Weight = ratio (min 0.1, max 5.0)."""
    if session_duration_seconds <= 0:
        ratio = 1.0
    else:
        ratio = topic_duration_seconds / session_duration_seconds
    multiplier = max(0.1, min(ratio * 2.0, 5.0))
    return SignalResult(
        signal_type="DURATION",
        raw_value=ratio,
        multiplier=multiplier,
    )


def compute_explicit_signal() -> SignalResult:
    """EXPLICIT: User said 'remember this'. Weight = x10."""
    return SignalResult(
        signal_type="EXPLICIT",
        raw_value=1.0,
        multiplier=10.0,
    )


def compute_passive_signal() -> SignalResult:
    """PASSIVE: Automatically observed event (e.g., git changes). Weight = x0.3."""
    return SignalResult(
        signal_type="PASSIVE",
        raw_value=1.0,
        multiplier=0.3,
    )


def compute_intuition_signal(importance: int) -> SignalResult:
    """INTUITION: Agent rates episode importance 1-5. Weight = max(1.0, importance * 0.4)."""
    clamped = max(1, min(importance, 5))
    multiplier = max(1.0, clamped * 0.4)
    return SignalResult(
        signal_type="INTUITION",
        raw_value=float(clamped),
        multiplier=multiplier,
    )


def compute_composite_weight(
    signals: list[SignalResult],
    max_weight: float = 1000.0,
) -> float:
    """Compute composite weight as product of all multipliers, capped."""
    weight = 1.0
    for signal in signals:
        weight *= signal.multiplier
    return min(weight, max_weight)


def compute_episode_signals(
    event_type: str,
    layers_touched: list[str],
    correction_count: int = 0,
    contradicts_theory: bool = False,
    times_explained: int = 0,
    topic_duration: float = 0.0,
    session_duration: float = 0.0,
    is_explicit: bool = False,
    importance: int = 0,
    is_passive: bool = False,
) -> tuple[list[SignalResult], float]:
    """Compute all applicable signals for an episode. Returns (signals, composite_weight).

    Active signal types: CORRECTION, DEPTH, SURPRISE, REPETITION, EXPLICIT,
    INTUITION, PASSIVE. DURATION is defined but requires session-level timing
    data that is not yet collected.
    """
    signals: list[SignalResult] = []

    # PASSIVE: auto-observed events (git changes) — always record for audit trail
    if is_passive or event_type == "observed":
        signals.append(compute_passive_signal())

    if event_type == "correction" and correction_count > 0:
        signals.append(compute_correction_signal(correction_count))

    if layers_touched:
        depth = compute_depth_signal(layers_touched)
        if depth.multiplier > 1.0:
            signals.append(depth)

    if contradicts_theory:
        signals.append(compute_surprise_signal(True))

    if times_explained > 1:
        signals.append(compute_repetition_signal(times_explained))

    if session_duration > 0:
        dur = compute_duration_signal(topic_duration, session_duration)
        if dur.multiplier != 1.0:
            signals.append(dur)

    if is_explicit:
        signals.append(compute_explicit_signal())

    if importance > 0:
        intuition = compute_intuition_signal(importance)
        if intuition.multiplier > 1.0:
            signals.append(intuition)

    composite = compute_composite_weight(signals) if signals else 1.0
    return signals, composite
