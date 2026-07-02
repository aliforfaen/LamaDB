"""Tests for Dozzle collector helpers: _sanitize, _fetch_containers, _fetch_container_logs."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys

sys.path.insert(0, "/home/messhias/LamaFiles/projects/lamadb")

from modules.dozzle.collector import _sanitize
from modules.dozzle.routes import _parse_since


# ── pure function tests (no fixtures needed) ──────────────────────────


def test_sanitize_strips_null_bytes():
    """Null bytes are removed from the text."""
    result = _sanitize("\x00test\x00")
    assert result == "test"


def test_sanitize_replaces_invalid_utf8():
    """Invalid UTF-8 surrogate-escaped sequences are replaced, not raised."""
    text = b"hello\xffworld".decode("utf-8", errors="surrogateescape")
    # Invalid byte gets replaced by Python's encode("utf-8", errors="replace")
    # which uses ? (0x3F) on this Python version
    result = _sanitize(text)
    assert "hello" in result
    assert "world" in result
    assert "?" in result


# ── _parse_since helper ──────────────────────────────────────────────


def test_parse_since_units():
    """_parse_since accepts s/m/h/d/w and defaults otherwise."""
    from datetime import timedelta
    assert _parse_since("30s") == timedelta(seconds=30)
    assert _parse_since("15m") == timedelta(minutes=15)
    assert _parse_since("1h") == timedelta(hours=1)
    assert _parse_since("2d") == timedelta(days=2)
    assert _parse_since("1w") == timedelta(weeks=1)
    assert _parse_since("") == timedelta(minutes=30)
    assert _parse_since("garbage") == timedelta(minutes=30)
    assert _parse_since("30x") == timedelta(minutes=30)


# ── mock-based async tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_containers_parses_sse():
    """_fetch_containers parses SSE events and returns container list."""
    containers_json = (
        '[{"id":"abc123","name":"web","host":"local","state":"running"},'
        '{"id":"def456","name":"db","host":"local","state":"stopped"}]'
    )
    sse_lines = [
        "event: containers-changed",
        "data: " + containers_json,
        "",
    ]

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = MagicMock(return_value=_async_iter(sse_lines))

    # client.stream() returns an async context manager synchronously
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.stream = MagicMock(return_value=mock_stream_ctx)

    with patch("modules.dozzle.collector.settings") as mock_settings:
        mock_settings.dozzle_url = "http://dozzle:8080"
        with patch(
            "modules.dozzle.collector.httpx.AsyncClient",
            return_value=mock_client,
        ):
            from modules.dozzle.collector import _fetch_containers

            result = await _fetch_containers()

    assert len(result) == 2
    assert result[0]["id"] == "abc123"
    assert result[0]["name"] == "web"
    assert result[0]["state"] == "running"
    assert result[1]["id"] == "def456"
    assert result[1]["name"] == "db"
    assert result[1]["state"] == "stopped"


@pytest.mark.asyncio
async def test_fetch_container_logs_parses_jsonl():
    """_fetch_container_logs parses Dozzle v10 JSONL lines into structured entries."""
    jsonl_lines = [
        json.dumps({"t": "", "m": {"level": "error", "message": "connection refused"}}),
        json.dumps({"t": "", "m": {"level": "warn", "message": "retrying"}}),
        json.dumps({"t": "", "m": {"level": "info", "message": "started"}}),
    ]
    raw_text = "\n".join(jsonl_lines)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = raw_text

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch("modules.dozzle.collector.settings") as mock_settings:
        mock_settings.dozzle_url = "http://dozzle:8080"
        with patch(
            "modules.dozzle.collector.httpx.AsyncClient",
            return_value=mock_client,
        ):
            from modules.dozzle.collector import _fetch_container_logs

            # collect() always passes from/to; verify they end up on the URL.
            result = await _fetch_container_logs(
                "local",
                "abc123",
                from_ts="2026-07-02T00:00:00+00:00",
                to_ts="2026-07-02T00:10:00+00:00",
            )

    called_url = mock_client.get.call_args[0][0]
    assert "from=2026-07-02T00" in called_url
    assert "to=2026-07-02T00" in called_url
    assert "levels=error" in called_url
    assert "levels=warn" in called_url

    assert len(result) == 3
    assert result[0]["level"] == "error"
    assert result[0]["message"] == "connection refused"
    assert result[1]["level"] == "warn"
    assert result[1]["message"] == "retrying"
    assert result[2]["level"] == "info"
    assert result[2]["message"] == "started"


@pytest.mark.asyncio
async def test_fetch_container_logs_without_bounds_still_works():
    """Backward-compat: omitting from_ts/to_ts preserves old behaviour."""
    jsonl_lines = [
        json.dumps({"t": "", "m": {"level": "info", "message": "started"}}),
    ]
    raw_text = "\n".join(jsonl_lines)

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = raw_text

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    with patch("modules.dozzle.collector.settings") as mock_settings:
        mock_settings.dozzle_url = "http://dozzle:8080"
        with patch(
            "modules.dozzle.collector.httpx.AsyncClient",
            return_value=mock_client,
        ):
            from modules.dozzle.collector import _fetch_container_logs

            result = await _fetch_container_logs("local", "abc123", from_ts=None, to_ts=None)

    called_url = mock_client.get.call_args[0][0]
    assert "from=" not in called_url
    assert "to=" not in called_url
    assert len(result) == 1


# ── helpers ───────────────────────────────────────────────────────────


async def _async_iter(items: list):
    """Yield items from a list as an async generator."""
    for item in items:
        yield item
