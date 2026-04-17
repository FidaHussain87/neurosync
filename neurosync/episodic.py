"""Layer 1: Episodic memory — session management and episode CRUD."""

from __future__ import annotations

from typing import Any, Optional

from neurosync.db import Database
from neurosync.models import Episode, Session, Signal, _utcnow
from neurosync.vectorstore import VectorStore


class EpisodicMemory:
    """Manages sessions and episodes (Layer 1)."""

    def __init__(self, db: Database, vectorstore: VectorStore) -> None:
        self._db = db
        self._vs = vectorstore

    # --- Sessions ---

    def start_session(self, project: str = "", branch: str = "") -> Session:
        session = Session(project=project, branch=branch)
        return self._db.save_session(session)

    def end_session(
        self, session_id: str, summary: str = "", duration_seconds: int = 0
    ) -> Optional[Session]:
        session = self._db.get_session(session_id)
        if not session:
            return None
        session.ended_at = _utcnow()
        session.summary = summary
        session.duration_seconds = duration_seconds
        return self._db.save_session(session)

    def get_session(self, session_id: str) -> Optional[Session]:
        return self._db.get_session(session_id)

    def list_sessions(self, project: Optional[str] = None, limit: int = 20) -> list[Session]:
        return self._db.list_sessions(project=project, limit=limit)

    # --- Episodes ---

    def record_episode(
        self,
        session_id: str,
        event_type: str,
        content: str,
        context: str = "",
        files_touched: Optional[list[str]] = None,
        layers_touched: Optional[list[str]] = None,
        signal_weight: float = 1.0,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Episode:
        """Record a new episode within a session."""
        episode = Episode(
            session_id=session_id,
            event_type=event_type,
            content=content,
            context=context,
            files_touched=files_touched or [],
            layers_touched=layers_touched or [],
            signal_weight=signal_weight,
            metadata=metadata or {},
        )
        self._db.save_episode(episode)
        session = self._db.get_session(session_id)
        project = session.project if session else ""
        self._vs.add_episode(episode, project=project)
        return episode

    def record_explicit(
        self,
        session_id: str,
        content: str,
        event_type: str = "explicit",
    ) -> Episode:
        """Record an explicit 'remember this' episode with high signal weight."""
        episode = self.record_episode(
            session_id=session_id,
            event_type=event_type,
            content=content,
            signal_weight=10.0,
        )
        signal = Signal(
            episode_id=episode.id,
            signal_type="EXPLICIT",
            raw_value=1.0,
            multiplier=10.0,
        )
        self._db.save_signal(signal)
        return episode

    def record_correction(
        self,
        session_id: str,
        wrong: str,
        right: str,
        correction_count: int = 1,
    ) -> Episode:
        """Record a correction episode with exponential weight."""
        weight = min(2**correction_count, 1000.0)
        content = f"CORRECTION: Was told '{wrong}' but correct answer is '{right}'"
        episode = self.record_episode(
            session_id=session_id,
            event_type="correction",
            content=content,
            signal_weight=weight,
        )
        signal = Signal(
            episode_id=episode.id,
            signal_type="CORRECTION",
            raw_value=float(correction_count),
            multiplier=weight,
        )
        self._db.save_signal(signal)
        return episode

    def get_episode(self, episode_id: str) -> Optional[Episode]:
        return self._db.get_episode(episode_id)

    def list_episodes(
        self,
        session_id: Optional[str] = None,
        consolidated: Optional[int] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[Episode]:
        return self._db.list_episodes(
            session_id=session_id,
            consolidated=consolidated,
            event_type=event_type,
            limit=limit,
        )

    def get_unconsolidated_episodes(self, limit: int = 500) -> list[Episode]:
        return self._db.list_episodes(consolidated=0, limit=limit)

    def mark_consolidated(self, episode_ids: list[str]) -> None:
        if episode_ids:
            self._db.mark_episodes_consolidated(episode_ids, _utcnow())

    def decay_episodes(self, episode_ids: list[str]) -> None:
        """Remove old consolidated episodes from vector store, keep in SQLite."""
        if episode_ids:
            self._db.mark_episodes_decayed(episode_ids)
            self._vs.remove_episodes(episode_ids)

    def search(
        self, query: str, n_results: int = 10, project: Optional[str] = None
    ) -> list[dict[str, Any]]:
        where = {"project": project} if project else None
        return self._vs.search_episodes(query, n_results=n_results, where=where)
