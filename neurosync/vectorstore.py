"""ChromaDB wrapper: episode + theory collections with semantic search."""

from __future__ import annotations

import os
import shutil
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from neurosync.db import Database

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
        self._recovered = False
        config.ensure_dirs()
        try:
            self._init_client(config)
        except Exception as first_err:
            logger.warning("ChromaDB init failed: %s — attempting recovery", first_err)
            self._attempt_recovery(config)
            self._init_client(config)
            self._recovered = True
            logger.info("ChromaDB recovered successfully after re-creation")

    def _init_client(self, config: NeuroSyncConfig) -> None:
        """Initialize the ChromaDB client and collections."""
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
        self._client = client
        self._episodes = episodes
        self._theories = theories
        self._failures = failures

    def _attempt_recovery(self, config: NeuroSyncConfig) -> None:
        """Move corrupted ChromaDB directory aside and let re-init create a fresh one."""
        corrupted_path = config.chroma_path + ".corrupted"
        if os.path.exists(config.chroma_path):
            if os.path.exists(corrupted_path):
                shutil.rmtree(corrupted_path, ignore_errors=True)
            os.rename(config.chroma_path, corrupted_path)
        os.makedirs(config.chroma_path, exist_ok=True)

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
        if episode.structural_fingerprint:
            metadata["structural_fingerprint"] = episode.structural_fingerprint
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
        metadata: dict[str, Any] = {
            "scope": theory.scope,
            "scope_qualifier": theory.scope_qualifier,
            "confidence": theory.confidence,
            "active": 1 if theory.active else 0,
            "validation_status": theory.validation_status,
            "application_count": theory.application_count,
        }
        if theory.structural_fingerprint:
            metadata["structural_fingerprint"] = theory.structural_fingerprint
        self._theories.upsert(
            ids=[theory.id],
            documents=[self._safe_document(theory.content)],
            metadatas=[metadata],
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
            metadatas=[
                {
                    "category": record.category,
                    "project": record.project,
                    "severity": record.severity,
                    "what_worked": record.what_worked,
                }
            ],
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
            items.append(
                {
                    "id": doc_id,
                    "document": documents[i] if i < len(documents) else "",
                    "distance": distances[i] if i < len(distances) else 0.0,
                    "metadata": metadatas[i] if i < len(metadatas) else {},
                }
            )
        return items

    def reindex_from_db(self, db: Database, project: str = "") -> dict[str, int]:
        """Re-populate ChromaDB from the SQLite source of truth.

        Reads all non-decayed episodes (consolidated=0 or 1), all active
        theories, and all failure records from the database and upserts them
        into ChromaDB collections in batches.

        Args:
            db: A Database instance (from neurosync.db).
            project: Optional project name for episode metadata.

        Returns:
            A summary dict with counts of indexed items.
        """
        summary = {"episodes": 0, "theories": 0, "failures": 0}
        batch_size = 200

        # --- Episodes (consolidated=0 and consolidated=1, skip decayed=2) ---
        for consolidated_val in (0, 1):
            all_episodes = db.list_episodes(consolidated=consolidated_val, limit=100000)
            ids: list[str] = []
            documents: list[str] = []
            metadatas: list[dict[str, Any]] = []
            for ep in all_episodes:
                if not ep.content.strip():
                    continue
                metadata: dict[str, Any] = {
                    "session_id": ep.session_id,
                    "event_type": ep.event_type,
                    "project": project,
                    "signal_weight": ep.signal_weight,
                    "timestamp": ep.timestamp,
                }
                if ep.cause:
                    metadata["has_causal"] = 1
                if ep.quality_score is not None:
                    metadata["quality_score"] = ep.quality_score
                if ep.structural_fingerprint:
                    metadata["structural_fingerprint"] = ep.structural_fingerprint
                ids.append(ep.id)
                documents.append(self._safe_document(ep.content))
                metadatas.append(metadata)
            # Batch upsert
            for i in range(0, len(ids), batch_size):
                self._episodes.upsert(
                    ids=ids[i : i + batch_size],
                    documents=documents[i : i + batch_size],
                    metadatas=metadatas[i : i + batch_size],
                )
            summary["episodes"] += len(ids)

        # --- Theories (active only) ---
        all_theories = db.list_theories(active_only=True, limit=100000)
        ids = []
        documents = []
        metadatas = []
        for theory in all_theories:
            if not theory.content.strip():
                continue
            meta: dict[str, Any] = {
                "scope": theory.scope,
                "scope_qualifier": theory.scope_qualifier,
                "confidence": theory.confidence,
                "active": 1 if theory.active else 0,
                "validation_status": theory.validation_status,
                "application_count": theory.application_count,
            }
            if theory.structural_fingerprint:
                meta["structural_fingerprint"] = theory.structural_fingerprint
            ids.append(theory.id)
            documents.append(self._safe_document(theory.content))
            metadatas.append(meta)
        for i in range(0, len(ids), batch_size):
            self._theories.upsert(
                ids=ids[i : i + batch_size],
                documents=documents[i : i + batch_size],
                metadatas=metadatas[i : i + batch_size],
            )
        summary["theories"] = len(ids)

        # --- Failure records ---
        all_failures = db.list_failure_records(min_severity=1, limit=100000)
        ids = []
        documents = []
        metadatas = []
        for record in all_failures:
            content = f"{record.what_failed} {record.why_failed}".strip()
            if not content:
                continue
            record_id = str(record.id) if record.id is not None else ""
            if not record_id:
                continue
            ids.append(record_id)
            documents.append(self._safe_document(content))
            metadatas.append(
                {
                    "category": record.category,
                    "project": record.project,
                    "severity": record.severity,
                    "what_worked": record.what_worked,
                }
            )
        for i in range(0, len(ids), batch_size):
            self._failures.upsert(
                ids=ids[i : i + batch_size],
                documents=documents[i : i + batch_size],
                metadatas=metadatas[i : i + batch_size],
            )
        summary["failures"] = len(ids)

        logger.info(
            "Reindex complete: %d episodes, %d theories, %d failures",
            summary["episodes"],
            summary["theories"],
            summary["failures"],
        )
        return summary

    def stats(self) -> dict[str, int]:
        return {
            "episodes": self._episodes.count(),
            "theories": self._theories.count(),
            "failures": self._failures.count(),
        }

    def integrity_check(self, db_episode_count: int = 0, db_theory_count: int = 0) -> dict[str, Any]:
        """Compare ChromaDB counts against source-of-truth DB counts to detect drift."""
        chroma_episodes = self._episodes.count()
        chroma_theories = self._theories.count()
        episode_drift = abs(db_episode_count - chroma_episodes)
        theory_drift = abs(db_theory_count - chroma_theories)
        healthy = episode_drift == 0 and theory_drift == 0
        return {
            "healthy": healthy,
            "chroma_episodes": chroma_episodes,
            "chroma_theories": chroma_theories,
            "db_episodes": db_episode_count,
            "db_theories": db_theory_count,
            "episode_drift": episode_drift,
            "theory_drift": theory_drift,
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
