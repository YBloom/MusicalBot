import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlmodel import SQLModel, Session, create_engine, select

from scripts.import_v0_json import (
    LEGACY_ALIAS_FILE,
    LEGACY_USER_FILE,
    LegacyImporter,
    normalize,
    parse_dt,
)
from services.db.models import (
    Group,
    Play,
    PlayAlias,
    PlaySource,
    PlaySourceLink,
    Subscription,
    SubscriptionOption,
    User,
)


def _expected_counts(data_root: Path) -> dict:
    user_payload = json.loads((data_root / LEGACY_USER_FILE).read_text(encoding="utf-8"))
    users = user_payload.get("users", {})
    groups = user_payload.get("groups", {})
    subscriptions = 0
    for record in users.values():
        subscribe = record.get("subscribe") or {}
        subscriptions += sum(
            len(subscribe.get(key) or [])
            for key in ("subscribe_tickets", "subscribe_events", "subscribe_actors")
        )

    alias_payload = json.loads((data_root / LEGACY_ALIAS_FILE).read_text(encoding="utf-8"))
    alias_to_event = alias_payload.get("alias_to_event", {})
    event_to_names = alias_payload.get("event_to_names", {})
    unique_events = {str(event_id) for event_id in alias_to_event.values()}
    unique_events.update(str(event_id) for event_id in event_to_names.keys())

    alias_norm_counts = {}
    for alias in alias_to_event.keys():
        norm = normalize(alias)
        if norm:
            alias_norm_counts[norm] = alias_norm_counts.get(norm, 0) + 1
    for names in event_to_names.values():
        for name in names:
            norm = normalize(name)
            if norm:
                alias_norm_counts[norm] = alias_norm_counts.get(norm, 0) + 1

    duplicate_norms = {norm for norm, count in alias_norm_counts.items() if count > 1}

    return {
        "users": len(users),
        "groups": len(groups),
        "subscriptions": subscriptions,
        "plays": len(unique_events),
        "aliases": len(alias_norm_counts),
        "duplicate_norms": duplicate_norms,
    }


def test_import_v0_json_migrates_sample_data(tmp_path):
    data_root = Path("tests/test_data")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy.db'}",
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        importer = LegacyImporter(data_root, session)
        importer.run()
        session.rollback()

    with Session(engine) as session:
        importer = LegacyImporter(data_root, session)
        stats = importer.run()
        session.commit()

    expected = _expected_counts(data_root)
    user_payload = json.loads((data_root / LEGACY_USER_FILE).read_text(encoding="utf-8"))
    group_payload = user_payload.get("groups", {})
    assert stats.as_dict() == {
        "users": expected["users"],
        "groups": expected["groups"],
        "subscriptions": expected["subscriptions"],
        "aliases": expected["aliases"],
        "plays": expected["plays"],
    }

    with Session(engine) as session:
        user_rows = session.exec(select(User)).all()
        group_rows = session.exec(select(Group)).all()
        subscription_rows = session.exec(select(Subscription)).all()
        option_rows = session.exec(select(SubscriptionOption)).all()
        play_rows = session.exec(select(Play)).all()
        alias_rows = session.exec(select(PlayAlias)).all()
        link_rows = session.exec(select(PlaySourceLink)).all()

        user_by_id = {user.user_id: user for user in user_rows}
        group_by_id = {group.group_id: group for group in group_rows}

        assert len(user_rows) == expected["users"]
        assert len(group_rows) == expected["groups"]
        assert len(subscription_rows) == expected["subscriptions"]
        assert len(option_rows) == expected["subscriptions"]
        assert len(play_rows) == expected["plays"]
        assert len(alias_rows) == expected["aliases"]
        assert len(link_rows) == expected["plays"]
        assert {link.source for link in link_rows} == {PlaySource.LEGACY}

        sample_user_id, sample_user_record = next(
            (user_id, record)
            for user_id, record in user_payload.get("users", {}).items()
            if record.get("create_time")
        )
        expected_user_dt = parse_dt(sample_user_record["create_time"])
        assert expected_user_dt is not None
        assert user_by_id[sample_user_id].created_at == expected_user_dt.replace(tzinfo=None)
        assert user_by_id[sample_user_id].updated_at == expected_user_dt.replace(tzinfo=None)

        sample_group_id, sample_group_record = next(
            (group_id, record)
            for group_id, record in group_payload.items()
            if record.get("create_time")
        )
        expected_group_dt = parse_dt(sample_group_record["create_time"])
        assert expected_group_dt is not None
        assert group_by_id[sample_group_id].created_at == expected_group_dt.replace(tzinfo=None)
        assert group_by_id[sample_group_id].updated_at == expected_group_dt.replace(tzinfo=None)

        alias_norms = {alias.alias_norm for alias in alias_rows}
        for dup_norm in expected["duplicate_norms"]:
            assert dup_norm in alias_norms
            dup_rows = session.exec(
                select(PlayAlias).where(PlayAlias.alias_norm == dup_norm)
            ).all()
            assert len(dup_rows) == 1
