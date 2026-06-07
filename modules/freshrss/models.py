"""Pydantic models for FreshRSS module."""
from pydantic import BaseModel


class FeedInfo(BaseModel):
    id: str
    title: str
    feedUrl: str
    siteUrl: str


class ArticleSyncResult(BaseModel):
    new_count: int
    total_count: int
    feeds_synced: int
    last_sync: str
