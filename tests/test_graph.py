"""Tests for Neo4j GraphStore — all tests mock the neo4j driver."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from neurosync.config import NeuroSyncConfig

# ---------------------------------------------------------------------------
# Helpers: fake neo4j module and driver
# ---------------------------------------------------------------------------


def _make_mock_result():
    """Create a mock Neo4j Result that supports .single() and iteration."""
    result = MagicMock()
    result.single.return_value = {"deleted": 0}
    result.__iter__ = MagicMock(return_value=iter([]))
    return result


def _make_mock_driver():
    """Create a mock Neo4j driver with session context manager.

    Supports both session.run() (for schema/batched writes) and
    session.execute_write(fn) (for cleanup transactions).
    """
    driver = MagicMock()
    driver.verify_connectivity = MagicMock()
    session = MagicMock()
    session.run = MagicMock(side_effect=lambda *a, **kw: _make_mock_result())

    # execute_write receives a transaction function and calls it with a tx object.
    # The tx object must support .run() returning a result with .single().
    def _execute_write(fn):
        tx = MagicMock()
        tx.run = MagicMock(side_effect=lambda *a, **kw: _make_mock_result())
        return fn(tx)
    session.execute_write = MagicMock(side_effect=_execute_write)

    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    driver.session = MagicMock(return_value=session)
    driver.close = MagicMock()
    return driver, session


def _make_fake_neo4j_module(driver):
    """Create a fake neo4j module with GraphDatabase.driver returning the mock."""
    module = MagicMock()
    module.GraphDatabase = MagicMock()
    module.GraphDatabase.driver = MagicMock(return_value=driver)
    return module


@pytest.fixture
def mock_neo4j():
    """Patch the neo4j import inside neurosync.graph and return (driver, session)."""
    driver, session = _make_mock_driver()
    fake_module = _make_fake_neo4j_module(driver)

    # Ensure the neo4j module is available when graph.py tries to import it
    with patch.dict(sys.modules, {"neo4j": fake_module}):
        # Re-import to pick up the patched module
        import neurosync.graph as graph_module

        # Patch module-level HAS_NEO4J and GraphDatabase
        original_has = graph_module.HAS_NEO4J
        original_gd = getattr(graph_module, "GraphDatabase", None)
        graph_module.HAS_NEO4J = True
        graph_module.GraphDatabase = fake_module.GraphDatabase

        yield driver, session

        graph_module.HAS_NEO4J = original_has
        if original_gd is not None:
            graph_module.GraphDatabase = original_gd
        else:
            # GraphDatabase didn't exist before patching; remove it
            if hasattr(graph_module, "GraphDatabase"):
                delattr(graph_module, "GraphDatabase")

# ---------------------------------------------------------------------------
# TestGraphStoreInit
# ---------------------------------------------------------------------------


class TestGraphStoreInit:
    def test_import_guard_raises_when_no_neo4j(self, config):
        """GraphStore raises ImportError when neo4j is not installed."""
        import neurosync.graph as graph_module

        original = graph_module.HAS_NEO4J
        graph_module.HAS_NEO4J = False
        try:
            with pytest.raises(ImportError, match="Neo4j driver not installed"):
                graph_module.GraphStore(config)
        finally:
            graph_module.HAS_NEO4J = original

    def test_constructor_connects_and_creates_schema(self, config, mock_neo4j):
        """Constructor connects to Neo4j and ensures schema."""
        driver, session = mock_neo4j
        from neurosync.graph import _SCHEMA_STATEMENTS, GraphStore

        gs = GraphStore(config)

        driver.verify_connectivity.assert_called_once()
        # Schema statements should be run
        assert session.run.call_count >= len(_SCHEMA_STATEMENTS)
        gs.close()
        driver.close.assert_called_once()


# ---------------------------------------------------------------------------
# TestGraphStoreSync
# ---------------------------------------------------------------------------


class TestGraphStoreSync:
    def test_sync_populates_all_node_types(self, config, db, mock_neo4j):
        """sync() reads from SQLite and writes MERGE statements to Neo4j."""
        driver, session = mock_neo4j
        # Populate SQLite with test data
        from neurosync.episodic import EpisodicMemory
        from neurosync.graph import GraphStore

        episodic = EpisodicMemory(db, None)
        s = episodic.start_session(project="test-proj", branch="main")
        episodic.record_episode(
            session_id=s.id,
            event_type="decision",
            content="Test episode content",
            files_touched=["file.py"],
            layers_touched=["service"],
        )

        gs = GraphStore(config)
        # Reset call count after schema creation
        session.run.reset_mock()

        result = gs.sync(db)

        assert "synced" in result
        assert result["synced"]["sessions"] >= 1
        assert result["synced"]["episodes"] >= 1
        # Verify MERGE statements were run
        assert session.run.call_count > 0
        gs.close()

    def test_sync_handles_empty_database(self, config, db, mock_neo4j):
        """sync() with empty database returns zero counts."""
        driver, session = mock_neo4j
        from neurosync.graph import GraphStore

        gs = GraphStore(config)
        session.run.reset_mock()

        result = gs.sync(db)

        assert result["synced"]["sessions"] == 0
        assert result["synced"]["episodes"] == 0
        assert result["synced"]["theories"] == 0
        gs.close()

    def test_sync_with_theories_and_relations(self, config, db, mock_neo4j):
        """sync() handles theories, relations, and junction tables."""
        driver, session = mock_neo4j
        from neurosync.episodic import EpisodicMemory
        from neurosync.graph import GraphStore
        from neurosync.semantic import SemanticMemory

        episodic = EpisodicMemory(db, None)
        semantic = SemanticMemory(db, None)

        s = episodic.start_session(project="proj", branch="main")
        ep = episodic.record_episode(
            session_id=s.id, event_type="decision", content="episode"
        )
        theory = semantic.create_theory(
            content="Test theory", scope="project", scope_qualifier="proj",
            source_episodes=[ep.id],
        )
        # Add junction table entry
        db.add_theory_episode(theory.id, ep.id)

        gs = GraphStore(config)
        session.run.reset_mock()
        result = gs.sync(db)

        assert result["synced"]["theories"] >= 1
        assert result["synced"]["rel_extracted_from"] >= 1
        gs.close()


# ---------------------------------------------------------------------------
# TestGraphStoreSyncProjectFilter
# ---------------------------------------------------------------------------


class TestGraphStoreSyncProjectFilter:
    def test_project_filter_limits_sessions(self, config, db, mock_neo4j):
        """sync(project=X) only syncs data from that project."""
        driver, session = mock_neo4j
        from neurosync.episodic import EpisodicMemory
        from neurosync.graph import GraphStore

        episodic = EpisodicMemory(db, None)
        s1 = episodic.start_session(project="proj-a", branch="main")
        episodic.record_episode(session_id=s1.id, event_type="decision", content="ep-a")
        s2 = episodic.start_session(project="proj-b", branch="main")
        episodic.record_episode(session_id=s2.id, event_type="decision", content="ep-b")

        gs = GraphStore(config)
        session.run.reset_mock()

        result = gs.sync(db, project="proj-a")

        assert result["project_filter"] == "proj-a"
        assert result["synced"]["sessions"] == 1
        assert result["synced"]["episodes"] == 1
        gs.close()


# ---------------------------------------------------------------------------
# TestGraphStoreCypher
# ---------------------------------------------------------------------------


class TestGraphStoreCypher:
    def test_run_cypher_delegates_to_driver(self, config, mock_neo4j):
        """run_cypher() passes query and params to the Neo4j session via execute_read."""
        driver, session = mock_neo4j
        from neurosync.graph import GraphStore

        # Make execute_read return mock records (list of dict-like objects)
        mock_record = MagicMock()
        mock_record.__iter__ = MagicMock(return_value=iter([("label", "Session"), ("count", 5)]))
        mock_record.keys = MagicMock(return_value=["label", "count"])
        session.execute_read = MagicMock(return_value=[mock_record])

        gs = GraphStore(config)

        gs.run_cypher("MATCH (n) RETURN n", {"param": "value"})

        # Verify execute_read was called (enforces read-only at driver level)
        session.execute_read.assert_called_once()
        gs.close()


# ---------------------------------------------------------------------------
# TestGraphStorePrebuilt
# ---------------------------------------------------------------------------


class TestGraphStorePrebuilt:
    def test_catalog_has_all_12_queries(self, config, mock_neo4j):
        """Pre-built query catalog has all expected queries."""
        from neurosync.graph import GraphStore

        gs = GraphStore(config)
        catalog = gs.get_prebuilt_queries()

        expected_names = [
            "theory_network", "causal_chains", "causal_chain_from",
            "high_confidence_theories", "theory_hierarchy", "failure_hotspots",
            "pattern_clusters", "project_timeline", "contradiction_analysis",
            "cross_project_patterns", "knowledge_graph_overview",
            "episode_to_theory_lineage",
        ]
        for name in expected_names:
            assert name in catalog, f"Missing pre-built query: {name}"
            assert "description" in catalog[name]
            assert "cypher" in catalog[name]
        gs.close()

    def test_catalog_queries_are_non_empty(self, config, mock_neo4j):
        """All pre-built queries have non-empty cypher and description."""
        from neurosync.graph import GraphStore

        gs = GraphStore(config)
        catalog = gs.get_prebuilt_queries()

        for name, info in catalog.items():
            assert len(info["description"]) > 5, f"{name} has empty description"
            assert len(info["cypher"]) > 10, f"{name} has empty cypher"
        gs.close()


# ---------------------------------------------------------------------------
# TestGraphStoreStats
# ---------------------------------------------------------------------------


class TestGraphStoreStats:
    def test_stats_returns_node_and_rel_counts(self, config, mock_neo4j):
        """stats() returns dicts of node and relationship counts."""
        driver, session = mock_neo4j
        from neurosync.graph import GraphStore

        # Mock the two Cypher calls for stats
        node_result = [{"label": "Session", "count": 3}, {"label": "Episode", "count": 10}]
        rel_result = [{"type": "CONTAINS", "count": 10}]
        session.run.side_effect = [
            # Schema statements return empty
            *([MagicMock()] * 20),
        ]

        gs = GraphStore(config)
        # Now set up the two stats calls
        session.run.side_effect = None
        session.run.return_value = iter(node_result)

        # Patch to return known data
        gs.run_cypher = MagicMock(side_effect=[node_result, rel_result])

        stats = gs.stats()

        assert "nodes" in stats
        assert "relationships" in stats
        assert stats["nodes"]["Session"] == 3
        assert stats["relationships"]["CONTAINS"] == 10
        gs.close()


# ---------------------------------------------------------------------------
# TestGraphStoreReset
# ---------------------------------------------------------------------------


class TestGraphStoreReset:
    def test_reset_executes_detach_delete(self, config, mock_neo4j):
        """reset() runs MATCH (n) DETACH DELETE n."""
        driver, session = mock_neo4j
        from neurosync.graph import GraphStore

        gs = GraphStore(config)
        session.run.reset_mock()

        result = gs.reset()

        assert result["message"] == "Graph cleared"
        session.run.assert_called_with(
            "CALL () { MATCH (n) DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS"
        )
        gs.close()


# ---------------------------------------------------------------------------
# TestIsWriteQuery
# ---------------------------------------------------------------------------


class TestIsWriteQuery:
    def test_blocks_create(self):
        from neurosync.graph import _is_write_query

        assert _is_write_query("CREATE (n:Foo)") is True

    def test_blocks_delete(self):
        from neurosync.graph import _is_write_query

        assert _is_write_query("MATCH (n) DELETE n") is True

    def test_blocks_detach_delete(self):
        from neurosync.graph import _is_write_query

        assert _is_write_query("MATCH (n) DETACH DELETE n") is True

    def test_blocks_set(self):
        from neurosync.graph import _is_write_query

        assert _is_write_query("MATCH (n) SET n.x = 1") is True

    def test_blocks_merge(self):
        from neurosync.graph import _is_write_query

        assert _is_write_query("MERGE (n:Foo {id: 1})") is True

    def test_blocks_remove(self):
        from neurosync.graph import _is_write_query

        assert _is_write_query("MATCH (n) REMOVE n.x") is True

    def test_blocks_drop(self):
        from neurosync.graph import _is_write_query

        assert _is_write_query("DROP CONSTRAINT foo") is True

    def test_allows_read_queries(self):
        from neurosync.graph import _is_write_query

        assert _is_write_query("MATCH (n) RETURN n") is False
        assert _is_write_query("MATCH (n)-[r]->(m) RETURN n, r, m") is False

    def test_allows_return_with_keyword_substrings(self):
        from neurosync.graph import _is_write_query

        # "CREATED" contains "CREATE" but should not match as whole word
        assert _is_write_query("MATCH (n) RETURN n.created_at") is False
        # "SETTINGS" contains "SET" but should not match
        assert _is_write_query("MATCH (n:SETTINGS) RETURN n") is False

    def test_blocks_foreach(self):
        from neurosync.graph import _is_write_query

        assert _is_write_query("FOREACH (x IN [1,2] | CREATE (n))") is True

    def test_blocks_call_in_transactions(self):
        from neurosync.graph import _is_write_query

        assert _is_write_query(
            "CALL { MATCH (n) DETACH DELETE n } IN TRANSACTIONS OF 1000 ROWS"
        ) is True


# ---------------------------------------------------------------------------
# TestGraphStoreContextManager
# ---------------------------------------------------------------------------


class TestGraphStoreContextManager:
    def test_context_manager_closes_driver(self, config, mock_neo4j):
        """GraphStore can be used as a context manager."""
        driver, session = mock_neo4j
        from neurosync.graph import GraphStore

        with GraphStore(config) as gs:
            assert gs is not None
        driver.close.assert_called_once()


# ---------------------------------------------------------------------------
# TestGraphStoreCleanup
# ---------------------------------------------------------------------------


class TestGraphStoreCleanup:
    def test_sync_includes_cleanup_stats(self, config, db, mock_neo4j):
        """sync() returns cleanup stats in the result."""
        driver, session = mock_neo4j
        from neurosync.graph import GraphStore

        gs = GraphStore(config)
        session.run.reset_mock()

        result = gs.sync(db)

        assert "cleaned" in result["synced"]
        cleaned = result["synced"]["cleaned"]
        assert "sessions" in cleaned
        assert "episodes" in cleaned
        assert "theories" in cleaned
        gs.close()


# ---------------------------------------------------------------------------
# TestConfigPasswordMasking
# ---------------------------------------------------------------------------


class TestConfigPasswordMasking:
    def test_repr_masks_password(self):
        """Config __repr__ masks neo4j_password."""

        config = NeuroSyncConfig(neo4j_password="secret123")
        r = repr(config)
        assert "secret123" not in r
        assert "***" in r

    def test_repr_shows_empty_password(self):
        """Config __repr__ shows empty string when password is empty."""

        config = NeuroSyncConfig(neo4j_password="")
        r = repr(config)
        assert "***" not in r


# ---------------------------------------------------------------------------
# TestLazyGraphInit
# ---------------------------------------------------------------------------


class TestLazyGraphInit:
    def test_get_graph_returns_none_without_neo4j(self):
        """_get_graph returns None when neo4j is not available."""
        import neurosync.mcp_server as srv

        original = srv._graph
        srv._graph = None
        # Force _config to be set
        original_config = srv._config
        srv._config = MagicMock()
        try:
            # This will fail to import GraphStore in test env (mocked)
            # but we test the sentinel logic
            srv._graph = False  # simulate previous failure
            result = srv._get_graph()
            assert result is None
        finally:
            srv._graph = original
            srv._config = original_config

    def test_get_graph_sentinel_prevents_retry(self):
        """_get_graph doesn't retry after failure (sentinel = False)."""
        import neurosync.mcp_server as srv

        original = srv._graph
        srv._graph = False
        try:
            result = srv._get_graph()
            assert result is None
            # Still False, not None
            assert srv._graph is False
        finally:
            srv._graph = original


# ---------------------------------------------------------------------------
# TestMcpGraphHandler
# ---------------------------------------------------------------------------


class TestMcpGraphHandler:
    def test_handle_graph_unavailable(self):
        """handle_graph returns error when _graph is None."""
        import neurosync.mcp_server as srv
        from neurosync.mcp_server import handle_graph

        original_graph = srv._graph
        original_config = srv._config
        srv._graph = None
        srv._config = MagicMock()  # _require_init(_config) needs non-None
        try:
            result = handle_graph({"action": "status"})
            assert "error" in result
            assert "not available" in result["error"]
        finally:
            srv._graph = original_graph
            srv._config = original_config

    def test_handle_graph_status(self):
        """handle_graph status action returns stats."""
        import neurosync.mcp_server as srv
        from neurosync.mcp_server import handle_graph

        mock_graph = MagicMock()
        mock_graph.stats.return_value = {"nodes": {}, "relationships": {}}
        original_graph = srv._graph
        original_config = srv._config
        srv._graph = mock_graph
        srv._config = MagicMock()
        try:
            result = handle_graph({"action": "status"})
            assert result["healthy"] is True
        finally:
            srv._graph = original_graph
            srv._config = original_config

    def test_handle_graph_prebuilt_catalog(self):
        """handle_graph prebuilt without name returns catalog."""
        import neurosync.mcp_server as srv
        from neurosync.mcp_server import handle_graph

        mock_graph = MagicMock()
        mock_graph.get_prebuilt_queries.return_value = {
            "test_query": {"description": "A test", "cypher": "MATCH (n) RETURN n"},
        }
        original_graph = srv._graph
        original_config = srv._config
        srv._graph = mock_graph
        srv._config = MagicMock()
        try:
            result = handle_graph({"action": "prebuilt"})
            assert "queries" in result
            assert "test_query" in result["queries"]
        finally:
            srv._graph = original_graph
            srv._config = original_config

    def test_handle_graph_prebuilt_run(self):
        """handle_graph prebuilt with name runs the query."""
        import neurosync.mcp_server as srv
        from neurosync.mcp_server import handle_graph

        mock_graph = MagicMock()
        mock_graph.get_prebuilt_queries.return_value = {
            "test_query": {"description": "A test", "cypher": "MATCH (n) RETURN n"},
        }
        mock_graph.run_cypher.return_value = [{"n": "result"}]
        original_graph = srv._graph
        original_config = srv._config
        srv._graph = mock_graph
        srv._config = MagicMock()
        try:
            result = handle_graph({"action": "prebuilt", "prebuilt_name": "test_query"})
            assert result["query"] == "test_query"
            assert result["results"] == [{"n": "result"}]
        finally:
            srv._graph = original_graph
            srv._config = original_config

    def test_handle_graph_query_blocks_writes(self):
        """handle_graph query action blocks write queries."""
        import neurosync.mcp_server as srv
        from neurosync.mcp_server import handle_graph

        mock_graph = MagicMock()
        original_graph = srv._graph
        original_config = srv._config
        srv._graph = mock_graph
        srv._config = MagicMock()
        try:
            result = handle_graph({"action": "query", "cypher": "CREATE (n:Foo)"})
            assert "error" in result
            assert "Write queries" in result["error"]
        finally:
            srv._graph = original_graph
            srv._config = original_config

    def test_handle_graph_query_allows_reads(self):
        """handle_graph query action allows read queries."""
        import neurosync.mcp_server as srv
        from neurosync.mcp_server import handle_graph

        mock_graph = MagicMock()
        mock_graph.run_cypher.return_value = [{"n": "result"}]
        original_graph = srv._graph
        original_config = srv._config
        srv._graph = mock_graph
        srv._config = MagicMock()
        try:
            result = handle_graph({"action": "query", "cypher": "MATCH (n) RETURN n"})
            assert result["results"] == [{"n": "result"}]
        finally:
            srv._graph = original_graph
            srv._config = original_config

    def test_handle_graph_sync(self, db):
        """handle_graph sync action calls sync on GraphStore."""
        import neurosync.mcp_server as srv
        from neurosync.mcp_server import handle_graph

        mock_graph = MagicMock()
        mock_graph.sync.return_value = {"synced": {}, "project_filter": None}
        original_graph = srv._graph
        original_db = srv._db
        original_config = srv._config
        srv._graph = mock_graph
        srv._db = db
        srv._config = MagicMock()
        try:
            handle_graph({"action": "sync", "project": "test"})
            mock_graph.sync.assert_called_once_with(db, project="test")
        finally:
            srv._graph = original_graph
            srv._db = original_db
            srv._config = original_config

    def test_handle_graph_unknown_action(self):
        """handle_graph returns error for unknown action."""
        import neurosync.mcp_server as srv
        from neurosync.mcp_server import handle_graph

        mock_graph = MagicMock()
        original_graph = srv._graph
        original_config = srv._config
        srv._graph = mock_graph
        srv._config = MagicMock()
        try:
            result = handle_graph({"action": "bogus"})
            assert "error" in result
            assert "Unknown action" in result["error"]
        finally:
            srv._graph = original_graph
            srv._config = original_config

    def test_tool_definition_exists(self):
        """neurosync_graph tool is in TOOLS list."""
        from neurosync.mcp_server import TOOLS

        names = [t["name"] for t in TOOLS]
        assert "neurosync_graph" in names

    def test_handler_registered(self):
        """neurosync_graph handler is in _HANDLERS."""
        from neurosync.mcp_server import _HANDLERS

        assert "neurosync_graph" in _HANDLERS


# ---------------------------------------------------------------------------
# TestBulkReadHelpers
# ---------------------------------------------------------------------------


class TestBulkReadHelpers:
    def test_list_all_theory_episodes(self, db):
        """list_all_theory_episodes returns all junction rows."""
        from neurosync.episodic import EpisodicMemory
        from neurosync.semantic import SemanticMemory

        episodic = EpisodicMemory(db, None)
        semantic = SemanticMemory(db, None)
        s = episodic.start_session(project="p", branch="b")
        ep = episodic.record_episode(session_id=s.id, event_type="decision", content="x")
        theory = semantic.create_theory(
            content="t", scope="project", scope_qualifier="p",
            source_episodes=[ep.id],
        )
        db.add_theory_episode(theory.id, ep.id)

        rows = db.list_all_theory_episodes()
        assert len(rows) >= 1
        assert rows[0]["theory_id"] == theory.id
        assert rows[0]["episode_id"] == ep.id

    def test_list_all_theory_relations(self, db):
        """list_all_theory_relations returns all junction rows."""
        from neurosync.semantic import SemanticMemory

        semantic = SemanticMemory(db, None)
        t1 = semantic.create_theory(content="t1", scope="craft", scope_qualifier="")
        t2 = semantic.create_theory(content="t2", scope="craft", scope_qualifier="")
        db.add_theory_relation(t1.id, t2.id)

        rows = db.list_all_theory_relations()
        assert len(rows) >= 1
        assert rows[0]["theory_id"] == t1.id
        assert rows[0]["related_theory_id"] == t2.id

    def test_list_all_entity_fingerprints(self, db):
        """list_all_entity_fingerprints returns all junction rows."""
        db.set_entity_fingerprints("eid1", "episode", ["loop", "error_handler"])

        rows = db.list_all_entity_fingerprints()
        assert len(rows) >= 2
        patterns = {r["pattern"] for r in rows}
        assert "loop" in patterns
        assert "error_handler" in patterns

    def test_list_all_causal_link_episodes(self, db):
        """list_all_causal_link_episodes returns all junction rows."""
        from neurosync.episodic import EpisodicMemory
        from neurosync.models import CausalLink, _utcnow

        episodic = EpisodicMemory(db, None)
        s = episodic.start_session(project="p", branch="b")
        ep = episodic.record_episode(session_id=s.id, event_type="decision", content="x")

        link = CausalLink(
            cause_text="cause", effect_text="effect",
            created_at=_utcnow(), updated_at=_utcnow(),
        )
        link = db.save_causal_link(link)
        db.add_causal_link_episode(link.id, ep.id)

        rows = db.list_all_causal_link_episodes()
        assert len(rows) >= 1
        assert rows[0]["causal_link_id"] == link.id
        assert rows[0]["episode_id"] == ep.id
