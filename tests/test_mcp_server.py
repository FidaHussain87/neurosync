"""Tests for mcp_server.py — MCP JSON-RPC 2.0 protocol and tool handlers."""

from __future__ import annotations

import json

import neurosync.mcp_server as mcp


def _reset_server():
    """Reset server state between tests."""
    mcp._config = None
    mcp._db = None
    mcp._vs = None
    mcp._episodic = None
    mcp._semantic = None
    mcp._working = None
    mcp._current_session_id = None
    mcp._correction_count = 0


class TestMcpProtocol:
    def setup_method(self):
        _reset_server()

    def test_initialize(self):
        req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        resp = mcp._handle_request(req)
        assert resp["result"]["protocolVersion"] == "2024-11-05"
        assert resp["result"]["serverInfo"]["name"] == "neurosync"

    def test_tools_list(self):
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        resp = mcp._handle_request(req)
        tools = resp["result"]["tools"]
        names = {t["name"] for t in tools}
        assert "neurosync_recall" in names
        assert "neurosync_record" in names
        assert "neurosync_remember" in names
        assert "neurosync_query" in names
        assert "neurosync_correct" in names
        assert "neurosync_status" in names
        assert "neurosync_theories" in names
        assert "neurosync_consolidate" in names
        assert len(tools) == 8

    def test_ping(self):
        req = {"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}}
        resp = mcp._handle_request(req)
        assert resp["result"] == {}

    def test_unknown_method(self):
        req = {"jsonrpc": "2.0", "id": 4, "method": "unknown/method", "params": {}}
        resp = mcp._handle_request(req)
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    def test_notification_no_response(self):
        req = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        resp = mcp._handle_request(req)
        assert resp is None

    def test_unknown_tool(self):
        req = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
        }
        resp = mcp._handle_request(req)
        assert "error" in resp
        assert resp["error"]["code"] == -32601


class TestMcpTools:
    def setup_method(self):
        _reset_server()

    def test_recall_empty(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "neurosync_recall", "arguments": {}},
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "No memories" in content.get("message", "")

    def test_record_events(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "neurosync_record",
                "arguments": {
                    "events": [
                        {"type": "decision", "content": "Chose REST API"},
                        {"type": "discovery", "content": "Found a bug in auth"},
                    ],
                    "session_summary": "Productive session",
                },
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["episodes_recorded"] == 2
        assert content["session_id"]

    def test_remember(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "neurosync_remember",
                "arguments": {"content": "Always use WAL mode"},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["signal_weight"] == 10.0

    def test_remember_empty(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "neurosync_remember",
                "arguments": {"content": "   "},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "error" in content

    def test_correct(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "neurosync_correct",
                "arguments": {"wrong": "use mock()", "right": "use redefine()"},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["correction_number"] == 1
        assert content["signal_weight"] == 2.0

    def test_status(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "neurosync_status", "arguments": {}},
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "database" in content
        assert "vectorstore" in content

    def test_theories_list(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "neurosync_theories",
                "arguments": {"action": "list"},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "theories" in content

    def test_theories_detail_missing_id(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "neurosync_theories",
                "arguments": {"action": "detail"},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "error" in content

    def test_query_empty(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "neurosync_query",
                "arguments": {"query": ""},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "error" in content

    def test_consolidate_not_enough(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "neurosync_consolidate",
                "arguments": {},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "Not enough" in content.get("message", "")

    def test_record_with_explicit_remember(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "neurosync_record",
                "arguments": {
                    "events": [{"type": "decision", "content": "Test event"}],
                    "explicit_remember": ["Remember this important thing"],
                },
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["episodes_recorded"] == 2

    def test_record_invalid_event_type(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "neurosync_record",
                "arguments": {
                    "events": [{"type": "invalid_type", "content": "Test"}],
                },
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["episodes_recorded"] == 1

    def test_correct_empty_fields(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "neurosync_correct",
                "arguments": {"wrong": "", "right": "something"},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "error" in content

    def test_query_with_scope(self):
        # First record something
        mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {
                "name": "neurosync_record",
                "arguments": {
                    "events": [{"type": "decision", "content": "Chose SQLite database"}],
                },
            },
        })
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 15,
            "method": "tools/call",
            "params": {
                "name": "neurosync_query",
                "arguments": {"query": "database", "scope": "episodes"},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "episodes" in content

    def test_theories_retire_missing_id(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 16,
            "method": "tools/call",
            "params": {
                "name": "neurosync_theories",
                "arguments": {"action": "retire"},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "error" in content

    def test_theories_detail_nonexistent(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 17,
            "method": "tools/call",
            "params": {
                "name": "neurosync_theories",
                "arguments": {"action": "detail", "theory_id": "nonexistent"},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "error" in content

    def test_theories_retire_nonexistent(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 18,
            "method": "tools/call",
            "params": {
                "name": "neurosync_theories",
                "arguments": {"action": "retire", "theory_id": "nonexistent"},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "error" in content

    def test_consolidate_dry_run(self):
        # Record enough episodes first
        for i in range(6):
            mcp._handle_request({
                "jsonrpc": "2.0",
                "id": 100 + i,
                "method": "tools/call",
                "params": {
                    "name": "neurosync_record",
                    "arguments": {
                        "events": [{"type": "decision", "content": f"Pattern episode {i}"}],
                    },
                },
            })
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 19,
            "method": "tools/call",
            "params": {
                "name": "neurosync_consolidate",
                "arguments": {"dry_run": True},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        # Should have enough episodes now
        assert "episodes_processed" in content or "pending_episodes" in content

    def test_send_and_error_response(self):
        resp = mcp._error_response(42, -32600, "Invalid Request")
        assert resp["id"] == 42
        assert resp["error"]["code"] == -32600

    def test_success_response(self):
        resp = mcp._success_response(42, {"data": "test"})
        assert resp["id"] == 42
        assert resp["result"]["data"] == "test"
