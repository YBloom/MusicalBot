"""Group and membership tables."""

from datetime import datetime
from typing import List, Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

from .base import GroupType, SoftDelete, TimeStamped, utcnow


class Group(TimeStamped, SoftDelete, SQLModel, table=True):
    group_id: str = Field(primary_key=True, max_length=32)
    name: Optional[str] = Field(default=None, max_length=128)
    group_type: GroupType = Field(default=GroupType.BROADCAST, nullable=False, index=True)
    active: bool = Field(default=True, nullable=False)
    extra_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))

    members: List["Membership"] = Relationship(back_populates="group")


class Membership(TimeStamped, SQLModel, table=True):
    """用户-群 关系；多对多中间表。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(foreign_key="user.user_id", index=True)
    group_id: str = Field(foreign_key="group.group_id", index=True)
    role: Optional[str] = Field(default=None, max_length=32)
    joined_at: Optional[datetime] = Field(default_factory=utcnow)
    receive_broadcast: bool = Field(default=True, nullable=False)

    user: "User" = Relationship(back_populates="memberships")
    group: "Group" = Relationship(back_populates="members")
