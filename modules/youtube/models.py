"""Pydantic models for YouTube module."""
from datetime import datetime

from pydantic import BaseModel, Field


class YouTubeVideo(BaseModel):
    """A normalized YouTube video."""

    video_id: str = Field(..., description="YouTube video ID")
    title: str = Field(..., description="Video title")
    description: str | None = Field(default=None, description="Video description")
    channel_id: str | None = Field(default=None, description="Uploader channel ID")
    channel_title: str | None = Field(default=None, description="Uploader channel title")
    published_at: datetime | None = Field(default=None, description="Original publish time")
    thumbnail_url: str | None = Field(default=None, description="Best available thumbnail URL")
    playlist_id: str | None = Field(default=None, description="Source playlist ID if any")
    list_type: str = Field(default="unknown", description="watch_later | history | search | unknown")
    position: int | None = Field(default=None, description="Position in playlist")


class YouTubeStatus(BaseModel):
    """Response for GET /api/youtube/status."""

    data: dict | None = None
    ts: str | None = None


class YouTubeHealth(BaseModel):
    """Response for GET /api/youtube/health."""

    reachable: bool
    reason: str | None = None
