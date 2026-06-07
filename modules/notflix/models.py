"""Pydantic models for Notflix module."""
from typing import Any

from pydantic import BaseModel, Field


class NotflixStatus(BaseModel):
    """Response for GET /api/notflix/status."""

    data: dict[str, Any] | None = None
    ts: str | None = None


class NotflixHealth(BaseModel):
    """Response for GET /api/notflix/health."""

    reachable: bool
    reason: str | None = None


class RecentWatch(BaseModel):
    """A single recent watch from Tautulli."""

    user: str
    title: str
    date: int
    platform: str


class TautulliData(BaseModel):
    """Tautulli polling result."""

    active_streams: int = 0
    recent_watches: list[RecentWatch] = Field(default_factory=list)


class SonarrData(BaseModel):
    """Sonarr polling result."""

    series_count: int = 0
    total_episodes: int = 0
    episodes_available: int = 0
    missing_count: int = 0
    queue_count: int = 0
    recent_grabs: int = 0


class RadarrData(BaseModel):
    """Radarr polling result."""

    movie_count: int = 0
    movies_available: int = 0
    missing_count: int = 0
    queue_count: int = 0
    recent_grabs: int = 0
