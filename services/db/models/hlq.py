"""呼啦圈相关表."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship

from .base import HLQTicketStatus, TimeStamped


class HLQEvent(TimeStamped, table=True):
    hlq_event_id: str = Field(primary_key=True, max_length=64)
    play_id: Optional[int] = Field(default=None, foreign_key="play.id", index=True)
    title: str = Field(max_length=256)
    title_norm: str = Field(index=True, max_length=256)
    location: Optional[str] = Field(default=None, max_length=128)
    start_time: Optional[datetime] = Field(default=None, index=True)
    update_time: Optional[datetime] = Field(default=None, index=True)

    tickets: list["HLQTicket"] = Relationship(
        sa_relationship=relationship("HLQTicket", back_populates="event"),
    )


class HLQTicket(TimeStamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: str = Field(index=True, max_length=64)
    hlq_event_id: str = Field(foreign_key="hlqevent.hlq_event_id", index=True)
    status: HLQTicketStatus = Field(default=HLQTicketStatus.UNKNOWN, index=True)
    price: Optional[float] = Field(default=None)
    total: Optional[int] = Field(default=None)
    left: Optional[int] = Field(default=None)
    valid_from: Optional[datetime] = Field(default=None)
    start_time: Optional[datetime] = Field(default=None)
    payload: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))

    event: "HLQEvent" = Relationship(
        sa_relationship=relationship("HLQEvent", back_populates="tickets"),
    )
