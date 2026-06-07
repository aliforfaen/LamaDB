"""Pydantic models for the Wiki module."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class ScratchpadEntry(BaseModel):
    """A scratchpad entry stored in the documents table."""

    id: str = Field(..., description="Document UUID")
    content: str = Field(..., description="Entry content")
    created_at: datetime = Field(..., description="When the entry was created")


class WikiPage(BaseModel):
    """A wiki page file discovered on the filesystem."""

    path: str = Field(..., description="Relative path from wiki root, e.g. entities/homelab-services.md")
    title: str = Field(..., description="Page title (derived from filename or first heading)")
    section: str = Field(..., description="Top-level directory section (entities, concepts, projects, raw, etc.)")
    size: int = Field(..., description="File size in bytes")


class WikiPageContent(BaseModel):
    """The full content of a wiki page."""

    path: str = Field(..., description="Relative path from wiki root")
    title: str = Field(..., description="Page title")
    content: str = Field(..., description="Raw markdown content")
    last_modified: datetime = Field(..., description="File last-modified timestamp")


class WikiLogEntry(BaseModel):
    """A wiki or scratchpad activity log entry from the events table."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Event ID")
    ts: datetime = Field(..., description="Event timestamp")
    source: str = Field(..., description="Event source (wiki or scratchpad)")
    title: str = Field(..., description="Event title")
    severity: str = Field(default="info", description="Severity level")
    body: str | None = Field(default=None, description="Event body")


class ScratchpadCreate(BaseModel):
    """Request body for creating a scratchpad entry."""

    content: str = Field(..., min_length=1, description="The scratchpad text to save")
    title: str = Field(default="Scratchpad", description="Entry title")


class WikiPageCreate(BaseModel):
    """Request body for creating a wiki page."""

    title: str = Field(..., description="Page title")
    content: str = Field(default="", description="Markdown body")
    path: str = Field(..., description="Filesystem path, e.g. 'entities/my-page.md'")
    tags: list[str] = Field(default_factory=list, description="Tag strings")


class WikiPageUpdate(BaseModel):
    """Request body for updating a wiki page."""

    title: Optional[str] = Field(default=None, description="New page title")
    content: Optional[str] = Field(default=None, description="New markdown content")
    tags: Optional[list[str]] = Field(default=None, description="New tag list")


class SearchResult(BaseModel):
    """A wiki search result."""

    path: str = Field(..., description="Relative path of the matching page")
    title: str = Field(..., description="Page title")
    snippet: str = Field(..., description="Text snippet around the match")
