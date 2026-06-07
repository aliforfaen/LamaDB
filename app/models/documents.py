"""Pydantic models for Document and DocumentLink."""
from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


class DocumentBase(BaseModel):
    """Base fields for Document."""

    source_type: str = Field(..., min_length=1, description="Source type (e.g., 'summary', 'agent_output')")
    title: str = Field(..., min_length=1, description="Document title")
    content: str | None = Field(default=None, description="Document content")
    metadata: dict = Field(default_factory=dict, description="Flexible JSON metadata")
    tags: list[str] = Field(default_factory=list, description="List of tags")


class DocumentCreate(DocumentBase):
    """Model for creating a document."""

    pass


class DocumentUpdate(BaseModel):
    """Model for updating a document. All fields optional."""

    source_type: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)
    content: str | None = None
    metadata: dict | None = None
    tags: list[str] | None = None


class Document(DocumentBase):
    """Document as stored in DB."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="Document UUID")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class DocumentLinkBase(BaseModel):
    """Base fields for DocumentLink."""

    target_id: UUID = Field(..., description="Target document UUID")
    link_type: str = Field(..., min_length=1, description="Type of relationship")
    context: str | None = Field(default=None, description="Context or description of the link")


class DocumentLinkCreate(DocumentLinkBase):
    """Model for creating a document link."""

    pass


class DocumentLink(DocumentLinkBase):
    """DocumentLink as stored in DB."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Link ID")
    source_id: UUID = Field(..., description="Source document UUID")
    created_at: datetime = Field(..., description="Creation timestamp")


class DocumentLinkResponse(BaseModel):
    """Response model for a document link with source details."""

    id: int
    source_id: UUID
    target_id: UUID
    link_type: str
    context: str | None
    created_at: datetime
    target_title: str | None = None
