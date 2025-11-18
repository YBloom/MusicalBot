"""Compat wrapper for the legacy UsersManager API."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from sqlmodel import select

from services.db.models import Group, User

from .context import CompatContext, get_default_context
from .utils import ensure_str, format_legacy_timestamp


class UsersManagerCompat:
    def __init__(self, context: CompatContext | None = None):
        self.context = context or get_default_context()

    def get_user(self, user_id: str | int) -> Optional[Dict[str, Any]]:
        user_id = ensure_str(user_id)
        with self.context.session() as session:
            user = session.get(User, user_id)
            if not user or user.is_deleted:
                return None
            _, payload = self._serialize_user(user)
            return payload

    def list_users(self) -> List[str]:
        with self.context.session() as session:
            stmt = (
                select(User.user_id)
                .where(User.is_deleted == False)  # noqa: E712
                .order_by(User.created_at)
            )
            return [row[0] for row in session.exec(stmt).all()]

    def get_group(self, group_id: str | int) -> Optional[Dict[str, Any]]:
        group_id = ensure_str(group_id)
        with self.context.session() as session:
            group = session.get(Group, group_id)
            if not group or group.is_deleted:
                return None
            _, payload = self._serialize_group(group)
            return payload

    def list_groups(self) -> List[str]:
        with self.context.session() as session:
            stmt = (
                select(Group.group_id)
                .where(Group.is_deleted == False)  # noqa: E712
                .order_by(Group.created_at)
            )
            return [row[0] for row in session.exec(stmt).all()]

    def export_payload(self) -> Dict[str, Any]:
        with self.context.session() as session:
            users_stmt = (
                select(User)
                .where(User.is_deleted == False)  # noqa: E712
                .order_by(User.created_at)
            )
            groups_stmt = (
                select(Group)
                .where(Group.is_deleted == False)  # noqa: E712
                .order_by(Group.created_at)
            )
            users = [self._serialize_user(row) for row in session.exec(users_stmt).all()]
            groups = [self._serialize_group(row) for row in session.exec(groups_stmt).all()]

        users_dict = {user_id: payload for user_id, payload in users}
        groups_dict = {group_id: payload for group_id, payload in groups}
        return {
            "users": users_dict,
            "users_list": sorted(users_dict.keys()),
            "groups": groups_dict,
            "groups_list": sorted(groups_dict.keys()),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _serialize_user(self, user: User) -> tuple[str, Dict[str, Any]]:
        payload = deepcopy(user.extra_json) if user.extra_json else {}
        payload.setdefault("activate", user.active)
        payload.setdefault("create_time", format_legacy_timestamp(user.created_at))
        payload.setdefault("attention_to_hulaquan", payload.get("attention_to_hulaquan", 0))
        payload.setdefault("chats_count", payload.get("chats_count", 0))
        subscribe = payload.setdefault("subscribe", {})
        subscribe.setdefault("is_subscribe", bool(payload.get("subscribe", {}).get("subscribe_tickets")))
        subscribe.setdefault("subscribe_time", format_legacy_timestamp(user.created_at))
        subscribe.setdefault("subscribe_tickets", [])
        subscribe.setdefault("subscribe_events", [])
        subscribe.setdefault("subscribe_actors", [])
        return user.user_id, payload

    def _serialize_group(self, group: Group) -> tuple[str, Dict[str, Any]]:
        payload = deepcopy(group.extra_json) if group.extra_json else {}
        payload.setdefault("activate", group.active)
        payload.setdefault("create_time", format_legacy_timestamp(group.created_at))
        payload.setdefault("attention_to_hulaquan", payload.get("attention_to_hulaquan", 0))
        return group.group_id, payload
