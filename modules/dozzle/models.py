"""Pydantic models for Dozzle module."""
from pydantic import BaseModel


class ContainerInfo(BaseModel):
    id: str
    name: str
    image: str
    status: str


class LogEntry(BaseModel):
    container_name: str
    level: str
    message: str
    timestamp: str


class DozzleSyncResult(BaseModel):
    errors: int
    warnings: int
    containers_scanned: int
