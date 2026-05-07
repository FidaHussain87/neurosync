"""Predictive Pre-emption — infers developer trajectory and pre-selects relevant lenses."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from neurosync.intelligence.domains import classify_episode


@dataclass
class Trajectory:
    """Predicted developer trajectory."""

    predicted_files: list[str] = field(default_factory=list)
    predicted_domains: list[str] = field(default_factory=list)
    mistake_probability: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0


# Branch name patterns
_BRANCH_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(fix|bugfix|hotfix)/", re.I), "debugging"),
    (re.compile(r"^(feature|feat)/", re.I), "feature"),
    (re.compile(r"^refactor/", re.I), "refactor"),
    (re.compile(r"^chore/", re.I), "chore"),
    (re.compile(r"^docs?/", re.I), "docs"),
    (re.compile(r"^test/", re.I), "testing"),
]


def parse_branch_intent(branch: str) -> dict[str, str]:
    """Extract likely work type from branch name.

    Examples:
      'fix/auth-timeout' -> {'type': 'debugging', 'area': 'auth', 'keyword': 'timeout'}
      'feature/payment-integration' -> {'type': 'feature', 'area': 'payment'}
      'refactor/db-layer' -> {'type': 'refactor', 'area': 'db'}
    """
    if not branch:
        return {}

    result: dict[str, str] = {}
    work_type = ""

    for pattern, wtype in _BRANCH_PATTERNS:
        if pattern.search(branch):
            work_type = wtype
            break

    if not work_type:
        return {}

    result["type"] = work_type

    # Extract area and keyword from remaining path segments
    parts = re.split(r"[/\-_]", branch)
    # Skip the prefix (fix, feature, etc.)
    meaningful = [p for p in parts[1:] if p and len(p) > 1]

    if meaningful:
        result["area"] = meaningful[0]
    if len(meaningful) > 1:
        result["keyword"] = meaningful[1]

    return result


def predict_files(
    current_files: list[str],
    db: Any,
    limit: int = 5,
) -> list[tuple[str, float]]:
    """Given files currently being touched, predict which other files
    will likely be touched next based on historical co-occurrence.

    Returns: [(file_path, probability), ...]
    """
    if not current_files:
        return []

    # Query recent episodes that contain any of the current files
    episodes = db.list_episodes(limit=500)

    # Count occurrences of each file and co-occurrences with current files
    file_occurrences: Counter[str] = Counter()
    cooccurrence: Counter[str] = Counter()
    current_set = set(current_files)

    for ep in episodes:
        files = ep.files_touched
        if isinstance(files, str):
            try:
                files = json.loads(files)
            except (json.JSONDecodeError, TypeError):
                continue
        if not files:
            continue

        file_set = set(files)
        has_overlap = bool(file_set & current_set)

        for f in file_set:
            file_occurrences[f] += 1
            if has_overlap and f not in current_set:
                cooccurrence[f] += 1

    if not cooccurrence:
        return []

    # Compute conditional probability: P(file_B | file_A) = count(A∩B) / count(A)
    # count(A) = number of episodes containing any current file
    episodes_with_current = sum(
        1
        for ep in episodes
        if _episode_has_files(ep, current_set)
    )
    if episodes_with_current == 0:
        return []

    predictions: list[tuple[str, float]] = []
    for f, count in cooccurrence.items():
        prob = count / episodes_with_current
        predictions.append((f, min(prob, 1.0)))

    predictions.sort(key=lambda x: -x[1])
    return predictions[:limit]


def _episode_has_files(ep: Any, file_set: set[str]) -> bool:
    """Check if an episode touches any file in the given set."""
    files = ep.files_touched
    if isinstance(files, str):
        try:
            files = json.loads(files)
        except (json.JSONDecodeError, TypeError):
            return False
    if not files:
        return False
    return bool(set(files) & file_set)


def predict_mistakes(
    predicted_files: list[str],
    predicted_domains: list[str],
    db: Any,
    project: str = "",
) -> list[tuple[str, float, str]]:
    """Predict which mistakes are likely given trajectory.

    Returns: [(mistake_description, probability, lens_advice), ...]
    """
    if not predicted_files and not predicted_domains:
        return []

    failure_records = db.list_failure_records(project=project or None, limit=100)
    if not failure_records:
        return []

    results: list[tuple[str, float, str]] = []
    seen_descriptions: set[str] = set()

    for record in failure_records:
        # Check file overlap
        file_match = False
        if predicted_files and record.context:
            for f in predicted_files:
                if f in record.context or f in record.what_failed:
                    file_match = True
                    break

        # Check domain overlap
        domain_match = False
        if predicted_domains and record.category:
            for domain in predicted_domains:
                if domain in record.category or record.category in domain:
                    domain_match = True
                    break

        if not file_match and not domain_match:
            continue

        # Score: P(mistake) = occurrence_count / (occurrence_count + 5)
        prob = record.occurrence_count / (record.occurrence_count + 5)
        if prob <= 0.3:
            continue

        description = record.what_failed
        if description in seen_descriptions:
            continue
        seen_descriptions.add(description)

        advice = record.what_worked if record.what_worked else "Review prior approach"
        results.append((description, prob, advice))

    results.sort(key=lambda x: -x[1])
    return results[:10]


def score_relevance(
    item_domains: list[str],
    item_files: list[str],
    trajectory: Trajectory,
) -> float:
    """Score how relevant an item is to predicted trajectory.
    0.0 = irrelevant, 1.0 = perfectly relevant.
    """
    if not trajectory.predicted_domains and not trajectory.predicted_files:
        return 0.0

    score = 0.0

    # Domain overlap
    if item_domains and trajectory.predicted_domains:
        traj_domains = set(trajectory.predicted_domains)
        overlap = len(set(item_domains) & traj_domains)
        score += (overlap / max(len(item_domains), 1)) * 2.0

    # File overlap
    if item_files and trajectory.predicted_files:
        traj_files = set(trajectory.predicted_files)
        overlap = len(set(item_files) & traj_files)
        score += (overlap / max(len(item_files), 1)) * 1.5

    # Normalize to [0, 1]
    max_possible = 2.0 + 1.5
    return min(score / max_possible, 1.0)


class PreemptionEngine:
    """Predicts developer trajectory and pre-selects relevant lenses."""

    def __init__(self, db: Any) -> None:
        self._db = db

    def infer_trajectory(
        self,
        project: str = "",
        branch: str = "",
        current_files: list[str] | None = None,
        context: str = "",
    ) -> Trajectory:
        """Infer what the developer is about to do."""
        current_files = current_files or []

        # Predict files from co-occurrence
        predicted_files_scored = predict_files(current_files, self._db)
        predicted_files = [f for f, _ in predicted_files_scored]

        # Infer domains from branch name, current files, and context
        branch_intent = parse_branch_intent(branch)
        predicted_domains = self._infer_domains(
            current_files, predicted_files, branch_intent, context
        )

        # Predict mistakes
        mistakes = predict_mistakes(
            predicted_files or current_files,
            predicted_domains,
            self._db,
            project=project,
        )
        mistake_probability = {desc: prob for desc, prob, _ in mistakes}

        # Compute overall confidence
        confidence = self._compute_confidence(
            current_files, predicted_files_scored, branch_intent
        )

        return Trajectory(
            predicted_files=predicted_files,
            predicted_domains=predicted_domains,
            mistake_probability=mistake_probability,
            confidence=confidence,
        )

    def get_preemptive_context(
        self,
        trajectory: Trajectory,
        project: str = "",
    ) -> dict[str, Any]:
        """Get pre-emptive information to inject before mistakes happen.

        Returns dict with:
          - predicted_files: files likely to be touched
          - warnings: pre-emptive warnings based on trajectory
          - relevant_domains: domains to focus lens selection on
        """
        warnings: list[dict[str, Any]] = []

        # Generate warnings from mistake predictions
        mistakes = predict_mistakes(
            trajectory.predicted_files,
            trajectory.predicted_domains,
            self._db,
            project=project,
        )
        for description, probability, advice in mistakes:
            warnings.append({
                "description": description,
                "probability": probability,
                "advice": advice,
            })

        return {
            "predicted_files": trajectory.predicted_files,
            "warnings": warnings,
            "relevant_domains": trajectory.predicted_domains,
            "confidence": trajectory.confidence,
        }

    def _infer_domains(
        self,
        current_files: list[str],
        predicted_files: list[str],
        branch_intent: dict[str, str],
        context: str,
    ) -> list[str]:
        """Infer domains from all available signals."""
        all_files = current_files + predicted_files

        # Use domain classifier on context + file paths
        domains = classify_episode(
            content=context,
            files_touched=all_files,
            event_type=branch_intent.get("type", ""),
        )

        # Boost domains from branch intent area
        area = branch_intent.get("area", "")
        if area and not domains:
            area_domains = classify_episode(
                content=area,
                files_touched=[],
            )
            domains.extend(area_domains)

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for d in domains:
            if d not in seen:
                seen.add(d)
                unique.append(d)

        return unique[:5]

    def _compute_confidence(
        self,
        current_files: list[str],
        predicted_files_scored: list[tuple[str, float]],
        branch_intent: dict[str, str],
    ) -> float:
        """Compute confidence in the trajectory prediction."""
        if not current_files and not branch_intent:
            return 0.0

        score = 0.0

        # More current files = more signal
        if current_files:
            score += min(len(current_files) / 5.0, 0.3)

        # Higher prediction probabilities = more confidence
        if predicted_files_scored:
            avg_prob = sum(p for _, p in predicted_files_scored) / len(
                predicted_files_scored
            )
            score += avg_prob * 0.4

        # Branch intent gives strong signal
        if branch_intent:
            score += 0.3

        return min(score, 1.0)
