"""Pydantic models for Uptime Kuma webhook module."""
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, field_validator


class HeartbeatPayload(BaseModel):
    """Heartbeat data from Uptime Kuma webhook."""

    model_config = ConfigDict(extra='allow')

    status: int = Field(..., description="Status: 0=DOWN, 1=UP, 2=pending, 3=maintained")
    msg: str = Field(default="", description="Status message")
    duration: int = Field(default=0, description="Duration in milliseconds")
    time: str = Field(default="", description="ISO timestamp of the heartbeat")


class KumaTag(BaseModel):
    """Tag object from Uptime Kuma."""

    model_config = ConfigDict(extra='allow')

    tag_id: int
    monitor_id: int | None = None
    name: str
    value: str = ""
    color: str = ""


class MonitorPayload(BaseModel):
    """Monitor data from Uptime Kuma webhook."""

    model_config = ConfigDict(extra='allow')

    id: int = Field(..., description="Uptime Kuma monitor ID")
    name: str = Field(default="", description="Monitor name")
    url: str = Field(default="", description="Monitor URL")
    tags: list[KumaTag] = Field(default_factory=list, description="Uptime Kuma tags")

    @field_validator('tags', mode='before')
    @classmethod
    def normalize_tags(cls, v):
        """Accept both list of dicts and list of strings."""
        if not v:
            return []
        result = []
        for tag in v:
            if isinstance(tag, dict):
                result.append(KumaTag(**tag))
            elif isinstance(tag, str):
                # Legacy format: just tag names
                result.append(KumaTag(tag_id=0, name=tag))
        return result


class UptimeWebhookPayload(BaseModel):
    """Full Uptime Kuma webhook payload."""

    heartbeat: HeartbeatPayload | None = None
    monitor: MonitorPayload | None = None


class MonitorStatus(BaseModel):
    """Monitor status as stored in the database."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    monitor_id: str
    monitor_name: str
    monitor_url: str | None
    status: int
    msg: str | None
    duration_ms: int | None
    tags: list[str] | None = None
    received_at: datetime


class CurrentStatus(BaseModel):
    """Current (latest) status of a monitor, returned by the API."""

    monitor_id: str = Field(..., description="Uptime Kuma monitor ID")
    monitor_name: str = Field(..., description="Monitor name")
    monitor_url: str | None = Field(..., description="Monitor URL")
    status: int = Field(..., description="Latest status code")
    msg: str | None = Field(..., description="Latest status message")
    duration_ms: int | None = Field(..., description="Latest duration in ms")
    received_at: datetime | None = Field(default=None, description="When this status was received")


class WebhookResponse(BaseModel):
    """Response from the webhook endpoint."""

    received: bool = Field(default=True, description="Whether the webhook was received")


# ---------------------------------------------------------------------------
# Topology models
# ---------------------------------------------------------------------------

STATUS_LABEL = {
    0: "DOWN",
    1: "UP",
    2: "PENDING",
    3: "MAINTAINED",
}


class TopologyService(BaseModel):
    """A service monitor belonging to a host."""

    monitor_id: str
    name: str
    url: str | None = None
    status: int
    status_label: str
    msg: str | None = None
    tags: list[str] = []


class TopologyHost(BaseModel):
    """A host node in the topology."""

    name: str
    host_key: str
    monitor_id: str
    status: int
    status_label: str
    msg: str | None = None
    total_services: int
    up_count: int
    services: list[TopologyService] = []


class TopologySummary(BaseModel):
    """Summary counts for the topology."""

    total_hosts: int
    hosts_up: int
    total_services: int
    services_up: int
    orphans: int


class TopologyResponse(BaseModel):
    """Full topology response with hosts, orphans, and summary."""

    hosts: list[TopologyHost] = []
    orphans: list[TopologyService] = []
    summary: TopologySummary
