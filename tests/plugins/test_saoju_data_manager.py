import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


def _install_ncatbot_stub():
    if "ncatbot" in sys.modules:
        return
    ncatbot_pkg = types.ModuleType("ncatbot")
    plugin_mod = types.ModuleType("ncatbot.plugin")
    core_mod = types.ModuleType("ncatbot.core")
    utils_mod = types.ModuleType("ncatbot.utils")
    logger_mod = types.ModuleType("ncatbot.utils.logger")

    class _BasePlugin:
        def __init__(self, *args, **kwargs):  # noqa: D401
            pass

    class _CompatEnrollment:
        @staticmethod
        def private_event(*args, **kwargs):  # noqa: D401
            def decorator(func):
                return func

            return decorator

        @staticmethod
        def request_event(*args, **kwargs):  # noqa: D401
            def decorator(func):
                return func

            return decorator

    class _Stub:
        pass

    plugin_mod.BasePlugin = _BasePlugin
    plugin_mod.CompatibleEnrollment = _CompatEnrollment
    plugin_mod.Event = _Stub
    core_mod.GroupMessage = _Stub
    core_mod.PrivateMessage = _Stub
    core_mod.BaseMessage = _Stub

    def _get_log():  # noqa: D401
        class _Logger:
            def __getattr__(self, _):  # noqa: D401
                return lambda *args, **kwargs: None

        return _Logger()

    logger_mod.get_log = _get_log

    ncatbot_pkg.plugin = plugin_mod
    ncatbot_pkg.core = core_mod
    ncatbot_pkg.utils = utils_mod

    sys.modules["ncatbot"] = ncatbot_pkg
    sys.modules["ncatbot.plugin"] = plugin_mod
    sys.modules["ncatbot.core"] = core_mod
    sys.modules["ncatbot.utils"] = utils_mod
    sys.modules["ncatbot.utils.logger"] = logger_mod


sys.path.append(str(Path(__file__).resolve().parents[2]))
_install_ncatbot_stub()

from plugins.Hulaquan.SaojuDataManager import SaojuDataManager


@pytest.fixture(autouse=True)
def reset_saoju_singleton():
    """Ensure each test gets a fresh SaojuDataManager singleton."""

    original_instance = getattr(SaojuDataManager, "_instance", None)
    had_instance = hasattr(SaojuDataManager, "_instance")
    if had_instance:
        delattr(SaojuDataManager, "_instance")
    try:
        yield
    finally:
        if hasattr(SaojuDataManager, "_instance"):
            delattr(SaojuDataManager, "_instance")
        if had_instance:
            SaojuDataManager._instance = original_instance


@pytest.mark.asyncio
async def test_search_for_musical_by_date_async_prefers_musical_api(tmp_path):
    manager = SaojuDataManager(file_path=str(tmp_path / "saoju.json"))

    async def fake_get_musical_shows(name, begin, end):
        assert name == "测试剧"
        assert begin == end == "2025-07-25"
        return [
            {
                "time": "2025-07-25 19:30",
                "city": "上海",
                "musical": "测试剧",
                "cast": [],
            }
        ]

    manager._get_musical_shows = fake_get_musical_shows  # type: ignore[method-assign]
    manager.get_data_by_date_async = AsyncMock(return_value=[])  # type: ignore[assignment]

    result = await manager.search_for_musical_by_date_async("测试剧", "2025-07-25 19:30", city="上海")

    assert result is not None
    assert result["city"] == "上海"
    manager.get_data_by_date_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_artist_events_data_formats_entries(tmp_path):
    manager = SaojuDataManager(file_path=str(tmp_path / "saoju.json"))
    manager.data["artists_map"] = {"演员A": 1}

    async def fake_ensure_map():
        return None

    async def fake_ensure_indexes():
        return {"artist_musicals": {"1": {"10": {"name": "剧目A", "roles": ["角色A"]}}}}

    async def fake_get_musical_shows(musical, begin, end):
        assert musical == "剧目A"
        return [
            {
                "musical": "剧目A",
                "time": "2025-08-20 19:30",
                "city": "上海",
                "theatre": "大剧院",
                "cast": [
                    {"role": "角色A", "artist": "演员A"},
                    {"role": "角色B", "artist": "演员B"},
                ],
            }
        ]

    manager._ensure_artist_map = fake_ensure_map  # type: ignore[method-assign]
    manager._ensure_artist_indexes = fake_ensure_indexes  # type: ignore[method-assign]
    manager._get_musical_shows = fake_get_musical_shows  # type: ignore[method-assign]

    events = await manager.get_artist_events_data("演员A")

    assert len(events) == 1
    event = events[0]
    assert event["city"] == "上海"
    assert event["location"] == "大剧院"
    assert event["role"] == "角色A"
    assert event["others"] == ["演员B"]
    assert "星期" in event["date"]
