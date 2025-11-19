if __name__ == '__main__':
    import os
    os.chdir("f:/MusicalBot/")
    import sys
    sys.path.append("f:/MusicalBot")


import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence

import aiohttp
import pandas as pd

from plugins.Hulaquan import BaseDataManager
from plugins.Hulaquan.utils import *

class SaojuDataManager(BaseDataManager):
    """Manage Saoju data with the latest JSON APIs instead of HTML scraping."""

    API_BASE = "https://y.saoju.net/yyj/api"
    DATE_CACHE_TTL_HOURS = 1
    MUSICAL_SHOW_CACHE_TTL_HOURS = 6
    ARTIST_INDEX_TTL_HOURS = 24
    ARTIST_LOOKBACK_DAYS = 180
    ARTIST_LOOKAHEAD_DAYS = 365
    WEEKDAY_LABEL = ["一", "二", "三", "四", "五", "六", "日"]

    def __init__(self, file_path=None):
        self._artist_index_lock = asyncio.Lock()
        super().__init__(file_path)

    def on_load(self):
        self.data.setdefault("date_dict", {})
        self.data.setdefault("musical_show_cache", {})
        self.data.setdefault("artists_map", {})
        self.data.setdefault("artist_indexes", {})
        update_dict = self.data.setdefault("update_time_dict", {})
        update_dict.setdefault("date_dict", {})
        update_dict.setdefault("musical_show_cache", {})
        self.refresh_expired_data()

    async def search_day_async(self, date: str, city: Optional[str] = None) -> Optional[Dict]:
        params = {"date": date}
        if city:
            params["city"] = city
        return await self._fetch_json("search_day/", params=params)

    async def get_data_by_date_async(self, date, update_delta_max_hours=1):
        cached = self._get_cached_entry(
            self.data["date_dict"],
            self.data["update_time_dict"]["date_dict"],
            date,
            update_delta_max_hours,
        )
        if cached is not None:
            return cached
        data = await self.search_day_async(date)
        show_list = (data or {}).get("show_list") if data else None
        if show_list is not None:
            self._set_cached_entry(
                self.data["date_dict"],
                self.data["update_time_dict"]["date_dict"],
                date,
                show_list,
            )
        return show_list

    async def search_for_musical_by_date_async(self, search_name, date_time, city=None):
        date_time = parse_datetime(date_time)
        if not date_time:
            return None
        target_date = dateToStr(date_time)
        target_time = timeToStr(date_time)
        names = self._normalize_search_names(search_name)
        if not names:
            return None
        for name in names:
            show_list = await self._get_musical_shows(name, target_date, target_date)
            match = self._match_show_entry(show_list, target_date, target_time, city, names)
            if match:
                return match
        # 兜底：回退到按日期缓存匹配，避免因关键字不完全导致的漏匹配
        daily_data = await self.get_data_by_date_async(target_date)
        if not daily_data:
            return None
        for show in daily_data:
            if target_time != show.get("time"):
                continue
            if city and city not in show.get("city", ""):
                continue
            if any(name in show.get("musical", "") for name in names):
                return show
        return None

    def refresh_expired_data(self):
        current_date = datetime.now()
        date_updates = self.data["update_time_dict"].get("date_dict", {})
        for date_key in list(date_updates.keys()):
            update_str = date_updates.get(date_key)
            date_obj = parse_datetime(update_str) if update_str else None
            if not date_obj or (current_date - date_obj) >= timedelta(hours=self.DATE_CACHE_TTL_HOURS):
                self.data["date_dict"].pop(date_key, None)
                date_updates.pop(date_key, None)
        musical_updates = self.data["update_time_dict"].get("musical_show_cache", {})
        for cache_key in list(musical_updates.keys()):
            update_str = musical_updates.get(cache_key)
            date_obj = parse_datetime(update_str) if update_str else None
            if not date_obj or (current_date - date_obj) >= timedelta(hours=self.MUSICAL_SHOW_CACHE_TTL_HOURS):
                self.data["musical_show_cache"].pop(cache_key, None)
                musical_updates.pop(cache_key, None)

    async def search_for_artist_async(self, search_name, date):
        date = dateToStr(date)
        data = await self.get_data_by_date_async(date)
        schedule = []
        if not data:
            return schedule
        for i in range(len(data)):
            for cast in data[i]["cast"]:
                if cast["artist"] == search_name:
                    schedule.append(data[i])
        return schedule

    async def search_artist_from_timetable_async(self, search_name, timetable: list):
        schedule = []
        for date in timetable:
            show = await self.search_for_artist_async(search_name, date)
            for i in show:
                show_date = dateToStr(date=date) + " " + i["time"]
                show_date = parse_datetime(show_date)
                schedule.append((show_date, i))
        schedule.sort(key=lambda x: x[0])
        return schedule

    async def check_artist_schedule_async(self, start_time, end_time, artist):
        timetable = delta_time_list(start_time, end_time)
        schedule = await self.search_artist_from_timetable_async(artist, timetable)
        data = []
        for event in schedule:
            date = event[0]
            info = event[1]
            data.append({
                '日期': date.strftime('%Y-%m-%d %H:%M'),
                '剧名': info['musical'],
                '时间': info['time'],
                '剧场': info['theatre'],
                '城市': info['city'],
                '卡司': " ".join([i["artist"] for i in info['cast']])
            })
        df = pd.DataFrame(data)
        schedule.sort(key=lambda x: x[0])
        return schedule
        
    def check_artist_schedule(self, start_time, end_time, artist):
        #start_time = "2025-05-19"
        #end_time = "2025-06-30"
        #artist = "丁辰西"
        timetable = delta_time_list(start_time, end_time)
        schedule = self.search_artist_from_timetable(artist, timetable)
        data = []
        for event in schedule:
            date = event[0]
            info = event[1]
            data.append({
                '日期': date.strftime('%Y-%m-%d %H:%M'),
                '剧名': info['musical'],
                '时间': info['time'],
                '剧场': info['theatre'],
                '城市': info['city'],
                '卡司': " ".join([i["artist"] for i in info['cast']])
            })

        df = pd.DataFrame(data)
        summary = (
            f"演员: {artist}\n"
            f"从{start_time}到{end_time}的排期\n"
            f"排期数量: {len(df)}\n"
            f"{df.to_string(index=False, justify='left')}"
        )
        return summary
    
    
            
    async def get_artist_events_data(self, cast_name: str) -> List[Dict]:
        await self._ensure_artist_map()
        artist_id = self.data.get("artists_map", {}).get(cast_name)
        if not artist_id:
            return []
        indexes = await self._ensure_artist_indexes()
        artist_musicals = indexes.get("artist_musicals", {}).get(str(artist_id), {})
        if not artist_musicals:
            return []
        begin_date = (datetime.now() - timedelta(days=self.ARTIST_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
        end_date = (datetime.now() + timedelta(days=self.ARTIST_LOOKAHEAD_DAYS)).strftime("%Y-%m-%d")
        events: List[Dict] = []
        seen_keys = set()
        for musical_info in artist_musicals.values():
            musical_name = musical_info.get("name")
            if not musical_name:
                continue
            show_list = await self._get_musical_shows(musical_name, begin_date, end_date)
            for show in show_list:
                cast_list = show.get("cast") or []
                matched = next((c for c in cast_list if c.get("artist") == cast_name), None)
                if not matched:
                    continue
                time_str = show.get("time")
                try:
                    dt = parse_datetime(time_str)
                except Exception:
                    continue
                if not dt:
                    continue
                formatted_date = self._format_readable_date(dt)
                city = show.get("city") or ""
                theatre = show.get("theatre") or ""
                others = [c.get("artist") for c in cast_list if c.get("artist") and c.get("artist") != cast_name]
                dedupe_key = (musical_name, dt.isoformat(), city)
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                events.append(
                    {
                        "date": formatted_date,
                        "title": show.get("musical") or musical_name,
                        "role": matched.get("role") or " / ".join(musical_info.get("roles", [])),
                        "others": others,
                        "city": city,
                        "location": theatre,
                    }
                )
        events.sort(key=lambda entry: standardize_datetime_for_saoju(entry["date"]))
        return events
    
    async def match_co_casts(self, co_casts: list, show_others=True, return_data=False):
        search_name = co_casts[0]
        _co_casts = co_casts[1:]
        events = await self.get_artist_events_data(search_name)
        result = []
        latest = ""
        for event in events:
            others_field = event.get('others') or []
            if isinstance(others_field, str):
                others = [name for name in others_field.split() if name]
            else:
                others = list(others_field)
            if all(cast in others for cast in _co_casts): 
                remaining = [item for item in others if item not in _co_casts]
                dt = event['date']
                event['date'] = standardize_datetime_for_saoju(dt, return_str=True, latest_str=latest)
                latest = dt
                event['others'] = remaining
                result.append(event)
        if return_data:
            return result
        else:
            return self.generate_co_casts_message(co_casts, show_others, result)

    def generate_co_casts_message(self, co_casts, show_others, co_casts_data):
        messages = []
        messages.append(" ".join(co_casts)+f"同场的音乐剧演出，目前有{len(co_casts_data)}场。")
        for event in co_casts_data:
            extra = ""
            if show_others and event.get('others'):
                extra = "\n同场其他演员：" + " ".join(event['others'])
            messages.append(f"{event['date']} {event['city']} {event['title']}{extra}")
        return messages

    async def request_co_casts_data(self, co_casts: list, show_others=False):
        return await self.match_co_casts(co_casts, show_others, return_data=True)
        
    
    async def fetch_saoju_artist_list(self):
        data = await self._fetch_json("artist/")
        if not data:
            return {}
        name_to_pk = {item.get("fields", {}).get("name"): item.get("pk") for item in data if item.get("fields")}
        # 移除值为None的条目
        return {name: pk for name, pk in name_to_pk.items() if name and pk}

    async def _fetch_json(self, path: str, params: Optional[Dict] = None) -> Optional[Dict]:
        url = f"{self.API_BASE}/{path.lstrip('/')}"
        last_error = None
        for attempt in range(5):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params, timeout=10) as response:
                        response.raise_for_status()
                        return await response.json()
            except aiohttp.ClientError as exc:
                last_error = exc
            except Exception as exc:  # noqa: BLE001
                last_error = exc
            await asyncio.sleep(1)
        print(f"SAOJU ERROR: failed to fetch {url} with params {params}: {last_error}")
        return None

    def _get_cached_entry(self, bucket: Dict, timestamps: Dict, key: str, ttl_hours: float):
        if key not in bucket:
            return None
        ts_str = timestamps.get(key)
        ts = parse_datetime(ts_str) if ts_str else None
        if ts and (datetime.now() - ts) < timedelta(hours=ttl_hours):
            return bucket[key]
        return None

    def _set_cached_entry(self, bucket: Dict, timestamps: Dict, key: str, value):
        bucket[key] = value
        timestamps[key] = dateTimeToStr(datetime.now())

    def _normalize_search_names(self, search_name) -> Sequence[str]:
        if isinstance(search_name, str):
            return [search_name]
        if isinstance(search_name, Sequence):
            return [str(item) for item in search_name if item]
        return []

    def _match_show_entry(self, show_list, target_date: str, target_time: str, city: Optional[str], names: Sequence[str]):
        if not show_list:
            return None
        for show in show_list:
            show_time_str = show.get("time")
            if not show_time_str:
                continue
            try:
                show_dt = parse_datetime(show_time_str)
            except Exception:
                continue
            if dateToStr(show_dt) != target_date:
                continue
            if show_dt.strftime("%H:%M") != target_time:
                continue
            if city and city not in show.get("city", ""):
                continue
            musical_name = show.get("musical", "")
            if any(name in musical_name for name in names):
                return show
        return None

    async def _get_musical_shows(self, musical: str, begin_date: str, end_date: str):
        if not musical:
            return []
        cache_key = f"{musical}|{begin_date}|{end_date}"
        cached = self._get_cached_entry(
            self.data["musical_show_cache"],
            self.data["update_time_dict"]["musical_show_cache"],
            cache_key,
            self.MUSICAL_SHOW_CACHE_TTL_HOURS,
        )
        if cached is not None:
            return cached
        response = await self._fetch_json(
            "search_musical_show/",
            params={"musical": musical, "begin_date": begin_date, "end_date": end_date},
        )
        show_list = (response or {}).get("show_list", []) if response else []
        self._set_cached_entry(
            self.data["musical_show_cache"],
            self.data["update_time_dict"]["musical_show_cache"],
            cache_key,
            show_list,
        )
        return show_list

    async def _ensure_artist_map(self):
        if self.data.get('artists_map'):
            return
        self.data['artists_map'] = await self.fetch_saoju_artist_list()

    async def _ensure_artist_indexes(self):
        indexes = self.data.get("artist_indexes") or {}
        updated_at = indexes.get("updated_at")
        needs_refresh = True
        if updated_at:
            dt = parse_datetime(updated_at)
            if dt and (datetime.now() - dt) < timedelta(hours=self.ARTIST_INDEX_TTL_HOURS):
                needs_refresh = False
        if not needs_refresh:
            return indexes
        async with self._artist_index_lock:
            # 双重检查，避免重复刷新
            indexes = self.data.get("artist_indexes") or {}
            updated_at = indexes.get("updated_at")
            if updated_at:
                dt = parse_datetime(updated_at)
                if dt and (datetime.now() - dt) < timedelta(hours=self.ARTIST_INDEX_TTL_HOURS):
                    return indexes
            new_indexes = await self._build_artist_indexes()
            if new_indexes:
                self.data["artist_indexes"] = new_indexes
                await self.save()
            return self.data.get("artist_indexes", {})

    async def _build_artist_indexes(self) -> Optional[Dict]:
        musical_data, role_data, cast_data = await asyncio.gather(
            self._fetch_json("musical/"),
            self._fetch_json("role/"),
            self._fetch_json("musicalcast/"),
        )
        if not musical_data or not role_data or not cast_data:
            return self.data.get("artist_indexes")
        musical_lookup = {str(item["pk"]): item.get("fields", {}).get("name", "") for item in musical_data}
        role_lookup = {
            str(item["pk"]): {
                "musical": str(item.get("fields", {}).get("musical")),
                "name": item.get("fields", {}).get("name", ""),
            }
            for item in role_data
        }
        artist_musicals: Dict[str, Dict[str, Dict[str, List[str]]]] = defaultdict(dict)
        for cast in cast_data:
            fields = cast.get("fields") or {}
            artist_id = fields.get("artist")
            role_id = fields.get("role")
            if artist_id is None or role_id is None:
                continue
            role_info = role_lookup.get(str(role_id))
            if not role_info:
                continue
            musical_id = role_info.get("musical")
            if not musical_id:
                continue
            entry = artist_musicals[str(artist_id)].setdefault(
                str(musical_id),
                {"roles": set(), "name": musical_lookup.get(str(musical_id), "")},
            )
            entry["roles"].add(role_info.get("name") or "")
        normalized: Dict[str, Dict[str, Dict[str, List[str]]]] = {}
        for artist_id, musicals in artist_musicals.items():
            normalized[artist_id] = {}
            for musical_id, payload in musicals.items():
                roles = sorted({role for role in payload["roles"] if role})
                normalized[artist_id][musical_id] = {"roles": roles, "name": payload.get("name", "")}
        return {
            "artist_musicals": normalized,
            "updated_at": dateTimeToStr(datetime.now(), with_second=True),
        }

    def _format_readable_date(self, dt: datetime) -> str:
        weekday = self.WEEKDAY_LABEL[dt.weekday()]
        return f"{dt.month:02d}月{dt.day:02d}日 星期{weekday} {dt.strftime('%H:%M')}"

    def search_artist_from_timetable(self, search_name, timetable):
        """同步调用封装，便于兼容旧代码路径。"""

        return asyncio.run(self.search_artist_from_timetable_async(search_name, timetable))


def search_artist_from_timetable(artist, timetable):
    """Legacy synchronous helper used by match_artists_on_schedule."""

    manager = SaojuDataManager()
    return manager.search_artist_from_timetable(artist, timetable)
    
def match_artists_on_schedule(
    artists, 
    start_time, 
    end_time, 
    week_time_slots,  # [["20:00"], ["20:00"], ["20:00"], ["20:00"], ["20:00"], ["14:00","17:00", "20:00"], ["14:00","17:00", "20:00"]]
    min_gap_hours=4, 
    target_city="上海", 
    cross_city_gap_hours=15
):
    """
    week_time_slots: 长度为7的列表，每个元素为当天需要判断的时间点字符串列表（如["20:00"]或["14:00","17:00","20:00"]）
    min_gap_hours: 同城赶场所需最少小时数
    target_city: 目标演出城市
    cross_city_gap_hours: 跨城市赶场所需最少小时数
    """
    timetable = delta_time_list(start_time, end_time)
    # 构建每个演员的排期字典: {artist: {date: [(datetime, city)]}}
    artist_schedules = {}
    for artist in artists:
        schedule = search_artist_from_timetable(artist, timetable)
        daily_events = {}
        for show_time, info in schedule:
            date_str = dateToStr(date=show_time)
            city = info.get("city", "")
            if date_str not in daily_events:
                daily_events[date_str] = []
            daily_events[date_str].append((show_time, city))
        artist_schedules[artist] = daily_events

    free_slots = []
    for date in timetable:
        date_str = date.strftime("%Y-%m-%d")
        weekday = date.weekday()  # 0=周一, 6=周日
        for slot_time_str in week_time_slots[weekday]:
            slot_time = datetime.strptime(slot_time_str, "%H:%M").time()
            slot_dt = datetime.combine(date, slot_time)
            all_free = True
            for artist in artists:
                busy = False
                events = artist_schedules[artist].get(date_str, [])
                for event_time, event_city in events:
                    # 计算时间间隔
                    delta_hours = abs((slot_dt - event_time).total_seconds()) / 3600
                    if event_city == target_city:
                        need_gap = min_gap_hours
                    else:
                        need_gap = cross_city_gap_hours
                    if delta_hours < need_gap:
                        busy = True
                        break
                if busy:
                    all_free = False
                    break
            if all_free:
                free_slots.append({"日期": date_str, "时间": slot_time_str})

    df = pd.DataFrame(free_slots)
    if not df.empty:
        df = df.sort_values(by=["日期", "时间"]).reset_index(drop=True)
        # 增加“星期”列
        df["星期"] = df["日期"].apply(lambda x: ["一", "二", "三", "四", "五", "六", "日"][datetime.strptime(x, "%Y-%m-%d").weekday()])
        # 调整列顺序
        df = df[["日期", "星期", "时间"]]
    print("演员: {}".format(", ".join(artists)))
    print("所有演员都空闲的指定时间段日期：")
    print(df)

if __name__ == "__main__":
    import asyncio
    async def test_match_co_casts():
        manager = SaojuDataManager()
        # 示例演员列表，替换为实际存在的演员名
        co_casts = ["丁辰西", "陈玉婷"]
        messages = await manager.match_co_casts(co_casts, show_others=True)
        for msg in messages:
            print(msg)
    asyncio.run(test_match_co_casts())
