"""Structured logging: stderr-only, idempotent configuration, namespaced loggers, metrics."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from typing import Any

_configured = False


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON for structured log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


class Metrics:
    """Lightweight in-process metrics: counters and latency histograms."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._latencies: dict[str, list[float]] = {}
        self._started_at = time.time()

    def increment(self, name: str, count: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + count

    def record_latency(self, name: str, duration_ms: float) -> None:
        with self._lock:
            self._latencies.setdefault(name, []).append(duration_ms)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            latency_summary: dict[str, Any] = {}
            for name, values in self._latencies.items():
                if not values:
                    continue
                sorted_vals = sorted(values)
                count = len(sorted_vals)
                latency_summary[name] = {
                    "count": count,
                    "avg_ms": round(sum(sorted_vals) / count, 2),
                    "p50_ms": round(sorted_vals[count // 2], 2),
                    "p95_ms": round(sorted_vals[int(count * 0.95)], 2) if count > 1 else round(sorted_vals[0], 2),
                    "max_ms": round(sorted_vals[-1], 2),
                }
            return {
                "uptime_seconds": round(time.time() - self._started_at, 2),
                "operations": dict(self._counters),
                "latencies": latency_summary,
            }


metrics = Metrics()


def configure_logging(level: str = "INFO") -> None:
    """Configure logging once. Idempotent — safe to call multiple times."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    log_format = os.environ.get("NEUROSYNC_LOG_FORMAT", "text")
    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
    env_level = os.environ.get("NEUROSYNC_LOG_LEVEL", level)
    root = logging.getLogger("neurosync")
    root.addHandler(handler)
    root.setLevel(getattr(logging, env_level.upper(), logging.INFO))
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Get a namespaced logger under the neurosync hierarchy."""
    return logging.getLogger(f"neurosync.{name}")
