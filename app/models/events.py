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
