"""Pydantic models for the groups module."""
from pydantic import BaseModel, Field
from typing import Optional


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    description: str = ""


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    description: Optional[str] = None


class GroupMember(BaseModel):
    user_id: str
    user_name: str
    role: str
    added_at: str


class GroupResponse(BaseModel):
    id: str
    name: str
    description: str
    member_count: int
    created_by: Optional[str] = None
    created_at: str
    updated_at: str


class GroupDetail(GroupResponse):
    members: list[GroupMember] = []


class MemberAdd(BaseModel):
    user_id: str
    role: str = "member"


class MemberUpdate(BaseModel):
    role: str
