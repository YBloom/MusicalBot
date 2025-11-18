"""User table definition."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import JSON, Column
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship

from .base import SoftDelete, TimeStamped


class User(TimeStamped, SoftDelete, table=True):
    """QQ 用户模型，对应 PRD 中的 User 表。"""

    user_id: str = Field(primary_key=True, max_length=32)
    nickname: Optional[str] = Field(default=None, max_length=128)
    active: bool = Field(default=True, nullable=False)
    transactions_success: int = Field(default=0, nullable=False, index=True)
    trust_score: int = Field(default=0, nullable=False, index=True)
    extra_json: Optional[dict] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )

    memberships: list["Membership"] = Relationship(
        sa_relationship=relationship("Membership", back_populates="user"),
    )
    subscriptions: list["Subscription"] = Relationship(
        sa_relationship=relationship("Subscription", back_populates="user"),
    )
