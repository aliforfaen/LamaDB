"""Pydantic models for ntfy module."""
from pydantic import BaseModel


class NtfyMessage(BaseModel):
    id: str
    time: int
    topic: str = ""
    title: str | None = None
    message: str
    priority: int = 3
    tags: list[str] = []


class NtfyHealth(BaseModel):
    reachable: bool
    topic: str
    message_count: int
