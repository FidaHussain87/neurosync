"""Tests for logging.py — structured logging configuration."""

from __future__ import annotations

import logging


class TestLogging:
    def test_configure_idempotent(self):
        """Calling configure_logging() twice should not duplicate handlers."""
        import neurosync.logging as ns_logging

        # Reset state for test isolation
        original = ns_logging._configured
        ns_logging._configured = False
        root = logging.getLogger("neurosync")
        initial_handlers = len(root.handlers)

        ns_logging.configure_logging()
        after_first = len(root.handlers)

        ns_logging.configure_logging()
        after_second = len(root.handlers)

        assert after_first == initial_handlers + 1
        assert after_second == after_first  # No duplicate

        # Restore
        ns_logging._configured = original

    def test_get_logger_namespace(self):
        from neurosync.logging import get_logger

        logger = get_logger("db")
        assert logger.name == "neurosync.db"

        logger2 = get_logger("vectorstore")
        assert logger2.name == "neurosync.vectorstore"
