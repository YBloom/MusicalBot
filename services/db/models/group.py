"""Group and membership tables."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship

from .base import GroupType, SoftDelete, TimeStamped, utcnow


class Group(TimeStamped, SoftDelete, table=True):
    group_id: str = Field(primary_key=True, max_length=32)
    name: Optional[str] = Field(default=None, max_length=128)
    group_type: GroupType = Field(default=GroupType.BROADCAST, nullable=False, index=True)
    active: bool = Field(default=True, nullable=False)
    extra_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))

    members: list["Membership"] = Relationship(
        sa_relationship=relationship("Membership", back_populates="group"),
    )


class Membership(TimeStamped, table=True):
    """用户-群 关系；多对多中间表。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(foreign_key="user.user_id", index=True)
    group_id: str = Field(foreign_key="group.group_id", index=True)
    role: Optional[str] = Field(default=None, max_length=32)
    joined_at: Optional[datetime] = Field(default_factory=utcnow)
    receive_broadcast: bool = Field(default=True, nullable=False)

    user: "User" = Relationship(
        sa_relationship=relationship("User", back_populates="memberships"),
    )
    group: "Group" = Relationship(
        sa_relationship=relationship("Group", back_populates="members"),
    )
