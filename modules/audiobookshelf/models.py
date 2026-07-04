"""Pydantic models for the Audiobookshelf module."""
from typing import Any

from pydantic import BaseModel, Field


class AudiobookshelfLibrary(BaseModel):
    """One library (book or podcast) returned by ABS."""

    id: str
    name: str
    media_type: str = Field(..., description="'book' or 'podcast'")
    icon: str | None = None
    item_count: int = 0


class AudiobookshelfBook(BaseModel):
    """A single audiobookshelf item as stored on a document."""

    item_id: str
    library_id: str
    library_name: str | None = None
    title: str
    author: str | None = None
    narrator: str | None = None
    description: str | None = None
    isbn: str | None = None
    language: str | None = None
    published_year: int | None = None
    genres: list[str] = Field(default_factory=list)
    series: list[str] = Field(default_factory=list)
    duration: float | None = None
    track_count: int | None = None
    added_at: str | None = None
    updated_at: str | None = None
    progress_percent: float | None = None
    is_finished: bool = False


class AudiobookshelfSnapshot(BaseModel):
    """Latest library + listening snapshot stored on an event."""

    libraries: list[AudiobookshelfLibrary] = Field(default_factory=list)
    book_count: int = 0
    finished_count: int = 0
    in_progress_count: int = 0
    recently_added: list[AudiobookshelfBook] = Field(default_factory=list)


class AudiobookshelfStatus(BaseModel):
    """Response for GET /api/audiobookshelf/status."""

    data: dict[str, Any] | None = None
    ts: str | None = None


class AudiobookshelfHealth(BaseModel):
    """Response for GET /api/audiobookshelf/health."""

    reachable: bool
    reason: str | None = None