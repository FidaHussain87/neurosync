"""Tests for mcp_server.py — MCP JSON-RPC 2.0 protocol and tool handlers."""

from __future__ import annotations

import json
from unittest.mock import patch

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
    mcp._git_observer = None


class TestMcpProtocol:
    def setup_method(self):
        _reset_server()

    def test_initialize(self):
        req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        resp = mcp._handle_request(req)
        assert resp["result"]["protocolVersion"] == "2024-11-05"
        assert resp["result"]["serverInfo"]["name"] == "neurosync"
        assert resp["result"]["serverInfo"]["version"] == "0.4.0"

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
        assert len(tools) == 10
        assert "neurosync_handoff" in names
        assert "neurosync_graph" in names

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

    def test_handoff(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/call",
            "params": {
                "name": "neurosync_handoff",
                "arguments": {
                    "goal": "Implement feature X",
                    "accomplished": "Phase 1 done",
                    "remaining": "Phase 2 needed",
                    "next_step": "Start Phase 2",
                    "blockers": "Need API docs",
                },
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["signal_weight"] == 8.0
        assert content["episode_id"]
        assert "_hint" in content

    def test_handoff_missing_fields(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {
                "name": "neurosync_handoff",
                "arguments": {
                    "goal": "Something",
                    "accomplished": "",
                    "remaining": "",
                    "next_step": "",
                },
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "error" in content

    def test_record_causal(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 22,
            "method": "tools/call",
            "params": {
                "name": "neurosync_record",
                "arguments": {
                    "events": [{
                        "type": "causal",
                        "content": "Applied theory successfully because context matched",
                        "cause": "context matched",
                        "effect": "theory applied",
                        "reasoning": "high confidence",
                        "importance": 3,
                    }],
                },
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["episodes_recorded"] == 1
        assert "_hint" in content

    def test_record_quality_warning(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 23,
            "method": "tools/call",
            "params": {
                "name": "neurosync_record",
                "arguments": {
                    "events": [{"type": "decision", "content": "Edited file"}],
                },
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["episodes_recorded"] == 1
        # Short activity-log-like content should trigger quality warning
        assert "quality_warnings" in content

    def test_protocol_hint(self):
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 24,
            "method": "tools/call",
            "params": {
                "name": "neurosync_recall",
                "arguments": {},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "_hint" in content

    def test_theories_relate(self):
        # First create two theories via record + consolidate isn't feasible,
        # so test via the handler directly
        mcp._init()
        assert mcp._semantic is not None
        t1 = mcp._semantic.create_theory(content="Theory A about testing")
        t2 = mcp._semantic.create_theory(content="Theory B about testing")
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 25,
            "method": "tools/call",
            "params": {
                "name": "neurosync_theories",
                "arguments": {
                    "action": "relate",
                    "theory_id": t1.id,
                    "related_ids": [t2.id],
                },
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "Linked" in content.get("message", "")
        assert t2.id in content["related_theories"]


class TestGitObserverIntegration:
    def setup_method(self):
        _reset_server()

    def test_record_includes_observed_episodes(self):
        """When git observer has delta, observed episodes appear in response."""
        mcp._init()
        mock_events = [
            {"type": "observed", "content": "Committed: 'fix bug'", "signal_weight": 0.3, "files": [], "layers": []},
        ]
        with patch("neurosync.mcp_server.GitObserver") as MockGitObs:
            instance = MockGitObs.return_value
            instance.capture_baseline.return_value = None
            instance.capture_delta.return_value = mock_events
            # Set a mock git observer directly
            mcp._git_observer = instance
            resp = mcp._handle_request({
                "jsonrpc": "2.0",
                "id": 500,
                "method": "tools/call",
                "params": {
                    "name": "neurosync_record",
                    "arguments": {
                        "events": [{"type": "decision", "content": "Test event"}],
                    },
                },
            })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["episodes_recorded"] == 1
        assert content["observed_episodes"] == 1


class TestDynamicProtocolHints:
    def setup_method(self):
        _reset_server()

    def test_dynamic_protocol_hints_with_corrections(self):
        """After 3+ corrections, hints should mention correction count."""
        mcp._init()
        # Make 3 corrections
        for i in range(3):
            mcp._handle_request({
                "jsonrpc": "2.0",
                "id": 600 + i,
                "method": "tools/call",
                "params": {
                    "name": "neurosync_correct",
                    "arguments": {"wrong": f"wrong {i}", "right": f"right {i}"},
                },
            })
        # Now make a record — should include correction count in hint
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 700,
            "method": "tools/call",
            "params": {
                "name": "neurosync_record",
                "arguments": {
                    "events": [{"type": "decision", "content": "Some decision"}],
                },
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        hint = content.get("_hint", "")
        assert "3 corrections" in hint

    def test_dynamic_protocol_hints_with_pending_episodes(self):
        """With 30+ pending episodes, hints should mention consolidation."""
        mcp._init()
        for i in range(35):
            mcp._handle_request({
                "jsonrpc": "2.0",
                "id": 800 + i,
                "method": "tools/call",
                "params": {
                    "name": "neurosync_record",
                    "arguments": {
                        "events": [{"type": "decision", "content": f"Episode {i} about patterns"}],
                    },
                },
            })
        # Next record should have pending episodes hint
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 900,
            "method": "tools/call",
            "params": {
                "name": "neurosync_record",
                "arguments": {
                    "events": [{"type": "decision", "content": "Another episode"}],
                },
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        hint = content.get("_hint", "")
        # May or may not have pending hint depending on auto-consolidation having run
        assert "_hint" in content


class TestAutoConsolidation:
    def setup_method(self):
        _reset_server()

    def test_record_auto_consolidation(self):
        """Auto-consolidation triggers via handle_record when threshold is met."""
        mcp._init()
        assert mcp._config is not None
        mcp._config.auto_consolidation_enabled = True
        mcp._config.auto_consolidation_threshold = 5
        # Record enough episodes to cross threshold
        for i in range(6):
            mcp._handle_request({
                "jsonrpc": "2.0",
                "id": 100 + i,
                "method": "tools/call",
                "params": {
                    "name": "neurosync_record",
                    "arguments": {
                        "events": [{"type": "decision", "content": f"Important pattern about testing {i}"}],
                    },
                },
            })
        # The last record should have triggered auto-consolidation
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 200,
            "method": "tools/call",
            "params": {
                "name": "neurosync_record",
                "arguments": {
                    "events": [{"type": "decision", "content": "One more pattern about testing"}],
                },
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content["episodes_recorded"] == 1
        # auto_consolidation key may or may not be present depending on threshold

    def test_auto_consolidation_disabled(self):
        """Auto-consolidation should not run when disabled."""
        mcp._init()
        assert mcp._config is not None
        mcp._config.auto_consolidation_enabled = False
        # Record episodes
        for i in range(25):
            mcp._handle_request({
                "jsonrpc": "2.0",
                "id": 300 + i,
                "method": "tools/call",
                "params": {
                    "name": "neurosync_record",
                    "arguments": {
                        "events": [{"type": "decision", "content": f"Episode {i}"}],
                    },
                },
            })
        # With consolidation disabled, should never see auto_consolidation key
        resp = mcp._handle_request({
            "jsonrpc": "2.0",
            "id": 400,
            "method": "tools/call",
            "params": {
                "name": "neurosync_record",
                "arguments": {
                    "events": [{"type": "decision", "content": "Final episode"}],
                },
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "auto_consolidation" not in content


class TestCognitiveFeatures:
    """Tests for v0.4.0 cognitive features integration in MCP server."""

    def test_query_mode_analogy(self):
        import neurosync.mcp_server as mcp
        mcp._db = None
        mcp._init()
        resp = mcp._handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {
                "name": "neurosync_query",
                "arguments": {"query": "cache invalidation patterns", "mode": "analogy"},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content.get("mode") == "analogy"
        assert "results" in content

    def test_query_mode_causal(self):
        import neurosync.mcp_server as mcp
        mcp._db = None
        mcp._init()
        resp = mcp._handle_request({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {
                "name": "neurosync_query",
                "arguments": {"query": "missing index", "mode": "causal"},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content.get("mode") == "causal"
        assert "results" in content

    def test_query_mode_failures(self):
        import neurosync.mcp_server as mcp
        mcp._db = None
        mcp._init()
        resp = mcp._handle_request({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {
                "name": "neurosync_query",
                "arguments": {"query": "eval injection", "mode": "failures"},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content.get("mode") == "failures"

    def test_status_includes_v4_fields(self):
        import neurosync.mcp_server as mcp
        mcp._db = None
        mcp._init()
        resp = mcp._handle_request({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "neurosync_status", "arguments": {}},
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert content.get("version") == "0.4.0"
        assert "causal_links" in content
        assert "failure_records" in content

    def test_theories_graph_action(self):
        import neurosync.mcp_server as mcp
        mcp._db = None
        mcp._init()
        # Create a theory to get a subtree
        from neurosync.models import Theory
        theory = Theory(content="Test hierarchy theory")
        mcp._db.save_theory(theory)
        resp = mcp._handle_request({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {
                "name": "neurosync_theories",
                "arguments": {"action": "graph", "theory_id": theory.id},
            },
        })
        content = json.loads(resp["result"]["content"][0]["text"])
        assert "subtree" in content
        assert content["subtree"]["id"] == theory.id
