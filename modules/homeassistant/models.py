"""Pydantic models for Home Assistant data."""
from pydantic import BaseModel, Field
from typing import Any, Optional
from datetime import datetime


class HAEntityState(BaseModel):
    entity_id: str
    state: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    last_changed: Optional[str] = None
    last_updated: Optional[str] = None


class HASnapshot(BaseModel):
    entities: list[HAEntityState]
    ts: str  # ISO timestamp


class ServiceCallRequest(BaseModel):
    domain: str = Field(..., description="Service domain (e.g. light, switch, climate)")
    service: str = Field(..., description="Service name (e.g. turn_on, turn_off)")
    entity_id: Optional[str] = Field(None, description="Target entity_id")
    data: Optional[dict[str, Any]] = Field(default_factory=dict, description="Additional service data")


class ServiceCallResponse(BaseModel):
    success: bool
    message: str
    changed_states: Optional[list[dict]] = None
