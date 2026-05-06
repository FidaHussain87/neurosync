"""Tests for production-readiness features: input bounds, graceful shutdown,
config validation, ChromaDB recovery, audit trail, integrity check, metrics,
export/import, and concurrency stress."""

from __future__ import annotations

import json
import os
import threading
import time
from unittest.mock import patch

import pytest

from neurosync.config import NeuroSyncConfig
from neurosync.db import Database
from neurosync.models import Session


@pytest.fixture
def tmp_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
def config(tmp_dir):
    return NeuroSyncConfig(data_dir=tmp_dir)


@pytest.fixture
def db(config):
    d = Database(config)
    yield d
    d.close()


# ---------------------------------------------------------------------------
# Input Bounds Validation
# ---------------------------------------------------------------------------


class TestInputBounds:
    def test_validate_string_accepts_normal_input(self):
        from neurosync.mcp_server import _validate_string

        result = _validate_string("hello world", "test", 100)
        assert result == "hello world"

    def test_validate_string_rejects_oversized(self):
        from neurosync.mcp_server import InputTooLargeError, _validate_string

        with pytest.raises(InputTooLargeError, match="exceeds maximum length"):
            _validate_string("x" * 1000, "test", 100)

    def test_validate_string_handles_non_string(self):
        from neurosync.mcp_server import _validate_string

        result = _validate_string(None, "test", 100)
        assert result == ""

    def test_validate_array_accepts_normal(self):
        from neurosync.mcp_server import _validate_array

        result = _validate_array([1, 2, 3], "test", 10)
        assert result == [1, 2, 3]

    def test_validate_array_rejects_oversized(self):
        from neurosync.mcp_server import InputTooLargeError, _validate_array

        with pytest.raises(InputTooLargeError, match="exceeds maximum items"):
            _validate_array(list(range(200)), "test", 100)

    def test_validate_array_handles_non_list(self):
        from neurosync.mcp_server import _validate_array

        result = _validate_array("not a list", "test", 10)
        assert result == []

    def test_handler_rejects_oversized_content(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("NEUROSYNC_DATA_DIR", tmp_dir)
        from neurosync.mcp_server import InputTooLargeError, handle_remember
        from tests.test_mcp_server import _reset_server

        _reset_server()

        from neurosync.mcp_server import _init
        _init()

        with pytest.raises(InputTooLargeError):
            handle_remember({"content": "x" * 60_000})

    def test_handler_rejects_too_many_events(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("NEUROSYNC_DATA_DIR", tmp_dir)
        from neurosync.mcp_server import InputTooLargeError, handle_record
        from tests.test_mcp_server import _reset_server

        _reset_server()

        from neurosync.mcp_server import _init
        _init()

        events = [{"type": "decision", "content": f"event {i}"} for i in range(150)]
        with pytest.raises(InputTooLargeError):
            handle_record({"events": events})


# ---------------------------------------------------------------------------
# Configuration Validation
# ---------------------------------------------------------------------------


class TestConfigValidation:
    def test_valid_config_passes(self, tmp_dir):
        config = NeuroSyncConfig(data_dir=tmp_dir)
        errors = config.validate()
        assert errors == []

    def test_invalid_backend_fails(self, tmp_dir):
        config = NeuroSyncConfig(data_dir=tmp_dir, db_backend="mongodb")
        errors = config.validate()
        assert any("db_backend" in e for e in errors)

    def test_invalid_pg_dsn_fails(self, tmp_dir):
        config = NeuroSyncConfig(data_dir=tmp_dir, db_backend="postgresql", pg_dsn="not_a_url")
        errors = config.validate()
        assert any("NEUROSYNC_PG_DSN" in e for e in errors)

    def test_invalid_min_episodes_fails(self, tmp_dir):
        config = NeuroSyncConfig(data_dir=tmp_dir, consolidation_min_episodes=1)
        errors = config.validate()
        assert any("consolidation_min_episodes" in e for e in errors)

    def test_invalid_similarity_threshold_fails(self, tmp_dir):
        config = NeuroSyncConfig(data_dir=tmp_dir, consolidation_similarity_threshold=0.0)
        errors = config.validate()
        assert any("consolidation_similarity_threshold" in e for e in errors)


# ---------------------------------------------------------------------------
# ChromaDB Auto-Recovery
# ---------------------------------------------------------------------------


class TestChromaDBRecovery:
    def test_vectorstore_init_normal(self, config):
        from neurosync.vectorstore import VectorStore

        vs = VectorStore(config)
        assert vs._recovered is False
        assert vs.stats()["episodes"] == 0

    def test_vectorstore_recovery_attempted_on_failure(self, config):
        """When ChromaDB init fails, recovery is attempted (rename + recreate)."""
        from neurosync.vectorstore import VectorStore

        # Mock _init_client to fail on first call, succeed on second
        call_count = [0]
        original_init_client = VectorStore._init_client

        def mock_init_client(self, cfg):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Simulated corruption")
            original_init_client(self, cfg)

        with patch.object(VectorStore, "_init_client", mock_init_client):
            vs = VectorStore(config)
            assert vs._recovered is True
            assert call_count[0] == 2

    def test_vectorstore_raises_when_recovery_fails(self, tmp_dir):
        """When both init and recovery fail, exception propagates."""
        from neurosync.vectorstore import VectorStore

        bad_config = NeuroSyncConfig(data_dir=tmp_dir)

        def always_fail(self, cfg):
            raise RuntimeError("Permanent failure")

        with patch.object(VectorStore, "_init_client", always_fail), pytest.raises(RuntimeError, match="Permanent failure"):
            VectorStore(bad_config)


# ---------------------------------------------------------------------------
# Audit Trail
# ---------------------------------------------------------------------------


class TestAuditTrail:
    def test_audit_write_and_read(self, db):
        db.audit("theory", "t-123", "confirm", "confidence", "0.5", "0.6", "test context")
        log = db.get_audit_log(entity_type="theory", entity_id="t-123")
        assert len(log) == 1
        assert log[0]["action"] == "confirm"
        assert log[0]["field_name"] == "confidence"
        assert log[0]["old_value"] == "0.5"
        assert log[0]["new_value"] == "0.6"

    def test_audit_multiple_entries(self, db):
        db.audit("theory", "t-1", "confirm", "confidence", "0.5", "0.6")
        db.audit("theory", "t-1", "contradict", "confidence", "0.6", "0.45")
        db.audit("theory", "t-2", "retire", "", "", "")
        log = db.get_audit_log(entity_type="theory")
        assert len(log) == 3

    def test_audit_filter_by_entity(self, db):
        db.audit("theory", "t-1", "confirm")
        db.audit("episode", "e-1", "decay")
        log = db.get_audit_log(entity_type="episode")
        assert len(log) == 1
        assert log[0]["entity_id"] == "e-1"


# ---------------------------------------------------------------------------
# Data Integrity Check
# ---------------------------------------------------------------------------


class TestIntegrityCheck:
    def test_integrity_healthy_with_matching_counts(self, config):
        from neurosync.vectorstore import VectorStore

        vs = VectorStore(config)
        result = vs.integrity_check(db_episode_count=0, db_theory_count=0)
        assert result["healthy"] is True
        assert result["theory_drift"] == 0

    def test_integrity_detects_drift(self, config):
        from neurosync.vectorstore import VectorStore

        vs = VectorStore(config)
        result = vs.integrity_check(db_episode_count=100, db_theory_count=50)
        assert result["episode_drift"] == 100
        assert result["theory_drift"] == 50


# ---------------------------------------------------------------------------
# Metrics / Observability
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_metrics_increment(self):
        from neurosync.logging import Metrics

        m = Metrics()
        m.increment("test.op")
        m.increment("test.op")
        summary = m.summary()
        assert summary["operations"]["test.op"] == 2

    def test_metrics_latency(self):
        from neurosync.logging import Metrics

        m = Metrics()
        m.record_latency("test.op", 10.0)
        m.record_latency("test.op", 20.0)
        m.record_latency("test.op", 30.0)
        summary = m.summary()
        assert "test.op" in summary["latencies"]
        assert summary["latencies"]["test.op"]["count"] == 3
        assert summary["latencies"]["test.op"]["avg_ms"] == 20.0

    def test_metrics_uptime(self):
        from neurosync.logging import Metrics

        m = Metrics()
        time.sleep(0.05)
        summary = m.summary()
        assert summary["uptime_seconds"] >= 0.04

    def test_json_log_format(self):
        import logging

        from neurosync.logging import JSONFormatter

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="neurosync.test", level=logging.INFO,
            pathname="", lineno=0, msg="Test message",
            args=None, exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["msg"] == "Test message"
        assert parsed["logger"] == "neurosync.test"


# ---------------------------------------------------------------------------
# Export / Import
# ---------------------------------------------------------------------------


class TestExportImport:
    def test_export_creates_file(self, tmp_dir, monkeypatch, capsys):
        monkeypatch.setenv("NEUROSYNC_DATA_DIR", tmp_dir)
        import argparse

        from neurosync.cli import cmd_export

        # Create some data first
        config = NeuroSyncConfig(data_dir=tmp_dir)
        db = Database(config)
        session = Session(project="test-proj", branch="main")
        db.save_session(session)
        db.close()

        output_path = os.path.join(tmp_dir, "export.json")
        args = argparse.Namespace(output=output_path)
        cmd_export(args)

        assert os.path.exists(output_path)
        with open(output_path) as f:
            data = json.load(f)
        assert data["sessions"]
        assert data["sessions"][0]["project"] == "test-proj"

    def test_import_restores_data(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("NEUROSYNC_DATA_DIR", tmp_dir)
        import argparse

        from neurosync.cli import cmd_export, cmd_import

        # Create and export
        config = NeuroSyncConfig(data_dir=tmp_dir)
        db = Database(config)
        session = Session(project="import-test", branch="dev")
        db.save_session(session)
        db.close()

        export_path = os.path.join(tmp_dir, "backup.json")
        cmd_export(argparse.Namespace(output=export_path))

        # Reset and import into fresh DB
        import_dir = os.path.join(tmp_dir, "fresh")
        monkeypatch.setenv("NEUROSYNC_DATA_DIR", import_dir)
        os.makedirs(import_dir, exist_ok=True)
        cmd_import(argparse.Namespace(input=export_path))

        # Verify
        config2 = NeuroSyncConfig(data_dir=import_dir)
        db2 = Database(config2)
        sessions = db2.list_sessions()
        assert any(s.project == "import-test" for s in sessions)
        db2.close()


# ---------------------------------------------------------------------------
# Graceful Shutdown
# ---------------------------------------------------------------------------


class TestGracefulShutdown:
    def test_cleanup_closes_db(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("NEUROSYNC_DATA_DIR", tmp_dir)
        from tests.test_mcp_server import _reset_server

        _reset_server()

        import neurosync.mcp_server as srv
        srv._init()
        assert srv._db is not None
        srv._cleanup()
        # After cleanup, session should be None
        assert srv._current_session_id is None

    def test_shutdown_handler_sets_flag(self, tmp_dir, monkeypatch):
        monkeypatch.setenv("NEUROSYNC_DATA_DIR", tmp_dir)
        from tests.test_mcp_server import _reset_server

        _reset_server()

        import neurosync.mcp_server as srv
        srv._shutting_down = False
        with pytest.raises(SystemExit):
            srv._shutdown_handler(15, None)
        assert srv._shutting_down is True
        srv._shutting_down = False  # Reset for other tests


# ---------------------------------------------------------------------------
# Concurrency Stress Tests
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_concurrent_episode_recording(self, tmp_dir, monkeypatch):
        """Multiple threads recording episodes simultaneously."""
        monkeypatch.setenv("NEUROSYNC_DATA_DIR", tmp_dir)
        config = NeuroSyncConfig(data_dir=tmp_dir)
        db = Database(config)
        session = Session(project="concurrency-test", branch="main")
        db.save_session(session)

        from neurosync.episodic import EpisodicMemory
        from neurosync.vectorstore import VectorStore

        vs = VectorStore(config)
        episodic = EpisodicMemory(db, vs)

        errors = []
        recorded_ids = []
        lock = threading.Lock()

        def record_batch(thread_id):
            try:
                for i in range(10):
                    ep = episodic.record_episode(
                        session_id=session.id,
                        event_type="decision",
                        content=f"Thread {thread_id} episode {i}: testing concurrent writes",
                    )
                    with lock:
                        recorded_ids.append(ep.id)
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=record_batch, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent recording errors: {errors}"
        assert len(recorded_ids) == 50
        # Verify all are in the DB
        all_episodes = db.list_episodes(session_id=session.id, limit=100)
        assert len(all_episodes) == 50
        db.close()

    def test_concurrent_theory_operations(self, tmp_dir, monkeypatch):
        """Multiple threads confirming/contradicting theories."""
        monkeypatch.setenv("NEUROSYNC_DATA_DIR", tmp_dir)
        config = NeuroSyncConfig(data_dir=tmp_dir)
        db = Database(config)

        from neurosync.semantic import SemanticMemory
        from neurosync.vectorstore import VectorStore

        vs = VectorStore(config)
        semantic = SemanticMemory(db, vs)

        # Create a theory
        theory = semantic.create_theory(
            content="Test theory for concurrency",
            scope="craft",
            confidence=0.5,
        )

        # Create a session and episode for contradictions
        session = Session(project="conc", branch="main")
        db.save_session(session)

        from neurosync.episodic import EpisodicMemory
        episodic = EpisodicMemory(db, vs)
        ep = episodic.record_episode(
            session_id=session.id, event_type="decision", content="reference episode"
        )

        errors = []

        def confirm_loop():
            try:
                for _ in range(10):
                    semantic.confirm_theory(theory.id, episode_id=ep.id)
            except Exception as e:
                errors.append(f"confirm: {e}")

        def read_loop():
            try:
                for _ in range(20):
                    t = db.get_theory(theory.id)
                    assert t is not None
            except Exception as e:
                errors.append(f"read: {e}")

        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=confirm_loop))
            threads.append(threading.Thread(target=read_loop))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent theory errors: {errors}"
        final = db.get_theory(theory.id)
        assert final.confirmation_count >= 10
        db.close()

    def test_concurrent_session_ensure(self, tmp_dir, monkeypatch):
        """Multiple threads calling _ensure_session don't create duplicates."""
        monkeypatch.setenv("NEUROSYNC_DATA_DIR", tmp_dir)
        from tests.test_mcp_server import _reset_server

        _reset_server()

        import neurosync.mcp_server as srv
        srv._init()

        session_ids = []
        lock = threading.Lock()

        def ensure():
            sid = srv._ensure_session(project="test", branch="main")
            with lock:
                session_ids.append(sid)

        threads = [threading.Thread(target=ensure) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should get the same session ID
        assert len(set(session_ids)) == 1
