"""Reflexive Calibration Network (RCN) — epistemic self-awareness for LLMs.

Gives the LLM ground-truth feedback about its own accuracy per domain,
predicts when it's about to be wrong, and injects calibrated uncertainty.

Core algorithms:
- Bayesian accuracy tracking: P(correct | domain, context)
- Isotonic calibration: maps self-reported confidence to actual accuracy
- Failure precursor detection: discovers context patterns → correction clusters
- Hazard rate: λ(t) = corrections(t) / surviving_assertions(t)
- Metacognitive triggers: automatic "STOP, verify" injection

No existing MCP tool, product, or research paper implements this:
teaching an LLM its own accuracy curve from its own correction history.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from neurosync.models import Episode, Theory


# --- Data Models ---


@dataclass
class DomainAccuracy:
    """Tracked accuracy for a single domain."""

    domain: str
    total_assertions: int = 0
    corrections: int = 0
    last_5_outcomes: list[bool] = field(default_factory=list)  # True=correct, False=wrong

    @property
    def accuracy(self) -> float:
        if self.total_assertions == 0:
            return 0.5  # Prior: no data = 50% confidence
        return 1.0 - (self.corrections / self.total_assertions)

    @property
    def recent_accuracy(self) -> float:
        if not self.last_5_outcomes:
            return 0.5
        return sum(self.last_5_outcomes) / len(self.last_5_outcomes)

    @property
    def brier_score(self) -> float:
        """Brier score: lower is better calibrated. 0 = perfect, 1 = worst.

        BS = (1/N) * [correct*(1-p)^2 + corrections*p^2]
        where p = predicted probability of being correct (= self.accuracy).
        """
        if self.total_assertions == 0:
            return 0.5
        p = self.accuracy
        correct = self.total_assertions - self.corrections
        return (correct * (1.0 - p) ** 2 + self.corrections * p ** 2) / self.total_assertions

    @property
    def confidence_band(self) -> str:
        """Human-readable confidence level."""
        acc = self.accuracy
        if acc >= 0.9:
            return "high"
        if acc >= 0.7:
            return "moderate"
        if acc >= 0.5:
            return "low"
        return "unreliable"


@dataclass
class FailurePrecursor:
    """A discovered context pattern that predicts corrections."""

    pattern_domains: list[str]
    pattern_description: str
    correction_rate: float  # 0-1, how often this pattern leads to corrections
    observation_count: int
    risk_multiplier: float  # How much more likely to be wrong vs baseline
    example_corrections: list[str] = field(default_factory=list)


@dataclass
class HazardSnapshot:
    """Instantaneous risk assessment for the current moment."""

    hazard_rate: float  # λ(t): instantaneous failure probability
    session_corrections_so_far: int
    session_assertions_so_far: int
    time_in_session_minutes: float
    fatigue_factor: float  # 1.0 = normal, >1 = elevated risk due to session length
    active_precursors: list[FailurePrecursor] = field(default_factory=list)


@dataclass
class CalibrationReport:
    """Full reflexive calibration report for the current context."""

    # Per-domain accuracy
    domain_accuracies: dict[str, DomainAccuracy] = field(default_factory=dict)

    # Current risk assessment
    hazard: HazardSnapshot | None = None

    # Active warnings (to inject into LLM context)
    metacognitive_triggers: list[str] = field(default_factory=list)

    # Overall calibration quality
    mean_accuracy: float = 0.5
    worst_domain: str = ""
    worst_accuracy: float = 1.0

    # Recommendations
    should_verify: bool = False
    doubt_level: str = "none"  # none, mild, moderate, severe

    def to_dict(self) -> dict[str, Any]:
        """Serialize for MCP response."""
        result: dict[str, Any] = {
            "mean_accuracy": round(self.mean_accuracy, 3),
            "doubt_level": self.doubt_level,
            "should_verify": self.should_verify,
        }
        if self.worst_domain:
            result["worst_domain"] = {
                "domain": self.worst_domain,
                "accuracy": round(self.worst_accuracy, 3),
            }
        if self.metacognitive_triggers:
            result["warnings"] = self.metacognitive_triggers
        if self.domain_accuracies:
            result["domains"] = {
                domain: {
                    "accuracy": round(da.accuracy, 3),
                    "recent": round(da.recent_accuracy, 3),
                    "confidence": da.confidence_band,
                    "observations": da.total_assertions,
                }
                for domain, da in sorted(
                    self.domain_accuracies.items(),
                    key=lambda x: x[1].accuracy,
                )[:5]  # Show worst 5
            }
        if self.hazard:
            result["hazard"] = {
                "rate": round(self.hazard.hazard_rate, 3),
                "session_corrections": self.hazard.session_corrections_so_far,
                "fatigue_factor": round(self.hazard.fatigue_factor, 2),
            }
        return result

    def format_injection(self) -> str:
        """Format as compact string to inject into LLM context."""
        parts: list[str] = []
        if self.doubt_level == "severe":
            parts.append("⚠ HIGH ERROR RISK: verify before committing.")
        elif self.doubt_level == "moderate":
            parts.append("△ Elevated error risk in this area.")

        if self.worst_domain and self.worst_accuracy < 0.7:
            da = self.domain_accuracies.get(self.worst_domain)
            if da:
                parts.append(
                    f"Your accuracy in '{self.worst_domain}': "
                    f"{self.worst_accuracy:.0%} ({da.corrections} "
                    f"corrections / {da.total_assertions} assertions)."
                )
            else:
                parts.append(
                    f"Your accuracy in '{self.worst_domain}': {self.worst_accuracy:.0%}."
                )

        if self.hazard and self.hazard.fatigue_factor > 1.3:
            parts.append(
                f"Session fatigue elevated ({self.hazard.fatigue_factor:.1f}x risk)."
            )

        for trigger in self.metacognitive_triggers[:2]:
            parts.append(trigger)

        return " ".join(parts) if parts else ""


# --- Isotonic Calibration ---


def isotonic_regression(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Pool Adjacent Violators Algorithm (PAVA) for isotonic regression.

    Input: list of (predicted_confidence, actual_outcome) pairs
    Output: calibrated mapping (monotonically non-decreasing)

    This maps the LLM's self-reported confidence to actual accuracy,
    revealing systematic over/under-confidence.
    """
    if not points:
        return []

    # Sort by predicted confidence
    sorted_points = sorted(points, key=lambda p: p[0])
    n = len(sorted_points)

    # Initialize blocks: each point is its own block
    values = [p[1] for p in sorted_points]
    weights = [1.0] * n

    # Pool Adjacent Violators
    i = 0
    while i < n - 1:
        if values[i] > values[i + 1]:
            # Violation: pool i and i+1
            combined_weight = weights[i] + weights[i + 1]
            combined_value = (values[i] * weights[i] + values[i + 1] * weights[i + 1]) / combined_weight
            values[i] = combined_value
            weights[i] = combined_weight
            values.pop(i + 1)
            weights.pop(i + 1)
            n -= 1
            # Check backward for new violations
            if i > 0:
                i -= 1
        else:
            i += 1

    # Rebuild mapping: assign pooled values back to original points
    result: list[tuple[float, float]] = []
    idx = 0
    for block_idx in range(len(values)):
        count = round(weights[block_idx])
        for _ in range(count):
            if idx < len(sorted_points):
                result.append((sorted_points[idx][0], values[block_idx]))
                idx += 1

    return result


def calibrate_confidence(
    claimed_confidence: float,
    calibration_curve: list[tuple[float, float]],
) -> float:
    """Map a claimed confidence to calibrated actual accuracy.

    Uses linear interpolation on the isotonic calibration curve.
    """
    if not calibration_curve:
        return claimed_confidence

    # Find surrounding points for interpolation
    for i in range(len(calibration_curve) - 1):
        x0, y0 = calibration_curve[i]
        x1, y1 = calibration_curve[i + 1]
        if x0 <= claimed_confidence <= x1:
            # Linear interpolation
            if x1 == x0:
                return y0
            t = (claimed_confidence - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)

    # Extrapolate from endpoints
    if claimed_confidence <= calibration_curve[0][0]:
        return calibration_curve[0][1]
    return calibration_curve[-1][1]


# --- Hazard Rate Function ---


def compute_hazard_rate(
    session_corrections: int,
    session_assertions: int,
    session_duration_minutes: float,
    baseline_rate: float = 0.1,
) -> HazardSnapshot:
    """Compute instantaneous failure risk.

    λ(t) = corrections(t) / surviving_assertions(t)

    Adjusted by session fatigue: longer sessions → higher error rate.
    Fatigue model: exponential growth after 90 minutes.
    """
    if session_assertions == 0:
        hazard_rate = baseline_rate
    else:
        hazard_rate = session_corrections / session_assertions

    # Fatigue factor: sessions over 90 min have elevated risk
    # Based on cognitive science: error rates increase ~1.5x per hour after 90min
    fatigue_factor = 1.0
    if session_duration_minutes > 90:
        overtime = session_duration_minutes - 90
        fatigue_factor = 1.0 + 0.5 * (overtime / 60.0)

    # Compound: hazard * fatigue
    adjusted_hazard = hazard_rate * fatigue_factor

    return HazardSnapshot(
        hazard_rate=adjusted_hazard,
        session_corrections_so_far=session_corrections,
        session_assertions_so_far=session_assertions,
        time_in_session_minutes=session_duration_minutes,
        fatigue_factor=fatigue_factor,
    )


# --- Failure Precursor Detection ---


def detect_failure_precursors(
    episodes: list[Episode],
    min_observations: int = 3,
    min_correction_rate: float = 0.3,
) -> list[FailurePrecursor]:
    """Discover context patterns that predict corrections.

    Algorithm:
    1. For each episode, identify its domain set
    2. Count episodes (not domain occurrences) per pattern — each episode
       contributes at most once per pattern to avoid multi-domain inflation
    3. Compute correction rate per pattern vs baseline
    4. Report patterns exceeding threshold
    """
    if not episodes:
        return []

    # Compute baseline correction rate (per-episode, no double-counting)
    total = len(episodes)
    total_corrections = sum(1 for ep in episodes if ep.event_type == "correction")
    baseline_rate = total_corrections / max(total, 1)

    if baseline_rate == 0:
        return []

    # Track episodes per pattern (set of episode indices to avoid double-counting)
    pattern_episodes: dict[tuple[str, ...], set[int]] = defaultdict(set)
    pattern_corrections: dict[tuple[str, ...], set[int]] = defaultdict(set)
    pattern_examples: dict[tuple[str, ...], list[str]] = defaultdict(list)

    for ep_idx, ep in enumerate(episodes):
        domains = getattr(ep, "domains", []) or []
        if isinstance(domains, str):
            domains = [d.strip() for d in domains.split(",") if d.strip()]
        if not domains:
            continue

        is_correction = ep.event_type == "correction"

        # Single domains — each episode counted once per domain it has
        for d in domains:
            key = (d,)
            pattern_episodes[key].add(ep_idx)
            if is_correction:
                pattern_corrections[key].add(ep_idx)
                if len(pattern_examples[key]) < 3:
                    pattern_examples[key].append(ep.content[:80] if ep.content else "")

        # Domain pairs — each episode counted once per pair
        sorted_domains = sorted(set(domains))
        if len(sorted_domains) >= 2:
            for i in range(len(sorted_domains)):
                for j in range(i + 1, len(sorted_domains)):
                    key = (sorted_domains[i], sorted_domains[j])
                    pattern_episodes[key].add(ep_idx)
                    if is_correction:
                        pattern_corrections[key].add(ep_idx)
                        if len(pattern_examples[key]) < 3:
                            pattern_examples[key].append(ep.content[:80] if ep.content else "")

    # Filter to significant precursors
    precursors: list[FailurePrecursor] = []
    for domain_key, ep_indices in pattern_episodes.items():
        obs = len(ep_indices)
        corr = len(pattern_corrections.get(domain_key, set()))
        if obs < min_observations:
            continue
        rate = corr / obs
        if rate < min_correction_rate:
            continue

        risk_mult = rate / baseline_rate if baseline_rate > 0 else 1.0

        precursors.append(FailurePrecursor(
            pattern_domains=list(domain_key),
            pattern_description=(
                f"When working in {' + '.join(domain_key)}: "
                f"{corr}/{obs} episodes were corrections ({rate:.0%})"
            ),
            correction_rate=rate,
            observation_count=obs,
            risk_multiplier=risk_mult,
            example_corrections=pattern_examples.get(domain_key, []),
        ))

    # Sort by risk multiplier descending
    precursors.sort(key=lambda p: p.risk_multiplier, reverse=True)
    return precursors[:10]


# --- Bayesian Accuracy Tracker ---


class AccuracyTracker:
    """Maintains per-domain accuracy statistics from episode history."""

    def __init__(self) -> None:
        self._domains: dict[str, DomainAccuracy] = {}

    def get_domain(self, domain: str) -> DomainAccuracy:
        if domain not in self._domains:
            self._domains[domain] = DomainAccuracy(domain=domain)
        return self._domains[domain]

    def peek_domain(self, domain: str) -> DomainAccuracy | None:
        """Read-only lookup — does not create entries for unknown domains."""
        return self._domains.get(domain)

    def record_assertion(self, domains: list[str], was_correct: bool) -> None:
        """Record an assertion outcome across its domains."""
        for domain in domains:
            da = self.get_domain(domain)
            da.total_assertions += 1
            if not was_correct:
                da.corrections += 1
            da.last_5_outcomes.append(was_correct)
            if len(da.last_5_outcomes) > 5:
                da.last_5_outcomes.pop(0)

    def build_from_episodes(self, episodes: list[Episode]) -> None:
        """Build accuracy model from historical episode data.

        Episodes are sorted by timestamp to ensure last_5_outcomes reflects
        the most recent temporal window, not insertion order.
        """
        sorted_eps = sorted(
            episodes,
            key=lambda ep: getattr(ep, "timestamp", "") or "",
        )
        for ep in sorted_eps:
            domains = getattr(ep, "domains", []) or []
            if isinstance(domains, str):
                domains = [d.strip() for d in domains.split(",") if d.strip()]
            if not domains:
                continue

            is_correction = ep.event_type == "correction"
            self.record_assertion(domains, was_correct=not is_correction)

    def build_from_theories(self, theories: list[Theory]) -> None:
        """Augment accuracy model from theory contradiction data."""
        for theory in theories:
            if not theory.active:
                continue
            # Use scope_qualifier as domain signal
            domain = theory.scope_qualifier or theory.scope
            if not domain:
                continue
            da = self.get_domain(domain)
            # Each confirmation = correct assertion, each contradiction = wrong
            da.total_assertions += theory.confirmation_count + theory.contradiction_count
            da.corrections += theory.contradiction_count

    @property
    def all_domains(self) -> dict[str, DomainAccuracy]:
        return self._domains

    @property
    def mean_accuracy(self) -> float:
        if not self._domains:
            return 0.5
        accuracies = [da.accuracy for da in self._domains.values() if da.total_assertions >= 3]
        if not accuracies:
            return 0.5
        return sum(accuracies) / len(accuracies)

    @property
    def worst_domain(self) -> tuple[str, float]:
        """Return (domain_name, accuracy) for the worst-performing domain."""
        worst_name = ""
        worst_acc = 1.0
        for domain, da in self._domains.items():
            if da.total_assertions < 3:
                continue
            if da.accuracy < worst_acc:
                worst_acc = da.accuracy
                worst_name = domain
        return worst_name, worst_acc


# --- Main Engine ---


class ReflexiveCalibrationEngine:
    """Computes epistemic self-model and generates metacognitive triggers."""

    def __init__(self, db: Any) -> None:
        self._db = db
        self._tracker = AccuracyTracker()
        self._calibration_curve: list[tuple[float, float]] = []
        self._precursors: list[FailurePrecursor] = []
        self._initialized = False
        self._lock = threading.Lock()

    def initialize(self, limit: int = 1000) -> None:
        """Build the accuracy model from historical data."""
        # Load episodes
        try:
            episodes = self._db.list_episodes(limit=limit)
            self._tracker.build_from_episodes(episodes)
        except Exception:
            episodes = []

        # Augment from theories
        try:
            theories = self._db.list_theories(limit=500)
            self._tracker.build_from_theories(theories)
        except Exception:
            theories = []

        # Detect failure precursors
        self._precursors = detect_failure_precursors(episodes)

        # Build calibration curve from theory confidence vs actual accuracy
        self._calibration_curve = self._build_calibration_curve(theories)

        self._initialized = True

    def calibrate(
        self,
        context_domains: list[str] | None = None,
        session_corrections: int = 0,
        session_assertions: int = 0,
        session_duration_minutes: float = 0.0,
        claimed_confidence: float | None = None,
    ) -> CalibrationReport:
        """Generate a calibration report for the current context.

        This is the main entry point — called before the LLM commits to an answer.
        """
        if not self._initialized:
            self.initialize()

        # Snapshot tracker state under lock to avoid races with record_outcome
        with self._lock:
            all_domains_snapshot = dict(self._tracker.all_domains)

        # No data at all → neutral report (no evidence of errors)
        if not all_domains_snapshot:
            return CalibrationReport(
                mean_accuracy=1.0,
                hazard=compute_hazard_rate(
                    session_corrections, session_assertions, session_duration_minutes
                ),
                doubt_level="none",
                should_verify=False,
            )

        context_domains = context_domains or []

        # Gather domain accuracies for current context (read-only, no side effects)
        relevant_accuracies: dict[str, DomainAccuracy] = {}
        for domain in context_domains:
            da = all_domains_snapshot.get(domain)
            if da and da.total_assertions > 0:
                relevant_accuracies[domain] = da

        # If no specific domains, use overall model
        if not relevant_accuracies:
            relevant_accuracies = {
                d: da for d, da in all_domains_snapshot.items()
                if da.total_assertions >= 3
            }

        # Compute mean accuracy for this context
        if relevant_accuracies:
            context_accuracy = sum(
                da.accuracy for da in relevant_accuracies.values()
            ) / len(relevant_accuracies)
        else:
            context_accuracy = self._tracker.mean_accuracy

        # Compute hazard rate
        hazard = compute_hazard_rate(
            session_corrections=session_corrections,
            session_assertions=session_assertions,
            session_duration_minutes=session_duration_minutes,
        )

        # Check for active precursors matching current domains
        active_precursors: list[FailurePrecursor] = []
        if context_domains:
            domain_set = set(context_domains)
            for precursor in self._precursors:
                if set(precursor.pattern_domains) & domain_set:
                    active_precursors.append(precursor)
                    hazard.active_precursors.append(precursor)

        # Generate metacognitive triggers
        triggers = self._generate_triggers(
            context_accuracy, hazard, active_precursors, relevant_accuracies
        )

        # Determine doubt level
        doubt_level = self._assess_doubt(context_accuracy, hazard, active_precursors)

        # Should verify?
        should_verify = doubt_level in ("moderate", "severe")

        # Calibrate claimed confidence if provided
        if claimed_confidence is not None and self._calibration_curve:
            calibrated = calibrate_confidence(claimed_confidence, self._calibration_curve)
            if calibrated < claimed_confidence - 0.15:
                triggers.append(
                    f"Calibration warning: your claimed {claimed_confidence:.0%} confidence "
                    f"maps to {calibrated:.0%} actual accuracy in similar contexts."
                )

        # Find worst domain
        worst_domain, worst_acc = self._tracker.worst_domain

        return CalibrationReport(
            domain_accuracies=relevant_accuracies,
            hazard=hazard,
            metacognitive_triggers=triggers,
            mean_accuracy=context_accuracy,
            worst_domain=worst_domain,
            worst_accuracy=worst_acc,
            should_verify=should_verify,
            doubt_level=doubt_level,
        )

    def record_outcome(self, domains: list[str], was_correct: bool) -> None:
        """Record a new assertion outcome (for live session tracking).

        This updates the in-memory model immediately for intra-session accuracy.
        Persistence across restarts is handled by initialize() which rebuilds
        from stored episodes — corrections recorded via handle_correct are
        persisted as episodes and automatically picked up on next startup.
        """
        with self._lock:
            self._tracker.record_assertion(domains, was_correct)

    def get_domain_report(self) -> dict[str, Any]:
        """Get full domain accuracy breakdown."""
        return {
            domain: {
                "accuracy": round(da.accuracy, 3),
                "recent_accuracy": round(da.recent_accuracy, 3),
                "brier_score": round(da.brier_score, 4),
                "confidence_band": da.confidence_band,
                "total": da.total_assertions,
                "corrections": da.corrections,
            }
            for domain, da in sorted(
                self._tracker.all_domains.items(),
                key=lambda x: x[1].accuracy,
            )
            if da.total_assertions >= 3
        }

    def _build_calibration_curve(
        self, theories: list[Theory]
    ) -> list[tuple[float, float]]:
        """Build isotonic calibration from theory confidence vs actual accuracy.

        Theory confidence is system-computed (not LLM self-reported), so this
        measures how well the system's confidence score predicts actual survival.
        The curve maps system-confidence → actual confirmation rate, which is
        useful for calibrating trust in theory retrieval results.

        Only theories with sufficient observations (≥3) and a meaningful
        spread of confidence levels contribute to the curve.
        """
        if not theories:
            return []

        points: list[tuple[float, float]] = []
        for theory in theories:
            total = theory.confirmation_count + theory.contradiction_count
            if total < 3:
                continue
            actual_accuracy = theory.confirmation_count / total
            claimed = theory.confidence
            points.append((claimed, actual_accuracy))

        if len(points) < 5:
            return []

        # Check spread: if all confidence values are within 0.1, the curve
        # is degenerate and won't provide useful calibration
        confidences = [p[0] for p in points]
        if max(confidences) - min(confidences) < 0.1:
            return []

        return isotonic_regression(points)

    def _generate_triggers(
        self,
        context_accuracy: float,
        hazard: HazardSnapshot,
        active_precursors: list[FailurePrecursor],
        domain_accuracies: dict[str, DomainAccuracy],
    ) -> list[str]:
        """Generate metacognitive trigger messages."""
        triggers: list[str] = []

        # Trigger 1: Low accuracy domain
        for domain, da in domain_accuracies.items():
            if da.accuracy < 0.6 and da.total_assertions >= 5:
                triggers.append(
                    f"You have been wrong {da.corrections}/{da.total_assertions} times "
                    f"in '{domain}'. Query neurosync before committing."
                )
                break  # Only one domain warning

        # Trigger 2: Active failure precursor
        for precursor in active_precursors[:1]:
            if precursor.risk_multiplier > 2.0:
                triggers.append(
                    f"Failure pattern detected: {precursor.pattern_description}. "
                    f"Risk is {precursor.risk_multiplier:.1f}x baseline."
                )

        # Trigger 3: Session fatigue
        if hazard.fatigue_factor > 1.5:
            triggers.append(
                "Session fatigue: error probability elevated. "
                "Consider verifying complex decisions."
            )

        # Trigger 4: High hazard rate
        if hazard.hazard_rate > 0.3 and hazard.session_assertions_so_far >= 3:
            triggers.append(
                f"Session correction rate: {hazard.hazard_rate:.0%}. "
                f"Recommend querying memory before assertions."
            )

        # Trigger 5: Declining recent accuracy
        declining_domains = [
            domain for domain, da in domain_accuracies.items()
            if da.recent_accuracy < da.accuracy - 0.2 and len(da.last_5_outcomes) >= 3
        ]
        if declining_domains:
            triggers.append(
                f"Recent accuracy declining in: {', '.join(declining_domains[:2])}. "
                "Your performance in this area is getting worse, not better."
            )

        return triggers[:3]  # Max 3 triggers

    def _assess_doubt(
        self,
        context_accuracy: float,
        hazard: HazardSnapshot,
        active_precursors: list[FailurePrecursor],
    ) -> str:
        """Assess overall doubt level for current context.

        Each component is bounded before summing to prevent any single signal
        from saturating the classification. Total range: 0–5.
        """
        risk = 0.0

        # Low accuracy = high doubt. Range: [0, 2]
        # Strongest signal: 50% accuracy → 1.0, 0% accuracy → 2.0
        risk += min((1.0 - context_accuracy) * 2.0, 2.0)

        # Active precursors. Range: [0, 1]
        if active_precursors:
            max_risk_mult = max(p.risk_multiplier for p in active_precursors)
            risk += min(max_risk_mult / 5.0, 1.0)

        # Hazard rate, clamped to [0, 1]
        risk += min(hazard.hazard_rate, 1.0)

        # Fatigue, clamped to [0, 1]
        if hazard.fatigue_factor > 1.3:
            risk += min((hazard.fatigue_factor - 1.0) * 0.5, 1.0)

        # Classify: accuracy=50% alone gives risk=1.0, should be at least moderate
        if risk >= 2.5:
            return "severe"
        if risk >= 1.2:
            return "moderate"
        if risk >= 0.6:
            return "mild"
        return "none"
