"""Base class for intelligence analyzers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from neurosync.db import Database
from neurosync.intelligence.models import Insight
from neurosync.vectorstore import VectorStore


class BaseAnalyzer(ABC):
    """Contract for all intelligence analyzers."""

    interval_seconds: int = 3600
    max_runtime_ms: int = 5000

    @abstractmethod
    def analyze(self, db: Database, vs: Optional[VectorStore]) -> list[Insight]:
        """Run analysis pass. Returns new/updated insights."""
        ...

    @abstractmethod
    def name(self) -> str:
        """Unique analyzer name for scheduling."""
        ...
