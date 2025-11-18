#!/usr/bin/env python3
"""Import legacy JSON data into the SQLModel schema.

Usage:
    python scripts/import_v0_json.py --data-root data/data_manager --db-path data/musicalbot.db

The importer now reads `UsersManager.json`, `alias.json`, `HulaquanDataManager.json`,
`SaojuDataManager.json`, and `StatsDataManager.json` from the legacy cache
directory to hydrate users, subscriptions, plays/aliases, HLQ events/tickets,
Saoju play snapshots, and Stats-derived metrics/error logs. Pass `--dry-run`
to execute the full migration inside a transaction and roll it back after
validating the counters printed at the end.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from sqlmodel import Session, select

from services.db.init import init_db
from services.db.models import (
    ErrorLog,
    Group,
    HLQEvent,
    HLQTicket,
    HLQTicketStatus,
    Metric,
    Play,
    PlayAlias,
    PlaySnapshot,
    PlaySource,
    PlaySourceLink,
    Subscription,
    SubscriptionFrequency,
    SubscriptionOption,
    SubscriptionTarget,
    SubscriptionTargetKind,
    User,
    utcnow,
)

LEGACY_USER_FILE = "UsersManager.json"
LEGACY_ALIAS_FILE = "alias.json"
LEGACY_HLQ_FILE = "HulaquanDataManager.json"
LEGACY_SNAPSHOT_FILE = "SaojuDataManager.json"
LEGACY_STATS_FILE = "StatsDataManager.json"


@dataclass
class ImportStats:
    users: int = 0
    groups: int = 0
    subscriptions: int = 0
    aliases: int = 0
    plays: int = 0
    hlq_events: int = 0
    hlq_tickets: int = 0
    snapshots: int = 0
    metrics: int = 0
    error_logs: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "users": self.users,
            "groups": self.groups,
            "subscriptions": self.subscriptions,
            "aliases": self.aliases,
            "plays": self.plays,
            "hlq_events": self.hlq_events,
            "hlq_tickets": self.hlq_tickets,
            "snapshots": self.snapshots,
            "metrics": self.metrics,
            "error_logs": self.error_logs,
        }


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Failed to parse {path}: {exc}") from exc


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    value = str(value).strip()
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
    ):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def normalize(value: Optional[str]) -> str:
    if not value:
        return ""
    return value.strip().lower()


def normalize_city(value: Optional[str]) -> Optional[str]:
    normalized = normalize(value)
    return normalized or None


def parse_valid_from(value: Optional[str], reference: Optional[datetime]) -> Optional[datetime]:
    if not value:
        return None
    reference = reference or utcnow()
    value = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    for fmt in ("%m-%d %H:%M", "%m-%d"):
        try:
            parsed = datetime.strptime(value, fmt)
            parsed = parsed.replace(year=reference.year)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def map_ticket_status(status: Optional[str], update_status: Optional[str]) -> HLQTicketStatus:
    status_norm = (status or "").strip().lower()
    update_norm = (update_status or "").strip().lower()
    if status_norm in {"active", "available"}:
        return HLQTicketStatus.AVAILABLE
    if status_norm in {"pending", "queue"}:
        return HLQTicketStatus.QUEUE
    if status_norm in {"expired", "sold_out"} or update_norm in {"sold_out", "expired"}:
        return HLQTicketStatus.SOLD_OUT
    return HLQTicketStatus.UNKNOWN


def hash_labels(labels: Optional[Dict[str, Any]]) -> Optional[str]:
    if not labels:
        return None
    payload = json.dumps(labels, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def build_hlq_event(event_id: str, data: Dict[str, Any]) -> HLQEvent:
    title = data.get("title") or f"Legacy-{event_id}"
    created_at = parse_dt(data.get("create_time")) or utcnow()
    updated_at = parse_dt(data.get("update_time")) or created_at
    return HLQEvent(
        hlq_event_id=str(event_id),
        title=title,
        title_norm=normalize(title) or f"legacy-{event_id}",
        location=data.get("location"),
        start_time=parse_dt(data.get("start_time")),
        update_time=parse_dt(data.get("update_time")),
        created_at=created_at,
        updated_at=updated_at,
    )


def build_hlq_ticket(event: HLQEvent, payload: Dict[str, Any]) -> Optional[HLQTicket]:
    ticket_id = payload.get("id") or payload.get("ticket_id")
    if ticket_id is None:
        return None
    start_time = parse_dt(payload.get("start_time"))
    created_at = parse_dt(payload.get("create_time")) or event.created_at
    valid_from = parse_valid_from(payload.get("valid_from"), start_time or event.start_time)
    status = map_ticket_status(payload.get("status"), payload.get("update_status"))
    extra_payload = {
        k: v
        for k, v in payload.items()
        if k
        not in {
            "id",
            "ticket_id",
            "event_id",
            "start_time",
            "create_time",
            "ticket_price",
            "total_ticket",
            "left_ticket_count",
            "valid_from",
            "status",
        }
    }
    return HLQTicket(
        ticket_id=str(ticket_id),
        hlq_event_id=event.hlq_event_id,
        status=status,
        price=float(payload["ticket_price"]) if payload.get("ticket_price") is not None else None,
        total=int(payload["total_ticket"]) if payload.get("total_ticket") is not None else None,
        left=int(payload["left_ticket_count"]) if payload.get("left_ticket_count") is not None else None,
        valid_from=valid_from,
        start_time=start_time,
        payload=extra_payload or None,
        created_at=created_at,
        updated_at=parse_dt(payload.get("update_time")) or created_at,
    )


def group_saoju_entries(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    grouped: Dict[Tuple[str, Optional[str]], Dict[str, Any]] = {}
    for date_str, entries in (payload.get("date_dict") or {}).items():
        for entry in entries or []:
            title = entry.get("musical") or entry.get("title")
            city = entry.get("city")
            if not title:
                continue
            city_norm = normalize_city(city)
            key = (normalize(title), city_norm)
            record_time = parse_dt(f"{date_str} {entry.get('time')}") if entry.get("time") else parse_dt(date_str)
            record = {
                "date": date_str,
                "time": entry.get("time"),
                "city": city,
                "theatre": entry.get("theatre"),
                "cast": entry.get("cast"),
                "start_time": record_time.isoformat() if record_time else None,
            }
            if key not in grouped:
                grouped[key] = {
                    "title": title,
                    "city": city,
                    "city_norm": city_norm,
                    "records": [record],
                }
            else:
                grouped[key]["records"].append(record)
    return grouped.values()


def iter_command_metrics(stats_payload: Dict[str, Any]) -> Iterable[Metric]:
    for command, count in (stats_payload.get("on_command_times") or {}).items():
        labels = {"command": command}
        yield Metric(
            name="legacy_command_count",
            value=float(count or 0),
            labels=labels,
            labels_hash=hash_labels(labels),
        )


def iter_repo_error_logs(stats_payload: Dict[str, Any]) -> Iterable[ErrorLog]:
    repo_payload = stats_payload.get("hlq_tickets_repo") or {}
    for event_id, reports in repo_payload.items():
        for report_id, report in (reports or {}).items():
            details = report.get("report_error_details") or {}
            if not details:
                continue
            timestamp = parse_dt(report.get("create_time")) or utcnow()
            for reporter, reasons in details.items():
                for reason in reasons or []:
                    yield ErrorLog(
                        scope="hlq_repo",
                        code=str(report_id),
                        message=reason,
                        context={
                            "event_id": str(event_id),
                            "report_id": str(report_id),
                            "reporter": reporter,
                            "event_title": report.get("event_title"),
                        },
                        ts=timestamp,
                    )


class LegacyImporter:
    def __init__(self, data_root: Path, session: Session):
        self.data_root = data_root
        self.session = session
        self.stats = ImportStats()
        self._play_cache: Dict[str, Play] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self) -> ImportStats:
        self._import_users_and_groups()
        self._import_aliases()
        self._import_hlq_events()
        self._import_play_snapshots()
        self._import_metrics_and_errors()
        return self.stats

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _import_users_and_groups(self) -> None:
        payload = load_json(self.data_root / LEGACY_USER_FILE)
        if not payload:
            print(f"[import] Skip users: {LEGACY_USER_FILE} not found or empty")
            return

        users = payload.get("users", {})
        groups = payload.get("groups", {})
        subscribe_defaults = payload.get("subscribe", {})

        for user_id in payload.get("users_list", users.keys()):
            record = users.get(str(user_id), {})
            created_at = parse_dt(record.get("create_time")) or utcnow()
            user = User(
                user_id=str(user_id),
                nickname=record.get("nickname"),
                active=bool(record.get("activate", True)),
                transactions_success=int(record.get("transactions_success", 0)),
                trust_score=int(record.get("trust_score", 0)),
                extra_json=record or None,
                created_at=created_at,
                updated_at=created_at,
            )
            self.session.merge(user)
            self.stats.users += 1
            self.stats.subscriptions += self._import_subscriptions_for_user(
                user.user_id,
                record.get("subscribe") or subscribe_defaults,
            )

        for group_id in payload.get("groups_list", groups.keys()):
            record = groups.get(str(group_id), {})
            created_at = parse_dt(record.get("create_time")) or utcnow()
            group = Group(
                group_id=str(group_id),
                name=record.get("name"),
                active=bool(record.get("activate", True)),
                extra_json=record or None,
                created_at=created_at,
                updated_at=created_at,
            )
            self.session.merge(group)
            self.stats.groups += 1

    def _import_subscriptions_for_user(self, user_id: str, payload: Dict[str, Any]) -> int:
        created = 0
        created += self._import_subscription_list(
            user_id,
            payload.get("subscribe_tickets", []),
            SubscriptionTargetKind.PLAY,
        )
        created += self._import_subscription_list(
            user_id,
            payload.get("subscribe_events", []),
            SubscriptionTargetKind.EVENT,
        )
        created += self._import_subscription_list(
            user_id,
            payload.get("subscribe_actors", []),
            SubscriptionTargetKind.ACTOR,
        )
        return created

    def _import_subscription_list(
        self,
        user_id: str,
        entries: Iterable[Any],
        kind: SubscriptionTargetKind,
    ) -> int:
        created = 0
        for entry in entries or []:
            target_id, name, city, flags = self._extract_subscription_entry(entry)
            if not target_id and not name:
                continue
            subscription = Subscription(user_id=user_id)
            self.session.add(subscription)
            self.session.flush()
            target = SubscriptionTarget(
                subscription_id=subscription.id,
                kind=kind,
                target_id=target_id,
                name=name,
                city_filter=city,
                flags=flags or None,
            )
            option = SubscriptionOption(
                subscription_id=subscription.id,
                mute=bool(flags.get("mute", False)) if isinstance(flags, dict) else False,
                freq=SubscriptionFrequency.REALTIME,
                allow_broadcast=True,
                last_notified_at=parse_dt(flags.get("subscribe_time")) if isinstance(flags, dict) else None,
            )
            self.session.add(target)
            self.session.add(option)
            created += 1
        return created

    @staticmethod
    def _extract_subscription_entry(entry: Any) -> tuple[str, Optional[str], Optional[str], Dict[str, Any]]:
        if isinstance(entry, dict):
            value = entry.get("id") or entry.get("event_id") or entry.get("actor")
            if not value:
                value = entry.get("name") or entry.get("keyword")
            target_id = str(value) if value is not None else None
            city = entry.get("city") or entry.get("city_filter")
            name = entry.get("name")
            flags = {
                k: v
                for k, v in entry.items()
                if k
                not in {"id", "event_id", "actor", "name", "city", "city_filter"}
            }
            return target_id, name, city, flags
        return str(entry), None, None, {}

    def _import_aliases(self) -> None:
        payload = load_json(self.data_root / LEGACY_ALIAS_FILE)
        if not payload:
            print(f"[import] Skip aliases: {LEGACY_ALIAS_FILE} not found or empty")
            return

        alias_to_event = payload.get("alias_to_event", {})
        event_to_names = payload.get("event_to_names", {})
        no_response = payload.get("no_response", {})

        for alias, event_id in alias_to_event.items():
            play = self._get_or_create_play(str(event_id), event_to_names.get(str(event_id), []))
            self.stats.aliases += self._create_alias(
                play,
                alias,
                source="alias",
                weight=100,
                no_response=self._lookup_no_response(no_response, alias),
            )

        for event_id, names in event_to_names.items():
            play = self._get_or_create_play(str(event_id), names)
            for name in names:
                self.stats.aliases += self._create_alias(
                    play,
                    name,
                    source="search_name",
                    weight=50,
                    no_response=0,
                )

    def _get_or_create_play(self, legacy_event_id: str, names: Iterable[str]) -> Play:
        if legacy_event_id in self._play_cache:
            return self._play_cache[legacy_event_id]

        primary_name = next((n for n in names if n), f"Legacy-{legacy_event_id}")
        play = Play(
            name=primary_name,
            name_norm=normalize(primary_name),
            note=f"Imported from legacy alias {legacy_event_id}",
        )
        self.session.add(play)
        self.session.flush()
        link = PlaySourceLink(
            play_id=play.id,
            source=PlaySource.LEGACY,
            source_id=legacy_event_id,
            title_at_source=primary_name,
        )
        self.session.add(link)
        self._play_cache[legacy_event_id] = play
        self.stats.plays += 1
        return play

    def _create_alias(
        self,
        play: Play,
        alias: str,
        *,
        source: str,
        weight: int,
        no_response: int,
    ) -> int:
        alias_norm = normalize(alias)
        if not alias_norm:
            return 0
        existing = self.session.exec(
            select(PlayAlias).where(
                PlayAlias.play_id == play.id,
                PlayAlias.alias_norm == alias_norm,
            )
        ).first()
        if existing:
            return 0
        self.session.add(
            PlayAlias(
                play_id=play.id,
                alias=alias,
                alias_norm=alias_norm,
                source=source,
                weight=weight,
                no_response_count=no_response,
            )
                )
        return 1

    @staticmethod
    def _lookup_no_response(
        no_response_map: Dict[str, Any],
        alias: str,
    ) -> int:
        prefix = f"{alias}:"
        values = [int(v) for k, v in no_response_map.items() if k.startswith(prefix)]
        return max(values) if values else 0

    # ------------------------------------------------------------------
    # HLQ + Snapshot import paths
    # ------------------------------------------------------------------
    def _import_hlq_events(self) -> None:
        payload = load_json(self.data_root / LEGACY_HLQ_FILE)
        if not payload:
            print(f"[import] Skip HLQ events: {LEGACY_HLQ_FILE} not found or empty")
            return

        for event_id, event_payload in (payload.get("events") or {}).items():
            event = build_hlq_event(str(event_id), event_payload or {})
            existing = self.session.get(HLQEvent, event.hlq_event_id)
            if existing:
                existing.title = event.title
                existing.title_norm = event.title_norm
                existing.location = event.location
                existing.start_time = event.start_time
                existing.update_time = event.update_time
                existing.updated_at = utcnow()
            else:
                self.session.add(event)
                self.stats.hlq_events += 1

            tickets = (event_payload or {}).get("ticket_details") or {}
            for ticket_payload in tickets.values():
                ticket = build_hlq_ticket(event, ticket_payload or {})
                if not ticket:
                    continue
                existing_ticket = self.session.exec(
                    select(HLQTicket).where(
                        HLQTicket.hlq_event_id == ticket.hlq_event_id,
                        HLQTicket.ticket_id == ticket.ticket_id,
                    )
                ).first()
                if existing_ticket:
                    existing_ticket.status = ticket.status
                    existing_ticket.price = ticket.price
                    existing_ticket.total = ticket.total
                    existing_ticket.left = ticket.left
                    existing_ticket.valid_from = ticket.valid_from
                    existing_ticket.start_time = ticket.start_time
                    existing_ticket.payload = ticket.payload
                    existing_ticket.updated_at = utcnow()
                else:
                    self.session.add(ticket)
                    self.stats.hlq_tickets += 1

    def _import_play_snapshots(self) -> None:
        payload = load_json(self.data_root / LEGACY_SNAPSHOT_FILE)
        if not payload:
            print(f"[import] Skip Saoju snapshots: {LEGACY_SNAPSHOT_FILE} not found or empty")
            return

        for group in group_saoju_entries(payload):
            title = group.get("title")
            city_norm = group.get("city_norm")
            if not title or not city_norm:
                continue
            play = self._get_or_create_play_by_name(title)
            snapshot = self.session.exec(
                select(PlaySnapshot).where(
                    PlaySnapshot.play_id == play.id,
                    PlaySnapshot.city_norm == city_norm,
                )
            ).first()
            payload_body = {
                "source": "legacy_saoju",
                "city": group.get("city"),
                "records": group.get("records"),
            }
            record_times = [
                parse_dt(record.get("start_time"))
                for record in group.get("records", [])
                if record.get("start_time")
            ]
            last_success = max(record_times) if record_times else utcnow()
            if snapshot:
                snapshot.payload = payload_body
                snapshot.last_success_at = last_success
                snapshot.ttl_seconds = 86400
                snapshot.stale = False
                snapshot.updated_at = utcnow()
            else:
                self.session.add(
                    PlaySnapshot(
                        play_id=play.id,
                        city_norm=city_norm,
                        payload=payload_body,
                        last_success_at=last_success,
                        ttl_seconds=86400,
                        stale=False,
                    )
                )
                self.stats.snapshots += 1

    def _import_metrics_and_errors(self) -> None:
        payload = load_json(self.data_root / LEGACY_STATS_FILE)
        if not payload:
            print(f"[import] Skip Stats: {LEGACY_STATS_FILE} not found or empty")
            return

        for metric in iter_command_metrics(payload):
            if self._upsert_metric(metric):
                self.stats.metrics += 1
        for log in iter_repo_error_logs(payload):
            if self._upsert_error_log(log):
                self.stats.error_logs += 1

    def _get_or_create_play_by_name(self, title: str) -> Play:
        normalized = normalize(title)
        if not normalized:
            normalized = f"legacy-play-{hashlib.sha1(title.encode('utf-8')).hexdigest()[:8]}"
        existing = self.session.exec(select(Play).where(Play.name_norm == normalized)).first()
        if existing:
            return existing
        play = Play(
            name=title,
            name_norm=normalized,
            note="Imported from Saoju schedule",
        )
        self.session.add(play)
        self.session.flush()
        self.stats.plays += 1
        return play

    def _upsert_metric(self, metric: Metric) -> bool:
        stmt = select(Metric).where(
            Metric.name == metric.name,
            Metric.labels_hash == metric.labels_hash,
        )
        existing = self.session.exec(stmt).first()
        if existing:
            existing.value = metric.value
            existing.labels = metric.labels
            existing.updated_at = utcnow()
            return False
        self.session.add(metric)
        return True

    def _upsert_error_log(self, log: ErrorLog) -> bool:
        stmt = select(ErrorLog).where(
            ErrorLog.scope == log.scope,
            ErrorLog.code == log.code,
            ErrorLog.message == log.message,
            ErrorLog.ts == log.ts,
        )
        existing = self.session.exec(stmt).first()
        if existing:
            return False
        self.session.add(log)
        return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import legacy JSON data into SQLite")
    parser.add_argument(
        "--data-root",
        default="data/data_manager",
        help=(
            "Directory that contains UsersManager.json/alias.json/"
            "HulaquanDataManager.json/SaojuDataManager.json/StatsDataManager.json"
        ),
    )
    parser.add_argument(
        "--db-path",
        default="data/musicalbot.db",
        help="SQLite file to migrate into",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load data but roll back the transaction after validation",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_root = Path(args.data_root)
    if not data_root.exists():
        raise SystemExit(f"Data directory {data_root} does not exist")

    engine = init_db(args.db_path)
    with Session(engine) as session:
        importer = LegacyImporter(data_root, session)
        stats = importer.run()
        if args.dry_run:
            session.rollback()
            print("[import] Dry-run complete; no data committed.")
        else:
            session.commit()
            print("[import] Migration finished:", stats.as_dict())


if __name__ == "__main__":
    main()
