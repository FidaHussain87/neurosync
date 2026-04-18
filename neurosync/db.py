"""SQLite database manager: schema init, migrations, thread-safe operations."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from typing import Any, Optional

from neurosync.config import NeuroSyncConfig
from neurosync.logging import get_logger
from neurosync.models import (
    CausalLink,
    Contradiction,
    Episode,
    FailureRecord,
    Session,
    Signal,
    Theory,
    UserKnowledge,
    _utcnow,
)

logger = get_logger("db")

CURRENT_SCHEMA_VERSION = 5

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
    cause TEXT DEFAULT '',
    effect TEXT DEFAULT '',
    reasoning TEXT DEFAULT '',
    quality_score INTEGER,
    metadata TEXT DEFAULT '{}',
    reinforcement_count INTEGER DEFAULT 0,
    last_accessed TEXT,
    structural_fingerprint TEXT DEFAULT ''
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
    parent_theory_id TEXT,
    related_theories TEXT DEFAULT '[]',
    last_applied TEXT,
    application_count INTEGER DEFAULT 0,
    validation_status TEXT DEFAULT 'unvalidated',
    metadata TEXT DEFAULT '{}',
    hierarchy_depth INTEGER DEFAULT 0,
    structural_fingerprint TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_theories_active ON theories(active);
CREATE INDEX IF NOT EXISTS idx_theories_scope ON theories(scope);
CREATE INDEX IF NOT EXISTS idx_theories_parent ON theories(parent_theory_id);

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

CREATE TABLE IF NOT EXISTS causal_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cause_text TEXT NOT NULL,
    effect_text TEXT NOT NULL,
    mechanism TEXT NOT NULL DEFAULT 'direct',
    mechanism_detail TEXT DEFAULT '',
    confidence_level TEXT DEFAULT 'observed',
    strength REAL DEFAULT 0.5,
    observation_count INTEGER DEFAULT 1,
    source_episode_ids TEXT DEFAULT '[]',
    source_theory_id TEXT DEFAULT '',
    project TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    cause_text_normalized TEXT DEFAULT '',
    effect_text_normalized TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_causal_cause ON causal_links(cause_text);
CREATE INDEX IF NOT EXISTS idx_causal_effect ON causal_links(effect_text);

CREATE TABLE IF NOT EXISTS failure_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    what_failed TEXT NOT NULL,
    why_failed TEXT NOT NULL DEFAULT '',
    what_worked TEXT DEFAULT '',
    category TEXT DEFAULT 'approach',
    project TEXT DEFAULT '',
    context TEXT DEFAULT '',
    source_episode_id TEXT DEFAULT '',
    severity INTEGER DEFAULT 3,
    occurrence_count INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_failures_project ON failure_records(project);
CREATE INDEX IF NOT EXISTS idx_failures_category ON failure_records(category);

-- v4: Junction tables for queryable relationships
CREATE TABLE IF NOT EXISTS theory_episodes (
    theory_id TEXT NOT NULL, episode_id TEXT NOT NULL,
    PRIMARY KEY (theory_id, episode_id)
);
CREATE INDEX IF NOT EXISTS idx_te_episode ON theory_episodes(episode_id);

CREATE TABLE IF NOT EXISTS theory_relations (
    theory_id TEXT NOT NULL, related_theory_id TEXT NOT NULL,
    PRIMARY KEY (theory_id, related_theory_id)
);
CREATE INDEX IF NOT EXISTS idx_tr_related ON theory_relations(related_theory_id);

CREATE TABLE IF NOT EXISTS causal_link_episodes (
    causal_link_id INTEGER NOT NULL, episode_id TEXT NOT NULL,
    PRIMARY KEY (causal_link_id, episode_id)
);
CREATE INDEX IF NOT EXISTS idx_cle_episode ON causal_link_episodes(episode_id);

CREATE TABLE IF NOT EXISTS entity_fingerprints (
    entity_id TEXT NOT NULL, entity_type TEXT NOT NULL, pattern TEXT NOT NULL,
    PRIMARY KEY (entity_id, entity_type, pattern)
);
CREATE INDEX IF NOT EXISTS idx_efp_pattern ON entity_fingerprints(pattern);
CREATE INDEX IF NOT EXISTS idx_efp_entity ON entity_fingerprints(entity_id, entity_type);

-- v4: Missing indexes for causal_links
CREATE INDEX IF NOT EXISTS idx_causal_project ON causal_links(project);
CREATE INDEX IF NOT EXISTS idx_causal_cause_effect ON causal_links(cause_text, effect_text);

-- v5: Composite index on normalized causal text for indexed dedup lookup
CREATE INDEX IF NOT EXISTS idx_causal_normalized ON causal_links(cause_text_normalized, effect_text_normalized);
"""


# Migration v1→v2: structured as (table, column, col_definition)
_V1_TO_V2_COLUMNS = [
    ("episodes", "cause", "TEXT DEFAULT ''"),
    ("episodes", "effect", "TEXT DEFAULT ''"),
    ("episodes", "reasoning", "TEXT DEFAULT ''"),
    ("episodes", "quality_score", "INTEGER"),
    ("theories", "parent_theory_id", "TEXT"),
    ("theories", "related_theories", "TEXT DEFAULT '[]'"),
    ("theories", "last_applied", "TEXT"),
    ("theories", "application_count", "INTEGER DEFAULT 0"),
    ("theories", "validation_status", "TEXT DEFAULT 'unvalidated'"),
]

# Migration v2→v3: columns, tables, and indexes
_V2_TO_V3_COLUMNS = [
    ("theories", "hierarchy_depth", "INTEGER DEFAULT 0"),
    ("episodes", "reinforcement_count", "INTEGER DEFAULT 0"),
    ("episodes", "last_accessed", "TEXT"),
    ("episodes", "structural_fingerprint", "TEXT DEFAULT ''"),
    ("theories", "structural_fingerprint", "TEXT DEFAULT ''"),
]

_V2_TO_V3_TABLES = [
    (
        """CREATE TABLE IF NOT EXISTS causal_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cause_text TEXT NOT NULL,
            effect_text TEXT NOT NULL,
            mechanism TEXT NOT NULL DEFAULT 'direct',
            mechanism_detail TEXT DEFAULT '',
            confidence_level TEXT DEFAULT 'observed',
            strength REAL DEFAULT 0.5,
            observation_count INTEGER DEFAULT 1,
            source_episode_ids TEXT DEFAULT '[]',
            source_theory_id TEXT DEFAULT '',
            project TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        "causal_links",
    ),
    (
        """CREATE TABLE IF NOT EXISTS failure_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            what_failed TEXT NOT NULL,
            why_failed TEXT NOT NULL DEFAULT '',
            what_worked TEXT DEFAULT '',
            category TEXT DEFAULT 'approach',
            project TEXT DEFAULT '',
            context TEXT DEFAULT '',
            source_episode_id TEXT DEFAULT '',
            severity INTEGER DEFAULT 3,
            occurrence_count INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL
        )""",
        "failure_records",
    ),
]

_V2_TO_V3_INDEXES = [
    ("CREATE INDEX IF NOT EXISTS idx_theories_parent ON theories(parent_theory_id)", "idx_theories_parent"),
    ("CREATE INDEX IF NOT EXISTS idx_causal_cause ON causal_links(cause_text)", "idx_causal_cause"),
    ("CREATE INDEX IF NOT EXISTS idx_causal_effect ON causal_links(effect_text)", "idx_causal_effect"),
    ("CREATE INDEX IF NOT EXISTS idx_failures_project ON failure_records(project)", "idx_failures_project"),
    ("CREATE INDEX IF NOT EXISTS idx_failures_category ON failure_records(category)", "idx_failures_category"),
]

# Migration v3→v4: junction tables and indexes
_V3_TO_V4_TABLES = [
    (
        """CREATE TABLE IF NOT EXISTS theory_episodes (
            theory_id TEXT NOT NULL, episode_id TEXT NOT NULL,
            PRIMARY KEY (theory_id, episode_id)
        )""",
        "theory_episodes",
    ),
    (
        """CREATE TABLE IF NOT EXISTS theory_relations (
            theory_id TEXT NOT NULL, related_theory_id TEXT NOT NULL,
            PRIMARY KEY (theory_id, related_theory_id)
        )""",
        "theory_relations",
    ),
    (
        """CREATE TABLE IF NOT EXISTS causal_link_episodes (
            causal_link_id INTEGER NOT NULL, episode_id TEXT NOT NULL,
            PRIMARY KEY (causal_link_id, episode_id)
        )""",
        "causal_link_episodes",
    ),
    (
        """CREATE TABLE IF NOT EXISTS entity_fingerprints (
            entity_id TEXT NOT NULL, entity_type TEXT NOT NULL, pattern TEXT NOT NULL,
            PRIMARY KEY (entity_id, entity_type, pattern)
        )""",
        "entity_fingerprints",
    ),
]

_V3_TO_V4_INDEXES = [
    ("CREATE INDEX IF NOT EXISTS idx_te_episode ON theory_episodes(episode_id)", "idx_te_episode"),
    ("CREATE INDEX IF NOT EXISTS idx_tr_related ON theory_relations(related_theory_id)", "idx_tr_related"),
    ("CREATE INDEX IF NOT EXISTS idx_cle_episode ON causal_link_episodes(episode_id)", "idx_cle_episode"),
    ("CREATE INDEX IF NOT EXISTS idx_efp_pattern ON entity_fingerprints(pattern)", "idx_efp_pattern"),
    ("CREATE INDEX IF NOT EXISTS idx_efp_entity ON entity_fingerprints(entity_id, entity_type)", "idx_efp_entity"),
    ("CREATE INDEX IF NOT EXISTS idx_causal_project ON causal_links(project)", "idx_causal_project"),
    ("CREATE INDEX IF NOT EXISTS idx_causal_cause_effect ON causal_links(cause_text, effect_text)", "idx_causal_cause_effect"),
]

# Migration v4→v5: normalized columns on causal_links for indexed dedup
_V4_TO_V5_COLUMNS = [
    ("causal_links", "cause_text_normalized", "TEXT DEFAULT ''"),
    ("causal_links", "effect_text_normalized", "TEXT DEFAULT ''"),
]

_V4_TO_V5_INDEXES = [
    (
        "CREATE INDEX IF NOT EXISTS idx_causal_normalized ON causal_links(cause_text_normalized, effect_text_normalized)",
        "idx_causal_normalized",
    ),
]


class Database:
    """Thread-safe SQLite database manager for NeuroSync."""

    def __init__(self, config: NeuroSyncConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._local = threading.local()
        config.ensure_dirs()
        self._init_schema()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(
                self._config.sqlite_path,
                check_same_thread=False,
                timeout=10.0,
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._get_conn()
            # Check if schema_version table exists (indicates existing DB)
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )
            is_existing_db = cur.fetchone() is not None

            if is_existing_db:
                # Existing DB — only run migrations, never re-run base schema
                cur = conn.execute("SELECT version FROM schema_version")
                row = cur.fetchone()
                if row is not None:
                    current_version = row["version"]
                    if current_version < CURRENT_SCHEMA_VERSION:
                        self._run_migrations(conn, current_version)
            else:
                # Fresh DB — run full base schema (all tables/indexes)
                conn.executescript(_SCHEMA_SQL)
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (CURRENT_SCHEMA_VERSION,),
                )
            conn.commit()

    @staticmethod
    def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
        """Check if column exists using PRAGMA table_info."""
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r[1] == column for r in rows)

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        return row is not None

    @staticmethod
    def _index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (index_name,)
        ).fetchone()
        return row is not None

    def _run_migrations(self, conn: sqlite3.Connection, from_version: int) -> None:
        """Run schema migrations from from_version to CURRENT_SCHEMA_VERSION."""
        if from_version < 2:
            for table, column, col_def in _V1_TO_V2_COLUMNS:
                if not self._column_exists(conn, table, column):
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
        if from_version < 3:
            for table, column, col_def in _V2_TO_V3_COLUMNS:
                if not self._column_exists(conn, table, column):
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
            for create_stmt, table_name in _V2_TO_V3_TABLES:
                if not self._table_exists(conn, table_name):
                    conn.execute(create_stmt)
            for create_stmt, index_name in _V2_TO_V3_INDEXES:
                if not self._index_exists(conn, index_name):
                    conn.execute(create_stmt)
        if from_version < 4:
            for create_stmt, table_name in _V3_TO_V4_TABLES:
                if not self._table_exists(conn, table_name):
                    conn.execute(create_stmt)
            for create_stmt, index_name in _V3_TO_V4_INDEXES:
                if not self._index_exists(conn, index_name):
                    conn.execute(create_stmt)
            self._backfill_v4_junction_tables(conn)
        if from_version < 5:
            for table, column, col_def in _V4_TO_V5_COLUMNS:
                if not self._column_exists(conn, table, column):
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
            for create_stmt, index_name in _V4_TO_V5_INDEXES:
                if not self._index_exists(conn, index_name):
                    conn.execute(create_stmt)
            self._backfill_v5_normalized_columns(conn)
        conn.execute(
            "UPDATE schema_version SET version = ?", (CURRENT_SCHEMA_VERSION,)
        )

    def _backfill_v4_junction_tables(self, conn: sqlite3.Connection) -> None:
        """Populate v4 junction tables from existing JSON columns."""
        # theory_episodes from theories.source_episodes
        rows = conn.execute("SELECT id, source_episodes FROM theories").fetchall()
        for row in rows:
            theory_id = row["id"]
            episode_ids = self._from_json(row["source_episodes"], [])
            for ep_id in episode_ids:
                if ep_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO theory_episodes (theory_id, episode_id) VALUES (?, ?)",
                        (theory_id, ep_id),
                    )
        # theory_relations from theories.related_theories
        rows2 = conn.execute("SELECT id, related_theories FROM theories").fetchall()
        for row in rows2:
            theory_id = row["id"]
            related_ids = self._from_json(row["related_theories"], [])
            for rid in related_ids:
                if rid:
                    conn.execute(
                        "INSERT OR IGNORE INTO theory_relations (theory_id, related_theory_id) VALUES (?, ?)",
                        (theory_id, rid),
                    )
        # causal_link_episodes from causal_links.source_episode_ids
        if self._table_exists(conn, "causal_links"):
            cl_rows = conn.execute("SELECT id, source_episode_ids FROM causal_links").fetchall()
            for row in cl_rows:
                link_id = row["id"]
                ep_ids = self._from_json(row["source_episode_ids"], [])
                for ep_id in ep_ids:
                    if ep_id:
                        conn.execute(
                            "INSERT OR IGNORE INTO causal_link_episodes (causal_link_id, episode_id) VALUES (?, ?)",
                            (link_id, ep_id),
                        )
        # entity_fingerprints from episodes.structural_fingerprint and theories.structural_fingerprint
        ep_rows = conn.execute("SELECT id, structural_fingerprint FROM episodes WHERE structural_fingerprint != ''").fetchall()
        for row in ep_rows:
            fp = row["structural_fingerprint"]
            if fp:
                for pattern in fp.split(","):
                    pattern = pattern.strip()
                    if pattern:
                        conn.execute(
                            "INSERT OR IGNORE INTO entity_fingerprints (entity_id, entity_type, pattern) VALUES (?, ?, ?)",
                            (row["id"], "episode", pattern),
                        )
        th_rows = conn.execute("SELECT id, structural_fingerprint FROM theories WHERE structural_fingerprint != ''").fetchall()
        for row in th_rows:
            fp = row["structural_fingerprint"]
            if fp:
                for pattern in fp.split(","):
                    pattern = pattern.strip()
                    if pattern:
                        conn.execute(
                            "INSERT OR IGNORE INTO entity_fingerprints (entity_id, entity_type, pattern) VALUES (?, ?, ?)",
                            (row["id"], "theory", pattern),
                        )

    def _backfill_v5_normalized_columns(self, conn: sqlite3.Connection) -> None:
        """Populate normalized text columns on existing causal_links rows."""
        rows = conn.execute("SELECT id, cause_text, effect_text FROM causal_links").fetchall()
        for row in rows:
            conn.execute(
                "UPDATE causal_links SET cause_text_normalized = ?, effect_text_normalized = ? WHERE id = ?",
                (
                    self._normalize_text(row["cause_text"]),
                    self._normalize_text(row["effect_text"]),
                    row["id"],
                ),
            )

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    # --- JSON helpers ---

    @staticmethod
    def _to_json(val: Any) -> str:
        return json.dumps(val, default=str)

    @staticmethod
    def _from_json(val: str, fallback: Any = None) -> Any:
        if not val:
            return fallback if fallback is not None else {}
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Corrupted JSON in database, using fallback: %.100s", val)
            return fallback if fallback is not None else {}

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
            metadata=self._from_json(row["metadata"], {}),
        )

    # --- Episodes ---

    def save_episode(self, episode: Episode) -> Episode:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT OR REPLACE INTO episodes
                   (id, session_id, timestamp, event_type, content, context,
                    files_touched, layers_touched, signal_weight, consolidated,
                    consolidated_at, cause, effect, reasoning, quality_score, metadata,
                    reinforcement_count, last_accessed, structural_fingerprint)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    episode.cause,
                    episode.effect,
                    episode.reasoning,
                    episode.quality_score,
                    self._to_json(episode.metadata),
                    episode.reinforcement_count,
                    episode.last_accessed,
                    episode.structural_fingerprint,
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
            files_touched=self._from_json(row["files_touched"], []),
            layers_touched=self._from_json(row["layers_touched"], []),
            signal_weight=row["signal_weight"],
            consolidated=row["consolidated"],
            consolidated_at=row["consolidated_at"],
            cause=row["cause"] or "",
            effect=row["effect"] or "",
            reasoning=row["reasoning"] or "",
            quality_score=row["quality_score"],
            metadata=self._from_json(row["metadata"], {}),
            reinforcement_count=row["reinforcement_count"] or 0,
            last_accessed=row["last_accessed"],
            structural_fingerprint=row["structural_fingerprint"] or "",
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
                    superseded_by, active, description_length, parent_theory_id,
                    related_theories, last_applied, application_count, validation_status,
                    metadata, hierarchy_depth, structural_fingerprint)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    theory.parent_theory_id,
                    self._to_json(theory.related_theories),
                    theory.last_applied,
                    theory.application_count,
                    theory.validation_status,
                    self._to_json(theory.metadata),
                    theory.hierarchy_depth,
                    theory.structural_fingerprint,
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
            source_episodes=self._from_json(row["source_episodes"], []),
            superseded_by=row["superseded_by"],
            active=bool(row["active"]),
            description_length=row["description_length"],
            parent_theory_id=row["parent_theory_id"],
            related_theories=self._from_json(row["related_theories"], []),
            last_applied=row["last_applied"],
            application_count=row["application_count"] or 0,
            validation_status=row["validation_status"] or "unvalidated",
            metadata=self._from_json(row["metadata"], {}),
            hierarchy_depth=row["hierarchy_depth"] or 0,
            structural_fingerprint=row["structural_fingerprint"] or "",
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
            metadata=self._from_json(row["metadata"], {}),
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
                metadata=self._from_json(r["metadata"], {}),
            )
            for r in rows
        ]

    # --- Episode helpers (v3) ---

    def update_episode_access(
        self, episode_id: str, reinforcement_count: int, last_accessed: str
    ) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE episodes SET reinforcement_count = ?, last_accessed = ? WHERE id = ?",
                (reinforcement_count, last_accessed, episode_id),
            )
            conn.commit()

    def list_episodes_for_pruning(
        self, min_age_days: int = 30, consolidated: int = 1, limit: int = 500
    ) -> list[Episode]:
        """List consolidated episodes older than min_age_days for pruning."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM episodes
               WHERE consolidated = ?
               AND julianday('now') - julianday(timestamp) > ?
               ORDER BY timestamp ASC LIMIT ?""",
            (consolidated, min_age_days, limit),
        ).fetchall()
        return [self._row_to_episode(r) for r in rows]

    # --- Theory helpers (v3) ---

    def list_children_of_theory(self, parent_id: str) -> list[Theory]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM theories WHERE parent_theory_id = ? AND active = 1",
            (parent_id,),
        ).fetchall()
        return [self._row_to_theory(r) for r in rows]

    # --- Causal Links ---

    def save_causal_link(self, link: CausalLink) -> CausalLink:
        with self._lock:
            conn = self._get_conn()
            norm_cause = self._normalize_text(link.cause_text)
            norm_effect = self._normalize_text(link.effect_text)
            if link.id is not None:
                conn.execute(
                    """UPDATE causal_links SET cause_text=?, effect_text=?, mechanism=?,
                       mechanism_detail=?, confidence_level=?, strength=?,
                       observation_count=?, source_episode_ids=?, source_theory_id=?,
                       project=?, updated_at=?,
                       cause_text_normalized=?, effect_text_normalized=?
                       WHERE id=?""",
                    (
                        link.cause_text,
                        link.effect_text,
                        link.mechanism,
                        link.mechanism_detail,
                        link.confidence_level,
                        link.strength,
                        link.observation_count,
                        self._to_json(link.source_episode_ids),
                        link.source_theory_id,
                        link.project,
                        link.updated_at,
                        norm_cause,
                        norm_effect,
                        link.id,
                    ),
                )
            else:
                cur = conn.execute(
                    """INSERT INTO causal_links
                       (cause_text, effect_text, mechanism, mechanism_detail,
                        confidence_level, strength, observation_count,
                        source_episode_ids, source_theory_id, project,
                        created_at, updated_at,
                        cause_text_normalized, effect_text_normalized)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        link.cause_text,
                        link.effect_text,
                        link.mechanism,
                        link.mechanism_detail,
                        link.confidence_level,
                        link.strength,
                        link.observation_count,
                        self._to_json(link.source_episode_ids),
                        link.source_theory_id,
                        link.project,
                        link.created_at,
                        link.updated_at,
                        norm_cause,
                        norm_effect,
                    ),
                )
                link.id = cur.lastrowid
            conn.commit()
        return link

    def get_causal_link(self, link_id: int) -> Optional[CausalLink]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM causal_links WHERE id = ?", (link_id,)).fetchone()
        if not row:
            return None
        return self._row_to_causal_link(row)

    def list_causal_links(
        self,
        cause_text: Optional[str] = None,
        effect_text: Optional[str] = None,
        project: Optional[str] = None,
        limit: int = 100,
    ) -> list[CausalLink]:
        conn = self._get_conn()
        clauses: list[str] = []
        params: list[Any] = []
        if cause_text is not None:
            clauses.append("cause_text = ?")
            params.append(cause_text)
        if effect_text is not None:
            clauses.append("effect_text = ?")
            params.append(effect_text)
        if project is not None:
            clauses.append("project = ?")
            params.append(project)
        where = " AND ".join(clauses) if clauses else "1=1"
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM causal_links WHERE {where} ORDER BY observation_count DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row_to_causal_link(r) for r in rows]

    def find_causal_links_by_text(self, text: str, role: str = "cause") -> list[CausalLink]:
        """Find causal links where text appears in cause or effect."""
        conn = self._get_conn()
        column = "cause_text" if role == "cause" else "effect_text"
        # Escape LIKE wildcards in user-provided text
        safe_text = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = conn.execute(
            f"SELECT * FROM causal_links WHERE {column} LIKE ? ESCAPE '\\' ORDER BY observation_count DESC",
            (f"%{safe_text}%",),
        ).fetchall()
        return [self._row_to_causal_link(r) for r in rows]

    def increment_causal_observation(self, link_id: int) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE causal_links SET observation_count = observation_count + 1, updated_at = ? WHERE id = ?",
                (_utcnow(), link_id),
            )
            conn.commit()

    def count_causal_links(self) -> int:
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM causal_links").fetchone()
        return row[0] if row else 0

    def _row_to_causal_link(self, row: sqlite3.Row) -> CausalLink:
        return CausalLink(
            id=row["id"],
            cause_text=row["cause_text"],
            effect_text=row["effect_text"],
            mechanism=row["mechanism"],
            mechanism_detail=row["mechanism_detail"] or "",
            confidence_level=row["confidence_level"] or "observed",
            strength=row["strength"],
            observation_count=row["observation_count"],
            source_episode_ids=self._from_json(row["source_episode_ids"], []),
            source_theory_id=row["source_theory_id"] or "",
            project=row["project"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- v4: Junction table methods ---

    def add_theory_episode(self, theory_id: str, episode_id: str) -> None:
        """Write a theory↔episode link to the junction table."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO theory_episodes (theory_id, episode_id) VALUES (?, ?)",
                (theory_id, episode_id),
            )
            conn.commit()

    def get_theory_episode_ids(self, theory_id: str) -> list[str]:
        """Forward lookup: get episode IDs for a theory."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT episode_id FROM theory_episodes WHERE theory_id = ?", (theory_id,)
        ).fetchall()
        return [r["episode_id"] for r in rows]

    def get_theories_for_episode(self, episode_id: str) -> list[str]:
        """Reverse lookup: get theory IDs that reference an episode."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT theory_id FROM theory_episodes WHERE episode_id = ?", (episode_id,)
        ).fetchall()
        return [r["theory_id"] for r in rows]

    def add_theory_relation(self, theory_id: str, related_id: str) -> None:
        """Write a theory↔theory relation to the junction table."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO theory_relations (theory_id, related_theory_id) VALUES (?, ?)",
                (theory_id, related_id),
            )
            conn.commit()

    def get_related_theory_ids(self, theory_id: str) -> list[str]:
        """Get related theory IDs from the junction table."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT related_theory_id FROM theory_relations WHERE theory_id = ?", (theory_id,)
        ).fetchall()
        return [r["related_theory_id"] for r in rows]

    def add_causal_link_episode(self, link_id: int, episode_id: str) -> None:
        """Write a causal_link↔episode link to the junction table."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO causal_link_episodes (causal_link_id, episode_id) VALUES (?, ?)",
                (link_id, episode_id),
            )
            conn.commit()

    def get_causal_link_episode_ids(self, link_id: int) -> list[str]:
        """Get episode IDs for a causal link."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT episode_id FROM causal_link_episodes WHERE causal_link_id = ?", (link_id,)
        ).fetchall()
        return [r["episode_id"] for r in rows]

    def set_entity_fingerprints(self, entity_id: str, entity_type: str, patterns: list[str]) -> None:
        """Replace all fingerprint patterns for an entity."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "DELETE FROM entity_fingerprints WHERE entity_id = ? AND entity_type = ?",
                (entity_id, entity_type),
            )
            for pattern in patterns:
                if pattern:
                    conn.execute(
                        "INSERT OR IGNORE INTO entity_fingerprints (entity_id, entity_type, pattern) VALUES (?, ?, ?)",
                        (entity_id, entity_type, pattern),
                    )
            conn.commit()

    def get_entity_fingerprints(self, entity_id: str, entity_type: str) -> list[str]:
        """Get fingerprint patterns for an entity."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT pattern FROM entity_fingerprints WHERE entity_id = ? AND entity_type = ?",
            (entity_id, entity_type),
        ).fetchall()
        return [r["pattern"] for r in rows]

    def find_entities_by_fingerprint(self, pattern: str, entity_type: Optional[str] = None) -> list[dict[str, str]]:
        """Find entities that have a specific fingerprint pattern."""
        conn = self._get_conn()
        if entity_type:
            rows = conn.execute(
                "SELECT entity_id, entity_type FROM entity_fingerprints WHERE pattern = ? AND entity_type = ?",
                (pattern, entity_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT entity_id, entity_type FROM entity_fingerprints WHERE pattern = ?",
                (pattern,),
            ).fetchall()
        return [{"entity_id": r["entity_id"], "entity_type": r["entity_type"]} for r in rows]

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize text for case/whitespace-insensitive comparison."""
        return re.sub(r'\s+', ' ', text.strip().lower())

    def list_causal_links_normalized(
        self, cause_text: str, effect_text: str, limit: int = 5
    ) -> list[CausalLink]:
        """Case-insensitive, whitespace-normalized causal link dedup lookup.

        Uses the idx_causal_normalized composite index on
        (cause_text_normalized, effect_text_normalized) for O(log n) lookup.
        """
        norm_cause = self._normalize_text(cause_text)
        norm_effect = self._normalize_text(effect_text)
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM causal_links
               WHERE cause_text_normalized = ? AND effect_text_normalized = ?
               ORDER BY observation_count DESC LIMIT ?""",
            (norm_cause, norm_effect, limit),
        ).fetchall()
        return [self._row_to_causal_link(r) for r in rows]

    # --- Failure Records ---

    def save_failure_record(self, record: FailureRecord) -> FailureRecord:
        with self._lock:
            conn = self._get_conn()
            if record.id is not None:
                conn.execute(
                    """UPDATE failure_records SET what_failed=?, why_failed=?,
                       what_worked=?, category=?, project=?, context=?,
                       source_episode_id=?, severity=?, occurrence_count=?,
                       last_seen=? WHERE id=?""",
                    (
                        record.what_failed,
                        record.why_failed,
                        record.what_worked,
                        record.category,
                        record.project,
                        record.context,
                        record.source_episode_id,
                        record.severity,
                        record.occurrence_count,
                        record.last_seen,
                        record.id,
                    ),
                )
            else:
                cur = conn.execute(
                    """INSERT INTO failure_records
                       (what_failed, why_failed, what_worked, category, project,
                        context, source_episode_id, severity, occurrence_count,
                        created_at, last_seen)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        record.what_failed,
                        record.why_failed,
                        record.what_worked,
                        record.category,
                        record.project,
                        record.context,
                        record.source_episode_id,
                        record.severity,
                        record.occurrence_count,
                        record.created_at,
                        record.last_seen,
                    ),
                )
                record.id = cur.lastrowid
            conn.commit()
        return record

    def get_failure_record(self, record_id: int) -> Optional[FailureRecord]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM failure_records WHERE id = ?", (record_id,)).fetchone()
        if not row:
            return None
        return self._row_to_failure_record(row)

    def list_failure_records(
        self,
        project: Optional[str] = None,
        category: Optional[str] = None,
        min_severity: int = 1,
        limit: int = 100,
    ) -> list[FailureRecord]:
        conn = self._get_conn()
        clauses = ["severity >= ?"]
        params: list[Any] = [min_severity]
        if project is not None:
            clauses.append("project = ?")
            params.append(project)
        if category is not None:
            clauses.append("category = ?")
            params.append(category)
        where = " AND ".join(clauses)
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM failure_records WHERE {where} ORDER BY occurrence_count DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row_to_failure_record(r) for r in rows]

    def increment_failure_occurrence(self, record_id: int) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE failure_records SET occurrence_count = occurrence_count + 1, last_seen = ? WHERE id = ?",
                (_utcnow(), record_id),
            )
            conn.commit()

    def count_failure_records(self) -> int:
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM failure_records").fetchone()
        return row[0] if row else 0

    def _row_to_failure_record(self, row: sqlite3.Row) -> FailureRecord:
        return FailureRecord(
            id=row["id"],
            what_failed=row["what_failed"],
            why_failed=row["why_failed"] or "",
            what_worked=row["what_worked"] or "",
            category=row["category"] or "approach",
            project=row["project"] or "",
            context=row["context"] or "",
            source_episode_id=row["source_episode_id"] or "",
            severity=row["severity"],
            occurrence_count=row["occurrence_count"],
            created_at=row["created_at"],
            last_seen=row["last_seen"],
        )

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
