"""Reranker: combines relevance score with usefulness score for memory selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neurosync.selflearn.usefulness import UsefulnessScorer


@dataclass
class RankedItem:
    entity_id: str
    entity_type: str
    relevance: float       # 0.0-1.0 from retrieval pipeline (semantic similarity etc.)
    usefulness_score: float  # 0.0-1.0 from Beta posterior mean
    thompson_sample: float   # Thompson draw for exploration-exploitation
    tokens: int
    content: str
    metadata: dict

    @property
    def combined_score(self) -> float:
        """Blend relevance and usefulness: relevance is primary, usefulness modulates."""
        return self.relevance * 0.6 + self.usefulness_score * 0.4

    @property
    def value_density(self) -> float:
        """combined_score per token — used by budget_packer greedy knapsack."""
        return self.combined_score / max(1, self.tokens)


class Reranker:
    """Reranks recall candidates using relevance × usefulness.

    Uses Thompson sampling for exploration: new memories (low recall_count) get
    a chance to prove themselves instead of being permanently suppressed.
    """

    # Minimum usefulness score before a memory is eligible for selection.
    # At Beta(1,1) = 0.5, so new memories always qualify.
    MIN_USEFULNESS = 0.15

    def __init__(self, scorer: UsefulnessScorer) -> None:
        self._scorer = scorer

    def rerank(
        self,
        candidates: list[dict],
        entity_type: str = "theory",
        use_thompson: bool = True,
    ) -> list[RankedItem]:
        """Rerank a list of recall candidates by combined relevance × usefulness.

        Each candidate dict must have:
          - 'id': str
          - 'relevance': float (from retrieval pipeline)
          - 'tokens': int (estimated token count)
          - 'content': str
          - 'metadata': dict (optional)

        Returns RankedItem list, best first.
        """
        if not candidates:
            return []

        entity_ids = [c["id"] for c in candidates]
        usefulness_map = self._scorer.get_bulk(entity_ids, entity_type)

        ranked: list[RankedItem] = []
        for c in candidates:
            eid = c["id"]
            rec = usefulness_map.get(eid)
            u_score = rec.score if rec else 0.5
            t_sample = rec.thompson_sample() if rec else 0.5

            # Filter out persistently low-usefulness memories
            # (but only after enough observations to be confident)
            recall_count = rec.recall_count if rec else 0
            if recall_count >= 5 and u_score < self.MIN_USEFULNESS:
                continue

            ranked.append(
                RankedItem(
                    entity_id=eid,
                    entity_type=entity_type,
                    relevance=float(c.get("relevance", 0.5)),
                    usefulness_score=u_score,
                    thompson_sample=t_sample,
                    tokens=int(c.get("tokens", 100)),
                    content=c.get("content", ""),
                    metadata=c.get("metadata", {}),
                )
            )

        # Pre-compute sort keys once — Thompson sample must NOT be called inside
        # the comparator because betavariate() returns a new value each call,
        # making the sort order non-deterministic and unstable.
        sort_keys: dict[str, float] = {}
        for item in ranked:
            rec = usefulness_map.get(item.entity_id)
            rc = rec.recall_count if rec else 0
            if use_thompson and rc < 5:
                sort_keys[item.entity_id] = item.relevance * 0.5 + item.thompson_sample * 0.5
            else:
                sort_keys[item.entity_id] = item.combined_score

        ranked.sort(key=lambda x: sort_keys[x.entity_id], reverse=True)
        return ranked
