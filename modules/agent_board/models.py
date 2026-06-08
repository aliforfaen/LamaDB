from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    task_type: str = "general"
    priority: str = "normal"  # low, normal, high, critical
    assigned_to: Optional[str] = None
    created_by: Optional[str] = None
    metadata: dict = {}


class TaskResponse(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    task_type: str
    priority: str
    status: str
    created_by: Optional[str] = None
    claimed_by: Optional[str] = None
    assigned_to: Optional[str] = None
    metadata: dict
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    claimed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TaskClaim(BaseModel):
    claimed_by: str


class TaskComplete(BaseModel):
    result: Optional[dict] = None
    error: Optional[str] = None


class MessageCreate(BaseModel):
    to_agent: Optional[str] = None
    inbox_for: Optional[str] = None
    subject: str
    body: Optional[str] = None
    message_type: str = "info"
    parent_id: Optional[int] = None
    reply_to: Optional[int] = None
    metadata: dict = {}


class MessageResponse(BaseModel):
    id: int
    from_agent: str
    to_agent: Optional[str] = None
    inbox_for: Optional[str] = None
    subject: str
    body: Optional[str] = None
    message_type: str
    parent_id: Optional[int] = None
    reply_to: Optional[int] = None
    metadata: dict
    read: bool
    created_at: datetime