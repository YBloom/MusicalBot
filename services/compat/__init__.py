"""Compat facade that shields plugins from legacy DataManager details.

The compat package exposes :class:`CompatContext`, which centralises access to
legacy ``DataManager`` instances so that plugins can treat them as
dependencies.  Production code uses :func:`get_default_context` which currently
provides JSON based managers, while tests (or future service layers) can
replace it via :func:`set_default_context`.
"""
"""Compat 层相关工具。"""

from .utils import CompatRouteDisabled, compat_entrypoint
from .context import CompatContext, get_default_context, set_default_context

__all__ = [
    "CompatContext",
    "get_default_context",
    "set_default_context",
  "CompatRouteDisabled", "compat_entrypoint"
]
