from datetime import datetime, timedelta
from plugins.Hulaquan.utils import *
from plugins.Hulaquan import BaseDataManager
from collections import defaultdict
from .Exceptions import *
import aiohttp
import os, shutil
import copy
import json
import asyncio
import re

"""
    更新思路：
    1.按照是否修改self将函数数据分类
    """



class HulaquanDataManager(BaseDataManager):

   

    
    """
    功能：
    1.存储/调取卡司排期数据
    2.根据卡司数据有效期刷新
    
    {
        "events":{}
        "update_time":datetime
    }
    """
    def __init__(self, file_path=None):
        super().__init__(file_path)
           
    def on_load(self):
        global Saoju, Stats, Alias, User
        import importlib
        
        dataManagers = importlib.import_module('plugins.Hulaquan.data_managers')
        Saoju = dataManagers.Saoju  # 动态获取
        Stats = dataManagers.Stats  # 动态获取
        Alias = dataManagers.Alias  # 动态获取
        User = dataManagers.User  # 动态获取
        self.semaphore = asyncio.Semaphore(10)  # 限制并发量10
        self.data.setdefault("events", {})  # 确保有一个事件字典来存储数据
        self.data["pending_events"] = self.data.get("pending_events", {}) # 确保有一个pending_events来存储待办事件
        self.data["ticket_id_to_event_id"] = self.data.get("ticket_id_to_event_id", {})
        self.update_ticket_dict_async()

    async def _update_events_dict_async(self):
        data = await self.search_all_events_async()
        data_dic = {"events": {}, "update_time": ""}
        keys_to_extract = ["id", "title", "location", "start_time", "end_time", "update_time", "deadline", "create_time"]
        for event in data:
            event_id = event['id'] = str(event['id'])
            Stats.register_event(event['title'], event_id)
            if event_id not in data_dic["events"]:
                data_dic["events"][event_id] = {key: event.get(key, None) for key in keys_to_extract}
        data_dic["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.data["events"] = data_dic["events"]
        self.data["last_update_time"] = self.data.get("update_time", None)
        self.data["update_time"] = data_dic["update_time"]
        return data_dic

    async def search_all_events_async(self):
        data = False
        cnt = 95
        while data is False:
            count, result = await self.search_events_data_by_recommendation_link_async(cnt, 0, True)
            data = result
            cnt -= 5
            if cnt != 90 and not data:
                print(f"获取呼啦圈数据失败，第{(19-cnt/5)}尝试。")
            if cnt == 75:
                raise RequestTimeoutException
        return data

    async def search_events_data_by_recommendation_link_async(self, limit=12, page=0, timeMark=True, tags=None):
        recommendation_url = "https://clubz.cloudsation.com/site/getevent.html?filter=recommendation&access_token="
        try:
            recommendation_url = recommendation_url + "&limit=" + str(limit) + "&page=" + str(page)
            
            # 配置超时(包括DNS解析超时)
            timeout = aiohttp.ClientTimeout(
                total=15,      # 总超时
                connect=5,     # 连接超时
                sock_connect=5,# Socket连接超时(DNS解析)
                sock_read=10   # 读取超时
            )
            
            # 配置连接器(DNS缓存、连接池)
            connector = aiohttp.TCPConnector(
                limit=10,
                ttl_dns_cache=300,  # DNS缓存5分钟
                family=0  # 同时支持IPv4/IPv6
            )
            
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.get(recommendation_url) as response:
                    json_data = await response.text()
                    json_data = json_data.encode().decode("utf-8-sig")  # 关键：去除BOM
                    json_data = json.loads(json_data)
                    if isinstance(json_data, bool):
                        return False, False
                    result = []
                    for event in json_data["events"]:
                        if not timeMark or (timeMark and event["timeMark"] > 0):
                            if not tags or (tags and any(tag in event["tags"] for tag in tags)):
                                result.append(event["basic_info"])
                    return json_data["count"], result
        except asyncio.TimeoutError:
            return "请求超时(可能是DNS解析失败或网络断连)", False
        except aiohttp.ClientConnectorError as e:
            # DNS解析错误或连接失败
            return f"连接失败(DNS或网络问题): {e}", False
        except Exception as e:
            return f"Error fetching recommendation: {e}", False

    async def _update_events_data_async(self):
        if self.updating:
            return self.data
        self.updating = True
        try:
            await self._update_events_dict_async()
            event_ids = list(self.events().keys())
            # 并发批量更新
            await asyncio.gather(*(self._update_ticket_details_async(eid) for eid in event_ids))
        except RequestTimeoutException:
            self.updating = False
            raise
        except Exception as e:
            self.updating = False
            raise
        self.updating = False
        return self.data

    async def _update_ticket_details_async(self, event_id, data_dict=None):
        retry = 0
        while retry < 3:
            async with self.semaphore:
                try:
                    json_data = await self.search_event_by_id_async(event_id)
                    keys_to_extract = ["id","event_id","title", "start_time", "end_time","status","create_time","ticket_price","total_ticket", "left_ticket_count", "left_days", "valid_from"]
                    ticket_list = json_data["ticket_details"]
                    ticket_dump_list = {}
                    
                    # 获取旧的 ticket_details 以保留 cast 和 city 数据
                    old_tickets = self.data.get("events", {}).get(event_id, {}).get("ticket_details", {})
                    
                    for i in range(len(ticket_list)):
                        ticket = ticket_list[i]
                        tid = ticket['id'] = str(ticket.get("id", 0))
                        if not tid or ticket.get("total_ticket", None) is None or not ticket.get('start_time') or ticket.get("status") not in ['active', 'pending']:
                            if ticket.get("status") != "expired":
                                print(ticket)
                            continue
                        ticket_dump_list[tid] = {key: ticket.get(key, None) for key in keys_to_extract}
                        
                        # 保留已有的 cast 和 city 数据
                        if tid in old_tickets:
                            if "cast" in old_tickets[tid]:
                                ticket_dump_list[tid]["cast"] = old_tickets[tid]["cast"]
                            if "city" in old_tickets[tid]:
                                ticket_dump_list[tid]["city"] = old_tickets[tid]["city"]
                        
                        if tid not in self.data['ticket_id_to_event_id'].keys():
                            self.data['ticket_id_to_event_id'][tid] = event_id
                    if data_dict is None:
                        self.data["events"][event_id]["ticket_details"] = ticket_dump_list
                        return self.data
                    else:
                        data_dict["events"][event_id]["ticket_details"] = ticket_dump_list
                        return data_dict
                except asyncio.TimeoutError:
                    retry += 1
                    if retry >= 15:
                        print(f"event_id {event_id} 请求超时，已重试2次，跳过")
                        return {}
                    else:
                        print(f"event_id {event_id} 请求超时，重试第{retry}次……")
                        await asyncio.sleep(1)
                except Exception as e:
                    print(f"event_id {event_id} 请求异常：{e}")
                    raise
                    return {}

    
    def events(self):
        return self.data["events"]
    
    def event(self, event_id=None, ticket_id=None, default=None):
        if ticket_id:
            event_id = self.ticketID_to_eventID(ticket_id)
        if event_id:
            return self.events().get(str(event_id), default)
        return default
                

    async def search_eventID_by_name_async(self, event_name):
        if self.updating:
            # 当数据正在更新时，等到数据全部更新完再继续
            await self._wait_for_data_update()
        data = self.events()
        result = []
        for eid, event in data.items():
            title = event["title"]
            if re.search(event_name, title, re.IGNORECASE):
                result.append([eid, title])
        return result
    
    async def search_event_by_id_async(self, event_id):
        event_url = f"https://clubz.cloudsation.com/event/getEventDetails.html?id={event_id}"
        
        timeout = aiohttp.ClientTimeout(
            total=20,
            connect=5,
            sock_connect=5,
            sock_read=15
        )
        
        connector = aiohttp.TCPConnector(
            limit=10,
            ttl_dns_cache=300,
            family=0
        )
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(event_url) as resp:
                json_data = await resp.text()
                json_data = json_data.encode().decode("utf-8-sig")  # 关键：去除BOM
                return json.loads(json_data)
        
    async def output_data_info(self):
        old_data = self.events()
        for eid, event in old_data.items():
            print(eid, event["title"], event["end_time"], event["update_time"])
        
    # ------------------------------------------ #


    def get_max_ticket_content_length(self, tickets, ticket_title_key='title'):
        max_len = 0
        for ticket in tickets:
            s = f"{ticket[ticket_title_key]} 余票{ticket['left_ticket_count']}/{ticket['total_ticket']}"
            max_len = max(max_len, get_display_width(s))
        return max_len

    # -------------------Query------------------------------ #         
    # ---------------------Announcement--------------------- #
    async def compare_to_database_async(self):
        old_data_all = copy.deepcopy(self.data)
        new_data_all = await self._update_events_data_async()
        try:
            return await self.__compare_to_database(old_data_all, new_data_all)
        except Exception as e:
            self.save_data_cache(old_data_all, new_data_all, "error_announcement_cache")
            raise  # 重新抛出异常，便于外层捕获和处理

    async def __compare_to_database(self, old_data_all, new_data_all):
        """
        比较新旧数据，返回分类后的票务变动信息，便于后续按需推送。
        返回结构：
        {
            "events": {
                event_id: [ticket_id,...]
                ...
            }
            "categorized": {
                "new": {
                    [{"event_id": "...", "ticket_id": [ticket_id], "message": }]
                    ...
                }
                "add": ..., 
                "pending": ..., 
                "return": ..., 
                "sold": ..., 
                "back": ...,
            }
            "prefix": {}
        }
        """
        save_cache = False
        new_data = new_data_all.get("events", {})
        old_data = old_data_all.get("events", {})
        
        # 检测新增的事件，用于虚拟事件迁移和演员订阅匹配
        new_event_ids = set(new_data.keys()) - set(old_data.keys())
        if new_event_ids:
            # 虚拟事件迁移
            await self.__migrate_virtual_events(new_event_ids, new_data)
            # 演员订阅自动匹配
            actor_match_counts = await self.match_actors_in_new_events_and_subscribe(new_event_ids)
            if actor_match_counts:
                from ncatbot.utils.logger import get_log
                log = get_log()
                log.info(f"新排期演员匹配完成，为 {len(actor_match_counts)} 个用户补充了票务订阅")
        
        comp_data = {}
        for eid in new_data.keys():
            comp = self.compare_tickets(old_data.get(eid, {}), new_data[eid].get("ticket_details", None))
            if not comp:
                continue
            comp_data[eid] = comp
            is_updated = True
            if any(k in ["new", "add", "pending"] for k in comp.keys()):
                save_cache = True
            # fix
        
        result = await self.__generate_compare_message_text(comp_data)
        if save_cache:
            self.save_data_cache(old_data_all, new_data_all, "update_data_cache")
        return result
    
    async def __migrate_virtual_events(self, new_event_ids, new_data):
        """
        检测新增事件是否匹配虚拟事件，如果匹配则自动迁移订阅
        """
        global Stats, User
        virtual_events = Stats.get_active_virtual_events()
        if not virtual_events:
            return
        
        from ncatbot.utils.logger import get_log
        log = get_log()
        
        for event_id in new_event_ids:
            event_info = new_data.get(event_id, {})
            event_title = event_info.get('title', '')
            if not event_title:
                continue
            
            # 标准化新事件标题
            normalized_title = extract_text_in_brackets(event_title, True).strip().lower()
            
            # 检查是否匹配任何虚拟事件
            for virtual_id, virtual_normalized in virtual_events.items():
                if normalized_title == virtual_normalized:
                    # 执行迁移
                    migrated_count = User.migrate_event_subscriptions(virtual_id, event_id)
                    Stats.deactivate_virtual_event(virtual_id)
                    log.info(f"虚拟事件迁移: {virtual_id} -> {event_id} ({event_title}), 迁移用户数: {migrated_count}")
                    break

    
    
    async def __generate_compare_message_text(self, compare_data):
        """
        生成比较数据后的文字消息，包含提醒信息。
        
        返回结构::
        {
            "events_prefixes": {
                event_id: "(
                f"剧名: {event_title}\n"
                f"购票链接: {url}\n"
                f"更新时间: {self.data['update_time']}\n"
                (f"⏲️开票时间：{valid_from}" if valid_from else "")
            ))"
            }
            "events": {
                event_id: [ticket_id,...]
                ...
            }
            "categorized": {
                "new": [ticket_id]
                "add": ..., 
                "pending": ..., 
                "return": ..., 
                "sold": ..., 
                "back": ...,    
            }
            "tickets": {
                ticket_id: 
                [{"categorized": "...", "event_id": event_id, "message": "..."}]
                }
            "prefix": {
                "new": "🆕上新",
                "add": "🟢补票",
                "return": "♻️回流",
                "sold": "➖票减",
                "back": "➕票增",
                "pending": "⏲️开票"
                }
        }
        """
        result = {
            "events_prefixes": {},
            "events": {},
            "categorized": {
                "new": [],
                "add": [],
                "return": [],
                "sold": [],
                "back": [],
                "pending": [],
                },
            "tickets": {},
            "prefix": {
                "new": "🆕上新",
                "add": "🟢补票",
                "return": "♻️回流",
                "sold": "➖票减",
                "back": "➕票增",
                "pending": "⏲️开票"
                }
        }
        for eid, comp in compare_data.items():
            if not comp:
                continue
            pending_message = {}
            valid_from = None
            event_title = self.title(event_id=eid, event_name_only=True, keep_brackets=False)
            result["events"][eid] = []
            for stat, tickets in comp.items(): # 一个id对应一部剧
                for ticket in tickets:
                    # 仅返回更新了的ticket detail
                    ticket_id = str(ticket.get("id", ""))
                    t = ("✨" if ticket['left_ticket_count'] > 0 else "❌") + f"{ticket['title']} 余票{ticket['left_ticket_count']}/{ticket['total_ticket']}" + " " + await self.get_cast_artists_str_async(event_title, ticket)
                    if stat == "pending":
                        valid_from = ticket.get("valid_from")
                        if not valid_from or valid_from == "null":
                            valid_from = "未知"
                        pending_message.setdefault(valid_from, [])
                        pending_message[valid_from].append(t)
                    elif stat == "active":
                        if stat == 'new':
                            if ticket["left_ticket_count"] == 0 and ticket['total_ticket'] == 0:
                                valid_from = ticket.get("valid_from")
                                if not valid_from or valid_from == "null":
                                    valid_from = "未知"
                                pending_message.setdefault(valid_from, [])
                                pending_message[valid_from].append(t)
                    result["tickets"][ticket_id] = {"message": t, "categorized": stat, "event_id": eid}
                    result["categorized"][stat].append(ticket_id)
                    result["events"][eid].append(ticket_id)
            self.pending_events_check_in(eid, pending_message, event_title) # 将即将开票的场次录入pending_dict
            url = f"https://clubz.cloudsation.com/event/{eid}.html"
            result["events_prefixes"][eid] = (
                f"剧名: {event_title}\n" +
                f"购票链接: {url}\n" +
                f"更新时间: {self.data['update_time']}\n" +
                (f"⏲️开票时间：{valid_from}" if valid_from else ""))
        return result

    def pending_events_check_in(self, eid, pending_message, title):
        if pending_message:
            cnt = 1
            for valid_from, m in pending_message.items():
                cnt += 1
                
                valid_date = standardize_datetime(valid_from, return_str=True) if valid_from != "NG" else "NG"
                if valid_date in self.data["pending_events"]:
                    if eid in self.data["pending_events"][valid_date]:
                        self.data["pending_events"][valid_date][eid] += '\n'.join(m)
                    else:
                        self.data["pending_events"][valid_date][eid] = (
                            f"剧名: {title}\n"
                                    f"购票链接: https://clubz.cloudsation.com/event/{eid}.html\n"
                                    f"更新时间: {self.data['update_time']}\n"
                                    f"开票时间: {valid_from}\n"
                                    f"场次信息：\n" + '\n'.join(m) + "\n"
                                    )
                else:
                    self.data["pending_events"][valid_date] = {
                        "valid_from": valid_date,
                        eid: (f"剧名: {title}\n"
                                    f"购票链接: https://clubz.cloudsation.com/event/{eid}.html\n"
                                    f"更新时间: {self.data['update_time']}\n"
                                    f"开票时间: {valid_from}\n"
                                    f"场次信息：\n" + '-'*10 + '\n'.join(m) + "\n"
                                    )
                                    
                    }

    def save_data_cache(self, old_data_all, new_data_all, cache_folder_name):
        cache_root = os.path.join(os.getcwd(), cache_folder_name)
        os.makedirs(cache_root, exist_ok=True)
                # 清理超过48小时的缓存
        now = datetime.now()
        for d in os.listdir(cache_root):
            dir_path = os.path.join(cache_root, d)
            if os.path.isdir(dir_path):
                try:
                            # 目录名格式为"2025-07-03_12-34-56"
                    dir_time = datetime.strptime(d, "%Y-%m-%d_%H-%M-%S")
                    if now - dir_time > timedelta(hours=48):
                        shutil.rmtree(dir_path)
                except Exception:
                    continue
                # 新建本次缓存
        update_time_str = str(self.data['update_time']).replace(":", "-").replace(" ", "_")
        cache_dir = os.path.join(cache_root, update_time_str)
        os.makedirs(cache_dir, exist_ok=True)
        with open(os.path.join(cache_dir, "old_data_all.json"), "w", encoding="utf-8") as f:
            json.dump(old_data_all, f, ensure_ascii=False, indent=2)
        with open(os.path.join(cache_dir, "new_data_all.json"), "w", encoding="utf-8") as f:
            json.dump(new_data_all, f, ensure_ascii=False, indent=2)


    def compare_tickets(self, old_data_all, new_data):
        """
        简介::
        比较旧票务数据和新票务数据，判断每个票务的更新状态。
        参数::
            old_data_all (dict 或 None): 之前的票务数据，预期包含 "ticket_details" 字典，映射票务ID到其详细信息。如果为 None 或为空，则所有新票务都视为新上架。
            new_data (dict 或 None): 当前的票务数据，映射票务ID到其详细信息。
        返回结构::
            dict: {'new': [ticket...], 'add', 'return', 'sold', 'back'}
        更新状态逻辑::
            - 'new': 票务为新上架，或之前不存在，或总票数从0变为正数。
            - 'add': 总票数增加。
            - 'return': 之前余票为0（售罄），现在有余票。
            - 'sold': 余票数量减少。
            - 'back': 余票数量增加（但不是从0变为正数）。
        注意事项::
            - 如果 old_data_all 缺失或为空，所有 new_data 条目都标记为 'new'。
            - 如果新旧数据都为空，返回 None。
            - 只处理标题和总票数非空的票务。
        """
        
        if (not old_data_all) and new_data:
            # 如果旧数据不存在，那么所有新数据都判定为新上架
            print("旧数据不存在，所有新数据都判定为新上架")
            for i in new_data:
                new_data[i]["update_status"] = 'new'
                
            return {'new': new_data.values()}
        elif not (old_data_all and new_data):
            # 如果旧数据新数据都为空 返回NONE
            return {}
        else:
            old_data_dict = old_data_all.get("ticket_details", {})
        if not old_data_dict:
            # 如果旧数据没有票务细节项，所有新数据判定为新上架
            print("旧数据无票务细节，所有新数据都判定为新上架")
            for i in new_data.values():
                i["update_status"] = 'new'
            return {'new': list(new_data.values())}
        
        # 以上情况都不存在，新旧数据都正常，则开始遍历
        
        update_data = []
        # 遍历 new_data 并根据条件进行更新
        for new_id in list(new_data.keys()):
            new_item = new_data[new_id]
            new_left_ticket_count = new_item['left_ticket_count']
            new_total_ticket = new_item['total_ticket']
            if not new_item['title'] and not new_total_ticket:
                continue
            if new_id not in list(old_data_dict.keys()):
                # 如果 new_data 中存在新的 ticket id，则标记为 新上架
                new_item['update_status'] = 'new'
                update_data.append(new_item)
            else:
                # 如果 没有新的ticket id
                old_item = old_data_dict[new_id]
                old_left_ticket_count = old_item['left_ticket_count']
                old_total_ticket = old_item['total_ticket']
                # 新增change逻辑：余票变化且总票数不变
                
                if (new_total_ticket > 0 and not old_total_ticket):
                    new_item['update_status'] = 'new'
                    print(2, new_total_ticket, old_total_ticket)
                    update_data.append(new_item)
                elif (new_total_ticket > (old_total_ticket or 0)):
                    # 如果 total_ticket 增加了，则标记为 "add"
                    new_item['update_status'] = 'add'
                    update_data.append(new_item)
                elif old_left_ticket_count is None or (new_left_ticket_count > old_left_ticket_count and old_left_ticket_count == 0):
                    # 如果 left_ticket_count 增加了，则标记为 "return"
                    new_item['update_status'] = 'return'
                    update_data.append(new_item)
                elif old_left_ticket_count > new_left_ticket_count:
                    new_item['update_status'] = 'sold'
                    update_data.append(new_item)
                elif old_left_ticket_count < new_left_ticket_count:
                    new_item['update_status'] = 'back'
                    update_data.append(new_item)
                else:
                    new_item['update_status'] = None
        update = {}
        for k in update_data:
            stat = k['update_status']
            update.setdefault(stat, [])
            update[stat].append(k)
        return update
    
    
    async def get_ticket_cast_and_city_async(self, eName, ticket, city=None):
        if not ticket['start_time']:
            return {"cast":[], "city":None}
        # 优先用别名系统检索名
        search_names = self.get_ordered_search_names(extract_text_in_brackets(eName, False), ticket['event_id'])
        for name in search_names:
            response = await Saoju.search_for_musical_by_date_async(name, ticket['start_time'], city=city)
            if response:
                Alias.set_no_response(eName, name, reset=True)
                cast = response.get("cast", [])
                ticket["cast"] = cast
                ticket['city'] = response.get('city', None)
                return {"cast": cast, "city": ticket.get('city', None)}
            else:
                Alias.set_no_response(eName, name, reset=False)
        return {"cast":[], "city":None}

    async def get_cast_artists_str_async(self, eName, ticket, city=None):
        cast = (await self.get_ticket_cast_and_city_async(eName, ticket, city))['cast']
        return " ".join([i["artist"] for i in cast])

    async def get_ticket_city_async(self, eName, ticket):
        return (await self.get_ticket_cast_and_city_async(eName, ticket))["city"]

    # /date
    async def on_message_search_event_by_date(self, date, _city=None, ignore_sold_out=False):
        try:
            date_obj = standardize_datetime(date, with_second=False, return_str=False)
        except ValueError:
            return "日期格式错误，请使用 YYYY-MM-DD 格式。\n例如：/date 2025-07-19"
        result_by_city = {}
        city_events_count = {}
        if self.updating:
            # 当数据正在更新时，等到数据全部更新完再继续
            await self._wait_for_data_update()
        for eid, event in self.events().items():
            try:
                event_start = standardize_datetime(event["start_time"], with_second=False, return_str=False)
                event_end = standardize_datetime(event["end_time"], with_second=False, return_str=False)
            except Exception:
                continue
            if not (event_start.date() <= date_obj.date() <= event_end.date()):
                continue
            for ticket in event.get("ticket_details", {}).values():
                if ignore_sold_out and ticket.get("left_ticket_count", 0)==0:
                    continue
                t_start = ticket.get("start_time")
                if not t_start:
                    continue
                try:
                    t_start = standardize_datetime(t_start, with_second=False, return_str=False)
                except Exception:
                    continue
                if t_start.date() != date_obj.date():
                    continue
                tInfo = extract_title_info(ticket.get("title", ""))
                event_title = tInfo['title'][1:-1]
                city = tInfo["city"]
                event_city = city if city else (await self.get_ticket_city_async(event_title, ticket) or "未知城市")  # 传入的是部分标题
                if _city:
                    if not event_city or _city not in event_city:
                        continue
                cast_str = await self.get_cast_artists_str_async(event_title, ticket, event_city) or "无卡司信息"
                time_key = t_start.strftime("%H:%M")
                if event_city not in result_by_city:
                    result_by_city[event_city] = {}
                    result_by_city[event_city][time_key] = []
                    city_events_count[event_city] = 1
                elif time_key not in result_by_city[event_city]:
                    result_by_city[event_city][time_key] = []
                city_events_count[event_city] += 1
                result_by_city[event_city][time_key].append({
                    "event_title": tInfo['title'] + " " + tInfo["price"] + (f"(原价：{tInfo['full_price']})" if tInfo["full_price"] else ""),
                    "ticket_title": ticket.get("title", ""),
                    "cast": cast_str,
                    "left": ticket.get("left_ticket_count", "-"),
                    "total": ticket.get("total_ticket", "-"),
                })
        if not result_by_city:
            return f"{date} {_city or ''} 当天无呼啦圈学生票场次信息。"
        message = f"{date} {_city or ''} 呼啦圈学生票场次：\n"
        sorted_keys = sorted(city_events_count, key=lambda x: city_events_count[x], reverse=True)
        if "未知城市" in sorted_keys:
            sorted_keys.remove("未知城市")
            sorted_keys.append("未知城市")
        for city_key in sorted_keys:
            message += f"城市：{city_key}\n"
            for t in sorted(result_by_city[city_key].keys()):
                message += f"⏲️时间：{t}\n"
                for item in result_by_city[city_key][t]:
                    message += ("✨" if item['left'] > 0 else "❌") + f"{item['event_title']} 余票{item['left']}/{item['total']}" + " " + item["cast"] + "\n"
        message += f"\n数据更新时间: {self.data['update_time']}\n"
        return message
    
    

    async def generate_tickets_query_message(self, eid, show_cast=True, ignore_sold_out=False, refresh=False, show_ticket_id=False):  
        if not refresh:
            event_data = self.events().get(str(eid), None)
        else:
            await self._update_ticket_details_async(eid)
            event_data = self.events().get(str(eid), None)
        if event_data:
            title = event_data.get("title", "未知剧名")
            tickets_details = event_data.get("ticket_details", {})
            remaining_tickets = []
            for ticket in tickets_details.values():
                if ticket["status"] == "active":
                    if ticket["left_ticket_count"] > (0 if ignore_sold_out else -1):
                        remaining_tickets.append(ticket)
                elif ticket["status"] == "pending":
                    remaining_tickets.append(ticket)
            url = f"https://clubz.cloudsation.com/event/{eid}.html"
            message = await self.build_ticket_query_info_message(
                title, url, event_data, remaining_tickets, show_cast=show_cast, show_ticket_id=show_ticket_id
            )
            return message
        else:
            return "未找到该剧目的详细信息。"
    
    
    async def build_ticket_query_info_message(self, title, url, event_data, remaining_tickets, show_cast=False, show_ticket_id=False):
        # 获取更新时间
        update_time = event_data.get('update_time', '未知')

        # 获取剩余票务信息
        ticket_info_message, no_saoju_data, pending_t = await self._generate_ticket_info_message(remaining_tickets, show_cast, extract_city(event_data.get("location", "")), show_ticket_id)
        pending = pending_t[0]
        valid_from = pending_t[1] if pending else ""
        # 拼接消息
        message = ""
        message += f"剧名: {title}\n"
        message += f"购票链接：{url}\n"
        message += f"最后更新时间：{update_time}\n"
        if pending:
            message += f"🕰️即将开票，开票时间：{valid_from}\n一切数据若有官方来源以官方为准，这个时间可能会因为主办方调整而改变。\n"
        message += "剩余票务信息:\n"
        message += ticket_info_message
        if no_saoju_data:
            message += "\n⚠️未在扫剧网站上找到此剧卡司"
        message += f"\n数据更新时间: {self.data['update_time']}\n"
        return message

    async def build_single_ticket_info_str(self, ticket, show_cast, city="上海", show_ticket_id=False):
        """
        根据ticket字典生成单条票务信息字符串。
        Args:
            ticket: 单个票务字典
            show_cast: 是否显示卡司
            event_data: 事件数据（用于查城市）
            show_ticket_id: 是否显示票id
        Returns:
            (str, bool, tuple): ✨ 32808《连壁》09-11 19:30￥199（原价￥299) 学生票 余票2/2 韩冰儿 胥子含, ,()
        """
        max_ticket_info_count = self.get_max_ticket_content_length([ticket])
        if ticket['status'] == 'active' and ticket['left_ticket_count'] > 0:
            ticket_status = "✨" 
        elif ticket["status"] == 'pending':
            v = ticket["valid_from"]
            v = v if v else "未知时间"
            ticket_status = f"🕰️"
        else:
            ticket_status = "❌"
        ticket_details = ljust_for_chinese(f"{ticket['title']} 余票{ticket['left_ticket_count']}/{ticket['total_ticket']}", max_ticket_info_count)
        if show_ticket_id:
            ticket_details = ' ' + ticket['id'] + ticket_details
        no_saoju_data = False
        if show_cast:
            cast_str = await self.get_cast_artists_str_async(ticket['title'], ticket, city=city)
            ticket_details += " " + cast_str
            if not cast_str:
                no_saoju_data = True
        text = ticket_status + ticket_details
        return text, no_saoju_data, (ticket["status"] == 'pending', ticket["valid_from"])

    async def _generate_ticket_info_message(self, remaining_tickets, show_cast, city, show_ticket_id):
        if not remaining_tickets:
            return "暂无余票。", True, (False, "")
        ticket_lines = []
        no_saoju_data = False
        pending_t = (False, "")
        for ticket in remaining_tickets:
            text, no_cast, pending_t = await self.build_single_ticket_info_str(ticket, show_cast, city, show_ticket_id)
            if no_cast:
                no_saoju_data = True
            ticket_lines.append(text)
        return ("\n".join(ticket_lines), no_saoju_data, pending_t)
    
    async def __update_ticket_dict_async(self):
        to_delete = []
        for ticket_id, event_id in self.data['ticket_id_to_event_id'].items():
            ticket = self.ticket(ticket_id, event_id)
            if not ticket:
                to_delete.append((event_id, ticket_id))
                continue
            if "end_time" not in ticket:
                continue
            end_time = standardize_datetime(ticket["end_time"], return_str=False)
            if datetime.now() > end_time:
                to_delete.append((event_id, ticket_id))
        for tup in to_delete:
            eid, tid = tup
            self.data['ticket_id_to_event_id'].pop(tid, None)
            self.delete_ticket(tid, eid)
            
    def update_ticket_dict_async(self):
        asyncio.create_task(self.__update_ticket_dict_async())
    
    def ticket(self, ticket_id, event_id=None, default=None):
        try:
            if not event_id:
                event_id = self.ticketID_to_eventID(ticket_id, raise_error=False)
                if not event_id:
                    return default
            if event_id not in self.events() or ticket_id not in self.ticket_details(event_id):
                return default
            return self.ticket_details(event_id)[ticket_id]
        except (KeyError, Exception):
            return default
    
    def delete_ticket(self, ticket_id, event_id=None):
        try:
            if not event_id:
                event_id = self.ticketID_to_eventID(ticket_id, raise_error=False)
                if not event_id:
                    return None
            if event_id not in self.events():
                return None
            return self.data['events'][event_id]["ticket_details"].pop(ticket_id, None)
        except (KeyError, Exception):
            return None
    
    def ticket_details(self, event_id):
        """根据eventid获取票务数据
        Args:
            event_id (str): 
        Returns:
            {
  ticket_id: {
  "id": 31777,
  "event_id": 3863,
  "title": "《海雾》07-19 20:00￥199（原价￥299) 学生票",
  "start_time": "2025-07-19 20:00:00",
  "end_time": "2025-07-19 21:00:00",
  "status": "active", /expired, /pending
  "create_time": "2025-06-11 11:06:13",
  "ticket_price": 199,
  "max_ticket": 1,
  "total_ticket": 14,
  "left_ticket_count": 0,
  "left_days": 25,
}}
        """        
        return self.data['events'][event_id]["ticket_details"]
    
    def ticketID_to_eventID(self, ticket_id, default=0, raise_error=True):
        if ticket_id not in self.data["ticket_id_to_event_id"]:
            for e in self.events():
                for t in self.ticket_details(e).keys():
                    if t == ticket_id:
                        return e
        else:
            return self.data["ticket_id_to_event_id"][ticket_id]
        if raise_error:
            raise KeyError
        return default
    
    def title(self, ticket_id=None, event_id=None, event_name_only=True, keep_brackets=False):
        if event_id:
            event = self.event(event_id, default={})
            title = event.get('title', None)
            if title:
                if event_name_only:
                    return extract_text_in_brackets(title, keep_brackets)
                else:
                    return title
        if ticket_id:
            if event_name_only:
                ticket_title = self.ticket(ticket_id=ticket_id, default={}).get('title', None)
                return extract_text_in_brackets(ticket_title, keep_brackets)
            else:
                event = self.event(ticket_id=ticket_id, default={})
                title = event.get('title', None)
                return title
                
    
    def verify_ticket_id(self, ticket_id):
        if isinstance(ticket_id, str):
            ticket_id = [ticket_id]
        denial = []
        yes: list = ticket_id
        for tid in ticket_id:
            if not self.ticketID_to_eventID(tid, raise_error=False):
                denial.append(tid)
                yes.pop(tid, None)
        return yes, denial
            
            
    async def on_message_tickets_query(self, eName, ignore_sold_out=False, show_cast=True, refresh=False, show_ticket_id=False, extra_id=None):
        if self.updating:
            await self._wait_for_data_update()
        eid, msg = await self.get_event_id_by_name(eName, extra_id=extra_id)
        if eid is None:
            return msg or "未找到该剧目。"
        return await self.generate_tickets_query_message(eid, show_cast=show_cast, ignore_sold_out=ignore_sold_out, refresh=refresh, show_ticket_id=show_ticket_id)

    async def get_event_id_by_name(self, eName, default="未找到该剧目", extra_id=None):
        """
        统一处理event_name转event_id逻辑。
        返回 (event_id, None) 或 (None, 错误消息)
        """
        queue = ""
        eName = eName.strip().lower()
        search_names = self.get_ordered_search_names(title=eName)
        for search_name in search_names:
            result = await self.search_eventID_by_name_async(search_name)
            if len(result) == 1:
                eid = result[0][0]
                Alias.set_no_response(eName, search_name, reset=True)
                return eid, None
            elif len(result) > 1:
                if extra_id:
                    if extra_id <= len(result):
                        return result[extra_id-1][0], None
                queue = [f"{i}. {event[1]}" for i, event in enumerate(result, start=1)]
            Alias.set_no_response(eName, search_name, reset=False)
        return None, f"找到多个匹配的剧名，请重新以唯一的关键词查询，或使用\n/hlq {eName} -下面的序号\n查询对应的剧：\n" + "\n".join(queue) if queue else default


    async def get_hlq_co_cast_event(self, co_casts, show_others=True):
        casts_data = await Saoju.request_co_casts_data(co_casts, show_others=show_others)
        message_id_list = []
        for event in casts_data:
            title = extract_text_in_brackets(event['title'], False)
            # 优先用别名系统查event_id
            event_id = await self.get_event_id_by_name(title)[0]
            if event_id:
                event['event_id'] = event_id
                message_id_list.append(event)
        if self.updating:
            # 当数据正在更新时，等到数据全部更新完再继续
            await self._wait_for_data_update()
        tickets = []
        for event in message_id_list:
            # 获取对应的票务数据和卡司数据
            event_id = event['event_id']
            for ticket_id, ticket in self.ticket_details(event_id).items():
                if standardize_datetime_for_saoju(event["date"]) == ticket['start_time']:
                    tickets.append(ticket)
                    break
    
    
    def get_ordered_search_names(self, title=None, event_id=None):
        """
        根据event_id或title，结合别名系统，返回排序有意义的检索名（search_name）列表。
        优先级：
        1. 若event_id存在且在别名系统中，返回别名系统中该event_id的所有search_name（按添加顺序）。
        2. 若title存在且为别名（alias），查找其event_id并返回对应search_name列表。
        3. 若title本身为search_name，直接返回[title]。
        4. 否则返回空列表。
        """
        # 优先用event_id
        if event_id:
            event_id = str(event_id)
            search_names = Alias.data.get("event_to_names", {}).get(event_id)
            if search_names:
                return list(search_names)
        # 其次用title查alias
        if title:
            t = title.strip()
            # 1. 作为alias查event_id
            eid = Alias.get_event_id_by_alias(t)
            if eid:
                search_names = Alias.data.get("event_to_names", {}).get(eid)
                if search_names:
                    return list(search_names)
            # 2. 作为search_name查event_id
            eid2 = Alias.get_event_id_by_name(t)
            if eid2:
                search_names = Alias.data.get("event_to_names", {}).get(eid2)
                if search_names:
                    return list(search_names)
            # 3. title本身为search_name
            return [t]
        return []
    
    async def find_tickets_by_actor_async(self, actor_name: str, include_eids=None, exclude_eids=None):
        """
        在当前缓存的所有事件中检索包含指定演员的场次
        
        参数:
            actor_name: 演员名（大小写不敏感）
            include_eids: 白名单，仅搜索这些事件ID（优先级更高）
            exclude_eids: 黑名单，排除这些事件ID
        
        返回:
            {ticket_id: event_id} 字典
        """
        actor_lower = actor_name.strip().lower()
        matched_tickets = {}
        
        # 确定需要搜索的事件范围
        events_to_search = self.data.get("events", {})
        if include_eids:
            include_eids_str = [str(e) for e in include_eids]
            events_to_search = {eid: event for eid, event in events_to_search.items() if eid in include_eids_str}
        elif exclude_eids:
            exclude_eids_str = [str(e) for e in exclude_eids]
            events_to_search = {eid: event for eid, event in events_to_search.items() if eid not in exclude_eids_str}
        
        # 遍历所有事件的所有场次
        for event_id, event_data in events_to_search.items():
            event_title = event_data.get('title', '')
            tickets = event_data.get('ticket_details', {})
            
            for ticket_id, ticket_info in tickets.items():
                # 获取该场次的卡司信息
                cast_data = await self.get_ticket_cast_and_city_async(event_title, ticket_info)
                cast_list = cast_data.get('cast', [])
                
                # 检查演员是否在卡司中
                for cast_member in cast_list:
                    if cast_member.get('artist', '').strip().lower() == actor_lower:
                        matched_tickets[str(ticket_id)] = str(event_id)
                        break
        
        return matched_tickets
    
    async def match_actors_in_new_events_and_subscribe(self, new_event_ids):
        """
        在新上架的事件中快速匹配所有用户订阅的演员，并自动为用户补充票务订阅
        
        参数:
            new_event_ids: 新增的事件ID集合
        
        返回:
            {user_id: added_ticket_count} 每个用户新增的票务订阅数量
        """
        global User
        
        # 收集所有用户的演员订阅
        all_users_actors = {}  # {user_id: [{actor, mode, include_events, exclude_events}]}
        for user_id in User.data.get("users_list", []):
            actors = User.subscribe_actors(user_id)
            if actors:
                all_users_actors[user_id] = actors
        
        if not all_users_actors:
            return {}
        
        # 为每个新事件检索卡司并匹配
        user_new_tickets = {}  # {user_id: [(ticket_id, mode, actor_name)]}
        
        for event_id in new_event_ids:
            event_data = self.data.get("events", {}).get(event_id)
            if not event_data:
                continue
            
            event_title = event_data.get('title', '')
            tickets = event_data.get('ticket_details', {})
            
            # 为该事件的每个场次获取卡司
            for ticket_id, ticket_info in tickets.items():
                cast_data = await self.get_ticket_cast_and_city_async(event_title, ticket_info)
                cast_list = cast_data.get('cast', [])
                cast_actors_lower = [c.get('artist', '').strip().lower() for c in cast_list]
                
                # 匹配所有用户的演员订阅
                for user_id, actors in all_users_actors.items():
                    for actor_sub in actors:
                        actor_name = actor_sub.get('actor', '').strip()
                        actor_name_lower = actor_name.lower()
                        mode = actor_sub.get('mode', 1)
                        include_events = actor_sub.get('include_events', [])
                        exclude_events = actor_sub.get('exclude_events', [])
                        
                        # 检查剧目筛选
                        if include_events and event_id not in [str(e) for e in include_events]:
                            continue
                        if exclude_events and event_id in [str(e) for e in exclude_events]:
                            continue
                        
                        # 检查演员是否在卡司中
                        if actor_name_lower in cast_actors_lower:
                            user_new_tickets.setdefault(user_id, [])
                            # 同时记录场次ID、模式和演员名
                            user_new_tickets[user_id].append((str(ticket_id), mode, actor_name))
                            break  # 一个场次只为该用户添加一次
        
        # 为用户批量添加票务订阅
        user_counts = {}
        for user_id, tickets in user_new_tickets.items():
            # 按 (模式, 演员) 分组
            mode_actor_tickets = {}  # {(mode, actor): [ticket_ids]}
            for tid, mode, actor in tickets:
                key = (mode, actor)
                mode_actor_tickets.setdefault(key, []).append(tid)
            
            for (mode, actor), ticket_ids in mode_actor_tickets.items():
                # 带演员关联添加场次订阅
                User.add_ticket_subscribe(user_id, ticket_ids, mode, related_to_actors=[actor])
            
            user_counts[user_id] = len(tickets)
        
        return user_counts

