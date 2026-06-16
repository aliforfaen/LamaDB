"""In-memory MCP tool call stats tracker.

Provides per-tool call counts, error counts, total/avg duration, and
last-call/last-error timestamps. Resets on process restart.

Used by the admin /stats endpoint and the /mcp server instrumentation.
"""
import threading
import time
from typing import Any

_lock = threading.Lock()
_stats: dict[str, dict[str, Any]] = {}


def _ensure(name: str) -> dict[str, Any]:
    if name not in _stats:
        _stats[name] = {
            "calls": 0,
            "errors": 0,
            "total_ms": 0.0,
            "last_call_ts": None,
            "last_error_ts": None,
            "last_error": None,
        }
    return _stats[name]


def track_call(name: str, duration_ms: float) -> None:
    """Record a successful tool call."""
    with _lock:
        s = _ensure(name)
        s["calls"] += 1
        s["total_ms"] += float(duration_ms)
        s["last_call_ts"] = time.time()


def track_error(name: str, error: str, duration_ms: float) -> None:
    """Record a failed tool call (still counts as a call)."""
    with _lock:
        s = _ensure(name)
        s["calls"] += 1
        s["errors"] += 1
        s["total_ms"] += float(duration_ms)
        s["last_call_ts"] = time.time()
        s["last_error_ts"] = time.time()
        # Truncate to keep the dict small.
        s["last_error"] = (error or "")[:500]


def get_stats() -> dict[str, dict[str, Any]]:
    """Return a snapshot of stats per tool, with avg_duration_ms computed."""
    with _lock:
        out: dict[str, dict[str, Any]] = {}
        for name, s in _stats.items():
            calls = s["calls"]
            avg = (s["total_ms"] / calls) if calls else 0.0
            out[name] = {
                "calls": calls,
                "errors": s["errors"],
                "total_ms": round(s["total_ms"], 3),
                "avg_duration_ms": round(avg, 3),
                "last_call_ts": s["last_call_ts"],
                "last_error_ts": s["last_error_ts"],
                "last_error": s["last_error"],
            }
        return out


def reset_stats() -> None:
    """Clear all stats. Intended for tests."""
    with _lock:
        _stats.clear()
