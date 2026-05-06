"""Integration tests for PostgreSQL backend (neurosync/pg_db.py).

These tests require a real PostgreSQL instance. They are automatically skipped
when the database is not available.

Configuration:
  - Set NEUROSYNC_PG_TEST_DSN env var to point to a test database, e.g.:
      export NEUROSYNC_PG_TEST_DSN=postgresql://localhost:5432/neurosync_test
  - Or the tests will attempt to connect to the default:
      postgresql://localhost:5432/neurosync_test

IMPORTANT: These tests TRUNCATE all tables between runs. Only run against a
dedicated test database.
"""

from __future__ import annotations

import os

import pytest

# Determine if PostgreSQL is available.
# Use a dedicated test DSN (NEUROSYNC_PG_TEST_DSN) to avoid touching the
# production database. Falls back to a local neurosync_test database.
_PG_TEST_DSN = os.environ.get(
    "NEUROSYNC_PG_TEST_DSN", "postgresql://localhost:5432/neurosync_test"
)


def _pg_is_available() -> bool:
    """Check if we can connect to the PostgreSQL test database."""
    try:
        import psycopg2

        conn = psycopg2.connect(_PG_TEST_DSN, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


# Skip all tests in this module if PG is not available
pytestmark = pytest.mark.skipif(
    not _pg_is_available(),
    reason="PostgreSQL not available (set NEUROSYNC_PG_TEST_DSN or run a local instance)",
)


# --- All tables that need to be truncated between tests ---
_ALL_TABLES = [
    "audit_log",
    "causal_link_episodes",
    "entity_fingerprints",
    "theory_relations",
    "theory_episodes",
    "failure_records",
    "causal_links",
    "contradictions",
    "signals",
    "episodes",
    "theories",
    "user_model",
    "sessions",
    "schema_version",
]


def _truncate_all_tables(database) -> None:
    """Truncate all known tables, skipping any that don't exist."""
    data_tables = [t for t in _ALL_TABLES if t != "schema_version"]
    conn = database._get_conn()
    try:
        with conn.cursor() as cur:
            # Build a single TRUNCATE for all existing tables
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename = ANY(%s)",
                (data_tables,),
            )
            existing = [row[0] for row in cur.fetchall()]
            if existing:
                cur.execute(f"TRUNCATE TABLE {', '.join(existing)} CASCADE")
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        database._put_conn(conn)


@pytest.fixture
def pg_config():
    """Create a NeuroSyncConfig pointing to the PG test database."""
    from neurosync.config import NeuroSyncConfig

    return NeuroSyncConfig(
        db_backend="postgresql",
        pg_dsn=_PG_TEST_DSN,
    )


@pytest.fixture
def pg_db(pg_config):
    """Create a PostgresDatabase instance with clean tables for each test."""
    from neurosync.pg_db import PostgresDatabase

    database = PostgresDatabase(pg_config)

    # Truncate all data tables BEFORE the test to ensure a clean slate.
    _truncate_all_tables(database)

    yield database

    # Truncate after the test as well for good hygiene
    _truncate_all_tables(database)

    database.close()


# =============================================================================
# Schema and Migration Tests
# =============================================================================


class TestSchemaAndMigration:
    """Tests for schema initialization and migration."""

    def test_schema_initialized_at_current_version(self, pg_db):
        """After init, schema_version should be at CURRENT_SCHEMA_VERSION."""
        from neurosync.pg_db import CURRENT_SCHEMA_VERSION

        stats = pg_db.stats()
        assert stats["schema_version"] == CURRENT_SCHEMA_VERSION
        assert stats["backend"] == "postgresql"

    def test_audit_log_table_exists_after_fresh_init(self, pg_db):
        """The audit_log table should exist after a fresh schema init (v6)."""
        rows = pg_db._query(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='audit_log')"
        )
        assert rows[0]["exists"] is True

    def test_all_expected_tables_exist(self, pg_db):
        """All schema tables should be present after initialization."""
        expected_tables = {
            "schema_version",
            "sessions",
            "episodes",
            "signals",
            "theories",
            "contradictions",
            "user_model",
            "causal_links",
            "failure_records",
            "theory_episodes",
            "theory_relations",
            "causal_link_episodes",
            "entity_fingerprints",
            "audit_log",
        }
        for table in expected_tables:
            rows = pg_db._query(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=%s)",
                (table,),
            )
            assert rows[0]["exists"] is True, f"Table '{table}' should exist"

    def test_audit_log_table_writable(self, pg_db):
        """Verify audit_log table can be written to and read from (schema v6)."""
        from neurosync.models import _utcnow

        timestamp = _utcnow()
        pg_db._execute(
            """INSERT INTO audit_log (timestamp, entity_type, entity_id, action, field_name, old_value, new_value, context)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (timestamp, "theory", "th-123", "confidence_update", "confidence", "0.5", "0.7", "test"),
        )

        rows = pg_db._query(
            "SELECT * FROM audit_log WHERE entity_id = %s", ("th-123",)
        )
        assert len(rows) == 1
        assert rows[0]["action"] == "confidence_update"
        assert rows[0]["old_value"] == "0.5"
        assert rows[0]["new_value"] == "0.7"

    def test_reinit_is_idempotent(self, pg_config):
        """Calling init twice should not fail or corrupt schema."""
        from neurosync.pg_db import PostgresDatabase

        db1 = PostgresDatabase(pg_config)
        stats1 = db1.stats()
        db1.close()

        db2 = PostgresDatabase(pg_config)
        stats2 = db2.stats()
        assert stats1["schema_version"] == stats2["schema_version"]

        # Cleanup
        _truncate_all_tables(db2)
        db2.close()


# =============================================================================
# Session CRUD Tests
# =============================================================================


class TestSessionCRUD:
    """Tests for session create, read, list operations."""

    def test_save_and_get_session(self, pg_db):
        from neurosync.models import Session

        session = Session(project="test-project", branch="main")
        pg_db.save_session(session)

        loaded = pg_db.get_session(session.id)
        assert loaded is not None
        assert loaded.project == "test-project"
        assert loaded.branch == "main"
        assert loaded.id == session.id

    def test_get_nonexistent_session_returns_none(self, pg_db):
        result = pg_db.get_session("nonexistent-id")
        assert result is None

    def test_save_session_upsert(self, pg_db):
        from neurosync.models import Session

        session = Session(project="original")
        pg_db.save_session(session)

        session.project = "updated"
        pg_db.save_session(session)

        loaded = pg_db.get_session(session.id)
        assert loaded.project == "updated"

    def test_list_sessions(self, pg_db):
        from neurosync.models import Session

        pg_db.save_session(Session(project="proj-a"))
        pg_db.save_session(Session(project="proj-b"))
        pg_db.save_session(Session(project="proj-a"))

        all_sessions = pg_db.list_sessions()
        assert len(all_sessions) == 3

        proj_a = pg_db.list_sessions(project="proj-a")
        assert len(proj_a) == 2

    def test_list_sessions_respects_limit(self, pg_db):
        from neurosync.models import Session

        for i in range(5):
            pg_db.save_session(Session(project=f"proj-{i}"))

        limited = pg_db.list_sessions(limit=3)
        assert len(limited) == 3

    def test_session_metadata_roundtrip(self, pg_db):
        from neurosync.models import Session

        session = Session(project="meta-test", metadata={"key": "value", "nested": {"a": 1}})
        pg_db.save_session(session)

        loaded = pg_db.get_session(session.id)
        assert loaded.metadata == {"key": "value", "nested": {"a": 1}}


# =============================================================================
# Episode CRUD Tests
# =============================================================================


class TestEpisodeCRUD:
    """Tests for episode create, read, list, mark operations."""

    def test_save_and_get_episode(self, pg_db):
        from neurosync.models import Episode, Session

        session = Session(project="test")
        pg_db.save_session(session)

        episode = Episode(
            session_id=session.id,
            event_type="decision",
            content="Chose REST over GraphQL",
            files_touched=["api.py", "routes.py"],
            layers_touched=["service", "endpoint"],
        )
        pg_db.save_episode(episode)

        loaded = pg_db.get_episode(episode.id)
        assert loaded is not None
        assert loaded.content == "Chose REST over GraphQL"
        assert loaded.files_touched == ["api.py", "routes.py"]
        assert loaded.layers_touched == ["service", "endpoint"]
        assert loaded.signal_weight == 1.0

    def test_get_nonexistent_episode_returns_none(self, pg_db):
        result = pg_db.get_episode("nonexistent-id")
        assert result is None

    def test_episode_causal_fields_roundtrip(self, pg_db):
        from neurosync.models import Episode, Session

        session = Session()
        pg_db.save_session(session)

        ep = Episode(
            session_id=session.id,
            content="causal episode",
            cause="user corrected",
            effect="model updated",
            reasoning="corrections have highest weight",
            quality_score=5,
        )
        pg_db.save_episode(ep)

        loaded = pg_db.get_episode(ep.id)
        assert loaded.cause == "user corrected"
        assert loaded.effect == "model updated"
        assert loaded.reasoning == "corrections have highest weight"
        assert loaded.quality_score == 5

    def test_episode_v3_fields_roundtrip(self, pg_db):
        from neurosync.models import Episode, Session

        session = Session()
        pg_db.save_session(session)

        ep = Episode(
            session_id=session.id,
            content="test",
            reinforcement_count=5,
            last_accessed="2026-01-01T00:00:00",
            structural_fingerprint="caching,retry_logic",
        )
        pg_db.save_episode(ep)

        loaded = pg_db.get_episode(ep.id)
        assert loaded.reinforcement_count == 5
        assert loaded.last_accessed == "2026-01-01T00:00:00"
        assert loaded.structural_fingerprint == "caching,retry_logic"

    def test_list_episodes_with_filters(self, pg_db):
        from neurosync.models import Episode, Session

        session = Session()
        pg_db.save_session(session)

        pg_db.save_episode(Episode(session_id=session.id, event_type="decision", content="d1"))
        pg_db.save_episode(Episode(session_id=session.id, event_type="correction", content="c1"))
        pg_db.save_episode(
            Episode(session_id=session.id, event_type="decision", content="d2", consolidated=1)
        )

        all_eps = pg_db.list_episodes()
        assert len(all_eps) == 3

        decisions = pg_db.list_episodes(event_type="decision")
        assert len(decisions) == 2

        pending = pg_db.list_episodes(consolidated=0)
        assert len(pending) == 2

    def test_count_episodes(self, pg_db):
        from neurosync.models import Episode, Session

        session = Session()
        pg_db.save_session(session)
        pg_db.save_episode(Episode(session_id=session.id, content="a"))
        pg_db.save_episode(Episode(session_id=session.id, content="b"))

        assert pg_db.count_episodes() == 2
        assert pg_db.count_episodes(consolidated=0) == 2

    def test_mark_episodes_consolidated(self, pg_db):
        from neurosync.models import Episode, Session

        session = Session()
        pg_db.save_session(session)
        ep1 = Episode(session_id=session.id, content="a")
        ep2 = Episode(session_id=session.id, content="b")
        pg_db.save_episode(ep1)
        pg_db.save_episode(ep2)

        pg_db.mark_episodes_consolidated([ep1.id], "2024-01-01T00:00:00")

        loaded1 = pg_db.get_episode(ep1.id)
        assert loaded1.consolidated == 1
        assert loaded1.consolidated_at == "2024-01-01T00:00:00"

        loaded2 = pg_db.get_episode(ep2.id)
        assert loaded2.consolidated == 0

    def test_mark_episodes_decayed(self, pg_db):
        from neurosync.models import Episode, Session

        session = Session()
        pg_db.save_session(session)
        ep = Episode(session_id=session.id, content="decay me", consolidated=1)
        pg_db.save_episode(ep)

        pg_db.mark_episodes_decayed([ep.id])

        loaded = pg_db.get_episode(ep.id)
        assert loaded.consolidated == 2

    def test_update_episode_access(self, pg_db):
        from neurosync.models import Episode, Session

        session = Session()
        pg_db.save_session(session)
        ep = Episode(session_id=session.id, content="test")
        pg_db.save_episode(ep)

        pg_db.update_episode_access(ep.id, reinforcement_count=3, last_accessed="2026-01-01T00:00:00")

        loaded = pg_db.get_episode(ep.id)
        assert loaded.reinforcement_count == 3
        assert loaded.last_accessed == "2026-01-01T00:00:00"

    def test_save_episode_upsert_updates_fields(self, pg_db):
        from neurosync.models import Episode, Session

        session = Session()
        pg_db.save_session(session)
        ep = Episode(session_id=session.id, content="original", signal_weight=1.0)
        pg_db.save_episode(ep)

        ep.signal_weight = 5.0
        pg_db.save_episode(ep)

        loaded = pg_db.get_episode(ep.id)
        assert loaded.signal_weight == 5.0


# =============================================================================
# Signal Tests
# =============================================================================


class TestSignalCRUD:
    """Tests for signal storage and retrieval."""

    def test_save_and_get_signal(self, pg_db):
        from neurosync.models import Episode, Session, Signal

        session = Session()
        pg_db.save_session(session)
        ep = Episode(session_id=session.id, content="test")
        pg_db.save_episode(ep)

        signal = Signal(episode_id=ep.id, signal_type="CORRECTION", raw_value=2.0, multiplier=4.0)
        pg_db.save_signal(signal)

        assert signal.id is not None

        signals = pg_db.get_signals_for_episode(ep.id)
        assert len(signals) == 1
        assert signals[0].signal_type == "CORRECTION"
        assert signals[0].multiplier == 4.0
        assert signals[0].raw_value == 2.0

    def test_multiple_signals_per_episode(self, pg_db):
        from neurosync.models import Episode, Session, Signal

        session = Session()
        pg_db.save_session(session)
        ep = Episode(session_id=session.id, content="test")
        pg_db.save_episode(ep)

        pg_db.save_signal(Signal(episode_id=ep.id, signal_type="CORRECTION", multiplier=4.0))
        pg_db.save_signal(Signal(episode_id=ep.id, signal_type="EXPLICIT", multiplier=10.0))

        signals = pg_db.get_signals_for_episode(ep.id)
        assert len(signals) == 2
        types = {s.signal_type for s in signals}
        assert types == {"CORRECTION", "EXPLICIT"}


# =============================================================================
# Theory CRUD Tests
# =============================================================================


class TestTheoryCRUD:
    """Tests for theory create, read, list operations."""

    def test_save_and_get_theory(self, pg_db):
        from neurosync.models import Theory

        theory = Theory(content="Always use type hints", scope="craft", confidence=0.8)
        pg_db.save_theory(theory)

        loaded = pg_db.get_theory(theory.id)
        assert loaded is not None
        assert loaded.content == "Always use type hints"
        assert loaded.confidence == 0.8
        assert loaded.active is True

    def test_get_nonexistent_theory_returns_none(self, pg_db):
        result = pg_db.get_theory("nonexistent-id")
        assert result is None

    def test_theory_v3_fields_roundtrip(self, pg_db):
        from neurosync.models import Theory

        theory = Theory(
            content="caching pattern",
            hierarchy_depth=2,
            structural_fingerprint="caching",
            parent_theory_id="parent-123",
            related_theories=["rel-a", "rel-b"],
            application_count=3,
            validation_status="confirmed",
        )
        pg_db.save_theory(theory)

        loaded = pg_db.get_theory(theory.id)
        assert loaded.hierarchy_depth == 2
        assert loaded.structural_fingerprint == "caching"
        assert loaded.parent_theory_id == "parent-123"
        assert loaded.related_theories == ["rel-a", "rel-b"]
        assert loaded.application_count == 3
        assert loaded.validation_status == "confirmed"

    def test_list_theories_active_only(self, pg_db):
        from neurosync.models import Theory

        pg_db.save_theory(Theory(content="t1", scope="craft", active=True))
        pg_db.save_theory(Theory(content="t2", scope="project", scope_qualifier="proj-a", active=True))
        pg_db.save_theory(Theory(content="t3", scope="craft", active=False))

        active = pg_db.list_theories(active_only=True)
        assert len(active) == 2

        all_t = pg_db.list_theories(active_only=False)
        assert len(all_t) == 3

    def test_list_theories_by_scope(self, pg_db):
        from neurosync.models import Theory

        pg_db.save_theory(Theory(content="t1", scope="craft", active=True))
        pg_db.save_theory(Theory(content="t2", scope="project", active=True))
        pg_db.save_theory(Theory(content="t3", scope="domain", active=True))

        craft = pg_db.list_theories(scope="craft")
        assert len(craft) == 1

        project = pg_db.list_theories(scope="project")
        assert len(project) == 1

    def test_list_theories_with_limit(self, pg_db):
        """Test pagination via the limit parameter."""
        from neurosync.models import Theory

        # Create 5 theories with descending confidence to control ordering
        for i in range(5):
            pg_db.save_theory(
                Theory(content=f"theory-{i}", scope="craft", confidence=0.9 - (i * 0.1))
            )

        # Get all
        all_theories = pg_db.list_theories(limit=10)
        assert len(all_theories) == 5

        # Limit to 2 -- should get the top 2 by confidence
        top2 = pg_db.list_theories(limit=2)
        assert len(top2) == 2
        # Ordered by confidence DESC
        assert top2[0].confidence >= top2[1].confidence
        assert top2[0].content == "theory-0"
        assert top2[1].content == "theory-1"

    def test_list_theories_limit_with_scope_filter(self, pg_db):
        """Test limit parameter combined with scope filter."""
        from neurosync.models import Theory

        for i in range(4):
            pg_db.save_theory(
                Theory(content=f"craft-{i}", scope="craft", confidence=0.8 - (i * 0.1))
            )
        pg_db.save_theory(Theory(content="project-0", scope="project", confidence=0.9))

        # Only craft theories, limit=2
        craft_page = pg_db.list_theories(scope="craft", limit=2)
        assert len(craft_page) == 2
        # All should be craft scope
        for t in craft_page:
            assert t.scope == "craft"
        # Should be the highest confidence craft theories
        assert craft_page[0].confidence >= craft_page[1].confidence

    def test_list_theories_ordered_by_confidence_desc(self, pg_db):
        """Verify theories are returned in descending confidence order."""
        from neurosync.models import Theory

        pg_db.save_theory(Theory(content="low", confidence=0.2))
        pg_db.save_theory(Theory(content="high", confidence=0.9))
        pg_db.save_theory(Theory(content="mid", confidence=0.5))

        theories = pg_db.list_theories()
        assert theories[0].content == "high"
        assert theories[1].content == "mid"
        assert theories[2].content == "low"

    def test_count_theories(self, pg_db):
        from neurosync.models import Theory

        pg_db.save_theory(Theory(content="active", active=True))
        pg_db.save_theory(Theory(content="inactive", active=False))

        assert pg_db.count_theories(active_only=True) == 1
        assert pg_db.count_theories(active_only=False) == 2

    def test_list_children_of_theory(self, pg_db):
        from neurosync.models import Theory

        parent = Theory(content="parent theory")
        pg_db.save_theory(parent)

        child1 = Theory(content="child1", parent_theory_id=parent.id)
        child2 = Theory(content="child2", parent_theory_id=parent.id)
        child3 = Theory(content="inactive child", parent_theory_id=parent.id, active=False)
        pg_db.save_theory(child1)
        pg_db.save_theory(child2)
        pg_db.save_theory(child3)

        children = pg_db.list_children_of_theory(parent.id)
        assert len(children) == 2
        child_ids = {c.id for c in children}
        assert child1.id in child_ids
        assert child2.id in child_ids

    def test_theory_upsert(self, pg_db):
        from neurosync.models import Theory

        theory = Theory(content="original", confidence=0.5)
        pg_db.save_theory(theory)

        theory.confidence = 0.9
        theory.content = "updated"
        pg_db.save_theory(theory)

        loaded = pg_db.get_theory(theory.id)
        assert loaded.confidence == 0.9
        assert loaded.content == "updated"


# =============================================================================
# Contradiction Tests
# =============================================================================


class TestContradictionCRUD:
    """Tests for contradiction storage and querying."""

    def test_save_and_list_contradictions(self, pg_db):
        from neurosync.models import Contradiction, Episode, Session, Theory

        theory = Theory(content="test theory")
        pg_db.save_theory(theory)
        session = Session()
        pg_db.save_session(session)
        ep = Episode(session_id=session.id, content="contradicts")
        pg_db.save_episode(ep)

        c = Contradiction(theory_id=theory.id, episode_id=ep.id, description="Wrong!")
        pg_db.save_contradiction(c)

        assert c.id is not None

        contras = pg_db.list_contradictions(theory_id=theory.id)
        assert len(contras) == 1
        assert contras[0].description == "Wrong!"

    def test_list_contradictions_unresolved_only(self, pg_db):
        from neurosync.models import Contradiction, Episode, Session, Theory, _utcnow

        theory = Theory(content="test")
        pg_db.save_theory(theory)
        session = Session()
        pg_db.save_session(session)
        ep1 = Episode(session_id=session.id, content="ep1")
        ep2 = Episode(session_id=session.id, content="ep2")
        pg_db.save_episode(ep1)
        pg_db.save_episode(ep2)

        # One unresolved
        pg_db.save_contradiction(
            Contradiction(theory_id=theory.id, episode_id=ep1.id, description="unresolved")
        )
        # One resolved
        pg_db.save_contradiction(
            Contradiction(
                theory_id=theory.id,
                episode_id=ep2.id,
                description="resolved",
                resolution="fixed",
                resolved_at=_utcnow(),
            )
        )

        unresolved = pg_db.list_contradictions(unresolved_only=True)
        assert len(unresolved) == 1
        assert unresolved[0].description == "unresolved"

        all_contras = pg_db.list_contradictions()
        assert len(all_contras) == 2

    def test_count_contradictions(self, pg_db):
        from neurosync.models import Contradiction, Episode, Session, Theory, _utcnow

        theory = Theory(content="test")
        pg_db.save_theory(theory)
        session = Session()
        pg_db.save_session(session)
        ep1 = Episode(session_id=session.id, content="ep1")
        ep2 = Episode(session_id=session.id, content="ep2")
        pg_db.save_episode(ep1)
        pg_db.save_episode(ep2)

        pg_db.save_contradiction(
            Contradiction(theory_id=theory.id, episode_id=ep1.id, description="a")
        )
        pg_db.save_contradiction(
            Contradiction(
                theory_id=theory.id,
                episode_id=ep2.id,
                description="b",
                resolved_at=_utcnow(),
            )
        )

        assert pg_db.count_contradictions() == 2
        assert pg_db.count_contradictions(unresolved_only=True) == 1


# =============================================================================
# Causal Link Tests
# =============================================================================


class TestCausalLinkCRUD:
    """Tests for causal link storage and querying."""

    def test_causal_link_crud(self, pg_db):
        from neurosync.models import CausalLink

        link = CausalLink(
            cause_text="using eval",
            effect_text="code injection vulnerability",
            mechanism="direct",
            strength=0.9,
            source_episode_ids=["ep1", "ep2"],
            project="test-proj",
        )
        pg_db.save_causal_link(link)

        assert link.id is not None

        loaded = pg_db.get_causal_link(link.id)
        assert loaded.cause_text == "using eval"
        assert loaded.effect_text == "code injection vulnerability"
        assert loaded.strength == 0.9
        assert loaded.source_episode_ids == ["ep1", "ep2"]
        assert loaded.project == "test-proj"

    def test_causal_link_list_and_find(self, pg_db):
        from neurosync.models import CausalLink

        pg_db.save_causal_link(CausalLink(cause_text="A", effect_text="B"))
        pg_db.save_causal_link(CausalLink(cause_text="A", effect_text="C"))
        pg_db.save_causal_link(CausalLink(cause_text="D", effect_text="B"))

        by_cause = pg_db.list_causal_links(cause_text="A")
        assert len(by_cause) == 2

        by_effect = pg_db.list_causal_links(effect_text="B")
        assert len(by_effect) == 2

        found = pg_db.find_causal_links_by_text("A", role="cause")
        assert len(found) == 2

    def test_causal_link_increment(self, pg_db):
        from neurosync.models import CausalLink

        link = CausalLink(cause_text="X", effect_text="Y")
        pg_db.save_causal_link(link)
        assert link.observation_count == 1

        pg_db.increment_causal_observation(link.id)
        loaded = pg_db.get_causal_link(link.id)
        assert loaded.observation_count == 2

    def test_causal_link_update(self, pg_db):
        from neurosync.models import CausalLink

        link = CausalLink(cause_text="X", effect_text="Y", strength=0.5)
        pg_db.save_causal_link(link)

        link.strength = 0.9
        pg_db.save_causal_link(link)

        loaded = pg_db.get_causal_link(link.id)
        assert loaded.strength == 0.9

    def test_causal_link_normalized_lookup(self, pg_db):
        from neurosync.models import CausalLink

        pg_db.save_causal_link(CausalLink(cause_text="ChromaDB Error", effect_text="Search Failure"))

        # Case-insensitive normalized lookup
        results = pg_db.list_causal_links_normalized("chromadb error", "search failure")
        assert len(results) == 1
        assert results[0].cause_text == "ChromaDB Error"

    def test_count_causal_links(self, pg_db):
        from neurosync.models import CausalLink

        pg_db.save_causal_link(CausalLink(cause_text="A", effect_text="B"))
        pg_db.save_causal_link(CausalLink(cause_text="C", effect_text="D"))

        assert pg_db.count_causal_links() == 2

    def test_causal_link_by_project(self, pg_db):
        from neurosync.models import CausalLink

        pg_db.save_causal_link(CausalLink(cause_text="A", effect_text="B", project="proj1"))
        pg_db.save_causal_link(CausalLink(cause_text="C", effect_text="D", project="proj2"))

        proj1_links = pg_db.list_causal_links(project="proj1")
        assert len(proj1_links) == 1
        assert proj1_links[0].cause_text == "A"


# =============================================================================
# Failure Record Tests
# =============================================================================


class TestFailureRecordCRUD:
    """Tests for failure record storage and querying."""

    def test_failure_record_crud(self, pg_db):
        from neurosync.models import FailureRecord

        rec = FailureRecord(
            what_failed="Used grep instead of rg",
            why_failed="grep doesn't support recursive search well",
            what_worked="Use ripgrep (rg) for recursive code search",
            category="tooling",
            project="GMP",
            severity=4,
        )
        pg_db.save_failure_record(rec)

        assert rec.id is not None

        loaded = pg_db.get_failure_record(rec.id)
        assert loaded.what_failed == "Used grep instead of rg"
        assert loaded.what_worked == "Use ripgrep (rg) for recursive code search"
        assert loaded.severity == 4
        assert loaded.category == "tooling"
        assert loaded.project == "GMP"

    def test_failure_record_list_filters(self, pg_db):
        from neurosync.models import FailureRecord

        pg_db.save_failure_record(
            FailureRecord(what_failed="a", category="approach", severity=2, project="p1")
        )
        pg_db.save_failure_record(
            FailureRecord(what_failed="b", category="tooling", severity=4, project="p1")
        )
        pg_db.save_failure_record(
            FailureRecord(what_failed="c", category="approach", severity=5, project="p2")
        )

        all_recs = pg_db.list_failure_records()
        assert len(all_recs) == 3

        by_cat = pg_db.list_failure_records(category="tooling")
        assert len(by_cat) == 1

        by_proj = pg_db.list_failure_records(project="p1")
        assert len(by_proj) == 2

        by_sev = pg_db.list_failure_records(min_severity=4)
        assert len(by_sev) == 2

    def test_failure_record_increment(self, pg_db):
        from neurosync.models import FailureRecord

        rec = FailureRecord(what_failed="X")
        pg_db.save_failure_record(rec)
        assert rec.occurrence_count == 1

        pg_db.increment_failure_occurrence(rec.id)
        loaded = pg_db.get_failure_record(rec.id)
        assert loaded.occurrence_count == 2

    def test_failure_record_update(self, pg_db):
        from neurosync.models import FailureRecord

        rec = FailureRecord(what_failed="original", severity=2)
        pg_db.save_failure_record(rec)

        rec.what_failed = "updated"
        rec.severity = 4
        pg_db.save_failure_record(rec)

        loaded = pg_db.get_failure_record(rec.id)
        assert loaded.what_failed == "updated"
        assert loaded.severity == 4

    def test_count_failure_records(self, pg_db):
        from neurosync.models import FailureRecord

        pg_db.save_failure_record(FailureRecord(what_failed="a"))
        pg_db.save_failure_record(FailureRecord(what_failed="b"))

        assert pg_db.count_failure_records() == 2


# =============================================================================
# User Model Tests
# =============================================================================


class TestUserModelCRUD:
    """Tests for user knowledge storage and retrieval."""

    def test_user_knowledge_create_and_get(self, pg_db):
        from neurosync.models import UserKnowledge

        uk = UserKnowledge(topic="pytest", project="neurosync", familiarity=0.7)
        pg_db.save_user_knowledge(uk)

        assert uk.id is not None

        loaded = pg_db.get_user_knowledge("pytest", "neurosync")
        assert loaded is not None
        assert loaded.familiarity == 0.7
        assert loaded.topic == "pytest"

    def test_user_knowledge_update(self, pg_db):
        from neurosync.models import UserKnowledge

        uk = UserKnowledge(topic="pytest", project="neurosync", familiarity=0.7)
        pg_db.save_user_knowledge(uk)

        uk.familiarity = 0.9
        pg_db.save_user_knowledge(uk)

        reloaded = pg_db.get_user_knowledge("pytest", "neurosync")
        assert reloaded.familiarity == 0.9

    def test_user_knowledge_get_nonexistent(self, pg_db):
        result = pg_db.get_user_knowledge("nonexistent", "")
        assert result is None

    def test_list_user_knowledge(self, pg_db):
        from neurosync.models import UserKnowledge

        pg_db.save_user_knowledge(UserKnowledge(topic="python", project="proj-a", familiarity=0.8))
        pg_db.save_user_knowledge(UserKnowledge(topic="rust", project="proj-a", familiarity=0.3))
        pg_db.save_user_knowledge(UserKnowledge(topic="go", project="proj-b", familiarity=0.5))

        all_uk = pg_db.list_user_knowledge()
        assert len(all_uk) == 3

        proj_a = pg_db.list_user_knowledge(project="proj-a")
        assert len(proj_a) == 2

    def test_user_knowledge_metadata_roundtrip(self, pg_db):
        from neurosync.models import UserKnowledge

        uk = UserKnowledge(
            topic="testing", project="ns", familiarity=0.6, metadata={"correction_rate": 0.1}
        )
        pg_db.save_user_knowledge(uk)

        loaded = pg_db.get_user_knowledge("testing", "ns")
        assert loaded.metadata == {"correction_rate": 0.1}


# =============================================================================
# Audit Log Table Tests (schema v6)
# =============================================================================


class TestAuditLogTable:
    """Tests for the audit_log table (v6 schema addition).

    Since the PostgresDatabase class does not yet expose audit helper methods,
    these tests verify the table structure and accessibility via raw SQL.
    """

    def test_audit_log_insert_and_query(self, pg_db):
        """Verify the audit_log table supports full insert and read cycle."""
        from neurosync.models import _utcnow

        ts = _utcnow()
        pg_db._execute(
            """INSERT INTO audit_log
               (timestamp, entity_type, entity_id, action, field_name, old_value, new_value, context)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (ts, "theory", "th-001", "confidence_update", "confidence", "0.5", "0.8", "test context"),
        )

        rows = pg_db._query("SELECT * FROM audit_log WHERE entity_id = %s", ("th-001",))
        assert len(rows) == 1
        assert rows[0]["entity_type"] == "theory"
        assert rows[0]["action"] == "confidence_update"
        assert rows[0]["old_value"] == "0.5"
        assert rows[0]["new_value"] == "0.8"
        assert rows[0]["context"] == "test context"

    def test_audit_log_indexes_exist(self, pg_db):
        """Verify indexes on audit_log are present."""
        rows = pg_db._query(
            """SELECT indexname FROM pg_indexes
               WHERE tablename = 'audit_log' AND schemaname = 'public'"""
        )
        index_names = {r["indexname"] for r in rows}
        assert "idx_audit_entity" in index_names
        assert "idx_audit_timestamp" in index_names

    def test_audit_log_multiple_entries(self, pg_db):
        """Verify multiple audit entries can be inserted and filtered."""
        from neurosync.models import _utcnow

        ts = _utcnow()
        for i in range(5):
            pg_db._execute(
                """INSERT INTO audit_log
                   (timestamp, entity_type, entity_id, action)
                   VALUES (%s, %s, %s, %s)""",
                (ts, "theory" if i < 3 else "episode", f"ent-{i}", "create"),
            )

        theory_rows = pg_db._query(
            "SELECT * FROM audit_log WHERE entity_type = %s", ("theory",)
        )
        assert len(theory_rows) == 3

        all_rows = pg_db._query("SELECT * FROM audit_log")
        assert len(all_rows) == 5


# =============================================================================
# Junction Table Tests
# =============================================================================


class TestJunctionTables:
    """Tests for theory-episode, theory-relation, and causal-link-episode junctions."""

    def test_theory_episode_junction(self, pg_db):
        from neurosync.models import Episode, Session, Theory

        session = Session()
        pg_db.save_session(session)
        ep1 = Episode(session_id=session.id, content="ep1")
        ep2 = Episode(session_id=session.id, content="ep2")
        pg_db.save_episode(ep1)
        pg_db.save_episode(ep2)

        theory = Theory(content="test theory")
        pg_db.save_theory(theory)

        pg_db.add_theory_episode(theory.id, ep1.id)
        pg_db.add_theory_episode(theory.id, ep2.id)
        # Idempotent
        pg_db.add_theory_episode(theory.id, ep1.id)

        ep_ids = pg_db.get_theory_episode_ids(theory.id)
        assert set(ep_ids) == {ep1.id, ep2.id}

        th_ids = pg_db.get_theories_for_episode(ep1.id)
        assert theory.id in th_ids

    def test_theory_relation_junction(self, pg_db):
        from neurosync.models import Theory

        t1 = Theory(content="theory 1")
        t2 = Theory(content="theory 2")
        pg_db.save_theory(t1)
        pg_db.save_theory(t2)

        pg_db.add_theory_relation(t1.id, t2.id)
        pg_db.add_theory_relation(t2.id, t1.id)

        assert t2.id in pg_db.get_related_theory_ids(t1.id)
        assert t1.id in pg_db.get_related_theory_ids(t2.id)

    def test_causal_link_episode_junction(self, pg_db):
        from neurosync.models import CausalLink

        link = CausalLink(cause_text="X", effect_text="Y")
        pg_db.save_causal_link(link)

        pg_db.add_causal_link_episode(link.id, "ep-a")
        pg_db.add_causal_link_episode(link.id, "ep-b")
        # Idempotent
        pg_db.add_causal_link_episode(link.id, "ep-a")

        ep_ids = pg_db.get_causal_link_episode_ids(link.id)
        assert set(ep_ids) == {"ep-a", "ep-b"}

    def test_entity_fingerprints(self, pg_db):
        pg_db.set_entity_fingerprints("ep1", "episode", ["caching", "retry_logic"])

        fps = pg_db.get_entity_fingerprints("ep1", "episode")
        assert set(fps) == {"caching", "retry_logic"}

        results = pg_db.find_entities_by_fingerprint("caching")
        assert any(r["entity_id"] == "ep1" for r in results)

        results = pg_db.find_entities_by_fingerprint("caching", entity_type="episode")
        assert len(results) >= 1

        results = pg_db.find_entities_by_fingerprint("caching", entity_type="theory")
        assert len(results) == 0

    def test_entity_fingerprints_replace(self, pg_db):
        pg_db.set_entity_fingerprints("ep1", "episode", ["caching", "retry_logic"])
        assert set(pg_db.get_entity_fingerprints("ep1", "episode")) == {"caching", "retry_logic"}

        pg_db.set_entity_fingerprints("ep1", "episode", ["auth_permission"])
        fps = pg_db.get_entity_fingerprints("ep1", "episode")
        assert fps == ["auth_permission"]

    def test_bulk_read_helpers(self, pg_db):
        from neurosync.models import CausalLink, Episode, Session, Theory

        session = Session()
        pg_db.save_session(session)
        ep = Episode(session_id=session.id, content="ep")
        pg_db.save_episode(ep)
        theory = Theory(content="t")
        pg_db.save_theory(theory)
        link = CausalLink(cause_text="A", effect_text="B")
        pg_db.save_causal_link(link)

        pg_db.add_theory_episode(theory.id, ep.id)
        pg_db.add_theory_relation(theory.id, theory.id)  # self-relation for test
        pg_db.add_causal_link_episode(link.id, ep.id)
        pg_db.set_entity_fingerprints(ep.id, "episode", ["pattern1"])

        assert len(pg_db.list_all_theory_episodes()) == 1
        assert len(pg_db.list_all_theory_relations()) == 1
        assert len(pg_db.list_all_causal_link_episodes()) == 1
        assert len(pg_db.list_all_entity_fingerprints()) == 1


# =============================================================================
# Connection Retry / Reconnect Tests
# =============================================================================


class TestConnectionResilience:
    """Tests for connection retry and reconnect logic."""

    def test_with_retry_succeeds_on_first_try(self, pg_db):
        """Normal operations should not trigger reconnect."""
        call_count = {"n": 0}

        def fn():
            call_count["n"] += 1
            return "ok"

        result = pg_db._with_retry(fn)
        assert result == "ok"
        assert call_count["n"] == 1

    def test_with_retry_reconnects_on_operational_error(self, pg_db):
        """On OperationalError, _with_retry should reconnect and retry once."""
        import psycopg2

        call_count = {"n": 0}

        def fn():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise psycopg2.OperationalError("connection lost")
            return "recovered"

        result = pg_db._with_retry(fn)
        assert result == "recovered"
        assert call_count["n"] == 2

    def test_with_retry_reconnects_on_interface_error(self, pg_db):
        """On InterfaceError, _with_retry should reconnect and retry once."""
        import psycopg2

        call_count = {"n": 0}

        def fn():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise psycopg2.InterfaceError("connection closed")
            return "recovered"

        result = pg_db._with_retry(fn)
        assert result == "recovered"
        assert call_count["n"] == 2

    def test_with_retry_fails_after_second_error(self, pg_db):
        """If retry also fails, the error should propagate."""
        import psycopg2

        def fn():
            raise psycopg2.OperationalError("persistent failure")

        with pytest.raises(psycopg2.OperationalError, match="persistent failure"):
            pg_db._with_retry(fn)

    def test_reconnect_creates_new_pool(self, pg_db):
        """_reconnect should close old pool and create a fresh one."""
        old_pool = pg_db._pool
        pg_db._reconnect()
        # Pool object should be different after reconnect
        assert pg_db._pool is not old_pool

    def test_operations_work_after_reconnect(self, pg_db):
        """After a reconnect, normal DB operations should still work."""
        from neurosync.models import Session

        pg_db._reconnect()

        session = Session(project="after-reconnect")
        pg_db.save_session(session)

        loaded = pg_db.get_session(session.id)
        assert loaded is not None
        assert loaded.project == "after-reconnect"

    def test_context_manager(self, pg_config):
        """Test that PostgresDatabase works as a context manager."""
        from neurosync.pg_db import PostgresDatabase

        with PostgresDatabase(pg_config) as db:
            stats = db.stats()
            assert stats["backend"] == "postgresql"

        # Cleanup: since the context manager calls close(), we need a fresh
        # connection for truncation
        db2 = PostgresDatabase(pg_config)
        _truncate_all_tables(db2)
        db2.close()

    def test_execute_with_retry_on_query(self, pg_db):
        """Verify that _query also benefits from retry logic (via _with_retry)."""
        from neurosync.models import Session

        # Normal query should work fine
        pg_db.save_session(Session(project="retry-test"))
        sessions = pg_db.list_sessions()
        assert len(sessions) == 1


# =============================================================================
# Stats Tests
# =============================================================================


class TestStats:
    """Tests for the stats() aggregate method."""

    def test_stats_empty_database(self, pg_db):
        stats = pg_db.stats()
        assert stats["sessions"] == 0
        assert stats["episodes"]["total"] == 0
        assert stats["episodes"]["pending"] == 0
        assert stats["episodes"]["consolidated"] == 0
        assert stats["episodes"]["decayed"] == 0
        assert stats["theories"]["total"] == 0
        assert stats["theories"]["active"] == 0
        assert stats["contradictions"]["total"] == 0
        assert stats["contradictions"]["unresolved"] == 0
        assert stats["backend"] == "postgresql"

    def test_stats_with_data(self, pg_db):
        from neurosync.models import Contradiction, Episode, Session, Theory

        session = Session()
        pg_db.save_session(session)
        pg_db.save_episode(Episode(session_id=session.id, content="a"))
        pg_db.save_episode(Episode(session_id=session.id, content="b", consolidated=1))

        theory = Theory(content="t1")
        pg_db.save_theory(theory)

        ep_for_c = Episode(session_id=session.id, content="c")
        pg_db.save_episode(ep_for_c)
        pg_db.save_contradiction(
            Contradiction(theory_id=theory.id, episode_id=ep_for_c.id, description="x")
        )

        stats = pg_db.stats()
        assert stats["sessions"] == 1
        assert stats["episodes"]["total"] == 3
        assert stats["episodes"]["pending"] == 2
        assert stats["episodes"]["consolidated"] == 1
        assert stats["theories"]["active"] == 1
        assert stats["contradictions"]["total"] == 1
        assert stats["contradictions"]["unresolved"] == 1
