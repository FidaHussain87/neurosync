"""Greedy knapsack token-budget packer for memory items."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neurosync.selflearn.reranker import RankedItem


@dataclass
class PackedResult:
    items: list[RankedItem]
    total_tokens: int
    budget: int
    utilization: float  # total_tokens / budget


class BudgetPacker:
    """Greedy knapsack that maximises value_density within a token budget.

    Algorithm (O(n log n)):
    1. Sort candidates by value_density descending.
    2. Greedily take items until budget exhausted.
    3. Always include must_include items regardless of budget (safety net).

    This is near-optimal for this use case because:
    - Items are roughly similar size (theories / distilled knowledge).
    - The greedy fraction approximation is within (1-1/e) of optimal.
    """

    DEFAULT_BUDGET = 500   # tokens
    MIN_ITEM_TOKENS = 5    # ignore items with < 5 tokens

    def pack(
        self,
        candidates: list[RankedItem],
        budget: int | None = None,
        must_include: list[str] | None = None,
    ) -> PackedResult:
        """Select items from candidates that fit within the token budget.

        Args:
            candidates: Ranked items from Reranker (best first).
            budget: Token limit for the normal greedy pass. Defaults to DEFAULT_BUDGET.
            must_include: entity_ids that are always included even if they exceed budget.
                          Callers must ensure must_include is small (e.g., ≤ 3 items) to
                          avoid silently blowing the budget. Total tokens may exceed budget
                          when must_include items are large.

        Returns:
            PackedResult with selected items and metadata.
        """
        token_budget = budget if budget is not None else self.DEFAULT_BUDGET
        force_ids: set[str] = set(must_include or [])

        # Sort by value_density descending (greedy knapsack criterion)
        sorted_candidates = sorted(
            candidates, key=lambda x: x.value_density, reverse=True
        )

        selected: list[RankedItem] = []
        tokens_used = 0

        # First pass: must_include items (bypass budget check)
        for item in sorted_candidates:
            if item.entity_id in force_ids and item.tokens >= self.MIN_ITEM_TOKENS:
                selected.append(item)
                tokens_used += item.tokens

        included_ids = {i.entity_id for i in selected}

        # Second pass: fill remaining budget greedily
        for item in sorted_candidates:
            if item.entity_id in included_ids:
                continue
            if item.tokens < self.MIN_ITEM_TOKENS:
                continue
            if tokens_used + item.tokens <= token_budget:
                selected.append(item)
                tokens_used += item.tokens
                included_ids.add(item.entity_id)

        utilization = tokens_used / max(1, token_budget)
        return PackedResult(
            items=selected,
            total_tokens=tokens_used,
            budget=token_budget,
            utilization=utilization,
        )

    def pack_raw(
        self,
        items: list[dict],
        budget: int | None = None,
        value_key: str = "combined_score",
        token_key: str = "tokens",
        id_key: str = "id",
    ) -> list[dict]:
        """Simpler version for dict-based items without RankedItem wrapper.

        Sorts by value/token density and greedily fills budget.
        Returns selected items list.
        """
        token_budget = budget if budget is not None else self.DEFAULT_BUDGET
        if not items:
            return []

        def density(item: dict) -> float:
            t = max(1, int(item.get(token_key, 100)))
            v = float(item.get(value_key, 0.5))
            return v / t

        sorted_items = sorted(items, key=density, reverse=True)
        selected: list[dict] = []
        tokens_used = 0

        for item in sorted_items:
            t = int(item.get(token_key, 100))
            if t < self.MIN_ITEM_TOKENS:
                continue
            if tokens_used + t <= token_budget:
                selected.append(item)
                tokens_used += t

        return selected
