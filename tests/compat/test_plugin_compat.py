"""Regression tests for the compat facade wiring."""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List

import sys
import importlib

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_data_managers():
    return importlib.import_module("plugins.Hulaquan.data_managers")

import pytest

from plugins.AdminPlugin.main import AdminPlugin
from services.compat import CompatContext


class _DummyEventBus:
    async def publish_async(self, *args: Any, **kwargs: Any) -> None:
        return None


class _DummyScheduler:
    pass


class _SQLiteUsersManager:
    """Minimal UsersManager clone that stores data in in-memory SQLite."""

    def __init__(self) -> None:
        self._conn = sqlite3.connect(":memory:")
        self._conn.execute(
            """
            CREATE TABLE users (
                user_id TEXT PRIMARY KEY,
                chats_count INTEGER DEFAULT 0,
                is_op INTEGER DEFAULT 0
            )
            """
        )

    def _ensure_user(self, user_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO users(user_id, chats_count, is_op) VALUES (?, 0, 0)",
            (str(user_id),),
        )
        self._conn.commit()

    def add_user(self, user_id: str) -> None:
        self._ensure_user(str(user_id))

    def add_chats_count(self, user_id: str) -> None:
        self._ensure_user(str(user_id))
        self._conn.execute(
            "UPDATE users SET chats_count = chats_count + 1 WHERE user_id = ?",
            (str(user_id),),
        )
        self._conn.commit()

    def add_op(self, user_id: str) -> bool:
        self._ensure_user(str(user_id))
        row = self._conn.execute(
            "SELECT is_op FROM users WHERE user_id = ?",
            (str(user_id),),
        ).fetchone()
        if row and row[0]:
            return False
        self._conn.execute(
            "UPDATE users SET is_op = 1 WHERE user_id = ?",
            (str(user_id),),
        )
        self._conn.commit()
        return True

    def de_op(self, user_id: str) -> bool:
        self._ensure_user(str(user_id))
        updated = self._conn.execute(
            "UPDATE users SET is_op = 0 WHERE user_id = ? AND is_op = 1",
            (str(user_id),),
        ).rowcount
        self._conn.commit()
        return bool(updated)

    def is_op(self, user_id: str) -> bool:
        row = self._conn.execute(
            "SELECT is_op FROM users WHERE user_id = ?",
            (str(user_id),),
        ).fetchone()
        return bool(row and row[0])

    def users(self) -> dict[str, dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT user_id, chats_count, is_op FROM users"
        ).fetchall()
        return {
            user_id: {"chats_count": chats_count, "is_op": bool(is_op)}
            for user_id, chats_count, is_op in rows
        }

    async def save(self, on_close: bool = False) -> dict[str, Any]:  # pragma: no cover - trivial
        return {"success": True, "updating": False}


@dataclass
class _DummyManager:
    name: str

    async def save(self, on_close: bool = False) -> dict[str, Any]:  # pragma: no cover
        return {"success": True, "updating": False}


class _FakeMessage:
    def __init__(self, raw_message: str, user_id: str = "10000") -> None:
        self.raw_message = raw_message
        self.user_id = user_id
        self._replies: List[str] = []

    async def reply(self, text: str) -> None:
        self._replies.append(text)

    @property
    def replies(self) -> List[str]:
        return self._replies


def _build_sqlite_context() -> CompatContext:
    users = _SQLiteUsersManager()
    return CompatContext(
        users=users,
        alias=_DummyManager("alias"),
        stats=_DummyManager("stats"),
        saoju=_DummyManager("saoju"),
        hulaquan=_DummyManager("hlq"),
    )


def test_admin_plugin_commands_respect_injected_context():
    async def runner():
        context = _build_sqlite_context()
        plugin = AdminPlugin(_DummyEventBus(), _DummyScheduler(), compat_context=context)
        await plugin.on_load()

        msg = _FakeMessage("/op 123456", user_id="3022402752")
        await plugin._on_add_op(msg)
        assert context.users.is_op("123456")
        assert any("管理员权限" in text for text in msg.replies)

        private_msg = _FakeMessage("hello", user_id="123456")
        handler = getattr(plugin.on_private_message, "__wrapped__", None)
        if handler is None:
            await plugin.on_private_message(private_msg)
        else:
            await handler(plugin, private_msg)
        users = context.users.users()
        assert users["123456"]["chats_count"] == 1

    asyncio.run(runner())


def test_hulaquan_data_managers_swap_context():
    async def runner():
        data_managers = _load_data_managers()
        original = data_managers.current_context()
        context = _build_sqlite_context()
        try:
            active = data_managers.use_compat_context(context)
            assert active is context
            assert data_managers.User is context.users
            assert data_managers.Alias is context.alias
            assert data_managers.Hlq is context.hulaquan
        finally:
            data_managers.use_compat_context(original)

    asyncio.run(runner())
