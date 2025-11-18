"""Compatibility layer that mimics the legacy DataManager API."""

from .context import CompatContext, get_default_context
from .users_manager import UsersManagerCompat
from .alias_manager import AliasManagerCompat

__all__ = [
    "AliasManagerCompat",
    "CompatContext",
    "UsersManagerCompat",
    "get_default_context",
]
