"""Pydantic models for the Feeds RSS generator module."""
import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")


class FeedBase(BaseModel):
    """Base fields for Feed."""

    name: str = Field(..., min_length=1, max_length=255, description="Feed name")
    slug: str = Field(..., min_length=1, max_length=100, description="URL-safe slug")
    description: str | None = Field(default=None, description="Feed description")
    filter_tags: list[str] = Field(default_factory=list, description="Tags to filter documents (ANY match)")
    filter_source_types: list[str] = Field(
        default_factory=list,
        description="Source types to filter documents (empty = all source types)"
    )
    max_items: int = Field(default=50, ge=1, le=200, description="Maximum items in RSS feed")

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        if not SLUG_PATTERN.match(v):
            raise ValueError("Slug must contain only lowercase letters, numbers, and hyphens")
        return v


class FeedCreate(FeedBase):
    """Model for creating a feed."""

    pass


class FeedUpdate(BaseModel):
    """Model for updating a feed. All fields optional."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, max_length=100)
    description: str | None = None
    filter_tags: list[str] | None = None
    filter_source_types: list[str] | None = None
    max_items: int | None = Field(default=None, ge=1, le=200)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str | None) -> str | None:
        if v is not None and not SLUG_PATTERN.match(v):
            raise ValueError("Slug must contain only lowercase letters, numbers, and hyphens")
        return v


class Feed(FeedBase):
    """Feed as stored in DB and returned by API."""

    model_config = {"from_attributes": True}

    id: UUID = Field(..., description="Feed UUID")
    created_at: datetime = Field(..., description="Creation timestamp")
