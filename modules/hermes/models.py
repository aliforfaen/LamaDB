"""Pydantic models for Hermes module."""
from pydantic import BaseModel


class HermesStatus(BaseModel):
    """Hermes server status."""
    version: str
    gateway_running: bool
    gateway_state: str
    active_sessions: int
    platforms: dict[str, dict] = {}


class HermesSessionStats(BaseModel):
    """Aggregate session statistics."""
    total: int
    active_store: int
    archived: int
    messages: int
    by_source: dict[str, int] = {}


class HermesSystemStats(BaseModel):
    """Host system metrics."""
    hostname: str
    hermes_version: str
    cpu_count: int
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    uptime_seconds: int
    process_rss: int
    process_threads: int


class HermesSessionSummary(BaseModel):
    """Per-session analytics summary."""
    id: str
    source: str
    model: str
    message_count: int
    tool_call_count: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    reasoning_tokens: int
    api_call_count: int
    estimated_cost_usd: float | None = None
    title: str | None = None
    preview: str | None = None
    started_at: float | None = None
    ended_at: float | None = None
    end_reason: str | None = None


class HermesHealth(BaseModel):
    """Reachability check."""
    reachable: bool
    url: str
    version: str | None = None
    gateway_running: bool | None = None
    error: str | None = None



# ---------------------------------------------------------------------------
# Ingest models — what Hermes pushes to LamaDB
# ---------------------------------------------------------------------------

class IngestPayload(BaseModel):
    """Top-level ingest envelope from Hermes."""
    event_type: str  # session_finalize, llm_call, credential_error, gateway_status
    timestamp: float  # unix timestamp
    data: dict  # event-specific payload (see sub-models below)


class IngestResponse(BaseModel):
    """Response from ingest endpoint."""
    accepted: bool
    event_id: int | None = None
    doc_id: str | None = None
    detail: str = ""


# ---------------------------------------------------------------------------
# Historical query / dashboard models
# ---------------------------------------------------------------------------

class CostRollup(BaseModel):
    """Daily cost rollup for dashboard."""
    date: str  # YYYY-MM-DD
    total_cost_usd: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    reasoning_tokens: int
    session_count: int
    by_model: dict[str, float] = {}  # model -> cost
    by_provider: dict[str, float] = {}  # provider -> cost


class AgentHealthSnapshot(BaseModel):
    """Agent health status for dashboard."""
    gateway_uptime_pct: float
    recent_errors: int  # last 24h
    credential_failures: int  # last 24h
    active_sessions: int
    total_sessions_24h: int
    messages_24h: int
    by_source: dict[str, int] = {}
    credential_pool: dict[str, str] = {}  # provider -> status