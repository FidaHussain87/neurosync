"""Tests for the NeuroSync FastAPI REST server (api_server.py).

Uses FastAPI's synchronous TestClient (backed by anyio) — no pytest-asyncio needed.

Design notes:
- Every test class that calls MCP endpoints gets its own isolated SQLite DB so
  API key state created in one class cannot bleed into another.
- NEUROSYNC_DB_BACKEND is forced to 'sqlite' so the tests work in environments
  that have a PostgreSQL DSN configured but no running server.
- The mcp_server module-level globals are reset before each TestClient is
  created so _init() starts fresh on lifespan startup.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest

import neurosync.mcp_server as _mcp
from neurosync.version import __version__


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_mcp_globals() -> None:
    """Reset all mcp_server module-level globals so _init() runs fresh."""
    if _mcp._db is not None:
        try:
            _mcp._db.close()
        except Exception:
            pass

    _mcp._config = None
    _mcp._db = None
    _mcp._vs = None
    _mcp._episodic = None
    _mcp._semantic = None
    _mcp._analogy = None
    _mcp._causal = None
    _mcp._failure = None
    _mcp._forgetting = None
    _mcp._hierarchy = None
    _mcp._user_model = None
    _mcp._retrieval = None
    _mcp._calibration = None
    _mcp._intelligence = None
    _mcp._current_session_id = None
    _mcp._session_started_at = None
    _mcp._correction_count = 0
    _mcp._assertion_count = 0
    _mcp._correction_topics = []
    _mcp._git_observer = None
    _mcp._consolidation_running = False
    _mcp._last_consolidation_result = None
    _mcp._recent_responses.clear()


def _force_sqlite_env(data_dir: str) -> None:
    """Point environment at *data_dir* and force SQLite backend."""
    os.environ["NEUROSYNC_DATA_DIR"] = data_dir
    os.environ["NEUROSYNC_DB_BACKEND"] = "sqlite"


def _fresh_client(data_dir: str):
    """Return a context-managed TestClient backed by a fresh SQLite DB."""
    from fastapi.testclient import TestClient
    from neurosync.api_server import create_app

    _force_sqlite_env(data_dir)
    _reset_mcp_globals()
    app = create_app()
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Shared fixture: one fresh app per test function that requests it
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_app(tmp_path):
    """
    Function-scoped isolated TestClient in bootstrap mode (no API keys).

    Used by most test classes that just need a clean server to call endpoints
    against without worrying about auth state from other tests.
    """
    data_dir = str(tmp_path / "ns_fresh")
    os.makedirs(data_dir, exist_ok=True)
    with _fresh_client(data_dir) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. Health / root (no auth, no mcp_server needed)
# ---------------------------------------------------------------------------

class TestPublicEndpoints:
    def test_health(self, fresh_app):
        """GET /health returns 200 with status=ok."""
        r = fresh_app.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "version" in body

    def test_root(self, fresh_app):
        """GET / returns name and version."""
        r = fresh_app.get("/")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "neurosync-api"
        assert body["version"] == __version__
        assert "docs" in body


# ---------------------------------------------------------------------------
# 2. Bootstrap mode — no auth required when no API keys exist
# ---------------------------------------------------------------------------

class TestBootstrapMode:
    """Tests that run against a completely fresh DB with no API keys."""

    def test_recall_no_auth_in_bootstrap_mode(self, fresh_app):
        """recall works without any Authorization header when no keys exist."""
        r = fresh_app.post("/v1/recall", json={})
        assert r.status_code == 200
        body = r.json()
        # Must not be an auth error
        assert body.get("error") != "Missing or invalid Authorization header"

    def test_status_no_auth_bootstrap(self, fresh_app):
        """GET /v1/status also works in bootstrap mode."""
        r = fresh_app.get("/v1/status")
        assert r.status_code == 200
        body = r.json()
        assert "version" in body


# ---------------------------------------------------------------------------
# 3. API key management + auth enforcement
# ---------------------------------------------------------------------------

class TestApiKeyAuth:
    """
    Each test in this class gets its own completely isolated DB so key creation
    in one test cannot interfere with auth checks in another.
    """

    @pytest.fixture(autouse=True)
    def keyed_app(self, tmp_path):
        """Per-test isolated client — stored on self for convenience."""
        data_dir = str(tmp_path / "ns_auth")
        os.makedirs(data_dir, exist_ok=True)
        with _fresh_client(data_dir) as c:
            self._client = c
            yield c

    def test_create_api_key(self):
        """POST /v1/api-keys creates a key and returns id + key starting with ns_."""
        r = self._client.post("/v1/api-keys", json={"name": "test-key"})
        assert r.status_code == 200
        body = r.json()
        assert "key" in body
        assert body["key"].startswith("ns_")
        assert "id" in body
        assert body["name"] == "test-key"

    def test_auth_required_after_key_created(self):
        """After creating a key, unauthenticated requests get 401."""
        self._client.post("/v1/api-keys", json={"name": "gatekeeper"})
        r = self._client.post("/v1/recall", json={})
        assert r.status_code == 401

    def test_auth_valid_key(self):
        """Valid Bearer key passes auth and gets a real response."""
        cr = self._client.post("/v1/api-keys", json={"name": "valid-key"})
        key = cr.json()["key"]
        r = self._client.post(
            "/v1/recall", json={}, headers={"Authorization": f"Bearer {key}"}
        )
        assert r.status_code == 200

    def test_auth_invalid_key(self):
        """Invalid Bearer token returns 401 once keys exist."""
        self._client.post("/v1/api-keys", json={"name": "sentinel"})
        r = self._client.post(
            "/v1/recall",
            json={},
            headers={"Authorization": "Bearer ns_thiskeyisnotvalid"},
        )
        assert r.status_code == 401

    def test_list_api_keys(self):
        """GET /v1/api-keys returns list of active keys."""
        # Create one key in bootstrap mode (no auth yet)
        cr = self._client.post("/v1/api-keys", json={"name": "list-test"})
        assert cr.status_code == 200
        key = cr.json()["key"]
        # Once a key exists, auth is required — use the key we just created
        r = self._client.get("/v1/api-keys", headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 200
        body = r.json()
        assert "keys" in body
        assert isinstance(body["keys"], list)
        assert len(body["keys"]) >= 1


# ---------------------------------------------------------------------------
# 4. Core endpoints (bootstrap mode — no auth)
# ---------------------------------------------------------------------------

class TestCoreEndpoints:
    """Verify each handler endpoint responds with the expected shape."""

    def test_record_endpoint(self, fresh_app):
        """POST /v1/record with events returns episode IDs."""
        r = fresh_app.post(
            "/v1/record",
            json={
                "events": [
                    {
                        "type": "decision",
                        "content": "Use SQLite for default storage because zero-config setup",
                    }
                ],
                "session_summary": "test session",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert "episode_ids" in body
        assert len(body["episode_ids"]) >= 1
        assert "episodes_recorded" in body

    def test_remember_endpoint(self, fresh_app):
        """POST /v1/remember creates an explicit memory and returns episode_id."""
        r = fresh_app.post(
            "/v1/remember",
            json={
                "content": "Always write causal statements in session records",
                "reasoning": "Causal language improves consolidation quality",
                "importance": 4,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert "episode_id" in body
        assert "signal_weight" in body

    def test_query_endpoint(self, fresh_app):
        """POST /v1/query returns results dict."""
        r = fresh_app.post(
            "/v1/query",
            json={"query": "SQLite storage", "mode": "semantic", "scope": "all"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "mode" in body
        assert body["mode"] == "semantic"

    def test_correct_endpoint(self, fresh_app):
        """POST /v1/correct returns episode_id and correction_number."""
        r = fresh_app.post(
            "/v1/correct",
            json={
                "wrong": "PostgreSQL is the default backend",
                "right": "SQLite is the default backend",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert "episode_id" in body
        assert "correction_number" in body
        assert body["correction_number"] >= 1

    def test_status_endpoint_get(self, fresh_app):
        """GET /v1/status returns version and database stats."""
        r = fresh_app.get("/v1/status")
        assert r.status_code == 200
        body = r.json()
        assert "version" in body
        assert body["version"] == __version__

    def test_status_endpoint_post(self, fresh_app):
        """POST /v1/status also returns version (dual-method endpoint)."""
        r = fresh_app.post("/v1/status", json={})
        assert r.status_code == 200
        body = r.json()
        assert "version" in body

    def test_theories_endpoint(self, fresh_app):
        """POST /v1/theories with action=list returns theories list."""
        r = fresh_app.post("/v1/theories", json={"action": "list"})
        assert r.status_code == 200
        body = r.json()
        assert "theories" in body
        assert isinstance(body["theories"], list)
        assert "count" in body

    def test_consolidate_dry_run(self, fresh_app):
        """POST /v1/consolidate with dry_run=true returns pending count or message."""
        r = fresh_app.post("/v1/consolidate", json={"dry_run": True})
        assert r.status_code == 200
        body = r.json()
        assert "pending_episodes" in body or "message" in body

    def test_poll_endpoint(self, fresh_app):
        """POST /v1/poll returns polled_at timestamp."""
        r = fresh_app.post("/v1/poll", json={"context": "testing poll endpoint"})
        assert r.status_code == 200
        body = r.json()
        assert "polled_at" in body

    def test_handoff_endpoint(self, fresh_app):
        """POST /v1/handoff creates a cross-session handoff record."""
        r = fresh_app.post(
            "/v1/handoff",
            json={
                "goal": "Write API tests",
                "accomplished": "Wrote bootstrap mode tests",
                "remaining": "Write auth tests",
                "next_step": "Run pytest and fix failures",
                "blockers": "",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert "episode_id" in body
        assert "signal_weight" in body


# ---------------------------------------------------------------------------
# 5. Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_invalid_remember_empty_content(self, fresh_app):
        """POST /v1/remember with empty content returns 400."""
        r = fresh_app.post("/v1/remember", json={"content": ""})
        assert r.status_code == 400
        body = r.json()
        assert "error" in body

    def test_invalid_remember_whitespace_only(self, fresh_app):
        """POST /v1/remember with whitespace-only content returns 400."""
        r = fresh_app.post("/v1/remember", json={"content": "   "})
        assert r.status_code == 400

    def test_input_too_large_returns_413(self, fresh_app):
        """POST /v1/remember with 60KB content returns 413."""
        large_content = "x" * 60_000  # 60KB > MAX_CONTENT_CHARS (50K)
        r = fresh_app.post("/v1/remember", json={"content": large_content})
        assert r.status_code == 413
        body = r.json()
        assert "error_code" in body
        assert body["error_code"] == "INPUT_TOO_LARGE"

    def test_correct_missing_fields(self, fresh_app):
        """POST /v1/correct without 'right' field returns 400."""
        r = fresh_app.post("/v1/correct", json={"wrong": "only wrong, no right"})
        assert r.status_code == 400

    def test_handoff_missing_required_fields(self, fresh_app):
        """POST /v1/handoff without next_step/remaining returns 400."""
        r = fresh_app.post(
            "/v1/handoff",
            json={
                "goal": "partial goal",
                "accomplished": "partial done",
                # missing: remaining, next_step
            },
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# 6. Recall endpoint details
# ---------------------------------------------------------------------------

class TestRecallEndpoint:
    def test_recall_returns_message_on_empty_db(self, fresh_app):
        """Fresh DB recall returns a friendly 'no memories yet' message or empty result."""
        r = fresh_app.post("/v1/recall", json={"context": "empty database test"})
        assert r.status_code == 200
        body = r.json()
        # Either a 'message' key or primary/supporting/recent_episodes keys
        assert "message" in body or "primary" in body or "recent_episodes" in body

    def test_recall_with_project_and_branch(self, fresh_app):
        """recall accepts project and branch parameters."""
        r = fresh_app.post(
            "/v1/recall",
            json={"project": "neurosync", "branch": "main", "max_tokens": 200},
        )
        assert r.status_code == 200
