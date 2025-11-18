"""用于给旧版 compat 入口包裹日志与指标的辅助工具。"""
from __future__ import annotations

import inspect
import logging
import os
import time
from functools import wraps
from typing import Any, Callable, Dict, Mapping, Optional, Tuple, TypeVar

from logs.metrics import emit as emit_metric

log = logging.getLogger(__name__)

TRUTHY = {"1", "true", "yes", "on"}
F = TypeVar("F", bound=Callable[..., Any])


class CompatRouteDisabled(RuntimeError):
    """当 compat 路径被特性开关禁用时抛出。"""


def _env_flag(name: str, *, default: str = "0") -> bool:
    value = os.getenv(name)
    if value is None:
        value = default
    return value.strip().lower() in TRUTHY


def _disabled_paths() -> Tuple[str, ...]:
    raw_value = os.getenv("COMPAT_DISABLED_PATHS", "")
    paths = tuple(filter(None, (part.strip() for part in raw_value.split(","))))
    return paths


def _extract_context(args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> Dict[str, Any]:
    fields = {"request_id": None, "user_id": None, "group_id": None}
    maybe_context = kwargs.get("compat_context")
    if isinstance(maybe_context, Mapping):
        for key in fields:
            if maybe_context.get(key) is not None:
                fields[key] = maybe_context[key]
    for key in fields:
        if kwargs.get(key) is not None:
            fields[key] = kwargs[key]
    if args:
        first = args[0]
        for key in fields:
            if fields[key] is None and hasattr(first, key):
                fields[key] = getattr(first, key)
    return fields


def _should_short_circuit(path: str) -> Optional[str]:
    if _env_flag("MAINTENANCE_MODE", default="0"):
        return "MAINTENANCE_MODE is enabled"
    if not _env_flag("LEGACY_COMPAT", default="1"):
        return "LEGACY_COMPAT flag disabled compat calls"
    if path in _disabled_paths():
        return f"{path} disabled via COMPAT_DISABLED_PATHS"
    return None


def _record_metric(path: str, mode: str, status: str) -> None:
    emit_metric(
        "service_calls_total",
        value=1,
        labels={"path": path, "mode": mode, "status": status},
    )


def compat_entrypoint(name: Optional[str] = None) -> Callable[[F], F]:
    """为 compat 方法添加日志、开关保护与指标记录。"""

    def decorator(func: F) -> F:
        entry_name = name or func.__name__
        is_async = inspect.iscoroutinefunction(func)

        def _log_start(context: Mapping[str, Any]) -> None:
            log.info(
                "compat.%s.start request_id=%s user_id=%s group_id=%s",
                entry_name,
                context.get("request_id"),
                context.get("user_id"),
                context.get("group_id"),
            )

        def _log_finish(context: Mapping[str, Any], latency_ms: float) -> None:
            log.info(
                "compat.%s.finish latency_ms=%.2f request_id=%s user_id=%s group_id=%s",
                entry_name,
                latency_ms,
                context.get("request_id"),
                context.get("user_id"),
                context.get("group_id"),
            )

        def _guard() -> None:
            reason = _should_short_circuit(entry_name)
            if reason:
                log.warning("compat.%s.short_circuit %s", entry_name, reason)
                _record_metric(entry_name, mode="native", status="blocked")
                raise CompatRouteDisabled(reason)

        if is_async:

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                _guard()
                context = _extract_context(args, kwargs)
                _log_start(context)
                start = time.perf_counter()
                try:
                    result = await func(*args, **kwargs)
                except Exception:
                    _record_metric(entry_name, mode="compat", status="error")
                    log.exception("compat.%s.error", entry_name)
                    raise
                else:
                    latency_ms = (time.perf_counter() - start) * 1000
                    _log_finish(context, latency_ms)
                    _record_metric(entry_name, mode="compat", status="success")
                    return result

            return async_wrapper  # type: ignore[return-value]

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            _guard()
            context = _extract_context(args, kwargs)
            _log_start(context)
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception:
                _record_metric(entry_name, mode="compat", status="error")
                log.exception("compat.%s.error", entry_name)
                raise
            else:
                latency_ms = (time.perf_counter() - start) * 1000
                _log_finish(context, latency_ms)
                _record_metric(entry_name, mode="compat", status="success")
                return result

        return sync_wrapper  # type: ignore[return-value]

    return decorator


__all__ = ["compat_entrypoint", "CompatRouteDisabled"]
