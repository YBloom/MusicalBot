"""Subscription-related tables."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlalchemy.orm import Mapped, relationship
from sqlmodel import Field, Relationship, SQLModel

from .base import SubscriptionFrequency, SubscriptionTargetKind, TimeStamped


class Subscription(TimeStamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(foreign_key="user.user_id", index=True)

    user: Mapped["User"] = Relationship(
        back_populates="subscriptions",
        sa_relationship=relationship("User", back_populates="subscriptions"),
    )
    targets: Mapped[List["SubscriptionTarget"]] = Relationship(
        back_populates="subscription",
        sa_relationship=relationship("SubscriptionTarget", back_populates="subscription"),
    )
    options: Mapped[List["SubscriptionOption"]] = Relationship(
        back_populates="subscription",
        sa_relationship=relationship("SubscriptionOption", back_populates="subscription"),
    )


class SubscriptionTarget(TimeStamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    subscription_id: int = Field(foreign_key="subscription.id", nullable=False)
    kind: SubscriptionTargetKind = Field(nullable=False, index=True)
    target_id: Optional[str] = Field(default=None, index=True, max_length=128)
    name: Optional[str] = Field(default=None, max_length=256)
    city_filter: Optional[str] = Field(default=None, max_length=64)
    flags: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))

    subscription: Mapped["Subscription"] = Relationship(
        back_populates="targets",
        sa_relationship=relationship("Subscription", back_populates="targets"),
    )

    __table_args__ = (
        UniqueConstraint(
            "subscription_id",
            "kind",
            "target_id",
            name="uq_subscription_target",
        ),
    )


class SubscriptionOption(TimeStamped, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    subscription_id: int = Field(foreign_key="subscription.id", nullable=False, unique=True)
    mute: bool = Field(default=False, nullable=False)
    freq: SubscriptionFrequency = Field(default=SubscriptionFrequency.REALTIME, nullable=False)
    allow_broadcast: bool = Field(default=True, nullable=False)
    last_notified_at: Optional[datetime] = Field(default=None)

    subscription: Mapped["Subscription"] = Relationship(
        back_populates="options",
        sa_relationship=relationship("Subscription", back_populates="options"),
    )
