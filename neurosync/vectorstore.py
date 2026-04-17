"""ChromaDB wrapper: episode + theory collections with semantic search."""

from __future__ import annotations

from typing import Any, Optional

import chromadb
from chromadb.config import Settings

from neurosync.config import NeuroSyncConfig
from neurosync.logging import get_logger
from neurosync.models import Episode, FailureRecord, Theory

logger = get_logger("vectorstore")

EPISODE_COLLECTION = "neurosync_episodes"
THEORY_COLLECTION = "neurosync_theories"
FAILURE_COLLECTION = "neurosync_failures"

MAX_EMBED_CHARS = 8000


class VectorStore:
    """Manages ChromaDB collections for episodes and theories."""

    def __init__(self, config: NeuroSyncConfig) -> None:
        self._config = config
        config.ensure_dirs()
        client = chromadb.PersistentClient(
            path=config.chroma_path,
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
        episodes = client.get_or_create_collection(
            name=EPISODE_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        theories = client.get_or_create_collection(
            name=THEORY_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        failures = client.get_or_create_collection(
            name=FAILURE_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        # Atomic commit — all collections created before assigning
        self._client = client
        self._episodes = episodes
        self._theories = theories
        self._failures = failures

    @property
    def episodes_collection(self) -> chromadb.Collection:
        return self._episodes

    @property
    def theories_collection(self) -> chromadb.Collection:
        return self._theories

    # --- Helpers ---

    def _safe_document(self, text: str) -> str:
        """Truncate to embedding model's context window."""
        if len(text) > MAX_EMBED_CHARS:
            logger.debug("Truncating document from %d to %d chars", len(text), MAX_EMBED_CHARS)
            return text[:MAX_EMBED_CHARS]
        return text

    # --- Episode operations ---

    def add_episode(self, episode: Episode, project: str = "") -> None:
        """Embed and store an episode."""
        if not episode.content.strip():
            return
        metadata: dict[str, Any] = {
            "session_id": episode.session_id,
            "event_type": episode.event_type,
            "project": project,
            "signal_weight": episode.signal_weight,
            "timestamp": episode.timestamp,
        }
        if episode.cause:
            metadata["has_causal"] = 1
        if episode.quality_score is not None:
            metadata["quality_score"] = episode.quality_score
        self._episodes.upsert(
            ids=[episode.id],
            documents=[self._safe_document(episode.content)],
            metadatas=[metadata],
        )

    def remove_episodes(self, episode_ids: list[str]) -> None:
        """Remove episodes from ChromaDB (decay)."""
        if not episode_ids:
            return
        # ChromaDB may raise if IDs don't exist; filter to existing
        existing = self._episodes.get(ids=episode_ids)
        if existing and existing["ids"]:
            self._episodes.delete(ids=existing["ids"])

    def search_episodes(
        self,
        query: str,
        n_results: int = 10,
        where: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Semantic search across episodes."""
        try:
            if self._episodes.count() == 0:
                return []
            kwargs: dict[str, Any] = {
                "query_texts": [query],
                "n_results": min(n_results, self._episodes.count()),
            }
            if where:
                kwargs["where"] = where
            results = self._episodes.query(**kwargs)
            return self._unpack_results(results)
        except Exception:
            logger.warning("ChromaDB search_episodes failed, returning empty", exc_info=True)
            return []

    # --- Theory operations ---

    def add_theory(self, theory: Theory) -> None:
        """Embed and store a theory."""
        if not theory.content.strip():
            return
        self._theories.upsert(
            ids=[theory.id],
            documents=[self._safe_document(theory.content)],
            metadatas=[{
                "scope": theory.scope,
                "scope_qualifier": theory.scope_qualifier,
                "confidence": theory.confidence,
                "active": 1 if theory.active else 0,
                "validation_status": theory.validation_status,
                "application_count": theory.application_count,
            }],
        )

    def remove_theory(self, theory_id: str) -> None:
        """Remove a theory from ChromaDB."""
        existing = self._theories.get(ids=[theory_id])
        if existing and existing["ids"]:
            self._theories.delete(ids=[theory_id])

    def search_theories(
        self,
        query: str,
        n_results: int = 10,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Semantic search across theories."""
        try:
            if self._theories.count() == 0:
                return []
            kwargs: dict[str, Any] = {
                "query_texts": [query],
                "n_results": min(n_results, self._theories.count()),
            }
            if active_only:
                kwargs["where"] = {"active": 1}
            results = self._theories.query(**kwargs)
            return self._unpack_results(results)
        except Exception:
            logger.warning("ChromaDB search_theories failed, returning empty", exc_info=True)
            return []

    # --- Failure operations ---

    def add_failure(self, record: FailureRecord) -> None:
        """Embed and store a failure record."""
        content = f"{record.what_failed} {record.why_failed}".strip()
        if not content:
            return
        record_id = str(record.id) if record.id is not None else ""
        if not record_id:
            return
        self._failures.upsert(
            ids=[record_id],
            documents=[self._safe_document(content)],
            metadatas=[{
                "category": record.category,
                "project": record.project,
                "severity": record.severity,
                "what_worked": record.what_worked,
            }],
        )

    def search_failures(
        self,
        query: str,
        n_results: int = 10,
        where: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Semantic search across failure records."""
        try:
            if self._failures.count() == 0:
                return []
            kwargs: dict[str, Any] = {
                "query_texts": [query],
                "n_results": min(n_results, self._failures.count()),
            }
            if where:
                kwargs["where"] = where
            results = self._failures.query(**kwargs)
            return self._unpack_results(results)
        except Exception:
            logger.warning("ChromaDB search_failures failed, returning empty", exc_info=True)
            return []

    def remove_failure(self, record_id: int) -> None:
        """Remove a failure record from ChromaDB."""
        str_id = str(record_id)
        existing = self._failures.get(ids=[str_id])
        if existing and existing["ids"]:
            self._failures.delete(ids=[str_id])

    # --- Shared ---

    @staticmethod
    def _unpack_results(results: dict[str, Any]) -> list[dict[str, Any]]:
        """Unpack ChromaDB query results into a flat list."""
        items = []
        if not results or not results.get("ids"):
            return items
        ids = results["ids"][0]
        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        for i, doc_id in enumerate(ids):
            items.append({
                "id": doc_id,
                "document": documents[i] if i < len(documents) else "",
                "distance": distances[i] if i < len(distances) else 0.0,
                "metadata": metadatas[i] if i < len(metadatas) else {},
            })
        return items

    def stats(self) -> dict[str, int]:
        return {
            "episodes": self._episodes.count(),
            "theories": self._theories.count(),
            "failures": self._failures.count(),
        }

    def reset(self) -> None:
        """Delete all data from ChromaDB collections."""
        self._client.delete_collection(EPISODE_COLLECTION)
        self._client.delete_collection(THEORY_COLLECTION)
        self._client.delete_collection(FAILURE_COLLECTION)
        self._episodes = self._client.get_or_create_collection(
            name=EPISODE_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        self._theories = self._client.get_or_create_collection(
            name=THEORY_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        self._failures = self._client.get_or_create_collection(
            name=FAILURE_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
