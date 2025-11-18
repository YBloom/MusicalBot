"""Context object that bundles compat-facing managers.

Plugins read the managers from :class:`CompatContext` instead of importing
``UsersManager``/``AliasManager``/``HulaquanDataManager`` directly.  This keeps
the module level dependencies centralised and allows unit tests (or future
service layers) to provide lightweight substitutes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Optional

from plugins.AdminPlugin.BaseDataManager import BaseDataManager


@dataclass(slots=True)
class CompatManagers:
    """Container describing the known compat managers."""

    users: BaseDataManager
    alias: BaseDataManager
    stats: BaseDataManager
    saoju: BaseDataManager
    hulaquan: BaseDataManager


class CompatContext:
    """Dependency container for legacy managers.

    Parameters
    ----------
    users, alias, stats, saoju, hulaquan:
        Instances that expose the public surface of the legacy data managers.
        They are stored verbatim so custom substitutes (for example in-memory
        implementations) are also supported.
    extra_managers:
        Optional iterable of additional managers that should participate in the
        ``save_all`` orchestration.  This is mainly useful for downstream
        plugins that need to inject more ``BaseDataManager`` compatible
        components.
    """

    def __init__(
        self,
        *,
        users: BaseDataManager,
        alias: BaseDataManager,
        stats: BaseDataManager,
        saoju: BaseDataManager,
        hulaquan: BaseDataManager,
        extra_managers: Optional[Iterable[BaseDataManager]] = None,
    ) -> None:
        self.managers = CompatManagers(
            users=users,
            alias=alias,
            stats=stats,
            saoju=saoju,
            hulaquan=hulaquan,
        )
        ordered: list[BaseDataManager] = [
            users,
            alias,
            stats,
            saoju,
            hulaquan,
        ]
        if extra_managers:
            ordered.extend(extra_managers)
        # ``BaseDataManager`` implements ``__new__`` as a singleton, but it is
        # still safer to deduplicate in case callers provide aliases of the
        # same instance.
        seen = set()
        deduped: list[BaseDataManager] = []
        for manager in ordered:
            ident = id(manager)
            if ident in seen:
                continue
            seen.add(ident)
            deduped.append(manager)
        self._ordered_managers: tuple[BaseDataManager, ...] = tuple(deduped)

    @property
    def users(self) -> BaseDataManager:
        return self.managers.users

    @property
    def alias(self) -> BaseDataManager:
        return self.managers.alias

    @property
    def stats(self) -> BaseDataManager:
        return self.managers.stats

    @property
    def saoju(self) -> BaseDataManager:
        return self.managers.saoju

    @property
    def hulaquan(self) -> BaseDataManager:
        return self.managers.hulaquan

    def iter_managers(self) -> Iterator[BaseDataManager]:
        """Yield the managers participating in ``save_all`` orchestration."""

        return iter(self._ordered_managers)

    async def save_all(self, on_close: bool = False) -> bool:
        """Persist every manager sequentially.

        Returns ``True`` if every manager reported ``{"success": True}``.
        ``BaseDataManager.save`` returns such a dictionary so this keeps the
        historical behaviour intact.
        """

        success = True
        for manager in self.iter_managers():
            save_fn = getattr(manager, "save", None)
            if save_fn is None:
                continue
            result = await save_fn(on_close)  # type: ignore[misc]
            success = success and bool(result.get("success", False))
        return success


_DEFAULT_CONTEXT: Optional[CompatContext] = None


def get_default_context() -> CompatContext:
    """Return the process-wide compat context.

    The first invocation builds a :class:`CompatContext` backed by the legacy
    JSON data managers so existing deployments continue to work.
    """

    global _DEFAULT_CONTEXT
    if _DEFAULT_CONTEXT is None:
        from .legacy import build_legacy_context

        _DEFAULT_CONTEXT = build_legacy_context()
    return _DEFAULT_CONTEXT


def set_default_context(context: CompatContext) -> None:
    """Replace the process wide context (mainly used in tests)."""

    global _DEFAULT_CONTEXT
    _DEFAULT_CONTEXT = context
