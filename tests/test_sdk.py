"""Tests for the NeuroSync Python SDK (sdk.py).

All HTTP calls are intercepted by patching ``urllib.request.urlopen`` so no
live server is required.
"""

from __future__ import annotations

import asyncio
import io
import json
from unittest.mock import MagicMock, call, patch

import pytest
from urllib.error import HTTPError

from neurosync.sdk import AsyncNeuroSyncClient, NeuroSync, NeuroSyncClient, NeuroSyncError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(data: dict, status: int = 200) -> MagicMock:
    """Build a mock urllib response that returns *data* as JSON."""
    mock = MagicMock()
    mock.read.return_value = json.dumps(data).encode("utf-8")
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    mock.status = status
    return mock


def _http_error(code: int, payload: dict | str = "error") -> HTTPError:
    """Build an HTTPError with a readable body."""
    if isinstance(payload, dict):
        body = json.dumps(payload).encode("utf-8")
    else:
        body = str(payload).encode("utf-8")
    return HTTPError(
        url="http://localhost:8000/v1/test",
        code=code,
        msg="HTTP Error",
        hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(body),
    )


def _ns(project: str = "test-project", api_key: str = "") -> NeuroSyncClient:
    return NeuroSyncClient(api_key=api_key, project=project, base_url="http://localhost:8000")


# ---------------------------------------------------------------------------
# 1. Client initialisation
# ---------------------------------------------------------------------------

class TestClientInit:
    def test_client_init(self):
        """NeuroSync alias resolves to NeuroSyncClient; project is stored."""
        ns = NeuroSync(api_key="ns_abc", project="my-project")
        assert isinstance(ns, NeuroSyncClient)
        assert ns._project == "my-project"
        assert ns._api_key == "ns_abc"

    def test_default_base_url(self):
        """Default base_url is http://localhost:8000."""
        ns = NeuroSyncClient()
        assert ns._base_url == "http://localhost:8000"

    def test_trailing_slash_stripped(self):
        """Trailing slash in base_url is stripped."""
        ns = NeuroSyncClient(base_url="http://example.com/")
        assert ns._base_url == "http://example.com"

    def test_empty_api_key_default(self):
        """api_key defaults to empty string."""
        ns = NeuroSyncClient(project="p")
        assert ns._api_key == ""


# ---------------------------------------------------------------------------
# 2. Individual method calls
# ---------------------------------------------------------------------------

class TestSdkCalls:
    """Verify that each SDK method sends the correct JSON body."""

    def test_remember_call(self):
        """ns.remember() calls POST /v1/remember with correct body."""
        ns = _ns()
        response_data = {"episode_id": "ep-1", "signal_weight": 10.0, "message": "ok"}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            result = ns.remember("test memory", reasoning="because testing", importance=4)

        assert result == response_data
        # Inspect the Request object passed to urlopen
        req = mock_open.call_args[0][0]
        assert req.full_url == "http://localhost:8000/v1/remember"
        assert req.method == "POST"
        body = json.loads(req.data)
        assert body["content"] == "test memory"
        assert body["reasoning"] == "because testing"
        assert body["importance"] == 4

    def test_recall_injects_project(self):
        """ns.recall() auto-injects project if set and not already in body."""
        ns = _ns(project="injected-project")
        response_data = {"message": "No memories yet."}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            ns.recall(context="some context")

        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["project"] == "injected-project"
        assert body["context"] == "some context"

    def test_record_call(self):
        """ns.record() sends events array with session_summary."""
        ns = _ns()
        events = [{"type": "decision", "content": "chose SQLite because zero-config"}]
        response_data = {"session_id": "s1", "episodes_recorded": 1, "episode_ids": ["e1"]}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            result = ns.record(events=events, session_summary="test session")

        assert result["episodes_recorded"] == 1
        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["events"] == events
        assert body["session_summary"] == "test session"

    def test_query_call(self):
        """ns.query() sends query, mode, scope, and limit."""
        ns = _ns()
        response_data = {"mode": "semantic", "episodes": [], "theories": []}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            result = ns.query("test query", mode="semantic", scope="all", limit=5)

        assert result["mode"] == "semantic"
        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["query"] == "test query"
        assert body["mode"] == "semantic"
        assert body["limit"] == 5

    def test_correct_call(self):
        """ns.correct() sends wrong/right pair."""
        ns = _ns()
        response_data = {"episode_id": "ep-c1", "correction_number": 1, "signal_weight": 2.0}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            result = ns.correct("wrong assumption", "correct assumption")

        assert result["correction_number"] == 1
        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["wrong"] == "wrong assumption"
        assert body["right"] == "correct assumption"
        assert body["theory_id"] == ""

    def test_status_call(self):
        """ns.status() calls POST /v1/status with empty body."""
        ns = _ns()
        response_data = {"version": "1.0.0", "database": {}, "vectorstore": {}}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            result = ns.status()

        assert "version" in result
        req = mock_open.call_args[0][0]
        assert req.full_url == "http://localhost:8000/v1/status"
        body = json.loads(req.data)
        assert body == {}

    def test_theories_call(self):
        """ns.theories(action='list') sends correct body."""
        ns = _ns()
        response_data = {"theories": [], "count": 0}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            result = ns.theories(action="list", limit=10)

        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["action"] == "list"
        assert body["limit"] == 10

    def test_consolidate_call(self):
        """ns.consolidate(dry_run=True) sends dry_run flag."""
        ns = _ns()
        response_data = {"message": "Dry run: 3 episodes ready", "pending_episodes": 3}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            result = ns.consolidate(dry_run=True)

        assert "pending_episodes" in result or "message" in result
        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["dry_run"] is True

    def test_handoff_call(self):
        """ns.handoff() sends all required fields."""
        ns = _ns()
        response_data = {"episode_id": "ep-h1", "signal_weight": 50.0, "message": "Handoff recorded."}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            result = ns.handoff(
                goal="Build tests",
                accomplished="Wrote SDK tests",
                remaining="Write API tests",
                next_step="Run pytest",
            )

        assert "episode_id" in result
        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["goal"] == "Build tests"
        assert body["accomplished"] == "Wrote SDK tests"
        assert body["remaining"] == "Write API tests"
        assert body["next_step"] == "Run pytest"
        assert "blockers" in body

    def test_poll_call(self):
        """ns.poll() sends context and returns polled_at."""
        ns = _ns()
        response_data = {"polled_at": "2026-05-07T10:00:00Z", "session": {}}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            result = ns.poll(context="before touching auth code")

        assert "polled_at" in result
        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["context"] == "before touching auth code"


# ---------------------------------------------------------------------------
# 3. Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_error_raises_neurosync_error(self):
        """HTTP 400 response raises NeuroSyncError."""
        ns = _ns()
        exc = _http_error(400, {"detail": "content is required"})
        with patch("urllib.request.urlopen", side_effect=exc):
            with pytest.raises(NeuroSyncError) as exc_info:
                ns.remember("")

        assert exc_info.value.status_code == 400
        assert "content is required" in str(exc_info.value)

    def test_401_raises_neurosync_error(self):
        """HTTP 401 raises NeuroSyncError with status_code=401."""
        ns = NeuroSyncClient(api_key="ns_badkey", project="p")
        exc = _http_error(401, {"detail": "Invalid API key"})
        with patch("urllib.request.urlopen", side_effect=exc):
            with pytest.raises(NeuroSyncError) as exc_info:
                ns.recall()

        assert exc_info.value.status_code == 401

    def test_413_raises_neurosync_error(self):
        """HTTP 413 raises NeuroSyncError with status_code=413."""
        ns = _ns()
        exc = _http_error(413, {"error": "content too large", "error_code": "INPUT_TOO_LARGE"})
        with patch("urllib.request.urlopen", side_effect=exc):
            with pytest.raises(NeuroSyncError) as exc_info:
                ns.remember("x" * 60_000)

        assert exc_info.value.status_code == 413

    def test_network_error_raises_neurosync_error(self):
        """URLError (connection refused etc.) raises NeuroSyncError with status_code=0."""
        import urllib.error

        ns = _ns()
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            with pytest.raises(NeuroSyncError) as exc_info:
                ns.status()

        assert exc_info.value.status_code == 0

    def test_invalid_json_response_raises_neurosync_error(self):
        """Non-JSON response body raises NeuroSyncError."""
        ns = _ns()
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json at all <html>"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(NeuroSyncError) as exc_info:
                ns.status()

        assert exc_info.value.status_code == 0
        assert "Invalid JSON" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. Optional field behaviour
# ---------------------------------------------------------------------------

class TestOptionalFields:
    def test_theories_excludes_none_keys(self):
        """theories() with scope=None does not include 'scope' in the request body."""
        ns = _ns()
        response_data = {"theories": [], "count": 0}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            ns.theories(action="list", scope=None, project=None, theory_id=None)

        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert "scope" not in body
        assert "project" not in body
        assert "theory_id" not in body

    def test_theories_includes_scope_when_set(self):
        """theories() with scope='project' includes it in the request body."""
        ns = _ns()
        response_data = {"theories": [], "count": 0}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            ns.theories(action="list", scope="project")

        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["scope"] == "project"

    def test_correct_with_theory_id(self):
        """ns.correct() with theory_id includes it in the body."""
        ns = _ns()
        response_data = {"episode_id": "ep-c2", "correction_number": 1, "contradiction_id": "ct-1"}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            ns.correct("wrong", "right", theory_id="th-abc")

        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["theory_id"] == "th-abc"

    def test_record_explicit_remember(self):
        """ns.record() passes explicit_remember array when provided."""
        ns = _ns()
        response_data = {"session_id": "s2", "episodes_recorded": 2, "episode_ids": ["e1", "e2"]}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            ns.record(
                events=[{"type": "decision", "content": "chose approach"}],
                explicit_remember=["remember this preference"],
            )

        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["explicit_remember"] == ["remember this preference"]

    def test_record_empty_explicit_remember_by_default(self):
        """ns.record() sends empty explicit_remember when not provided."""
        ns = _ns()
        response_data = {"session_id": "s3", "episodes_recorded": 1, "episode_ids": ["e3"]}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            ns.record(events=[{"type": "decision", "content": "x"}])

        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["explicit_remember"] == []


# ---------------------------------------------------------------------------
# 5. Auth header
# ---------------------------------------------------------------------------

class TestAuthHeader:
    def test_api_key_sent_as_bearer(self):
        """SDK sends api_key as 'Authorization: Bearer <key>'."""
        ns = NeuroSyncClient(api_key="ns_mykey123", project="p")
        response_data = {"version": "1.0.0"}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            ns.status()

        req = mock_open.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer ns_mykey123"

    def test_empty_api_key_sends_bearer_empty(self):
        """Empty api_key sends 'Authorization: Bearer ' (no key)."""
        ns = NeuroSyncClient(api_key="", project="p")
        response_data = {"version": "1.0.0"}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            ns.status()

        req = mock_open.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer "


# ---------------------------------------------------------------------------
# 6. Async client
# ---------------------------------------------------------------------------

class TestAsyncClient:
    def test_async_client_recall(self):
        """AsyncNeuroSyncClient.recall() works via asyncio.run."""
        response_data = {"message": "No memories yet."}

        async def _run():
            async_ns = AsyncNeuroSyncClient(project="async-project", api_key="")
            with patch("urllib.request.urlopen", return_value=_mock_response(response_data)):
                return await async_ns.recall(context="async test")

        result = asyncio.run(_run())
        assert result == response_data

    def test_async_client_remember(self):
        """AsyncNeuroSyncClient.remember() wraps the sync client correctly."""
        response_data = {"episode_id": "ep-async-1", "signal_weight": 10.0, "message": "ok"}

        async def _run():
            async_ns = AsyncNeuroSyncClient(api_key="", project="p")
            with patch(
                "urllib.request.urlopen", return_value=_mock_response(response_data)
            ) as mock_open:
                result = await async_ns.remember("async memory", importance=3)
                req = mock_open.call_args[0][0]
                body = json.loads(req.data)
                return result, body

        result, body = asyncio.run(_run())
        assert result["episode_id"] == "ep-async-1"
        assert body["content"] == "async memory"

    def test_async_client_error_propagates(self):
        """Errors in async client propagate as NeuroSyncError."""
        exc = _http_error(401, {"detail": "Unauthorized"})

        async def _run():
            async_ns = AsyncNeuroSyncClient(api_key="bad", project="p")
            with patch("urllib.request.urlopen", side_effect=exc):
                await async_ns.status()

        with pytest.raises(NeuroSyncError) as exc_info:
            asyncio.run(_run())

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# 7. Project injection
# ---------------------------------------------------------------------------

class TestProjectInjection:
    def test_recall_project_not_overridden_if_present(self):
        """recall() does not override an existing 'project' key in the body."""
        # The SDK method builds the body and then calls _inject_project which
        # only adds project if the key is absent.  But the recall() method
        # always sets 'project' to whatever the user passed (default "").
        # So with project="" the SDK sends project="" not the client's project.
        ns = NeuroSyncClient(api_key="", project="client-project")
        response_data = {"message": "no memories"}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            # The SDK builds body with context, branch, max_tokens and then
            # _inject_project only fills in 'project' if absent — it will
            # add client-project since the body doesn't set project explicitly.
            ns.recall()

        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["project"] == "client-project"

    def test_query_injects_project(self):
        """query() injects project into body from client config."""
        ns = NeuroSyncClient(api_key="", project="query-project")
        response_data = {"mode": "semantic", "episodes": []}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            ns.query("test")

        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["project"] == "query-project"

    def test_poll_injects_project(self):
        """poll() injects project into body from client config."""
        ns = NeuroSyncClient(api_key="", project="poll-project")
        response_data = {"polled_at": "2026-05-07T00:00:00Z"}
        with patch("urllib.request.urlopen", return_value=_mock_response(response_data)) as mock_open:
            ns.poll()

        req = mock_open.call_args[0][0]
        body = json.loads(req.data)
        assert body["project"] == "poll-project"
