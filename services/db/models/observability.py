"""Observability and send queue tables."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field

from .base import SendQueueStatus, TimeStamped, utcnow


class Metric(TimeStamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=128)
    value: float = Field(default=0)
    labels: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))


class ErrorLog(TimeStamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    scope: str = Field(index=True, max_length=64)
    code: Optional[str] = Field(default=None, max_length=32)
    message: str
    context: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    ts: datetime = Field(default_factory=utcnow, index=True)


class SendQueue(TimeStamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    scope: str = Field(index=True, max_length=64)
    payload: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    status: SendQueueStatus = Field(default=SendQueueStatus.PENDING, index=True)
    next_retry_at: Optional[datetime] = Field(default=None, index=True)
    retry_count: int = Field(default=0)
