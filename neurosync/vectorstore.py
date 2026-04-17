"""ChromaDB wrapper: episode + theory collections with semantic search."""

from __future__ import annotations

from typing import Any, Optional

import chromadb
from chromadb.config import Settings

from neurosync.config import NeuroSyncConfig
from neurosync.models import Episode, Theory

EPISODE_COLLECTION = "neurosync_episodes"
THEORY_COLLECTION = "neurosync_theories"


class VectorStore:
    """Manages ChromaDB collections for episodes and theories."""

    def __init__(self, config: NeuroSyncConfig) -> None:
        self._config = config
        config.ensure_dirs()
        self._client = chromadb.PersistentClient(
            path=config.chroma_path,
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
        self._episodes = self._client.get_or_create_collection(
            name=EPISODE_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        self._theories = self._client.get_or_create_collection(
            name=THEORY_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def episodes_collection(self) -> chromadb.Collection:
        return self._episodes

    @property
    def theories_collection(self) -> chromadb.Collection:
        return self._theories

    # --- Episode operations ---

    def add_episode(self, episode: Episode, project: str = "") -> None:
        """Embed and store an episode."""
        if not episode.content.strip():
            return
        self._episodes.upsert(
            ids=[episode.id],
            documents=[episode.content],
            metadatas=[{
                "session_id": episode.session_id,
                "event_type": episode.event_type,
                "project": project,
                "signal_weight": episode.signal_weight,
                "timestamp": episode.timestamp,
            }],
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

    # --- Theory operations ---

    def add_theory(self, theory: Theory) -> None:
        """Embed and store a theory."""
        if not theory.content.strip():
            return
        self._theories.upsert(
            ids=[theory.id],
            documents=[theory.content],
            metadatas=[{
                "scope": theory.scope,
                "scope_qualifier": theory.scope_qualifier,
                "confidence": theory.confidence,
                "active": 1 if theory.active else 0,
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
        }

    def reset(self) -> None:
        """Delete all data from ChromaDB collections."""
        self._client.delete_collection(EPISODE_COLLECTION)
        self._client.delete_collection(THEORY_COLLECTION)
        self._episodes = self._client.get_or_create_collection(
            name=EPISODE_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        self._theories = self._client.get_or_create_collection(
            name=THEORY_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
