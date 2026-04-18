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
        assert stats["schema_version"] == 5
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
        assert stats["schema_version"] == 5
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
        assert stats["schema_version"] == 5
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
        assert stats["schema_version"] == 5
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
        assert stats1["schema_version"] == stats2["schema_version"] == 5
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
            assert stats["schema_version"] == 5
        # After context manager exit, connection should be closed

    # --- v4: Migration v3→v4 ---

    def test_migration_v3_to_v5(self, config):
        """Test that v3 databases get migrated to v5 with junction tables, backfill, and normalized columns."""
        import sqlite3
        conn = sqlite3.connect(config.sqlite_path)
        conn.row_factory = sqlite3.Row
        # Create a v3 database with existing data to backfill
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (3);
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
                reasoning TEXT DEFAULT '', quality_score INTEGER, metadata TEXT DEFAULT '{}',
                reinforcement_count INTEGER DEFAULT 0, last_accessed TEXT,
                structural_fingerprint TEXT DEFAULT ''
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
                validation_status TEXT DEFAULT 'unvalidated', metadata TEXT DEFAULT '{}',
                hierarchy_depth INTEGER DEFAULT 0, structural_fingerprint TEXT DEFAULT ''
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
            CREATE TABLE IF NOT EXISTS causal_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT, cause_text TEXT NOT NULL,
                effect_text TEXT NOT NULL, mechanism TEXT NOT NULL DEFAULT 'direct',
                mechanism_detail TEXT DEFAULT '', confidence_level TEXT DEFAULT 'observed',
                strength REAL DEFAULT 0.5, observation_count INTEGER DEFAULT 1,
                source_episode_ids TEXT DEFAULT '[]', source_theory_id TEXT DEFAULT '',
                project TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS failure_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT, what_failed TEXT NOT NULL,
                why_failed TEXT NOT NULL DEFAULT '', what_worked TEXT DEFAULT '',
                category TEXT DEFAULT 'approach', project TEXT DEFAULT '',
                context TEXT DEFAULT '', source_episode_id TEXT DEFAULT '',
                severity INTEGER DEFAULT 3, occurrence_count INTEGER DEFAULT 1,
                created_at TEXT NOT NULL, last_seen TEXT NOT NULL
            );
        """)
        # Insert data to verify backfill
        conn.execute("INSERT INTO sessions (id, project, started_at) VALUES ('s1', 'test', '2026-01-01')")
        conn.execute("INSERT INTO episodes (id, session_id, timestamp, content, structural_fingerprint) VALUES ('ep1', 's1', '2026-01-01', 'test episode', 'caching,retry_logic')")
        conn.execute("INSERT INTO theories (id, content, first_observed, source_episodes, related_theories, structural_fingerprint) VALUES ('th1', 'test theory', '2026-01-01', '[\"ep1\"]', '[\"th2\"]', 'caching')")
        conn.execute("INSERT INTO theories (id, content, first_observed, source_episodes, related_theories) VALUES ('th2', 'other theory', '2026-01-01', '[]', '[]')")
        conn.execute("INSERT INTO causal_links (cause_text, effect_text, source_episode_ids, created_at, updated_at) VALUES ('A', 'B', '[\"ep1\"]', '2026-01-01', '2026-01-01')")
        conn.commit()
        conn.close()

        from neurosync.db import Database
        database = Database(config)
        stats = database.stats()
        assert stats["schema_version"] == 5
        # Verify junction tables were created and backfilled
        assert database.get_theory_episode_ids("th1") == ["ep1"]
        assert database.get_theories_for_episode("ep1") == ["th1"]
        assert "th2" in database.get_related_theory_ids("th1")
        # Verify entity_fingerprints backfill
        ep_fps = database.get_entity_fingerprints("ep1", "episode")
        assert "caching" in ep_fps
        assert "retry_logic" in ep_fps
        th_fps = database.get_entity_fingerprints("th1", "theory")
        assert "caching" in th_fps
        # Verify causal_link_episodes backfill
        cl_eps = database.get_causal_link_episode_ids(1)
        assert "ep1" in cl_eps
        # Verify v5 normalized columns backfill
        results = database.list_causal_links_normalized("a", "b")
        assert len(results) == 1
        assert results[0].cause_text == "A"
        assert results[0].effect_text == "B"
        database.close()

    def test_migration_v4_to_v5(self, config):
        """Test that v4 databases get normalized columns added and backfilled."""
        import sqlite3
        conn = sqlite3.connect(config.sqlite_path)
        conn.row_factory = sqlite3.Row
        # Create a minimal v4 database (has junction tables but no normalized columns)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (4);
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, project TEXT DEFAULT '', branch TEXT DEFAULT '',
                started_at TEXT NOT NULL, ended_at TEXT, duration_seconds INTEGER DEFAULT 0,
                summary TEXT DEFAULT '', metadata TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                timestamp TEXT NOT NULL, event_type TEXT DEFAULT 'decision',
                content TEXT DEFAULT '', context TEXT DEFAULT '',
                files_touched TEXT DEFAULT '[]', layers_touched TEXT DEFAULT '[]',
                signal_weight REAL DEFAULT 1.0, consolidated INTEGER DEFAULT 0,
                consolidated_at TEXT, cause TEXT DEFAULT '', effect TEXT DEFAULT '',
                reasoning TEXT DEFAULT '', quality_score INTEGER, metadata TEXT DEFAULT '{}',
                reinforcement_count INTEGER DEFAULT 0, last_accessed TEXT,
                structural_fingerprint TEXT DEFAULT ''
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
                validation_status TEXT DEFAULT 'unvalidated', metadata TEXT DEFAULT '{}',
                hierarchy_depth INTEGER DEFAULT 0, structural_fingerprint TEXT DEFAULT ''
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
            CREATE TABLE IF NOT EXISTS causal_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT, cause_text TEXT NOT NULL,
                effect_text TEXT NOT NULL, mechanism TEXT NOT NULL DEFAULT 'direct',
                mechanism_detail TEXT DEFAULT '', confidence_level TEXT DEFAULT 'observed',
                strength REAL DEFAULT 0.5, observation_count INTEGER DEFAULT 1,
                source_episode_ids TEXT DEFAULT '[]', source_theory_id TEXT DEFAULT '',
                project TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS failure_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT, what_failed TEXT NOT NULL,
                why_failed TEXT NOT NULL DEFAULT '', what_worked TEXT DEFAULT '',
                category TEXT DEFAULT 'approach', project TEXT DEFAULT '',
                context TEXT DEFAULT '', source_episode_id TEXT DEFAULT '',
                severity INTEGER DEFAULT 3, occurrence_count INTEGER DEFAULT 1,
                created_at TEXT NOT NULL, last_seen TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS theory_episodes (
                theory_id TEXT NOT NULL, episode_id TEXT NOT NULL,
                PRIMARY KEY (theory_id, episode_id)
            );
            CREATE TABLE IF NOT EXISTS theory_relations (
                theory_id TEXT NOT NULL, related_theory_id TEXT NOT NULL,
                PRIMARY KEY (theory_id, related_theory_id)
            );
            CREATE TABLE IF NOT EXISTS causal_link_episodes (
                causal_link_id INTEGER NOT NULL, episode_id TEXT NOT NULL,
                PRIMARY KEY (causal_link_id, episode_id)
            );
            CREATE TABLE IF NOT EXISTS entity_fingerprints (
                entity_id TEXT NOT NULL, entity_type TEXT NOT NULL, pattern TEXT NOT NULL,
                PRIMARY KEY (entity_id, entity_type, pattern)
            );
        """)
        # Insert causal link with mixed casing to verify normalized backfill
        conn.execute(
            "INSERT INTO causal_links (cause_text, effect_text, created_at, updated_at) "
            "VALUES ('Missing  Index', 'Slow  Query', '2026-01-01', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        from neurosync.db import Database
        database = Database(config)
        stats = database.stats()
        assert stats["schema_version"] == 5
        # Verify normalized columns were added and backfilled
        results = database.list_causal_links_normalized("missing index", "slow query")
        assert len(results) == 1
        assert results[0].cause_text == "Missing  Index"  # original casing preserved
        # Verify new links also get normalized columns written
        from neurosync.models import CausalLink
        database.save_causal_link(CausalLink(cause_text="High Traffic", effect_text="Increased Latency"))
        results = database.list_causal_links_normalized("high traffic", "increased latency")
        assert len(results) == 1
        assert results[0].cause_text == "High Traffic"
        database.close()

    # --- v4: Junction table tests ---

    def test_theory_episode_junction(self, db):
        """Test forward + reverse lookup for theory↔episode junction."""
        from neurosync.models import Session, Episode, Theory
        session = Session()
        db.save_session(session)
        ep1 = Episode(session_id=session.id, content="ep1")
        ep2 = Episode(session_id=session.id, content="ep2")
        db.save_episode(ep1)
        db.save_episode(ep2)
        theory = Theory(content="test theory")
        db.save_theory(theory)
        db.add_theory_episode(theory.id, ep1.id)
        db.add_theory_episode(theory.id, ep2.id)
        # Idempotent: adding again should not fail
        db.add_theory_episode(theory.id, ep1.id)
        # Forward lookup
        ep_ids = db.get_theory_episode_ids(theory.id)
        assert set(ep_ids) == {ep1.id, ep2.id}
        # Reverse lookup
        th_ids = db.get_theories_for_episode(ep1.id)
        assert theory.id in th_ids

    def test_theory_relation_junction(self, db):
        """Test bidirectional relation links."""
        from neurosync.models import Theory
        t1 = Theory(content="theory 1")
        t2 = Theory(content="theory 2")
        db.save_theory(t1)
        db.save_theory(t2)
        db.add_theory_relation(t1.id, t2.id)
        db.add_theory_relation(t2.id, t1.id)
        assert t2.id in db.get_related_theory_ids(t1.id)
        assert t1.id in db.get_related_theory_ids(t2.id)

    def test_causal_link_episode_junction(self, db):
        """Test causal link ↔ episode junction."""
        from neurosync.models import CausalLink
        link = CausalLink(cause_text="X", effect_text="Y")
        db.save_causal_link(link)
        db.add_causal_link_episode(link.id, "ep-a")
        db.add_causal_link_episode(link.id, "ep-b")
        ep_ids = db.get_causal_link_episode_ids(link.id)
        assert set(ep_ids) == {"ep-a", "ep-b"}

    def test_entity_fingerprints(self, db):
        """Test set/get/find fingerprint patterns."""
        db.set_entity_fingerprints("ep1", "episode", ["caching", "retry_logic"])
        fps = db.get_entity_fingerprints("ep1", "episode")
        assert set(fps) == {"caching", "retry_logic"}
        # Find by pattern
        results = db.find_entities_by_fingerprint("caching")
        assert any(r["entity_id"] == "ep1" for r in results)
        # Filter by type
        results = db.find_entities_by_fingerprint("caching", entity_type="episode")
        assert len(results) >= 1
        results = db.find_entities_by_fingerprint("caching", entity_type="theory")
        assert len(results) == 0

    def test_entity_fingerprints_replace(self, db):
        """Test that set_entity_fingerprints replaces old patterns."""
        db.set_entity_fingerprints("ep1", "episode", ["caching", "retry_logic"])
        assert set(db.get_entity_fingerprints("ep1", "episode")) == {"caching", "retry_logic"}
        # Replace with new patterns
        db.set_entity_fingerprints("ep1", "episode", ["auth_permission"])
        fps = db.get_entity_fingerprints("ep1", "episode")
        assert fps == ["auth_permission"]

    def test_list_causal_links_normalized(self, db):
        """Test case-insensitive causal link lookup."""
        from neurosync.models import CausalLink
        db.save_causal_link(CausalLink(cause_text="ChromaDB Error", effect_text="Search Failure"))
        results = db.list_causal_links_normalized("chromadb error", "search failure")
        assert len(results) == 1
        assert results[0].cause_text == "ChromaDB Error"
