"""Legacy compat facade.

The helpers in this module lazily import the historical JSON based data
managers.  This keeps heavy imports (and their singleton initialisers) away
from module import time until the compat layer is actually required.
"""

from __future__ import annotations

from .context import CompatContext


def build_legacy_context() -> CompatContext:
    """Create a context backed by the existing JSON managers."""

    from plugins.Hulaquan import data_managers

    return data_managers.current_context()
