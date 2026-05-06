"""PostgreSQL database backend: schema init, migrations, connection pooling.

Drop-in replacement for db.Database when db_backend='postgresql'.
Requires psycopg2: pip install neurosync[postgresql]
"""

from __future__ import annotations

import json
import re
import threading
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from neurosync.replay import CognitiveReplay

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

logger = get_logger("pg_db")

CURRENT_SCHEMA_VERSION = 10

# PostgreSQL schema — uses SERIAL instead of AUTOINCREMENT, BOOLEAN instead of
# INTEGER for booleans, and native JSON handling.
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
    metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'decision',
    content TEXT NOT NULL DEFAULT '',
    context TEXT DEFAULT '',
    files_touched JSONB DEFAULT '[]',
    layers_touched JSONB DEFAULT '[]',
    signal_weight REAL DEFAULT 1.0,
    consolidated INTEGER DEFAULT 0,
    consolidated_at TEXT,
    cause TEXT DEFAULT '',
    effect TEXT DEFAULT '',
    reasoning TEXT DEFAULT '',
    quality_score INTEGER,
    metadata JSONB DEFAULT '{}',
    reinforcement_count INTEGER DEFAULT 0,
    last_accessed TEXT,
    structural_fingerprint TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_episodes_session ON episodes(session_id);
CREATE INDEX IF NOT EXISTS idx_episodes_consolidated ON episodes(consolidated);
CREATE INDEX IF NOT EXISTS idx_episodes_type ON episodes(event_type);

CREATE TABLE IF NOT EXISTS signals (
    id SERIAL PRIMARY KEY,
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
    source_episodes JSONB DEFAULT '[]',
    superseded_by TEXT,
    active BOOLEAN DEFAULT TRUE,
    description_length INTEGER DEFAULT 0,
    parent_theory_id TEXT,
    related_theories JSONB DEFAULT '[]',
    last_applied TEXT,
    application_count INTEGER DEFAULT 0,
    validation_status TEXT DEFAULT 'unvalidated',
    metadata JSONB DEFAULT '{}',
    hierarchy_depth INTEGER DEFAULT 0,
    structural_fingerprint TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_theories_active ON theories(active);
CREATE INDEX IF NOT EXISTS idx_theories_scope ON theories(scope);
CREATE INDEX IF NOT EXISTS idx_theories_parent ON theories(parent_theory_id);

CREATE TABLE IF NOT EXISTS contradictions (
    id SERIAL PRIMARY KEY,
    theory_id TEXT NOT NULL REFERENCES theories(id),
    episode_id TEXT NOT NULL REFERENCES episodes(id),
    description TEXT DEFAULT '',
    resolution TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_model (
    id SERIAL PRIMARY KEY,
    topic TEXT NOT NULL,
    project TEXT DEFAULT '',
    familiarity REAL DEFAULT 0.5,
    last_seen TEXT NOT NULL,
    times_seen INTEGER DEFAULT 0,
    times_explained INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_user_model_topic ON user_model(topic);

CREATE TABLE IF NOT EXISTS causal_links (
    id SERIAL PRIMARY KEY,
    cause_text TEXT NOT NULL,
    effect_text TEXT NOT NULL,
    mechanism TEXT NOT NULL DEFAULT 'direct',
    mechanism_detail TEXT DEFAULT '',
    confidence_level TEXT DEFAULT 'observed',
    strength REAL DEFAULT 0.5,
    observation_count INTEGER DEFAULT 1,
    source_episode_ids JSONB DEFAULT '[]',
    source_theory_id TEXT DEFAULT '',
    project TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    cause_text_normalized TEXT DEFAULT '',
    effect_text_normalized TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_causal_cause ON causal_links(cause_text);
CREATE INDEX IF NOT EXISTS idx_causal_effect ON causal_links(effect_text);
CREATE INDEX IF NOT EXISTS idx_causal_project ON causal_links(project);
CREATE INDEX IF NOT EXISTS idx_causal_cause_effect ON causal_links(cause_text, effect_text);
CREATE INDEX IF NOT EXISTS idx_causal_normalized ON causal_links(cause_text_normalized, effect_text_normalized);

CREATE TABLE IF NOT EXISTS failure_records (
    id SERIAL PRIMARY KEY,
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

CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    timestamp TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    field_name TEXT DEFAULT '',
    old_value TEXT DEFAULT '',
    new_value TEXT DEFAULT '',
    context TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);

CREATE TABLE IF NOT EXISTS theory_versions (
    id SERIAL PRIMARY KEY,
    theory_id TEXT NOT NULL REFERENCES theories(id),
    version_number INTEGER NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    confidence REAL DEFAULT 0.5,
    confirmation_count INTEGER DEFAULT 0,
    contradiction_count INTEGER DEFAULT 0,
    validation_status TEXT DEFAULT 'unvalidated',
    scope TEXT DEFAULT 'craft',
    scope_qualifier TEXT DEFAULT '',
    active BOOLEAN DEFAULT TRUE,
    source_episodes JSONB DEFAULT '[]',
    created_at TEXT NOT NULL,
    action TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tv_theory ON theory_versions(theory_id);
CREATE INDEX IF NOT EXISTS idx_tv_version ON theory_versions(theory_id, version_number);

CREATE TABLE IF NOT EXISTS insights (
    id TEXT PRIMARY KEY,
    insight_type TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    evidence JSONB DEFAULT '[]',
    confidence REAL DEFAULT 0.5,
    staleness_days REAL DEFAULT 0.0,
    project TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    surfaced_count INTEGER DEFAULT 0,
    dismissed BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_insights_type ON insights(insight_type);
CREATE INDEX IF NOT EXISTS idx_insights_project ON insights(project);
CREATE INDEX IF NOT EXISTS idx_insights_confidence ON insights(confidence);

CREATE TABLE IF NOT EXISTS developer_profile (
    id SERIAL PRIMARY KEY,
    profile_key TEXT NOT NULL UNIQUE,
    profile_value TEXT NOT NULL DEFAULT '',
    computed_at TEXT NOT NULL,
    observation_count INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.5,
    metadata JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_devprofile_key ON developer_profile(profile_key);
"""


class PostgresDatabase:
    """PostgreSQL database backend for NeuroSync.

    Same public interface as db.Database (SQLite), backed by psycopg2
    with connection pooling.
    """

    def __init__(self, config: NeuroSyncConfig) -> None:
        try:
            import psycopg2
            import psycopg2.pool
        except ImportError as e:
            raise ImportError(
                "psycopg2 is required for PostgreSQL backend. "
                "Install with: pip install neurosync[postgresql]"
            ) from e

        self._config = config
        self._lock = threading.Lock()
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=5,
            dsn=config.pg_dsn,
        )
        self._init_schema()

    def __enter__(self) -> PostgresDatabase:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _get_conn(self) -> Any:
        return self._pool.getconn()

    def _put_conn(self, conn: Any) -> None:
        self._pool.putconn(conn)

    def _reconnect(self) -> None:
        """Close stale pool and create a fresh one. Thread-safe via self._lock."""
        import contextlib

        import psycopg2.pool

        with self._lock:
            with contextlib.suppress(Exception):
                self._pool.closeall()
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=5,
                dsn=self._config.pg_dsn,
            )

    def _with_retry(self, fn: Any) -> Any:
        """Execute fn(); on OperationalError/InterfaceError, reconnect and retry once."""
        import psycopg2

        try:
            return fn()
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            logger.warning("PostgreSQL connection lost, attempting reconnect", exc_info=True)
            self._reconnect()
            return fn()

    def _execute(self, sql: str, params: Any = None, returning: bool = False) -> Any:
        """Execute a single SQL statement with automatic connection management and retry."""
        return self._with_retry(lambda: self._execute_inner(sql, params, returning))

    def _execute_inner(self, sql: str, params: Any = None, returning: bool = False) -> Any:
        """Execute a single SQL statement with automatic connection management."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if returning:
                    result = cur.fetchone()
                    conn.commit()
                    return result
                conn.commit()
                return cur
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    def _query(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        """Execute a query and return results as list of dicts, with retry on connection loss."""
        return self._with_retry(lambda: self._query_inner(sql, params))

    def _query_inner(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        """Execute a query and return results as list of dicts."""
        conn = self._get_conn()
        try:
            import psycopg2.extras

            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(row) for row in cur.fetchall()]
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    def _query_one(self, sql: str, params: Any = None) -> Optional[dict[str, Any]]:
        """Execute a query and return first result as dict, or None."""
        rows = self._query(sql, params)
        return rows[0] if rows else None

    def _init_schema(self) -> None:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                # Check if schema_version table exists
                cur.execute(
                    "SELECT EXISTS(SELECT 1 FROM information_schema.tables"
                    " WHERE table_name='schema_version')"
                )
                exists = cur.fetchone()[0]

                if exists:
                    cur.execute("SELECT version FROM schema_version")
                    row = cur.fetchone()
                    current_version = row[0] if row else 0
                    if current_version < CURRENT_SCHEMA_VERSION:
                        self._run_migrations(cur, current_version)
                        cur.execute(
                            "UPDATE schema_version SET version = %s",
                            (CURRENT_SCHEMA_VERSION,),
                        )
                else:
                    # Fresh DB — split and execute each statement individually
                    for stmt in _SCHEMA_SQL.split(";"):
                        stmt = stmt.strip()
                        if stmt:
                            cur.execute(stmt)
                    cur.execute(
                        "INSERT INTO schema_version (version) VALUES (%s)",
                        (CURRENT_SCHEMA_VERSION,),
                    )
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    def _run_migrations(self, cur: Any, from_version: int) -> None:
        """Run incremental schema migrations."""
        if from_version < 6:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    field_name TEXT DEFAULT '',
                    old_value TEXT DEFAULT '',
                    new_value TEXT DEFAULT '',
                    context TEXT DEFAULT ''
                )"""
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_entity"
                " ON audit_log(entity_type, entity_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_audit_timestamp"
                " ON audit_log(timestamp)"
            )
        if from_version < 7:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS theory_versions (
                    id SERIAL PRIMARY KEY,
                    theory_id TEXT NOT NULL REFERENCES theories(id),
                    version_number INTEGER NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    confidence REAL DEFAULT 0.5,
                    confirmation_count INTEGER DEFAULT 0,
                    contradiction_count INTEGER DEFAULT 0,
                    validation_status TEXT DEFAULT 'unvalidated',
                    scope TEXT DEFAULT 'craft',
                    scope_qualifier TEXT DEFAULT '',
                    active BOOLEAN DEFAULT TRUE,
                    source_episodes JSONB DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    action TEXT DEFAULT ''
                )"""
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_tv_theory"
                " ON theory_versions(theory_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_tv_version"
                " ON theory_versions(theory_id, version_number)"
            )
        if from_version < 8:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS insights (
                    id TEXT PRIMARY KEY,
                    insight_type TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    evidence JSONB DEFAULT '[]',
                    confidence REAL DEFAULT 0.5,
                    staleness_days REAL DEFAULT 0.0,
                    project TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    surfaced_count INTEGER DEFAULT 0,
                    dismissed BOOLEAN DEFAULT FALSE,
                    metadata JSONB DEFAULT '{}'
                )"""
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_insights_type ON insights(insight_type)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_insights_project ON insights(project)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_insights_confidence ON insights(confidence)"
            )
            cur.execute(
                """CREATE TABLE IF NOT EXISTS developer_profile (
                    id SERIAL PRIMARY KEY,
                    profile_key TEXT NOT NULL UNIQUE,
                    profile_value TEXT NOT NULL DEFAULT '',
                    computed_at TEXT NOT NULL,
                    observation_count INTEGER DEFAULT 0,
                    confidence REAL DEFAULT 0.5,
                    metadata JSONB DEFAULT '{}'
                )"""
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_devprofile_key"
                " ON developer_profile(profile_key)"
            )
        if from_version < 9:
            cur.execute(
                "ALTER TABLE episodes ADD COLUMN IF NOT EXISTS domains JSONB DEFAULT '[]'"
            )
            cur.execute(
                """CREATE TABLE IF NOT EXISTS episode_domains (
                    episode_id TEXT NOT NULL REFERENCES episodes(id),
                    domain TEXT NOT NULL,
                    PRIMARY KEY (episode_id, domain)
                )"""
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_episode_domains_domain"
                " ON episode_domains(domain)"
            )
        if from_version < 10:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS cognitive_replays (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    strategy_type TEXT NOT NULL DEFAULT 'elimination',
                    problem_signature TEXT NOT NULL DEFAULT '',
                    steps JSONB NOT NULL DEFAULT '[]',
                    shortcut TEXT DEFAULT '',
                    domains JSONB DEFAULT '[]',
                    files_involved JSONB DEFAULT '[]',
                    source_episode_ids JSONB DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    times_surfaced INTEGER DEFAULT 0,
                    times_helpful INTEGER DEFAULT 0,
                    confidence REAL DEFAULT 0.5
                )"""
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_replays_session"
                " ON cognitive_replays(session_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_replays_strategy"
                " ON cognitive_replays(strategy_type)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_replays_confidence"
                " ON cognitive_replays(confidence)"
            )

    def close(self) -> None:
        if self._pool:
            self._pool.closeall()

    # --- JSON helpers ---

    @staticmethod
    def _to_json(val: Any) -> str:
        return json.dumps(val, default=str)

    @staticmethod
    def _from_json(val: Any, fallback: Any = None) -> Any:
        if val is None:
            return fallback if fallback is not None else {}
        if isinstance(val, (dict, list)):
            return val  # psycopg2 auto-deserializes JSONB
        if isinstance(val, str):
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return fallback if fallback is not None else {}
        return fallback if fallback is not None else {}

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())

    # --- Sessions ---

    def save_session(self, session: Session) -> Session:
        self._execute(
            """INSERT INTO sessions
               (id, project, branch, started_at, ended_at, duration_seconds, summary, metadata)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET
               project=EXCLUDED.project, branch=EXCLUDED.branch,
               started_at=EXCLUDED.started_at, ended_at=EXCLUDED.ended_at,
               duration_seconds=EXCLUDED.duration_seconds, summary=EXCLUDED.summary,
               metadata=EXCLUDED.metadata""",
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
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        row = self._query_one("SELECT * FROM sessions WHERE id = %s", (session_id,))
        return self._row_to_session(row) if row else None

    def list_sessions(self, project: Optional[str] = None, limit: int = 20) -> list[Session]:
        if project:
            rows = self._query(
                "SELECT * FROM sessions WHERE project = %s ORDER BY started_at DESC LIMIT %s",
                (project, limit),
            )
        else:
            rows = self._query("SELECT * FROM sessions ORDER BY started_at DESC LIMIT %s", (limit,))
        return [self._row_to_session(r) for r in rows]

    def _row_to_session(self, row: dict[str, Any]) -> Session:
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
        self._execute(
            """INSERT INTO episodes
               (id, session_id, timestamp, event_type, content, context,
                files_touched, layers_touched, signal_weight, consolidated,
                consolidated_at, cause, effect, reasoning, quality_score, metadata,
                reinforcement_count, last_accessed, structural_fingerprint, domains)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
               signal_weight=EXCLUDED.signal_weight, consolidated=EXCLUDED.consolidated,
               consolidated_at=EXCLUDED.consolidated_at, quality_score=EXCLUDED.quality_score,
               metadata=EXCLUDED.metadata, reinforcement_count=EXCLUDED.reinforcement_count,
               last_accessed=EXCLUDED.last_accessed, structural_fingerprint=EXCLUDED.structural_fingerprint,
               domains=EXCLUDED.domains""",
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
                self._to_json(episode.domains),
            ),
        )
        # Maintain episode_domains junction table
        self._execute(
            "DELETE FROM episode_domains WHERE episode_id = %s", (episode.id,)
        )
        if episode.domains:
            for domain in episode.domains:
                self._execute(
                    "INSERT INTO episode_domains (episode_id, domain) VALUES (%s, %s)"
                    " ON CONFLICT DO NOTHING",
                    (episode.id, domain),
                )
        return episode

    def get_episode(self, episode_id: str) -> Optional[Episode]:
        row = self._query_one("SELECT * FROM episodes WHERE id = %s", (episode_id,))
        return self._row_to_episode(row) if row else None

    def list_episodes(
        self,
        session_id: Optional[str] = None,
        consolidated: Optional[int] = None,
        event_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[Episode]:
        clauses = []
        params: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = %s")
            params.append(session_id)
        if consolidated is not None:
            clauses.append("consolidated = %s")
            params.append(consolidated)
        if event_type is not None:
            clauses.append("event_type = %s")
            params.append(event_type)
        where = " AND ".join(clauses) if clauses else "TRUE"
        params.append(limit)
        rows = self._query(
            f"SELECT * FROM episodes WHERE {where} ORDER BY timestamp DESC LIMIT %s",
            params,
        )
        return [self._row_to_episode(r) for r in rows]

    def list_episodes_lightweight(
        self,
        columns: list[str],
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        """Fetch episodes with only the specified columns (for analytics)."""
        allowed = {
            "id", "session_id", "event_type", "timestamp", "signal_weight",
            "quality_score", "files_touched", "layers_touched", "consolidated",
        }
        safe_cols = [c for c in columns if c in allowed]
        if not safe_cols:
            return []
        col_str = ", ".join(safe_cols)
        rows = self._query(
            f"SELECT {col_str} FROM episodes ORDER BY timestamp DESC LIMIT %s",
            (limit,),
        )
        results = []
        for row in rows:
            d = dict(row)
            if "files_touched" in d and isinstance(d["files_touched"], str):
                import json as _json
                try:
                    d["files_touched"] = _json.loads(d["files_touched"])
                except (ValueError, TypeError):
                    d["files_touched"] = []
            results.append(d)
        return results

    def count_episodes(self, consolidated: Optional[int] = None) -> int:
        if consolidated is not None:
            row = self._query_one(
                "SELECT COUNT(*) AS cnt FROM episodes WHERE consolidated = %s", (consolidated,)
            )
        else:
            row = self._query_one("SELECT COUNT(*) AS cnt FROM episodes")
        return row["cnt"] if row else 0

    def mark_episodes_consolidated(self, episode_ids: list[str], timestamp: str) -> None:
        if not episode_ids:
            return
        self._execute(
            "UPDATE episodes SET consolidated = 1, consolidated_at = %s WHERE id = ANY(%s)",
            (timestamp, episode_ids),
        )

    def mark_episodes_decayed(self, episode_ids: list[str]) -> None:
        if not episode_ids:
            return
        self._execute(
            "UPDATE episodes SET consolidated = 2 WHERE id = ANY(%s)",
            (episode_ids,),
        )

    def list_episodes_by_domain(
        self,
        domain: str,
        consolidated: Optional[int] = None,
        limit: int = 100,
    ) -> list[Episode]:
        """Retrieve episodes tagged with a specific domain (cross-project)."""
        clauses = ["ed.domain = %s"]
        params: list[Any] = [domain]
        if consolidated is not None:
            clauses.append("e.consolidated = %s")
            params.append(consolidated)
        where = " AND ".join(clauses)
        params.append(limit)
        rows = self._query(
            f"""SELECT e.* FROM episodes e
                JOIN episode_domains ed ON e.id = ed.episode_id
                WHERE {where}
                ORDER BY e.timestamp DESC LIMIT %s""",
            tuple(params),
        )
        return [self._row_to_episode(r) for r in rows]

    def count_episodes_by_domain(self, domain: str, consolidated: Optional[int] = None) -> int:
        """Count episodes in a domain."""
        if consolidated is not None:
            row = self._query_one(
                """SELECT COUNT(*) as cnt FROM episode_domains ed
                   JOIN episodes e ON e.id = ed.episode_id
                   WHERE ed.domain = %s AND e.consolidated = %s""",
                (domain, consolidated),
            )
        else:
            row = self._query_one(
                "SELECT COUNT(*) as cnt FROM episode_domains WHERE domain = %s", (domain,)
            )
        return row["cnt"] if row else 0

    def list_active_domains(self, min_episodes: int = 3) -> list[tuple[str, int]]:
        """List domains with at least min_episodes episodes, sorted by count."""
        rows = self._query(
            """SELECT domain, COUNT(*) as cnt FROM episode_domains
               GROUP BY domain HAVING COUNT(*) >= %s
               ORDER BY cnt DESC""",
            (min_episodes,),
        )
        return [(r["domain"], r["cnt"]) for r in rows]

    # --- Cognitive Replays ---

    def save_replay(self, replay: CognitiveReplay) -> CognitiveReplay:
        """Persist a cognitive replay skeleton."""
        self._execute(
            """INSERT INTO cognitive_replays
               (id, session_id, strategy_type, problem_signature, steps,
                shortcut, domains, files_involved, source_episode_ids,
                created_at, times_surfaced, times_helpful, confidence)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET
                steps = EXCLUDED.steps,
                shortcut = EXCLUDED.shortcut,
                times_surfaced = EXCLUDED.times_surfaced,
                times_helpful = EXCLUDED.times_helpful,
                confidence = EXCLUDED.confidence""",
            (
                replay.id,
                replay.session_id,
                replay.strategy_type,
                replay.problem_signature,
                self._to_json([s.to_dict() for s in replay.steps]),
                replay.shortcut,
                self._to_json(replay.domains),
                self._to_json(replay.files_involved),
                self._to_json(replay.source_episode_ids),
                replay.created_at,
                replay.times_surfaced,
                replay.times_helpful,
                replay.confidence,
            ),
        )
        return replay

    def get_replay(self, replay_id: str) -> Optional[CognitiveReplay]:
        """Retrieve a replay by ID."""
        row = self._query_one(
            "SELECT * FROM cognitive_replays WHERE id = %s", (replay_id,)
        )
        if not row:
            return None
        return self._row_to_replay(row)

    def list_replays(self, limit: int = 50) -> list[CognitiveReplay]:
        """List replays ordered by confidence (highest first)."""
        rows = self._query(
            "SELECT * FROM cognitive_replays ORDER BY confidence DESC, created_at DESC LIMIT %s",
            (limit,),
        )
        return [self._row_to_replay(r) for r in rows]

    def increment_replay_surfaced(self, replay_id: str) -> None:
        """Increment times_surfaced counter."""
        self._execute(
            "UPDATE cognitive_replays SET times_surfaced = times_surfaced + 1 WHERE id = %s",
            (replay_id,),
        )

    def mark_replay_helpful(self, replay_id: str) -> None:
        """Mark a replay as helpful (boosts confidence)."""
        self._execute(
            """UPDATE cognitive_replays
               SET times_helpful = times_helpful + 1,
                   confidence = LEAST(1.0, confidence + 0.1)
               WHERE id = %s""",
            (replay_id,),
        )

    def count_replays(self) -> int:
        """Count total replays."""
        row = self._query_one("SELECT COUNT(*) as cnt FROM cognitive_replays")
        return row["cnt"] if row else 0

    def _row_to_replay(self, row: dict[str, Any]) -> CognitiveReplay:
        from neurosync.replay import CognitiveReplay, ReplayStep

        steps_raw = self._from_json(row["steps"], [])
        return CognitiveReplay(
            id=row["id"],
            session_id=row["session_id"],
            strategy_type=row["strategy_type"],
            problem_signature=row["problem_signature"],
            steps=[ReplayStep.from_dict(s) for s in steps_raw],
            shortcut=row["shortcut"] or "",
            domains=self._from_json(row["domains"], []),
            files_involved=self._from_json(row["files_involved"], []),
            source_episode_ids=self._from_json(row["source_episode_ids"], []),
            created_at=row["created_at"],
            times_surfaced=row["times_surfaced"],
            times_helpful=row["times_helpful"],
            confidence=row["confidence"],
        )

    def _row_to_episode(self, row: dict[str, Any]) -> Episode:
        return Episode(
            id=row["id"],
            session_id=row["session_id"],
            timestamp=row["timestamp"],
            event_type=row["event_type"],
            content=row["content"],
            context=row["context"] or "",
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
            domains=self._from_json(row.get("domains"), []),
        )

    # --- Signals ---

    def save_signal(self, signal: Signal) -> Signal:
        result = self._execute(
            """INSERT INTO signals (episode_id, signal_type, raw_value, multiplier, timestamp)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (
                signal.episode_id,
                signal.signal_type,
                signal.raw_value,
                signal.multiplier,
                signal.timestamp,
            ),
            returning=True,
        )
        if result:
            signal.id = result[0]
        return signal

    def get_signals_for_episode(self, episode_id: str) -> list[Signal]:
        rows = self._query("SELECT * FROM signals WHERE episode_id = %s", (episode_id,))
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
        self._execute(
            """INSERT INTO theories
               (id, content, scope, scope_qualifier, confidence, confirmation_count,
                contradiction_count, first_observed, last_confirmed, source_episodes,
                superseded_by, active, description_length, parent_theory_id,
                related_theories, last_applied, application_count, validation_status,
                metadata, hierarchy_depth, structural_fingerprint)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
               content=EXCLUDED.content, confidence=EXCLUDED.confidence,
               confirmation_count=EXCLUDED.confirmation_count,
               contradiction_count=EXCLUDED.contradiction_count,
               last_confirmed=EXCLUDED.last_confirmed,
               source_episodes=EXCLUDED.source_episodes,
               superseded_by=EXCLUDED.superseded_by, active=EXCLUDED.active,
               description_length=EXCLUDED.description_length,
               parent_theory_id=EXCLUDED.parent_theory_id,
               related_theories=EXCLUDED.related_theories,
               last_applied=EXCLUDED.last_applied,
               application_count=EXCLUDED.application_count,
               validation_status=EXCLUDED.validation_status,
               metadata=EXCLUDED.metadata,
               hierarchy_depth=EXCLUDED.hierarchy_depth,
               structural_fingerprint=EXCLUDED.structural_fingerprint""",
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
                theory.active,
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
        return theory

    def get_theory(self, theory_id: str) -> Optional[Theory]:
        row = self._query_one("SELECT * FROM theories WHERE id = %s", (theory_id,))
        return self._row_to_theory(row) if row else None

    def list_theories(
        self,
        active_only: bool = True,
        scope: Optional[str] = None,
        project: Optional[str] = None,
        limit: int = 50,
    ) -> list[Theory]:
        clauses = []
        params: list[Any] = []
        if active_only:
            clauses.append("active = TRUE")
        if scope:
            clauses.append("scope = %s")
            params.append(scope)
        if project:
            clauses.append("scope_qualifier = %s")
            params.append(project)
        where = " AND ".join(clauses) if clauses else "TRUE"
        params.append(limit)
        rows = self._query(
            f"SELECT * FROM theories WHERE {where} ORDER BY confidence DESC LIMIT %s",
            params,
        )
        return [self._row_to_theory(r) for r in rows]

    def count_theories(self, active_only: bool = True) -> int:
        if active_only:
            row = self._query_one("SELECT COUNT(*) AS cnt FROM theories WHERE active = TRUE")
        else:
            row = self._query_one("SELECT COUNT(*) AS cnt FROM theories")
        return row["cnt"] if row else 0

    def _row_to_theory(self, row: dict[str, Any]) -> Theory:
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
        result = self._execute(
            """INSERT INTO contradictions
               (theory_id, episode_id, description, resolution, resolved_at, created_at)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (
                contradiction.theory_id,
                contradiction.episode_id,
                contradiction.description,
                contradiction.resolution,
                contradiction.resolved_at,
                contradiction.created_at,
            ),
            returning=True,
        )
        if result:
            contradiction.id = result[0]
        return contradiction

    def list_contradictions(
        self,
        theory_id: Optional[str] = None,
        unresolved_only: bool = False,
        limit: int = 50,
    ) -> list[Contradiction]:
        clauses = []
        params: list[Any] = []
        if theory_id:
            clauses.append("theory_id = %s")
            params.append(theory_id)
        if unresolved_only:
            clauses.append("resolved_at IS NULL")
        where = " AND ".join(clauses) if clauses else "TRUE"
        params.append(limit)
        rows = self._query(
            f"SELECT * FROM contradictions WHERE {where} ORDER BY created_at DESC LIMIT %s",
            params,
        )
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
        if unresolved_only:
            row = self._query_one(
                "SELECT COUNT(*) AS cnt FROM contradictions WHERE resolved_at IS NULL"
            )
        else:
            row = self._query_one("SELECT COUNT(*) AS cnt FROM contradictions")
        return row["cnt"] if row else 0

    # --- User Model ---

    def save_user_knowledge(self, uk: UserKnowledge) -> UserKnowledge:
        if uk.id is not None:
            self._execute(
                """UPDATE user_model SET topic=%s, project=%s, familiarity=%s,
                   last_seen=%s, times_seen=%s, times_explained=%s, metadata=%s
                   WHERE id=%s""",
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
            result = self._execute(
                """INSERT INTO user_model
                   (topic, project, familiarity, last_seen, times_seen, times_explained, metadata)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (
                    uk.topic,
                    uk.project,
                    uk.familiarity,
                    uk.last_seen,
                    uk.times_seen,
                    uk.times_explained,
                    self._to_json(uk.metadata),
                ),
                returning=True,
            )
            if result:
                uk.id = result[0]
        return uk

    def get_user_knowledge(self, topic: str, project: str = "") -> Optional[UserKnowledge]:
        row = self._query_one(
            "SELECT * FROM user_model WHERE topic = %s AND project = %s",
            (topic, project),
        )
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
        if project:
            rows = self._query(
                "SELECT * FROM user_model WHERE project = %s ORDER BY familiarity DESC",
                (project,),
            )
        else:
            rows = self._query("SELECT * FROM user_model ORDER BY familiarity DESC")
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

    # --- Episode helpers ---

    def update_episode_access(
        self, episode_id: str, reinforcement_count: int, last_accessed: str
    ) -> None:
        self._execute(
            "UPDATE episodes SET reinforcement_count = %s, last_accessed = %s WHERE id = %s",
            (reinforcement_count, last_accessed, episode_id),
        )

    def list_episodes_for_pruning(
        self,
        min_age_days: int = 30,
        consolidated: int = 1,
        limit: int = 500,
    ) -> list[Episode]:
        rows = self._query(
            """SELECT * FROM episodes
               WHERE consolidated = %s
               AND timestamp::timestamptz < NOW() - make_interval(days => %s)
               ORDER BY timestamp ASC LIMIT %s""",
            (consolidated, min_age_days, limit),
        )
        return [self._row_to_episode(r) for r in rows]

    # --- Theory helpers ---

    def list_children_of_theory(self, parent_id: str) -> list[Theory]:
        rows = self._query(
            "SELECT * FROM theories WHERE parent_theory_id = %s AND active = TRUE",
            (parent_id,),
        )
        return [self._row_to_theory(r) for r in rows]

    # --- Theory Versioning ---

    def save_theory_version(self, theory: Theory, action: str = "") -> int:
        """Snapshot current theory state before mutation. Returns version number."""
        row = self._query_one(
            "SELECT COALESCE(MAX(version_number), 0) AS max_v FROM theory_versions WHERE theory_id = %s",
            (theory.id,),
        )
        next_version = (row["max_v"] if row else 0) + 1
        self._execute(
            """INSERT INTO theory_versions
               (theory_id, version_number, content, confidence,
                confirmation_count, contradiction_count, validation_status,
                scope, scope_qualifier, active, source_episodes, created_at, action)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                theory.id,
                next_version,
                theory.content,
                theory.confidence,
                theory.confirmation_count,
                theory.contradiction_count,
                theory.validation_status,
                theory.scope,
                theory.scope_qualifier,
                theory.active,
                self._to_json(theory.source_episodes),
                _utcnow(),
                action,
            ),
        )
        return next_version

    def get_theory_versions(self, theory_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Get version history for a theory, most recent first."""
        rows = self._query(
            """SELECT * FROM theory_versions
               WHERE theory_id = %s
               ORDER BY version_number DESC LIMIT %s""",
            (theory_id, limit),
        )
        return [
            {
                "version_number": r["version_number"],
                "content": r["content"],
                "confidence": r["confidence"],
                "confirmation_count": r["confirmation_count"],
                "contradiction_count": r["contradiction_count"],
                "validation_status": r["validation_status"],
                "scope": r["scope"],
                "scope_qualifier": r["scope_qualifier"],
                "active": bool(r["active"]),
                "source_episodes": self._from_json(r["source_episodes"], []),
                "created_at": r["created_at"],
                "action": r["action"],
            }
            for r in rows
        ]

    def rollback_theory(self, theory_id: str, version_number: int) -> Optional[Theory]:
        """Restore a theory to a previous version. Snapshots current state first."""
        theory = self.get_theory(theory_id)
        if not theory:
            return None
        row = self._query_one(
            "SELECT * FROM theory_versions WHERE theory_id = %s AND version_number = %s",
            (theory_id, version_number),
        )
        if not row:
            return None
        self.save_theory_version(theory, action="pre-rollback")
        theory.content = row["content"]
        theory.confidence = row["confidence"]
        theory.confirmation_count = row["confirmation_count"]
        theory.contradiction_count = row["contradiction_count"]
        theory.validation_status = row["validation_status"]
        theory.scope = row["scope"]
        theory.scope_qualifier = row["scope_qualifier"]
        theory.active = bool(row["active"])
        theory.source_episodes = self._from_json(row["source_episodes"], [])
        self.save_theory(theory)
        return theory

    # --- Causal Links ---

    def save_causal_link(self, link: CausalLink) -> CausalLink:
        norm_cause = self._normalize_text(link.cause_text)
        norm_effect = self._normalize_text(link.effect_text)
        if link.id is not None:
            self._execute(
                """UPDATE causal_links SET cause_text=%s, effect_text=%s, mechanism=%s,
                   mechanism_detail=%s, confidence_level=%s, strength=%s,
                   observation_count=%s, source_episode_ids=%s, source_theory_id=%s,
                   project=%s, updated_at=%s,
                   cause_text_normalized=%s, effect_text_normalized=%s
                   WHERE id=%s""",
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
            result = self._execute(
                """INSERT INTO causal_links
                   (cause_text, effect_text, mechanism, mechanism_detail,
                    confidence_level, strength, observation_count,
                    source_episode_ids, source_theory_id, project,
                    created_at, updated_at,
                    cause_text_normalized, effect_text_normalized)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
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
                returning=True,
            )
            if result:
                link.id = result[0]
        return link

    def get_causal_link(self, link_id: int) -> Optional[CausalLink]:
        row = self._query_one("SELECT * FROM causal_links WHERE id = %s", (link_id,))
        return self._row_to_causal_link(row) if row else None

    def list_causal_links(
        self,
        cause_text: Optional[str] = None,
        effect_text: Optional[str] = None,
        project: Optional[str] = None,
        limit: int = 100,
    ) -> list[CausalLink]:
        clauses: list[str] = []
        params: list[Any] = []
        if cause_text is not None:
            clauses.append("cause_text = %s")
            params.append(cause_text)
        if effect_text is not None:
            clauses.append("effect_text = %s")
            params.append(effect_text)
        if project is not None:
            clauses.append("project = %s")
            params.append(project)
        where = " AND ".join(clauses) if clauses else "TRUE"
        params.append(limit)
        rows = self._query(
            f"SELECT * FROM causal_links WHERE {where} ORDER BY observation_count DESC LIMIT %s",
            params,
        )
        return [self._row_to_causal_link(r) for r in rows]

    def find_causal_links_by_text(self, text: str, role: str = "cause") -> list[CausalLink]:
        column = "cause_text" if role == "cause" else "effect_text"
        rows = self._query(
            f"SELECT * FROM causal_links WHERE {column} ILIKE %s ORDER BY observation_count DESC",
            (f"%{text}%",),
        )
        return [self._row_to_causal_link(r) for r in rows]

    def increment_causal_observation(self, link_id: int) -> None:
        self._execute(
            "UPDATE causal_links SET observation_count = observation_count + 1, updated_at = %s WHERE id = %s",
            (_utcnow(), link_id),
        )

    def count_causal_links(self) -> int:
        row = self._query_one("SELECT COUNT(*) AS cnt FROM causal_links")
        return row["cnt"] if row else 0

    def list_causal_links_normalized(
        self,
        cause_text: str,
        effect_text: str,
        limit: int = 5,
    ) -> list[CausalLink]:
        norm_cause = self._normalize_text(cause_text)
        norm_effect = self._normalize_text(effect_text)
        rows = self._query(
            """SELECT * FROM causal_links
               WHERE cause_text_normalized = %s AND effect_text_normalized = %s
               ORDER BY observation_count DESC LIMIT %s""",
            (norm_cause, norm_effect, limit),
        )
        return [self._row_to_causal_link(r) for r in rows]

    def _row_to_causal_link(self, row: dict[str, Any]) -> CausalLink:
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

    # --- Junction tables ---

    def add_theory_episode(self, theory_id: str, episode_id: str) -> None:
        self._execute(
            "INSERT INTO theory_episodes (theory_id, episode_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (theory_id, episode_id),
        )

    def get_theory_episode_ids(self, theory_id: str) -> list[str]:
        rows = self._query(
            "SELECT episode_id FROM theory_episodes WHERE theory_id = %s", (theory_id,)
        )
        return [r["episode_id"] for r in rows]

    def get_theories_for_episode(self, episode_id: str) -> list[str]:
        rows = self._query(
            "SELECT theory_id FROM theory_episodes WHERE episode_id = %s", (episode_id,)
        )
        return [r["theory_id"] for r in rows]

    def add_theory_relation(self, theory_id: str, related_id: str) -> None:
        self._execute(
            "INSERT INTO theory_relations (theory_id, related_theory_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (theory_id, related_id),
        )

    def get_related_theory_ids(self, theory_id: str) -> list[str]:
        rows = self._query(
            "SELECT related_theory_id FROM theory_relations WHERE theory_id = %s", (theory_id,)
        )
        return [r["related_theory_id"] for r in rows]

    def add_causal_link_episode(self, link_id: int, episode_id: str) -> None:
        self._execute(
            "INSERT INTO causal_link_episodes (causal_link_id, episode_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (link_id, episode_id),
        )

    def get_causal_link_episode_ids(self, link_id: int) -> list[str]:
        rows = self._query(
            "SELECT episode_id FROM causal_link_episodes WHERE causal_link_id = %s", (link_id,)
        )
        return [r["episode_id"] for r in rows]

    def set_entity_fingerprints(
        self, entity_id: str, entity_type: str, patterns: list[str]
    ) -> None:
        def _do_set() -> None:
            conn = self._get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM entity_fingerprints WHERE entity_id = %s AND entity_type = %s",
                        (entity_id, entity_type),
                    )
                    for pattern in patterns:
                        if pattern:
                            cur.execute(
                                "INSERT INTO entity_fingerprints (entity_id, entity_type, pattern) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                                (entity_id, entity_type, pattern),
                            )
                    conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                self._put_conn(conn)

        self._with_retry(_do_set)

    def get_entity_fingerprints(self, entity_id: str, entity_type: str) -> list[str]:
        rows = self._query(
            "SELECT pattern FROM entity_fingerprints WHERE entity_id = %s AND entity_type = %s",
            (entity_id, entity_type),
        )
        return [r["pattern"] for r in rows]

    def find_entities_by_fingerprint(
        self, pattern: str, entity_type: Optional[str] = None
    ) -> list[dict[str, str]]:
        if entity_type:
            rows = self._query(
                "SELECT entity_id, entity_type FROM entity_fingerprints WHERE pattern = %s AND entity_type = %s",
                (pattern, entity_type),
            )
        else:
            rows = self._query(
                "SELECT entity_id, entity_type FROM entity_fingerprints WHERE pattern = %s",
                (pattern,),
            )
        return [{"entity_id": r["entity_id"], "entity_type": r["entity_type"]} for r in rows]

    # --- Bulk-read helpers for graph sync ---

    def list_all_entity_fingerprints(self) -> list[dict[str, str]]:
        rows = self._query("SELECT entity_id, entity_type, pattern FROM entity_fingerprints")
        return [
            {"entity_id": r["entity_id"], "entity_type": r["entity_type"], "pattern": r["pattern"]}
            for r in rows
        ]

    def list_all_theory_episodes(self) -> list[dict[str, str]]:
        rows = self._query("SELECT theory_id, episode_id FROM theory_episodes")
        return [{"theory_id": r["theory_id"], "episode_id": r["episode_id"]} for r in rows]

    def list_all_theory_relations(self) -> list[dict[str, str]]:
        rows = self._query("SELECT theory_id, related_theory_id FROM theory_relations")
        return [
            {"theory_id": r["theory_id"], "related_theory_id": r["related_theory_id"]} for r in rows
        ]

    def list_all_causal_link_episodes(self) -> list[dict[str, Any]]:
        rows = self._query("SELECT causal_link_id, episode_id FROM causal_link_episodes")
        return [
            {"causal_link_id": r["causal_link_id"], "episode_id": r["episode_id"]} for r in rows
        ]

    # --- Failure Records ---

    def save_failure_record(self, record: FailureRecord) -> FailureRecord:
        if record.id is not None:
            self._execute(
                """UPDATE failure_records SET what_failed=%s, why_failed=%s,
                   what_worked=%s, category=%s, project=%s, context=%s,
                   source_episode_id=%s, severity=%s, occurrence_count=%s,
                   last_seen=%s WHERE id=%s""",
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
            result = self._execute(
                """INSERT INTO failure_records
                   (what_failed, why_failed, what_worked, category, project,
                    context, source_episode_id, severity, occurrence_count,
                    created_at, last_seen)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
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
                returning=True,
            )
            if result:
                record.id = result[0]
        return record

    def get_failure_record(self, record_id: int) -> Optional[FailureRecord]:
        row = self._query_one("SELECT * FROM failure_records WHERE id = %s", (record_id,))
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
        clauses = ["severity >= %s"]
        params: list[Any] = [min_severity]
        if project is not None:
            clauses.append("project = %s")
            params.append(project)
        if category is not None:
            clauses.append("category = %s")
            params.append(category)
        where = " AND ".join(clauses)
        params.append(limit)
        rows = self._query(
            f"SELECT * FROM failure_records WHERE {where} ORDER BY occurrence_count DESC LIMIT %s",
            params,
        )
        return [self._row_to_failure_record(r) for r in rows]

    def increment_failure_occurrence(self, record_id: int) -> None:
        self._execute(
            "UPDATE failure_records SET occurrence_count = occurrence_count + 1, last_seen = %s WHERE id = %s",
            (_utcnow(), record_id),
        )

    def count_failure_records(self) -> int:
        row = self._query_one("SELECT COUNT(*) AS cnt FROM failure_records")
        return row["cnt"] if row else 0

    def _row_to_failure_record(self, row: dict[str, Any]) -> FailureRecord:
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

    # --- Audit Log ---

    def audit(
        self,
        entity_type: str,
        entity_id: str,
        action: str,
        field_name: str = "",
        old_value: str = "",
        new_value: str = "",
        context: str = "",
    ) -> None:
        """Record an audit trail entry for entity changes."""
        self._execute(
            """INSERT INTO audit_log
               (timestamp, entity_type, entity_id, action,
                field_name, old_value, new_value, context)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                _utcnow(),
                entity_type,
                entity_id,
                action,
                field_name,
                old_value,
                new_value,
                context,
            ),
        )

    def get_audit_log(
        self,
        entity_type: str = "",
        entity_id: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Retrieve audit log entries."""
        clauses: list[str] = []
        params: list[Any] = []
        if entity_type:
            clauses.append("entity_type = %s")
            params.append(entity_type)
        if entity_id:
            clauses.append("entity_id = %s")
            params.append(entity_id)
        where = " AND ".join(clauses) if clauses else "TRUE"
        params.append(limit)
        return self._query(
            f"SELECT * FROM audit_log WHERE {where}"
            " ORDER BY timestamp DESC LIMIT %s",
            params,
        )

    # --- Schema Downgrade ---

    def _rollback_migrations(
        self, cur: Any, from_version: int, to_version: int
    ) -> None:
        """Run schema rollbacks from from_version down to to_version (exclusive).

        Supports v7->v6 and v6->v5.
        """
        if from_version >= 7 and to_version < 7:
            cur.execute("DROP INDEX IF EXISTS idx_tv_version")
            cur.execute("DROP INDEX IF EXISTS idx_tv_theory")
            cur.execute("DROP TABLE IF EXISTS theory_versions")

        if from_version >= 6 and to_version < 6:
            cur.execute("DROP INDEX IF EXISTS idx_audit_timestamp")
            cur.execute("DROP INDEX IF EXISTS idx_audit_entity")
            cur.execute("DROP TABLE IF EXISTS audit_log")

        cur.execute("UPDATE schema_version SET version = %s", (to_version,))

    def downgrade(self, target_version: int) -> None:
        """Downgrade the schema to target_version.

        Validates the version range and runs rollbacks in reverse order.
        Only supports downgrade to version 5 currently.
        """
        if target_version < 5:
            raise ValueError(
                f"Cannot downgrade below version 5. Requested: {target_version}"
            )
        if target_version >= CURRENT_SCHEMA_VERSION:
            raise ValueError(
                f"Target version {target_version} is not below current version"
                f" {CURRENT_SCHEMA_VERSION}"
            )

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT version FROM schema_version")
                row = cur.fetchone()
                current = row[0] if row else CURRENT_SCHEMA_VERSION

                if target_version >= current:
                    raise ValueError(
                        f"Target version {target_version} is not below current"
                        f" schema version {current}"
                    )

                self._rollback_migrations(cur, current, target_version)
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._put_conn(conn)

    # --- Orphan Session Detection ---

    def close_orphaned_sessions(self, max_age_hours: int = 24) -> list[str]:
        """Find and close sessions with ended_at=NULL older than max_age_hours."""
        rows = self._query(
            """SELECT id FROM sessions
               WHERE ended_at IS NULL
               AND started_at::timestamptz < NOW() - make_interval(hours => %s)""",
            (max_age_hours,),
        )
        orphan_ids = [r["id"] for r in rows]
        if orphan_ids:
            now = _utcnow()
            self._execute(
                """UPDATE sessions
                   SET ended_at = %s, summary = '[auto-closed: orphaned session]'
                   WHERE id = ANY(%s)""",
                (now, orphan_ids),
            )
        return orphan_ids

    # --- Intelligence Layer ---

    def upsert_insight(self, insight: Any) -> None:
        """Insert or update an insight."""
        self._execute(
            """INSERT INTO insights
               (id, insight_type, category, content, evidence, confidence,
                staleness_days, project, created_at, updated_at, expires_at,
                surfaced_count, dismissed, metadata)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT(id) DO UPDATE SET
                content = EXCLUDED.content,
                confidence = EXCLUDED.confidence,
                updated_at = EXCLUDED.updated_at,
                evidence = EXCLUDED.evidence,
                metadata = EXCLUDED.metadata,
                staleness_days = EXCLUDED.staleness_days""",
            (
                insight.id,
                insight.insight_type,
                insight.category,
                insight.content,
                self._to_json(insight.evidence),
                insight.confidence,
                insight.staleness_days,
                insight.project,
                insight.created_at,
                insight.updated_at,
                insight.expires_at or None,
                insight.surfaced_count,
                insight.dismissed,
                self._to_json(insight.metadata),
            ),
        )

    def list_insights(
        self,
        min_confidence: float = 0.0,
        dismissed: bool = False,
        insight_type: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List insights matching criteria."""
        clauses = ["confidence >= %s"]
        params: list[Any] = [min_confidence]
        if not dismissed:
            clauses.append("dismissed = FALSE")
        if insight_type:
            clauses.append("insight_type = %s")
            params.append(insight_type)
        where = " AND ".join(clauses)
        params.append(limit)
        rows = self._query(
            f"SELECT * FROM insights WHERE {where} ORDER BY confidence DESC LIMIT %s",
            tuple(params),
        )
        return [dict(r) for r in rows]

    def delete_expired_insights(self) -> int:
        """Delete insights whose expires_at has passed. Returns count deleted."""
        now = _utcnow()
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "DELETE FROM insights WHERE expires_at IS NOT NULL AND expires_at < %s",
                (now,),
            )
            count = cur.rowcount
            conn.commit()
            return count
        finally:
            cur.close()

    def increment_insight_surfaced(self, insight_id: str) -> None:
        self._execute(
            "UPDATE insights SET surfaced_count = surfaced_count + 1 WHERE id = %s",
            (insight_id,),
        )

    def dismiss_insight(self, insight_id: str) -> None:
        self._execute(
            "UPDATE insights SET dismissed = TRUE WHERE id = %s",
            (insight_id,),
        )

    def count_insights(self) -> int:
        row = self._query_one("SELECT COUNT(*) AS cnt FROM insights WHERE dismissed = FALSE")
        return row["cnt"] if row else 0

    def upsert_developer_profile(
        self,
        key: str,
        value: Any,
        observation_count: int = 0,
        confidence: float = 0.5,
    ) -> None:
        import json as _json

        self._execute(
            """INSERT INTO developer_profile
               (profile_key, profile_value, computed_at, observation_count, confidence)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT(profile_key) DO UPDATE SET
                profile_value = EXCLUDED.profile_value,
                computed_at = EXCLUDED.computed_at,
                observation_count = EXCLUDED.observation_count,
                confidence = EXCLUDED.confidence""",
            (key, _json.dumps(value), _utcnow(), observation_count, confidence),
        )

    def list_developer_profile(self) -> list[dict[str, Any]]:
        import json as _json

        rows = self._query(
            "SELECT * FROM developer_profile ORDER BY profile_key"
        )
        results = []
        for row in rows:
            d = dict(row)
            try:
                d["profile_value"] = _json.loads(d.get("profile_value", "null"))
            except (TypeError, ValueError):
                pass
            results.append(d)
        return results

    # --- Stats ---

    def stats(self) -> dict[str, Any]:
        return {
            "sessions": self._query_one("SELECT COUNT(*) AS cnt FROM sessions")["cnt"],
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
            "backend": "postgresql",
        }
