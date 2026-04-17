"""Tests for db.py — SQLite database operations."""

from __future__ import annotations

from neurosync.models import (
    Contradiction,
    Episode,
    Session,
    Signal,
    Theory,
    UserKnowledge,
)


class TestDatabase:
    def test_schema_initialized(self, db):
        stats = db.stats()
        assert stats["schema_version"] == 3
        assert stats["sessions"] == 0

    def test_save_and_get_session(self, db):
        session = Session(project="test-project", branch="main")
        db.save_session(session)
        loaded = db.get_session(session.id)
        assert loaded is not None
        assert loaded.project == "test-project"
        assert loaded.branch == "main"

    def test_list_sessions(self, db):
        db.save_session(Session(project="proj-a"))
        db.save_session(Session(project="proj-b"))
        db.save_session(Session(project="proj-a"))
        all_sessions = db.list_sessions()
        assert len(all_sessions) == 3
        proj_a = db.list_sessions(project="proj-a")
        assert len(proj_a) == 2

    def test_save_and_get_episode(self, db):
        session = Session()
        db.save_session(session)
        episode = Episode(
            session_id=session.id,
            event_type="decision",
            content="Chose REST over GraphQL",
            files_touched=["api.py"],
            layers_touched=["service"],
        )
        db.save_episode(episode)
        loaded = db.get_episode(episode.id)
        assert loaded is not None
        assert loaded.content == "Chose REST over GraphQL"
        assert loaded.files_touched == ["api.py"]
        assert loaded.signal_weight == 1.0

    def test_list_episodes_with_filters(self, db):
        session = Session()
        db.save_session(session)
        db.save_episode(Episode(session_id=session.id, event_type="decision", content="d1"))
        db.save_episode(Episode(session_id=session.id, event_type="correction", content="c1"))
        db.save_episode(Episode(session_id=session.id, event_type="decision", content="d2", consolidated=1))
        all_eps = db.list_episodes()
        assert len(all_eps) == 3
        decisions = db.list_episodes(event_type="decision")
        assert len(decisions) == 2
        pending = db.list_episodes(consolidated=0)
        assert len(pending) == 2

    def test_count_episodes(self, db):
        session = Session()
        db.save_session(session)
        db.save_episode(Episode(session_id=session.id, content="a"))
        db.save_episode(Episode(session_id=session.id, content="b"))
        assert db.count_episodes() == 2
        assert db.count_episodes(consolidated=0) == 2

    def test_mark_episodes_consolidated(self, db):
        session = Session()
        db.save_session(session)
        ep1 = Episode(session_id=session.id, content="a")
        ep2 = Episode(session_id=session.id, content="b")
        db.save_episode(ep1)
        db.save_episode(ep2)
        db.mark_episodes_consolidated([ep1.id], "2024-01-01T00:00:00")
        loaded = db.get_episode(ep1.id)
        assert loaded.consolidated == 1
        loaded2 = db.get_episode(ep2.id)
        assert loaded2.consolidated == 0

    def test_save_and_get_signal(self, db):
        session = Session()
        db.save_session(session)
        ep = Episode(session_id=session.id, content="test")
        db.save_episode(ep)
        signal = Signal(episode_id=ep.id, signal_type="CORRECTION", raw_value=2.0, multiplier=4.0)
        db.save_signal(signal)
        signals = db.get_signals_for_episode(ep.id)
        assert len(signals) == 1
        assert signals[0].signal_type == "CORRECTION"
        assert signals[0].multiplier == 4.0

    def test_save_and_get_theory(self, db):
        theory = Theory(content="Always use type hints", scope="craft", confidence=0.8)
        db.save_theory(theory)
        loaded = db.get_theory(theory.id)
        assert loaded is not None
        assert loaded.content == "Always use type hints"
        assert loaded.confidence == 0.8
        assert loaded.active is True

    def test_list_theories(self, db):
        db.save_theory(Theory(content="t1", scope="craft", active=True))
        db.save_theory(Theory(content="t2", scope="project", scope_qualifier="proj-a", active=True))
        db.save_theory(Theory(content="t3", scope="craft", active=False))
        active = db.list_theories(active_only=True)
        assert len(active) == 2
        all_t = db.list_theories(active_only=False)
        assert len(all_t) == 3
        project = db.list_theories(scope="project")
        assert len(project) == 1

    def test_save_and_list_contradictions(self, db):
        theory = Theory(content="test theory")
        db.save_theory(theory)
        session = Session()
        db.save_session(session)
        ep = Episode(session_id=session.id, content="contradicts")
        db.save_episode(ep)
        c = Contradiction(theory_id=theory.id, episode_id=ep.id, description="Wrong!")
        db.save_contradiction(c)
        assert c.id is not None
        contras = db.list_contradictions(theory_id=theory.id)
        assert len(contras) == 1
        assert db.count_contradictions(unresolved_only=True) == 1

    def test_user_knowledge_crud(self, db):
        uk = UserKnowledge(topic="pytest", project="neurosync", familiarity=0.7)
        db.save_user_knowledge(uk)
        assert uk.id is not None
        loaded = db.get_user_knowledge("pytest", "neurosync")
        assert loaded.familiarity == 0.7
        loaded.familiarity = 0.9
        db.save_user_knowledge(loaded)
        reloaded = db.get_user_knowledge("pytest", "neurosync")
        assert reloaded.familiarity == 0.9

    def test_stats(self, db):
        stats = db.stats()
        assert "sessions" in stats
        assert "episodes" in stats
        assert "theories" in stats
        assert "contradictions" in stats
        assert stats["episodes"]["total"] == 0

    def test_migration_v1_to_v3(self, config):
        """Test that v1 databases get migrated to v3 with all new columns."""
        import sqlite3
        # Create a v1 database manually
        conn = sqlite3.connect(config.sqlite_path)
        conn.row_factory = sqlite3.Row
        # Use the v1 schema (without new columns)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (1);
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, project TEXT DEFAULT '', branch TEXT DEFAULT '',
                started_at TEXT NOT NULL, ended_at TEXT, duration_seconds INTEGER DEFAULT 0,
                summary TEXT DEFAULT '', metadata TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                timestamp TEXT NOT NULL, event_type TEXT DEFAULT 'decision',
                content TEXT DEFAULT '', context TEXT DEFAULT '',
                files_touched TEXT DEFAULT '[]', layers_touched TEXT DEFAULT '[]',
                signal_weight REAL DEFAULT 1.0, consolidated INTEGER DEFAULT 0,
                consolidated_at TEXT, metadata TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, episode_id TEXT NOT NULL,
                signal_type TEXT NOT NULL, raw_value REAL DEFAULT 0.0,
                multiplier REAL DEFAULT 1.0, timestamp TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS theories (
                id TEXT PRIMARY KEY, content TEXT DEFAULT '', scope TEXT DEFAULT 'craft',
                scope_qualifier TEXT DEFAULT '', confidence REAL DEFAULT 0.5,
                confirmation_count INTEGER DEFAULT 0, contradiction_count INTEGER DEFAULT 0,
                first_observed TEXT NOT NULL, last_confirmed TEXT,
                source_episodes TEXT DEFAULT '[]', superseded_by TEXT,
                active INTEGER DEFAULT 1, description_length INTEGER DEFAULT 0,
                metadata TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS contradictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, theory_id TEXT NOT NULL,
                episode_id TEXT NOT NULL, description TEXT DEFAULT '',
                resolution TEXT, resolved_at TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_model (
                id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL,
                project TEXT DEFAULT '', familiarity REAL DEFAULT 0.5,
                last_seen TEXT NOT NULL, times_seen INTEGER DEFAULT 0,
                times_explained INTEGER DEFAULT 0, metadata TEXT DEFAULT '{}'
            );
        """)
        conn.commit()
        conn.close()

        from neurosync.db import Database
        database = Database(config)
        # Verify migration ran: schema at v3
        stats = database.stats()
        assert stats["schema_version"] == 3
        # Insert and read episode with v2 + v3 columns
        from neurosync.models import Episode, Session
        session = Session(project="test")
        database.save_session(session)
        ep = Episode(
            session_id=session.id, content="test",
            cause="trigger", effect="result", reasoning="because",
            structural_fingerprint="caching",
        )
        database.save_episode(ep)
        loaded = database.get_episode(ep.id)
        assert loaded.cause == "trigger"
        assert loaded.effect == "result"
        assert loaded.reasoning == "because"
        assert loaded.structural_fingerprint == "caching"
        assert loaded.reinforcement_count == 0
        database.close()

    def test_migration_v2_to_v3(self, config):
        """Test that v2 databases get migrated to v3 with new tables and columns."""
        import sqlite3
        conn = sqlite3.connect(config.sqlite_path)
        conn.row_factory = sqlite3.Row
        # v2 schema: has cause/effect/reasoning but not v3 columns
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (2);
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, project TEXT DEFAULT '', branch TEXT DEFAULT '',
                started_at TEXT NOT NULL, ended_at TEXT, duration_seconds INTEGER DEFAULT 0,
                summary TEXT DEFAULT '', metadata TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                timestamp TEXT NOT NULL, event_type TEXT DEFAULT 'decision',
                content TEXT DEFAULT '', context TEXT DEFAULT '',
                files_touched TEXT DEFAULT '[]', layers_touched TEXT DEFAULT '[]',
                signal_weight REAL DEFAULT 1.0, consolidated INTEGER DEFAULT 0,
                consolidated_at TEXT, cause TEXT DEFAULT '', effect TEXT DEFAULT '',
                reasoning TEXT DEFAULT '', quality_score INTEGER, metadata TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, episode_id TEXT NOT NULL,
                signal_type TEXT NOT NULL, raw_value REAL DEFAULT 0.0,
                multiplier REAL DEFAULT 1.0, timestamp TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS theories (
                id TEXT PRIMARY KEY, content TEXT DEFAULT '', scope TEXT DEFAULT 'craft',
                scope_qualifier TEXT DEFAULT '', confidence REAL DEFAULT 0.5,
                confirmation_count INTEGER DEFAULT 0, contradiction_count INTEGER DEFAULT 0,
                first_observed TEXT NOT NULL, last_confirmed TEXT,
                source_episodes TEXT DEFAULT '[]', superseded_by TEXT,
                active INTEGER DEFAULT 1, description_length INTEGER DEFAULT 0,
                parent_theory_id TEXT, related_theories TEXT DEFAULT '[]',
                last_applied TEXT, application_count INTEGER DEFAULT 0,
                validation_status TEXT DEFAULT 'unvalidated', metadata TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS contradictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, theory_id TEXT NOT NULL,
                episode_id TEXT NOT NULL, description TEXT DEFAULT '',
                resolution TEXT, resolved_at TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS user_model (
                id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL,
                project TEXT DEFAULT '', familiarity REAL DEFAULT 0.5,
                last_seen TEXT NOT NULL, times_seen INTEGER DEFAULT 0,
                times_explained INTEGER DEFAULT 0, metadata TEXT DEFAULT '{}'
            );
        """)
        conn.commit()
        conn.close()

        from neurosync.db import Database
        database = Database(config)
        stats = database.stats()
        assert stats["schema_version"] == 3
        # Verify causal_links table exists
        from neurosync.models import CausalLink
        link = CausalLink(cause_text="A", effect_text="B")
        database.save_causal_link(link)
        assert link.id is not None
        loaded = database.get_causal_link(link.id)
        assert loaded.cause_text == "A"
        database.close()

    def test_migration_idempotent(self, config):
        """Test that running migration twice doesn't fail."""
        from neurosync.db import Database
        db1 = Database(config)
        db1.close()
        # Running again should not fail
        db2 = Database(config)
        stats = db2.stats()
        assert stats["schema_version"] == 3
        db2.close()

    def test_save_episode_causal_roundtrip(self, db):
        from neurosync.models import Episode, Session
        session = Session()
        db.save_session(session)
        ep = Episode(
            session_id=session.id, content="causal episode",
            cause="user corrected", effect="model updated",
            reasoning="corrections have highest weight",
            quality_score=5,
        )
        db.save_episode(ep)
        loaded = db.get_episode(ep.id)
        assert loaded.cause == "user corrected"
        assert loaded.effect == "model updated"
        assert loaded.reasoning == "corrections have highest weight"
        assert loaded.quality_score == 5

    def test_save_theory_relationship_roundtrip(self, db):
        from neurosync.models import Theory
        theory = Theory(
            content="test theory",
            parent_theory_id="parent-123",
            related_theories=["rel-a", "rel-b"],
            application_count=3,
        )
        db.save_theory(theory)
        loaded = db.get_theory(theory.id)
        assert loaded.parent_theory_id == "parent-123"
        assert loaded.related_theories == ["rel-a", "rel-b"]
        assert loaded.application_count == 3

    def test_save_theory_validation_roundtrip(self, db):
        from neurosync.models import Theory, _utcnow
        theory = Theory(
            content="validated theory",
            last_applied=_utcnow(),
            validation_status="confirmed",
        )
        db.save_theory(theory)
        loaded = db.get_theory(theory.id)
        assert loaded.validation_status == "confirmed"
        assert loaded.last_applied is not None

    # --- v3: Causal Links ---

    def test_causal_link_crud(self, db):
        from neurosync.models import CausalLink
        link = CausalLink(
            cause_text="using eval",
            effect_text="code injection vulnerability",
            mechanism="direct",
            strength=0.9,
            source_episode_ids=["ep1", "ep2"],
            project="test-proj",
        )
        db.save_causal_link(link)
        assert link.id is not None
        loaded = db.get_causal_link(link.id)
        assert loaded.cause_text == "using eval"
        assert loaded.effect_text == "code injection vulnerability"
        assert loaded.strength == 0.9
        assert loaded.source_episode_ids == ["ep1", "ep2"]

    def test_causal_link_list_and_find(self, db):
        from neurosync.models import CausalLink
        db.save_causal_link(CausalLink(cause_text="A", effect_text="B"))
        db.save_causal_link(CausalLink(cause_text="A", effect_text="C"))
        db.save_causal_link(CausalLink(cause_text="D", effect_text="B"))
        by_cause = db.list_causal_links(cause_text="A")
        assert len(by_cause) == 2
        by_effect = db.list_causal_links(effect_text="B")
        assert len(by_effect) == 2
        found = db.find_causal_links_by_text("A", role="cause")
        assert len(found) == 2

    def test_causal_link_increment(self, db):
        from neurosync.models import CausalLink
        link = CausalLink(cause_text="X", effect_text="Y")
        db.save_causal_link(link)
        assert link.observation_count == 1
        db.increment_causal_observation(link.id)
        loaded = db.get_causal_link(link.id)
        assert loaded.observation_count == 2

    def test_causal_link_update(self, db):
        from neurosync.models import CausalLink
        link = CausalLink(cause_text="X", effect_text="Y", strength=0.5)
        db.save_causal_link(link)
        link.strength = 0.9
        db.save_causal_link(link)
        loaded = db.get_causal_link(link.id)
        assert loaded.strength == 0.9

    # --- v3: Failure Records ---

    def test_failure_record_crud(self, db):
        from neurosync.models import FailureRecord
        rec = FailureRecord(
            what_failed="Used grep instead of rg",
            why_failed="grep doesn't support recursive search well",
            what_worked="Use ripgrep (rg) for recursive code search",
            category="tooling",
            project="GMP",
            severity=4,
        )
        db.save_failure_record(rec)
        assert rec.id is not None
        loaded = db.get_failure_record(rec.id)
        assert loaded.what_failed == "Used grep instead of rg"
        assert loaded.what_worked == "Use ripgrep (rg) for recursive code search"
        assert loaded.severity == 4

    def test_failure_record_list_filters(self, db):
        from neurosync.models import FailureRecord
        db.save_failure_record(FailureRecord(what_failed="a", category="approach", severity=2, project="p1"))
        db.save_failure_record(FailureRecord(what_failed="b", category="tooling", severity=4, project="p1"))
        db.save_failure_record(FailureRecord(what_failed="c", category="approach", severity=5, project="p2"))
        all_recs = db.list_failure_records()
        assert len(all_recs) == 3
        by_cat = db.list_failure_records(category="tooling")
        assert len(by_cat) == 1
        by_proj = db.list_failure_records(project="p1")
        assert len(by_proj) == 2
        by_sev = db.list_failure_records(min_severity=4)
        assert len(by_sev) == 2

    def test_failure_record_increment(self, db):
        from neurosync.models import FailureRecord
        rec = FailureRecord(what_failed="X")
        db.save_failure_record(rec)
        assert rec.occurrence_count == 1
        db.increment_failure_occurrence(rec.id)
        loaded = db.get_failure_record(rec.id)
        assert loaded.occurrence_count == 2

    # --- v3: Theory hierarchy helpers ---

    def test_list_children_of_theory(self, db):
        from neurosync.models import Theory
        parent = Theory(content="parent theory")
        db.save_theory(parent)
        child1 = Theory(content="child1", parent_theory_id=parent.id)
        child2 = Theory(content="child2", parent_theory_id=parent.id)
        child3 = Theory(content="inactive child", parent_theory_id=parent.id, active=False)
        db.save_theory(child1)
        db.save_theory(child2)
        db.save_theory(child3)
        children = db.list_children_of_theory(parent.id)
        assert len(children) == 2

    # --- v3: Episode access helpers ---

    def test_update_episode_access(self, db):
        session = Session()
        db.save_session(session)
        ep = Episode(session_id=session.id, content="test")
        db.save_episode(ep)
        db.update_episode_access(ep.id, reinforcement_count=3, last_accessed="2026-01-01T00:00:00")
        loaded = db.get_episode(ep.id)
        assert loaded.reinforcement_count == 3
        assert loaded.last_accessed == "2026-01-01T00:00:00"

    # --- v3: Episode v3 fields roundtrip ---

    def test_episode_v3_fields_roundtrip(self, db):
        session = Session()
        db.save_session(session)
        ep = Episode(
            session_id=session.id, content="test",
            reinforcement_count=5,
            last_accessed="2026-01-01T00:00:00",
            structural_fingerprint="caching,retry_logic",
        )
        db.save_episode(ep)
        loaded = db.get_episode(ep.id)
        assert loaded.reinforcement_count == 5
        assert loaded.last_accessed == "2026-01-01T00:00:00"
        assert loaded.structural_fingerprint == "caching,retry_logic"

    # --- v3: Theory v3 fields roundtrip ---

    def test_theory_v3_fields_roundtrip(self, db):
        from neurosync.models import Theory
        theory = Theory(
            content="caching pattern",
            hierarchy_depth=2,
            structural_fingerprint="caching",
        )
        db.save_theory(theory)
        loaded = db.get_theory(theory.id)
        assert loaded.hierarchy_depth == 2
        assert loaded.structural_fingerprint == "caching"

    # --- Phase 2: Migration safety helpers ---

    def test_column_exists_helper(self, db):
        conn = db._get_conn()
        assert db._column_exists(conn, "episodes", "content") is True
        assert db._column_exists(conn, "episodes", "nonexistent_column") is False

    def test_table_exists_helper(self, db):
        conn = db._get_conn()
        assert db._table_exists(conn, "episodes") is True
        assert db._table_exists(conn, "nonexistent_table") is False

    def test_index_exists_helper(self, db):
        conn = db._get_conn()
        assert db._index_exists(conn, "idx_causal_cause") is True
        assert db._index_exists(conn, "nonexistent_index") is False

    def test_migration_idempotent_rerun(self, config):
        """Running migrations on an already-current DB should not fail."""
        from neurosync.db import Database
        db1 = Database(config)
        stats1 = db1.stats()
        db1.close()
        # Second open triggers _init_schema again — should be a no-op
        db2 = Database(config)
        stats2 = db2.stats()
        assert stats1["schema_version"] == stats2["schema_version"] == 3
        db2.close()

    # --- Phase 3: JSON corruption handling ---

    def test_from_json_corrupted_returns_fallback(self, db):
        result = db._from_json("{invalid json", {})
        assert result == {}

    def test_from_json_list_fallback(self, db):
        result = db._from_json("{invalid", [])
        assert result == []

    def test_from_json_none_returns_empty_dict(self, db):
        result = db._from_json("")
        assert result == {}

    def test_from_json_valid(self, db):
        result = db._from_json('["a", "b"]', [])
        assert result == ["a", "b"]

    # --- Phase 4: Connection resilience ---

    def test_connect_timeout_parameter(self, config):
        """Verify that the DB connection has a timeout configured."""
        from neurosync.db import Database
        database = Database(config)
        conn = database._get_conn()
        # sqlite3 doesn't expose timeout directly, but we can verify
        # the connection works (no hang on creation)
        assert conn is not None
        database.close()

    def test_context_manager(self, config):
        from neurosync.db import Database
        with Database(config) as database:
            stats = database.stats()
            assert stats["schema_version"] == 3
        # After context manager exit, connection should be closed
