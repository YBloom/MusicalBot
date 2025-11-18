"""Regression tests for scripts/import_v0_json.py."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, select

from scripts.import_v0_json import LegacyImporter, normalize
from services.db.init import init_db
from services.db.models import ErrorLog, HLQEvent, HLQTicket, Metric, Play, PlaySnapshot


DATA_ROOT = Path(__file__).parent / "test_data"


def test_importer_loads_hlq_and_observability(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    engine = init_db(str(db_path))

    with Session(engine) as session:
        importer = LegacyImporter(DATA_ROOT, session)
        stats = importer.run()
        session.commit()

    assert stats.hlq_events > 0
    assert stats.hlq_tickets > 0
    assert stats.snapshots > 0
    assert stats.metrics > 0
    assert stats.error_logs > 0

    with Session(engine) as session:
        event = session.get(HLQEvent, "3911")
        assert event is not None
        assert "本杰明" in event.title
        assert event.start_time is not None

        ticket = session.exec(
            select(HLQTicket).where(
                HLQTicket.hlq_event_id == "3911",
                HLQTicket.ticket_id == "34865",
            )
        ).first()
        assert ticket is not None
        assert ticket.left == 33
        assert ticket.status.name == "AVAILABLE"
        assert ticket.valid_from is not None

        metric = session.exec(
            select(Metric).where(Metric.name == "legacy_command_count")
        ).first()
        assert metric is not None
        assert metric.labels == {"command": "hulaquan_announcer"}
        assert metric.value == 86543
        assert metric.labels_hash is not None

        logs = session.exec(select(ErrorLog).where(ErrorLog.code == "1007"))
        log_list = logs.all()
        assert len(log_list) == 2
        assert any("价格与票面不符" in item.message for item in log_list)
        assert all(item.ts is not None for item in log_list)

        play = session.exec(select(Play).where(Play.name == "阿波罗尼亚")).first()
        assert play is not None
        snapshot = session.exec(
            select(PlaySnapshot).where(
                PlaySnapshot.play_id == play.id,
                PlaySnapshot.city_norm == normalize("上海"),
            )
        ).first()
        assert snapshot is not None
        assert snapshot.payload is not None
        assert snapshot.payload["source"] == "legacy_saoju"
        assert len(snapshot.payload["records"]) == 33
        assert snapshot.last_success_at is not None
