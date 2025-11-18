"""Compat aware accessors for Hulaquan's legacy data managers."""

from __future__ import annotations

from typing import Optional

from ncatbot.utils.logger import get_log

from services.compat import CompatContext

from plugins.Hulaquan.SaojuDataManager import SaojuDataManager
from plugins.Hulaquan.StatsDataManager import StatsDataManager
from plugins.Hulaquan.AliasManager import AliasManager
from plugins.Hulaquan.HulaquanDataManager import HulaquanDataManager
from plugins.AdminPlugin.UsersManager import UsersManager

log = get_log()

User = UsersManager()
Alias = AliasManager()
Stats = StatsDataManager()
Saoju = SaojuDataManager()
Hlq = HulaquanDataManager()

_CURRENT_CONTEXT = CompatContext(
    users=User,
    alias=Alias,
    stats=Stats,
    saoju=Saoju,
    hulaquan=Hlq,
)


def use_compat_context(context: Optional[CompatContext]) -> CompatContext:
    """Install a compat context for module level manager references."""

    global _CURRENT_CONTEXT, User, Alias, Stats, Saoju, Hlq
    if context is None:
        context = _CURRENT_CONTEXT
    else:
        _CURRENT_CONTEXT = context
    User = context.users
    Alias = context.alias
    Stats = context.stats
    Saoju = context.saoju
    Hlq = context.hulaquan
    return context


def current_context() -> CompatContext:
    return _CURRENT_CONTEXT


async def save_all(on_close: bool = False) -> bool:
    """Persist every manager tracked by the active context."""

    return await _CURRENT_CONTEXT.save_all(on_close)