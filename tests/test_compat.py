from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.import_v0_json import LegacyImporter
from services.compat import AliasManagerCompat, CompatContext, UsersManagerCompat


@pytest.fixture(scope="module")
def legacy_users_payload() -> dict:
    return json.loads(Path("tests/test_data/UsersManager.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def legacy_alias_payload() -> dict:
    return json.loads(Path("tests/test_data/alias.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def compat_context(legacy_alias_payload: dict) -> CompatContext:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    data_root = Path("tests/test_data")
    with Session(engine) as session:
        importer = LegacyImporter(data_root, session)
        importer.run()
        session.commit()

    @contextmanager
    def _session_factory():
        with Session(engine) as session:
            yield session

    cache = dict(legacy_alias_payload.get("no_response", {}))
    return CompatContext(session_factory=_session_factory, alias_no_response_cache=cache)


def test_users_manager_roundtrip(compat_context: CompatContext, legacy_users_payload: dict):
    manager = UsersManagerCompat(compat_context)
    exported = manager.export_payload()

    assert exported["users"] == legacy_users_payload["users"]
    assert exported["groups"] == legacy_users_payload["groups"]
    assert sorted(exported["users_list"]) == sorted(legacy_users_payload["users_list"])
    assert sorted(exported["groups_list"]) == sorted(legacy_users_payload["groups_list"])

    sample_id = legacy_users_payload["users_list"][0]
    assert manager.get_user(sample_id) == legacy_users_payload["users"][sample_id]


def test_alias_manager_roundtrip(compat_context: CompatContext, legacy_alias_payload: dict):
    manager = AliasManagerCompat(compat_context)
    exported = manager.export_payload()

    assert exported["alias_to_event"] == legacy_alias_payload["alias_to_event"]
    assert exported["event_to_names"] == {
        key: sorted(value) for key, value in legacy_alias_payload["event_to_names"].items()
    }
    assert exported["no_response"] == legacy_alias_payload["no_response"]

    for alias, event_id in list(legacy_alias_payload["alias_to_event"].items())[:3]:
        assert manager.get_event_id_by_alias(alias) == event_id
        assert manager.get_event_id_by_name(alias) == event_id
