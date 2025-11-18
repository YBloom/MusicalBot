"""Play, alias, and source link models."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlalchemy.orm import Mapped, relationship
from sqlmodel import Field, Relationship, SQLModel

from .base import PlaySource, TimeStamped


class Play(TimeStamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=256)
    name_norm: str = Field(index=True, max_length=256)
    default_city_norm: Optional[str] = Field(default=None, index=True, max_length=64)
    note: Optional[str] = Field(default=None)

    aliases: Mapped[List["PlayAlias"]] = Relationship(
        back_populates="play",
        sa_relationship=relationship("PlayAlias", back_populates="play"),
    )
    source_links: Mapped[List["PlaySourceLink"]] = Relationship(
        back_populates="play",
        sa_relationship=relationship("PlaySourceLink", back_populates="play"),
    )
    snapshots: Mapped[List["PlaySnapshot"]] = Relationship(
        back_populates="play",
        sa_relationship=relationship("PlaySnapshot", back_populates="play"),
    )


class PlayAlias(TimeStamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    play_id: int = Field(foreign_key="play.id", nullable=False, index=True)
    alias: str = Field(index=True, max_length=256)
    alias_norm: str = Field(index=True, max_length=256)
    source: Optional[str] = Field(default=None, max_length=32)
    weight: int = Field(default=0)
    no_response_count: int = Field(default=0)
    last_used_at: Optional[datetime] = Field(default=None)

    play: Mapped["Play"] = Relationship(
        back_populates="aliases",
        sa_relationship=relationship("Play", back_populates="aliases"),
    )

    __table_args__ = (
        UniqueConstraint("play_id", "alias_norm", name="uq_play_alias_norm"),
    )


class PlaySourceLink(TimeStamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    play_id: int = Field(foreign_key="play.id", nullable=False, index=True)
    source: PlaySource = Field(nullable=False, index=True)
    source_id: str = Field(nullable=False, index=True, max_length=128)
    title_at_source: Optional[str] = Field(default=None, max_length=256)
    city_hint: Optional[str] = Field(default=None, max_length=64)
    confidence: float = Field(default=0.0)
    last_sync_at: Optional[datetime] = Field(default=None)
    payload_hash: Optional[str] = Field(default=None, max_length=64)

    play: Mapped["Play"] = Relationship(
        back_populates="source_links",
        sa_relationship=relationship("Play", back_populates="source_links"),
    )

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_source_link"),
    )


class PlaySnapshot(TimeStamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    play_id: int = Field(foreign_key="play.id", nullable=False, index=True)
    city_norm: Optional[str] = Field(default=None, index=True, max_length=64)
    payload: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    last_success_at: Optional[datetime] = Field(default=None)
    ttl_seconds: int = Field(default=0)
    stale: bool = Field(default=False)

    play: Mapped["Play"] = Relationship(
        back_populates="snapshots",
        sa_relationship=relationship("Play", back_populates="snapshots"),
    )
