"""Compat wrapper that mimics the legacy AliasManager API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from sqlmodel import Session, select

from services.db.models import Play, PlayAlias, PlaySource, PlaySourceLink

from .context import CompatContext, get_default_context
from .utils import normalize_text


@dataclass
class _PlayHandle:
    play: Play
    link: PlaySourceLink


class AliasManagerCompat:
    def __init__(self, context: CompatContext | None = None):
        self.context = context or get_default_context()

    # ------------------------------------------------------------------
    # Legacy read helpers
    # ------------------------------------------------------------------
    def get_event_id_by_alias(self, alias: str) -> Optional[str]:
        alias_norm = normalize_text(alias)
        with self.context.session() as session:
            entry = self._find_alias(session, alias_norm)
            if not entry:
                return None
            return self._resolve_event_id(session, entry.play_id)

    def get_event_id_by_name(self, search_name: str) -> Optional[str]:
        return self.get_event_id_by_alias(search_name)

    def get_search_names(self, event_id: str) -> List[str]:
        event_id = str(event_id)
        with self.context.session() as session:
            handle = self._get_play_by_event_id(session, event_id)
            if not handle:
                return []
            stmt = (
                select(PlayAlias)
                .where(
                    PlayAlias.play_id == handle.play.id,
                    PlayAlias.source == "search_name",
                )
                .order_by(PlayAlias.created_at)
            )
            return [row.alias for row in session.exec(stmt)]

    # ------------------------------------------------------------------
    # Legacy mutating helpers
    # ------------------------------------------------------------------
    def set_alias(self, event_id: str | int, alias: str) -> bool:
        event_id = str(event_id)
        alias_norm = normalize_text(alias)
        with self.context.session() as session:
            handle = self._get_or_create_play(session, event_id, alias)
            self._upsert_alias(session, handle.play, alias, alias_norm, source="alias", weight=100)
            session.commit()
        return True

    def add_search_name(self, event_id: str | int, search_name: str) -> bool:
        event_id = str(event_id)
        alias_norm = normalize_text(search_name)
        with self.context.session() as session:
            handle = self._get_or_create_play(session, event_id, search_name)
            self._upsert_alias(session, handle.play, search_name, alias_norm, source="search_name", weight=50)
            session.commit()
        return True

    def delete_alias(self, alias: str) -> bool:
        alias_norm = normalize_text(alias)
        with self.context.session() as session:
            entry = self._find_alias(session, alias_norm)
            if not entry:
                return False
            session.delete(entry)
            session.commit()
            return True

    def set_no_response(self, alias: str, search_name: str, reset: bool = False) -> None:
        key = f"{alias}:{search_name}"
        cache = self.context.alias_no_response_cache
        if reset:
            cache[key] = 0
        else:
            cache[key] = cache.get(key, 0) + 1

    # ------------------------------------------------------------------
    # Export helpers used by tests and migration scripts
    # ------------------------------------------------------------------
    def export_payload(self) -> Dict[str, Dict[str, str] | Dict[str, List[str]]]:
        with self.context.session() as session:
            links = session.exec(
                select(PlaySourceLink)
                .where(PlaySourceLink.source == PlaySource.LEGACY)
                .order_by(PlaySourceLink.source_id)
            ).all()
            alias_to_event: Dict[str, str] = {}
            event_to_names: Dict[str, List[str]] = {}
            name_to_alias: Dict[str, str] = {}

            for link in links:
                event_id = link.source_id
                stmt = (
                    select(PlayAlias)
                    .where(PlayAlias.play_id == link.play_id)
                    .order_by(PlayAlias.created_at)
                )
                aliases = session.exec(stmt).all()
                search_names: List[str] = []
                fallback_names: List[str] = []
                for alias_row in aliases:
                    if alias_row.source == "alias" or alias_row.source is None:
                        alias_to_event[alias_row.alias] = event_id
                        fallback_names.append(alias_row.alias)
                    else:
                        search_names.append(alias_row.alias)
                        name_to_alias[alias_row.alias] = event_id
                if not search_names:
                    search_names = fallback_names
                if search_names:
                    event_to_names[event_id] = sorted(search_names)
                else:
                    event_to_names.setdefault(event_id, [])

        return {
            "alias_to_event": alias_to_event,
            "event_to_names": event_to_names,
            "name_to_alias": name_to_alias,
            "no_response": dict(self.context.alias_no_response_cache),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _find_alias(self, session: Session, alias_norm: str) -> Optional[PlayAlias]:
        stmt = select(PlayAlias).where(PlayAlias.alias_norm == alias_norm)
        return session.exec(stmt).first()

    def _resolve_event_id(self, session: Session, play_id: int) -> Optional[str]:
        stmt = select(PlaySourceLink).where(
            PlaySourceLink.play_id == play_id,
            PlaySourceLink.source == PlaySource.LEGACY,
        )
        link = session.exec(stmt).first()
        return link.source_id if link else None

    def _get_play_by_event_id(self, session: Session, event_id: str) -> Optional[_PlayHandle]:
        stmt = select(PlaySourceLink, Play).where(
            PlaySourceLink.source == PlaySource.LEGACY,
            PlaySourceLink.source_id == event_id,
            PlaySourceLink.play_id == Play.id,
        )
        result = session.exec(stmt).first()
        if not result:
            return None
        link, play = result
        return _PlayHandle(play=play, link=link)

    def _get_or_create_play(self, session: Session, event_id: str, fallback_name: str) -> _PlayHandle:
        existing = self._get_play_by_event_id(session, event_id)
        if existing:
            return existing
        play = Play(name=fallback_name, name_norm=normalize_text(fallback_name))
        session.add(play)
        session.flush()
        link = PlaySourceLink(
            play_id=play.id,
            source=PlaySource.LEGACY,
            source_id=event_id,
            title_at_source=fallback_name,
        )
        session.add(link)
        session.flush()
        return _PlayHandle(play=play, link=link)

    def _upsert_alias(
        self,
        session: Session,
        play: Play,
        alias: str,
        alias_norm: str,
        *,
        source: str,
        weight: int,
    ) -> PlayAlias:
        stmt = select(PlayAlias).where(
            PlayAlias.play_id == play.id,
            PlayAlias.alias_norm == alias_norm,
        )
        existing = session.exec(stmt).first()
        if existing:
            existing.alias = alias
            existing.source = source
            existing.weight = weight
            return existing
        entry = PlayAlias(
            play_id=play.id,
            alias=alias,
            alias_norm=alias_norm,
            source=source,
            weight=weight,
        )
        session.add(entry)
        return entry
