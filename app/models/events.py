"""Pydantic models for Event."""
from datetime import datetime

from pydantic import BaseModel, Field, ConfigDict


class EventBase(BaseModel):
    """Base fields for Event."""

    source: str = Field(..., min_length=1, description="Event source")
    type: str = Field(..., min_length=1, description="Event type")
    severity: str = Field(default="info", description="Severity level")
    title: str = Field(..., min_length=1, description="Event title")
    body: str | None = Field(default=None, description="Event body/description")
    metadata: dict = Field(default_factory=dict, description="Flexible JSON metadata")
    ticker: bool = Field(default=False, description="Whether to show this event in the dashboard ticker")
    tags: list[str] = Field(default_factory=list, description="Tags for filtering and display")


class EventCreate(EventBase):
    """Model for creating an event."""

    pass


class Event(EventBase):
    """Event as stored in DB."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Event ID")
    ts: datetime = Field(..., description="Event timestamp")
    processed: bool = Field(default=False, description="Whether event has been processed")


class EventPatch(BaseModel):
    """Model for patching an event (mark processed)."""

    processed: bool = Field(default=True, description="Mark event as processed")


class BulkDismissRequest(BaseModel):
    """Request body for POST /api/events/bulk-dismiss."""

    event_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Event IDs to mark processed (1-500 entries).",
    )


class BulkDismissResponse(BaseModel):
    """Response for POST /api/events/bulk-dismiss.

    `count` is the number of rows actually transitioned to processed=true
    (i.e. were not already processed). `event_ids` is the subset of the
    request that was updated — useful for the frontend to know which ids
    were no-ops (unknown or already dismissed).
    """

    count: int = Field(..., ge=0, description="Number of events marked processed")
    event_ids: list[int] = Field(
        default_factory=list,
        description="Subset of input event_ids actually updated",
    )
