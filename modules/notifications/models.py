"""Pydantic models for notification rules."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    match_source: Optional[str] = None
    match_type: Optional[str] = None
    match_severity: Optional[str] = None
    match_tags: list[str] = []
    channel: str  # 'telegram', 'ntfy', 'webhook'
    channel_config: dict = Field(default_factory=dict)
    priority: str = 'normal'
    cooldown_seconds: int = 0


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    match_source: Optional[str] = None
    match_type: Optional[str] = None
    match_severity: Optional[str] = None
    match_tags: Optional[list[str]] = None
    channel: Optional[str] = None
    channel_config: Optional[dict] = None
    priority: Optional[str] = None
    cooldown_seconds: Optional[int] = None


class RuleResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    enabled: bool
    match_source: Optional[str] = None
    match_type: Optional[str] = None
    match_severity: Optional[str] = None
    match_tags: list[str]
    channel: str
    channel_config: dict
    priority: str
    cooldown_seconds: int
    last_fired_at: Optional[datetime] = None
    fire_count: int
    created_at: datetime
    updated_at: datetime


class FireRequest(BaseModel):
    event_id: int
    source: str
    type: str
    severity: str = 'info'
    title: str
    body: Optional[str] = None
    tags: list[str] = []


class FireResponse(BaseModel):
    event_id: int
    rules_matched: int
    notifications_sent: int
    results: list[dict]
