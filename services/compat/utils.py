"""Utilities shared by compat shims."""

from __future__ import annotations

from datetime import datetime, timezone


LEGACY_TS_FMT = "%Y-%m-%d %H:%M:%S"


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_legacy_timestamp(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return ensure_utc(dt).strftime(LEGACY_TS_FMT)


def normalize_text(value: str) -> str:
    return value.strip().lower()


def ensure_str(value: str | int) -> str:
    return str(value)
