"""SQLite database manager: schema init, migrations, thread-safe operations."""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Optional

from neurosync.config import NeuroSyncConfig
from neurosync.models import (
    Contradiction,
    Episode,
    Session,
    Signal,
    Theory,
    UserKnowledge,
)

CURRENT_SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project TEXT NOT NULL DEFAULT '',
    branch TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds INTEGER DEFAULT 0,
    summary TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'decision',
    content TEXT NOT NULL DEFAULT '',
    context TEXT DEFAULT '',
    files_touched TEXT DEFAULT '[]',
    layers_touched TEXT DEFAULT '[]',
    signal_weight REAL DEFAULT 1.0,
    consolidated INTEGER DEFAULT 0,
    consolidated_at TEXT,
    metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_episodes_session ON episodes(session_id);
CREATE INDEX IF NOT EXISTS idx_episodes_consolidated ON episodes(consolidated);
CREATE INDEX IF NOT EXISTS idx_episodes_type ON episodes(event_type);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL REFERENCES episodes(id),
    signal_type TEXT NOT NULL,
    raw_value REAL DEFAULT 0.0,
    multiplier REAL DEFAULT 1.0,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_episode ON signals(episode_id);

CREATE TABLE IF NOT EXISTS theories (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT 'craft',
    scope_qualifier TEXT DEFAULT '',
    confidence REAL DEFAULT 0.5,
    confirmation_count INTEGER DEFAULT 0,
    contradiction_count INTEGER DEFAULT 0,
    first_observed TEXT NOT NULL,
    last_confirmed TEXT,
    source_episodes TEXT DEFAULT '[]',
    superseded_by TEXT,
    active INTEGER DEFAULT 1,
    description_length INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_theories_active ON theories(active);
CREATE INDEX IF NOT EXISTS idx_theories_scope ON theories(scope);

CREATE TABLE IF NOT EXISTS contradictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    theory_id TEXT NOT NULL REFERENCES theories(id),
    episode_id TEXT NOT NULL REFERENCES episodes(id),
    description TEXT DEFAULT '',
    resolution TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_model (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    project TEXT DEFAULT '',
    familiarity REAL DEFAULT 0.5,
    last_seen TEXT NOT NULL,
    times_seen INTEGER DEFAULT 0,
    times_explained INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_user_model_topic ON user_model(topic);
"""


class Database:
    """Thread-safe SQLite database manager for NeuroSync."""

    def __init__(self, config: NeuroSyncConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._local = threading.local()
        config.ensure_dirs()
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._config.sqlite_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.executescript(_SCHEMA_SQL)
            cur = conn.execute("SELECT version FROM schema_version")
            row = cur.fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (CURRENT_SCHEMA_VERSION,),
                )
            conn.commit()

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    # --- JSON helpers ---

    @staticmethod
    def _to_json(val: Any) -> str:
        return json.dumps(val, default=str)

    @staticmethod
    def _from_json(val: str) -> Any:
        if not val:
            return {}
        return json.loads(val)

    # --- Sessions ---

    def save_session(self, session: Session) -> Session:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT OR REPLACE INTO sessions
                   (id, project, branch, started_at, ended_at, duration_seconds, summary, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session.id,
                    session.project,
                    session.branch,
                    session.started_at,
                    session.ended_at,
                    session.duration_seconds,
                    session.summary,
                    self._to_json(session.metadata),
                ),
            )
            conn.commit()
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return None
        return self._row_to_session(row)

    def list_sessions(
        self, project: Optional[str] = None, limit: int = 20
    ) -> list[Session]:
        conn = self._get_conn()
        if project:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE project = ? ORDER BY started_at DESC LIMIT ?",
                (project, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def _row_to_session(self, row: sqlite3.Row) -> Session:
        return Session(
            id=row["id"],
            project=row["project"],
            branch=row["branch"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            duration_seconds=row["duration_seconds"],
            summary=row["summary"],
            metadata=self._from_json(row["metadata"]),
        )

    # --- Episodes ---

    def save_episode(self, episode: Episode) -> Episode:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT OR REPLACE INTO episodes
                   (id, session_id, timestamp, event_type, content, context,
                    files_touched, layers_touched, signal_weight, consolidated,
                    consolidated_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    episode.id,
                    episode.session_id,
                    episode.timestamp,
                    episode.event_type,
                    episode.content,
                    episode.context,
                    self._to_json(episode.files_touched),
                    self._to_json(episode.layers_touched),
                    episode.signal_weight,
                    episode.consolidated,
                    episode.consolidated_at,
                    self._to_json(episode.metadata),
                ),
            )
            conn.commit()
        return episode

    def get_episode(self, episode_id: str) -> Optional[Episode]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if not row:
            return None
        return self._row_to_episode(row)

    def list_episodes(
        self,
        session_id: Optional[str] = None,
        consolidated: Optional[int] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[Episode]:
        conn = self._get_conn()
        clauses = []
        params: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if consolidated is not None:
            clauses.append("consolidated = ?")
            params.append(consolidated)
        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        where = " AND ".join(clauses) if clauses else "1=1"
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM episodes WHERE {where} ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row_to_episode(r) for r in rows]

    def count_episodes(self, consolidated: Optional[int] = None) -> int:
        conn = self._get_conn()
        if consolidated is not None:
            row = conn.execute(
                "SELECT COUNT(*) FROM episodes WHERE consolidated = ?", (consolidated,)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()
        return row[0] if row else 0

    def mark_episodes_consolidated(self, episode_ids: list[str], timestamp: str) -> None:
        with self._lock:
            conn = self._get_conn()
            placeholders = ",".join("?" for _ in episode_ids)
            conn.execute(
                f"UPDATE episodes SET consolidated = 1, consolidated_at = ? WHERE id IN ({placeholders})",
                [timestamp, *episode_ids],
            )
            conn.commit()

    def mark_episodes_decayed(self, episode_ids: list[str]) -> None:
        with self._lock:
            conn = self._get_conn()
            placeholders = ",".join("?" for _ in episode_ids)
            conn.execute(
                f"UPDATE episodes SET consolidated = 2 WHERE id IN ({placeholders})",
                episode_ids,
            )
            conn.commit()

    def _row_to_episode(self, row: sqlite3.Row) -> Episode:
        return Episode(
            id=row["id"],
            session_id=row["session_id"],
            timestamp=row["timestamp"],
            event_type=row["event_type"],
            content=row["content"],
            context=row["context"],
            files_touched=self._from_json(row["files_touched"]),
            layers_touched=self._from_json(row["layers_touched"]),
            signal_weight=row["signal_weight"],
            consolidated=row["consolidated"],
            consolidated_at=row["consolidated_at"],
            metadata=self._from_json(row["metadata"]),
        )

    # --- Signals ---

    def save_signal(self, signal: Signal) -> Signal:
        with self._lock:
            conn = self._get_conn()
            cur = conn.execute(
                """INSERT INTO signals (episode_id, signal_type, raw_value, multiplier, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    signal.episode_id,
                    signal.signal_type,
                    signal.raw_value,
                    signal.multiplier,
                    signal.timestamp,
                ),
            )
            signal.id = cur.lastrowid
            conn.commit()
        return signal

    def get_signals_for_episode(self, episode_id: str) -> list[Signal]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM signals WHERE episode_id = ?", (episode_id,)
        ).fetchall()
        return [
            Signal(
                id=r["id"],
                episode_id=r["episode_id"],
                signal_type=r["signal_type"],
                raw_value=r["raw_value"],
                multiplier=r["multiplier"],
                timestamp=r["timestamp"],
            )
            for r in rows
        ]

    # --- Theories ---

    def save_theory(self, theory: Theory) -> Theory:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT OR REPLACE INTO theories
                   (id, content, scope, scope_qualifier, confidence, confirmation_count,
                    contradiction_count, first_observed, last_confirmed, source_episodes,
                    superseded_by, active, description_length, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    theory.id,
                    theory.content,
                    theory.scope,
                    theory.scope_qualifier,
                    theory.confidence,
                    theory.confirmation_count,
                    theory.contradiction_count,
                    theory.first_observed,
                    theory.last_confirmed,
                    self._to_json(theory.source_episodes),
                    theory.superseded_by,
                    1 if theory.active else 0,
                    theory.description_length,
                    self._to_json(theory.metadata),
                ),
            )
            conn.commit()
        return theory

    def get_theory(self, theory_id: str) -> Optional[Theory]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM theories WHERE id = ?", (theory_id,)).fetchone()
        if not row:
            return None
        return self._row_to_theory(row)

    def list_theories(
        self,
        active_only: bool = True,
        scope: Optional[str] = None,
        project: Optional[str] = None,
        limit: int = 50,
    ) -> list[Theory]:
        conn = self._get_conn()
        clauses = []
        params: list[Any] = []
        if active_only:
            clauses.append("active = 1")
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        if project:
            clauses.append("scope_qualifier = ?")
            params.append(project)
        where = " AND ".join(clauses) if clauses else "1=1"
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM theories WHERE {where} ORDER BY confidence DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row_to_theory(r) for r in rows]

    def count_theories(self, active_only: bool = True) -> int:
        conn = self._get_conn()
        if active_only:
            row = conn.execute("SELECT COUNT(*) FROM theories WHERE active = 1").fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM theories").fetchone()
        return row[0] if row else 0

    def _row_to_theory(self, row: sqlite3.Row) -> Theory:
        return Theory(
            id=row["id"],
            content=row["content"],
            scope=row["scope"],
            scope_qualifier=row["scope_qualifier"],
            confidence=row["confidence"],
            confirmation_count=row["confirmation_count"],
            contradiction_count=row["contradiction_count"],
            first_observed=row["first_observed"],
            last_confirmed=row["last_confirmed"],
            source_episodes=self._from_json(row["source_episodes"]),
            superseded_by=row["superseded_by"],
            active=bool(row["active"]),
            description_length=row["description_length"],
            metadata=self._from_json(row["metadata"]),
        )

    # --- Contradictions ---

    def save_contradiction(self, contradiction: Contradiction) -> Contradiction:
        with self._lock:
            conn = self._get_conn()
            cur = conn.execute(
                """INSERT INTO contradictions
                   (theory_id, episode_id, description, resolution, resolved_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    contradiction.theory_id,
                    contradiction.episode_id,
                    contradiction.description,
                    contradiction.resolution,
                    contradiction.resolved_at,
                    contradiction.created_at,
                ),
            )
            contradiction.id = cur.lastrowid
            conn.commit()
        return contradiction

    def list_contradictions(
        self,
        theory_id: Optional[str] = None,
        unresolved_only: bool = False,
        limit: int = 50,
    ) -> list[Contradiction]:
        conn = self._get_conn()
        clauses = []
        params: list[Any] = []
        if theory_id:
            clauses.append("theory_id = ?")
            params.append(theory_id)
        if unresolved_only:
            clauses.append("resolved_at IS NULL")
        where = " AND ".join(clauses) if clauses else "1=1"
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM contradictions WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [
            Contradiction(
                id=r["id"],
                theory_id=r["theory_id"],
                episode_id=r["episode_id"],
                description=r["description"],
                resolution=r["resolution"],
                resolved_at=r["resolved_at"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def count_contradictions(self, unresolved_only: bool = False) -> int:
        conn = self._get_conn()
        if unresolved_only:
            row = conn.execute(
                "SELECT COUNT(*) FROM contradictions WHERE resolved_at IS NULL"
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM contradictions").fetchone()
        return row[0] if row else 0

    # --- User Model ---

    def save_user_knowledge(self, uk: UserKnowledge) -> UserKnowledge:
        with self._lock:
            conn = self._get_conn()
            if uk.id is not None:
                conn.execute(
                    """UPDATE user_model SET topic=?, project=?, familiarity=?,
                       last_seen=?, times_seen=?, times_explained=?, metadata=?
                       WHERE id=?""",
                    (
                        uk.topic,
                        uk.project,
                        uk.familiarity,
                        uk.last_seen,
                        uk.times_seen,
                        uk.times_explained,
                        self._to_json(uk.metadata),
                        uk.id,
                    ),
                )
            else:
                cur = conn.execute(
                    """INSERT INTO user_model
                       (topic, project, familiarity, last_seen, times_seen, times_explained, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        uk.topic,
                        uk.project,
                        uk.familiarity,
                        uk.last_seen,
                        uk.times_seen,
                        uk.times_explained,
                        self._to_json(uk.metadata),
                    ),
                )
                uk.id = cur.lastrowid
            conn.commit()
        return uk

    def get_user_knowledge(self, topic: str, project: str = "") -> Optional[UserKnowledge]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM user_model WHERE topic = ? AND project = ?",
            (topic, project),
        ).fetchone()
        if not row:
            return None
        return UserKnowledge(
            id=row["id"],
            topic=row["topic"],
            project=row["project"],
            familiarity=row["familiarity"],
            last_seen=row["last_seen"],
            times_seen=row["times_seen"],
            times_explained=row["times_explained"],
            metadata=self._from_json(row["metadata"]),
        )

    def list_user_knowledge(self, project: Optional[str] = None) -> list[UserKnowledge]:
        conn = self._get_conn()
        if project:
            rows = conn.execute(
                "SELECT * FROM user_model WHERE project = ? ORDER BY familiarity DESC",
                (project,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM user_model ORDER BY familiarity DESC"
            ).fetchall()
        return [
            UserKnowledge(
                id=r["id"],
                topic=r["topic"],
                project=r["project"],
                familiarity=r["familiarity"],
                last_seen=r["last_seen"],
                times_seen=r["times_seen"],
                times_explained=r["times_explained"],
                metadata=self._from_json(r["metadata"]),
            )
            for r in rows
        ]

    # --- Stats ---

    def stats(self) -> dict[str, Any]:
        conn = self._get_conn()
        return {
            "sessions": conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
            "episodes": {
                "total": self.count_episodes(),
                "pending": self.count_episodes(consolidated=0),
                "consolidated": self.count_episodes(consolidated=1),
                "decayed": self.count_episodes(consolidated=2),
            },
            "theories": {
                "total": self.count_theories(active_only=False),
                "active": self.count_theories(active_only=True),
            },
            "contradictions": {
                "total": self.count_contradictions(),
                "unresolved": self.count_contradictions(unresolved_only=True),
            },
            "schema_version": CURRENT_SCHEMA_VERSION,
        }
