"""Shared context for compat managers."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, ContextManager, MutableMapping

from sqlmodel import Session

from services.db.connection import session_scope
from services.db.models import utcnow

SessionFactory = Callable[[], ContextManager[Session]]


@dataclass(slots=True)
class CompatContext:
    """State bundle shared by compat manager facades.

    The legacy managers expected implicit singletons that knew how to open
    JSON files, cache counters, etc.  The new service layer uses repositories
    backed by SQLModel, so we centralize the dependencies here and pass the
    context into each compat manager.
    """

    session_factory: SessionFactory
    alias_no_response_cache: MutableMapping[str, int] = field(default_factory=dict)
    now_factory: Callable[[], datetime] = utcnow

    @contextmanager
    def session(self) -> ContextManager[Session]:
        """Yield a SQLModel session using the configured factory."""

        with self.session_factory() as session:
            yield session

    def now(self):
        """Return a timezone-aware UTC timestamp."""

        return self.now_factory()


def _default_session_factory() -> ContextManager[Session]:
    return session_scope()


_DEFAULT_CONTEXT = CompatContext(session_factory=_default_session_factory)


def get_default_context() -> CompatContext:
    """Return the process-wide compat context."""

    return _DEFAULT_CONTEXT


__all__ = ["CompatContext", "get_default_context"]
