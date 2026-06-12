"""Pydantic models for the secrets module."""
from pydantic import BaseModel, Field
from typing import Optional


class SecretCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    service: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    secret_type: str = Field(..., pattern="^(api_key|oauth|login|token|custom)$")
    value: str = Field(..., min_length=1)
    extra_1: Optional[str] = None
    extra_2: Optional[str] = None
    priority: str = "primary"
    tags: list[str] = []
    owner_user_id: Optional[str] = None
    owner_group_id: Optional[str] = None
    expires_at: Optional[str] = None


class SecretUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    service: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    secret_type: Optional[str] = Field(None, pattern="^(api_key|oauth|login|token|custom)$")
    value: Optional[str] = None
    extra_1: Optional[str] = None
    extra_2: Optional[str] = None
    priority: Optional[str] = None
    tags: Optional[list[str]] = None
    owner_user_id: Optional[str] = None
    owner_group_id: Optional[str] = None
    expires_at: Optional[str] = None


class SecretResponse(BaseModel):
    id: str
    name: str
    service: str
    description: str
    secret_type: str
    priority: str
    tags: list[str]
    owner_user_id: Optional[str] = None
    owner_group_id: Optional[str] = None
    expires_at: Optional[str] = None
    last_revealed_at: Optional[str] = None
    created_at: str
    updated_at: str


class SecretRevealResponse(BaseModel):
    id: str
    value: str
    extra_1: Optional[str] = None
    extra_2: Optional[str] = None
    secret_type: str


class SecretAccessGrant(BaseModel):
    id: int
    secret_id: str
    grantee_type: str
    grantee_id: str
    grantee_name: str = ""
    access_level: str
    granted_by: Optional[str] = None
    granted_at: str


class AccessGrantCreate(BaseModel):
    grantee_type: str = Field(..., pattern="^(user|group)$")
    grantee_id: str
    access_level: str = "read"


class AccessRequestCreate(BaseModel):
    reason: str = ""
    requested_level: str = "read"


class AccessRequestResponse(BaseModel):
    id: int
    secret_id: str
    secret_name: str = ""
    requester_user_id: str
    requester_name: str = ""
    requested_level: str
    reason: str
    status: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    created_at: str


class AccessRequestUpdate(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected)$")
