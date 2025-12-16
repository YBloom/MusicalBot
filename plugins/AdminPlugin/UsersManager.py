from datetime import datetime
from plugins.AdminPlugin.BaseDataManager import BaseDataManager
from ncatbot.plugin import BasePlugin
from ncatbot.utils.logger import get_log
from copy import deepcopy
log = get_log()

def USER_MODEL():
        model = {
        "activate": True,
        "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "attention_to_hulaquan": 0,
        "chats_count":0,
        # 订阅权限
        "subscribe": {
            "is_subscribe": False,
            "subscribe_time": None,
            "subscribe_tickets": [],
            "subscribe_events": [],
            "subscribe_actors": [],  # [{actor: str, mode: int}]
            }
        }
        return model


class UsersManager(BaseDataManager):

    
    
    admin_id = "3022402752"

    def __init__(self, file_path=None):
        super().__init__(file_path=file_path)


    def on_load(self, data=None):
        first_init = False
        if data:
            first_init = True
            self.data["users"] = data["users"]
            self.data["users_list"] = data["users_list"]
            self.data["ops_list"] = data["ops_list"]
            self.data["groups"] = data["groups"]
            self.data["groups_list"] = data["groups_list"]
            print(len(self.data["users_list"]))
            return super().on_load()
        if "users" not in self.data:
            self.data["users"] = data["users"] if first_init else {}
        if "users_list" not in self.data:
            self.data["users_list"] = data["users_list"] if first_init else []
        if "ops_list" not in self.data:
            self.data["ops_list"] = data["ops_list"] if first_init else []
        if "groups" not in self.data:
            self.data["groups"] = data["groups"] if first_init else {}
        if "groups_list" not in self.data:
            self.data["groups_list"] = data["groups_list"] if first_init else []
        self.data.setdefault("todays_likes", [])
        return super().on_load()
    
    
        
    def users(self):
        return deepcopy(self.data.get("users", {}))
        
    def users_list(self):
        return deepcopy(self.data.get("users_list", []))
    
    def ops_list(self):
        return self.data.get("ops_list", [])
    
    def groups(self):
        return deepcopy(self.data.get("groups", {}))
        
    def groups_list(self):
        return deepcopy(self.data.get("groups_list", []))
        
    def add_group(self, group_id):
        if not isinstance(group_id, str):
            group_id = str(group_id)
        if group_id in self.data["groups_list"]:
            return
        self.data["groups_list"].append(group_id)
        self.data["groups"][group_id] = {
            "activate": True,
            "create_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "attention_to_hulaquan": 0,
        }
    
    def delete_group(self, group_id):
        if not isinstance(group_id, str):
            group_id = str(group_id)
        if group_id in self.data["groups_list"]:
            self.data["groups_list"].remove(group_id)
            del self.data["groups"][group_id]
        
    def add_user(self, user_id):
        if not isinstance(user_id, str):
            user_id = str(user_id)
        if user_id in self.data["users_list"]:
            return
        self.data["users_list"].append(user_id)
        self.data["users"][user_id] = USER_MODEL()
        return self.data["users"][user_id]
        
    def update_user_keys(self, user_id):
        user_id = str(user_id)
        user = self.data["users"].get(user_id, None)
        if user is None:
            return self.add_user(user_id)
        
        def goto(origin, model):
            for k, v in model.items():
                if k not in origin:
                    origin[k] = v
                elif isinstance(v, dict):
                    goto(origin[k], v)
            
        goto(user, USER_MODEL())
    
    def attention_to_hulaquan(self, user_id, default=0):
        """
        需确定user存在
        return int
        """
        return self.data['users'].get(user_id, {}).get("attention_to_hulaquan", default)
               
        
    def add_chats_count(self, user_id):
        if not isinstance(user_id, str):
            user_id = str(user_id)
        if "chats_count" not in self.data['users'][user_id]:
            self.data["users"][user_id]["chats_count"] = 0
        self.data["users"][user_id]["chats_count"] += 1
        return self.data["users"][user_id]
    
    def delete_user(self, user_id):
        if not isinstance(user_id, str):
            user_id = str(user_id)
        if user_id in self.data["users_list"]:
            self.data["users_list"].remove(user_id)
            del self.data["users"][user_id]
            
    def add_op(self, user_id):
        if not isinstance(user_id, str):
            user_id = str(user_id)
        if user_id in self.data["ops_list"]:
            
            return False
        if user_id not in self.data["users_list"]:
            self.add_user(user_id)
        self.data["ops_list"].append(user_id)
        self.data["users"][user_id]["is_op"] = True
        return True
        
    def de_op(self, user_id):
        if not isinstance(user_id, str):
            user_id = str(user_id)
        if user_id in self.data["ops_list"]:
            self.data["ops_list"].remove(user_id)
            self.data["users"][user_id]["is_op"] = False
            return True
        return False
            
    def is_op(self, user_id):
        if not isinstance(user_id, str):
            user_id = str(user_id)
        if user_id in self.data["ops_list"]:
            return True
        return False
    
    def remove_ticket_subscribe(self, user_id, ticket_id):
        user_id = str(user_id)
        ticket_id = str(ticket_id)
        tickets = self.data["users"][user_id]["subscribe"].setdefault("subscribe_tickets", [])
        before = len(tickets)
        self.data["users"][user_id]["subscribe"]["subscribe_tickets"] = [t for t in tickets if str(t['id']) != ticket_id]
        return before != len(self.data["users"][user_id]["subscribe"]["subscribe_tickets"])

    def remove_event_subscribe(self, user_id, event_id):
        user_id = str(user_id)
        event_id = str(event_id)
        events = self.data["users"][user_id]["subscribe"].setdefault("subscribe_events", [])
        before = len(events)
        self.data["users"][user_id]["subscribe"]["subscribe_events"] = [e for e in events if str(e['id']) != event_id]
        return before != len(self.data["users"][user_id]["subscribe"]["subscribe_events"])
    
    def switch_attention_to_hulaquan(self, user_id, mode=0, is_group=False):
        # mode = 0: 取消推送，mode = 1: 关注更新，mode = 2：关注一切推送（更新或无更新）
        if not isinstance(user_id, str):
            user_id = str(user_id)
        key = "users" if not is_group else "groups"
        try:
            self.data[key][user_id]["attention_to_hulaquan"] = mode
        except KeyError:
            if key == "users":
                self.add_user(user_id)
            else:
                self.add_group(user_id)
            self.data[key][user_id]["attention_to_hulaquan"] = mode
        return mode
    
    def new_subscribe(self, user_id, is_subscribe=False):
        if not isinstance(user_id, str):
            user_id = str(user_id)
        if user_id not in self.data["users_list"]:
            self.add_user(user_id)
        self.data["users"][user_id]["subscribe"]["is_subscribe"] = True if self.data["users"][user_id]["subscribe"]["is_subscribe"] else is_subscribe
        self.data["users"][user_id]["subscribe"].setdefault("subscribe_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.data["users"][user_id]["subscribe"].setdefault("subscribe_tickets", [])
        self.data["users"][user_id]["subscribe"].setdefault("subscribe_events", [])
        self.data["users"][user_id]["subscribe"].setdefault("subscribe_actors", [])  # 确保演员订阅字段存在
        return self.data["users"][user_id]["subscribe"]
   
    def add_ticket_subscribe(self, user_id, ticket_ids, mode, related_to_actors=None):
        """
        为用户添加场次订阅
        
        Args:
            user_id: 用户ID
            ticket_ids: 场次ID或场次ID列表
            mode: 订阅模式 (1/2/3)
            related_to_actors: 关联的演员名列表（因关注演员而关注的场次）
                             - None: 非演员关联的场次订阅
                             - []: 空列表（暂时不应该出现，会被转换为None）
                             - ['actor1', 'actor2']: 因关注这些演员而订阅的场次
        """
        user_id = str(user_id)
        self.data["users"][user_id]["subscribe"].setdefault("subscribe_tickets", [])
        if user_id not in self.users_list():
            self.add_user(user_id)
        if isinstance(ticket_ids, int) or isinstance(ticket_ids, str):
            ticket_ids = [ticket_ids]
        
        # 标准化 related_to_actors
        if related_to_actors is not None:
            if isinstance(related_to_actors, str):
                related_to_actors = [related_to_actors]
            # 空列表转为 None
            if not related_to_actors:
                related_to_actors = None
        
        for i in ticket_ids:
            ticket_entry = {
                'id': str(i),
                'mode': mode
            }
            # 只有非None时才添加字段
            if related_to_actors is not None:
                ticket_entry['related_to_actors'] = related_to_actors
            
            self.data["users"][user_id]["subscribe"]["subscribe_tickets"].append(ticket_entry)
        return True
    
    def add_event_subscribe(self, user_id, event_ids, mode):
        user_id = str(user_id)
        self.data["users"][user_id]["subscribe"].setdefault("subscribe_events", [])
        if user_id not in self.users_list():
            self.add_user(user_id)
        if isinstance(event_ids, int) or isinstance(event_ids, str):
            event_ids = [event_ids]
        for i in event_ids:
            self.data["users"][user_id]["subscribe"]["subscribe_events"].append(
                {
                'id': str(i),
                'mode': mode,
                })
        return True
    
    def subscribe_tickets(self, user_id):
        self.new_subscribe(user_id)
        return self.data["users"][user_id]["subscribe"]["subscribe_tickets"]
    
    def subscribe_events(self, user_id):
        self.new_subscribe(user_id)
        return self.data["users"][user_id]["subscribe"]["subscribe_events"]
    
    def is_ticket_subscribed(self, user_id, ticket_id):
        return str(ticket_id) in self.subscribe_tickets(user_id)
    
    def is_event_subscribed(self, user_id, event_id):
        return str(event_id) in self.subscribe_events(user_id)
    
    async def post_private_msg(self, bot: BasePlugin, user_id, text, condition=True):
        if not condition:
            return False
        else:
            return await bot.api.post_private_msg(user_id, text)
   
    async def send_likes(self, bot: BasePlugin):
        """给当日好友批量点赞（每日仅一次，持久化去重，避免自赞）。"""
        date = datetime.now().strftime("%Y-%m-%d")
        # 已执行则跳过（依赖持久化，防止多次重启重复发送）
        if date in self.data.get("todays_likes", []):
            return False

        # 使用实时好友列表，避免包含自身或非好友账号
        try:
            result = await bot.api.get_friend_list(False)
            friend_ids = [str(i.get("user_id")) for i in result.get("data", []) if "user_id" in i]
        except Exception as e:
            log.error(f"获取好友列表失败，取消当日点赞：{e}")
            return False

        # 先标记当日执行并持久化，避免中途重启造成重复执行
        if "todays_likes" not in self.data:
            self.data["todays_likes"] = []
        self.data["todays_likes"].append(date)
        try:
            await self.save()
        except Exception as e:
            log.error(f"保存点赞状态失败（将继续执行点赞）：{e}")

        # 逐个尝试点赞；对上限/自赞等业务错误静默跳过
        for uid in friend_ids:
            try:
                r = await bot.api.send_like(uid, 10)
                # 如果返回结构中包含业务失败，也仅记录
                if isinstance(r, dict) and r.get("status") == "failed":
                    log.warning(f"点赞 {uid} 失败：{r.get('message') or r}")
            except Exception as e:
                log.warning(f"点赞 {uid} 异常，已跳过：{e}")
                continue
        return True
    
    async def check_friend_status(self, bot: BasePlugin):
        result = await bot.api.get_friend_list(False)
        
        friends = [str(i["user_id"]) for i in result["data"]]
        for user_id in self.users_list():
            if user_id not in friends:
                r = await bot.api.post_private_msg(user_id, text="老师请添加bot为好友，防止消息被误吞~")
                if r['retcode'] == 1200 and not r['data']:
                        self.delete_user(user_id)
            else:
                self.add_user(user_id)
    
    async def update_friends_list(self, bot: BasePlugin):
        await self.check_friend_status(bot)
        for user_id in self.users_list():
            self.update_user_keys(str(user_id))
        return await self.send_likes(bot)


    def update_ticket_subscribe_mode(self, user_id, ticket_id, new_mode):
        """
        更新已关注场次的关注模式
        """
        user_id = str(user_id)
        ticket_id = str(ticket_id)
        tickets = self.data["users"][user_id]["subscribe"].setdefault("subscribe_tickets", [])
        for t in tickets:
            if str(t['id']) == ticket_id:
                t['mode'] = new_mode
                break

    def update_event_subscribe_mode(self, user_id, event_id, new_mode):
        """
        更新已关注剧目的关注模式
        """
        user_id = str(user_id)
        event_id = str(event_id)
        events = self.data["users"][user_id]["subscribe"].setdefault("subscribe_events", [])
        for e in events:
            if str(e['id']) == event_id:
                e['mode'] = new_mode
                break
    
    def migrate_event_subscriptions(self, from_event_id: str, to_event_id: str):
        """
        将所有用户从旧事件ID的订阅迁移到新事件ID
        用于虚拟事件到真实事件的自动迁移
        返回: 迁移的用户数量
        """
        from_event_id = str(from_event_id)
        to_event_id = str(to_event_id)
        migrated_count = 0
        
        for user_id in self.data.get("users_list", []):
            events = self.data["users"][user_id]["subscribe"].get("subscribe_events", [])
            for e in events:
                if str(e['id']) == from_event_id:
                    e['id'] = to_event_id
                    migrated_count += 1
                    break
        
        return migrated_count
    
    def add_actor_subscribe(self, user_id, actor_names, mode, include_events=None, exclude_events=None):
        """
        为用户添加演员订阅
        actor_names: 演员名列表或单个演员名
        mode: 订阅模式 (1/2/3)
        include_events: 白名单，仅关注这些剧目的该演员（event_id列表）
        exclude_events: 黑名单，不关注这些剧目的该演员（event_id列表）
        """
        user_id = str(user_id)
        self.new_subscribe(user_id)
        if isinstance(actor_names, str):
            actor_names = [actor_names]
        
        actors = self.data["users"][user_id]["subscribe"]["subscribe_actors"]
        for actor in actor_names:
            actor_entry = {
                'actor': actor, 
                'mode': mode,
            }
            if include_events:
                actor_entry['include_events'] = [str(e) for e in include_events]
            if exclude_events:
                actor_entry['exclude_events'] = [str(e) for e in exclude_events]
            actors.append(actor_entry)
        return True
    
    def remove_actor_subscribe(self, user_id, actor_name):
        """
        移除演员订阅，并清理仅因该演员而关注的场次
        
        Args:
            user_id: 用户ID
            actor_name: 演员名
            
        Returns:
            dict: {
                'actor_removed': bool,  # 是否成功移除演员订阅
                'tickets_removed': int  # 移除的场次数量
            }
        """
        user_id = str(user_id)
        actor_name_lower = str(actor_name).strip().lower()
        
        # 1. 移除演员订阅
        actors = self.data["users"][user_id]["subscribe"].get("subscribe_actors", [])
        before = len(actors)
        self.data["users"][user_id]["subscribe"]["subscribe_actors"] = [
            a for a in actors if a.get('actor', '').strip().lower() != actor_name_lower
        ]
        actor_removed = before != len(self.data["users"][user_id]["subscribe"]["subscribe_actors"])
        
        # 2. 清理关联场次
        tickets = self.data["users"][user_id]["subscribe"].get("subscribe_tickets", [])
        tickets_to_keep = []
        tickets_removed_count = 0
        
        for ticket in tickets:
            related_actors = ticket.get('related_to_actors')
            
            # 如果没有关联演员（None），保留场次
            if related_actors is None:
                tickets_to_keep.append(ticket)
                continue
            
            # 如果有关联演员列表，移除当前演员
            if isinstance(related_actors, list):
                # 过滤掉当前演员（不区分大小写）
                updated_actors = [
                    a for a in related_actors 
                    if str(a).strip().lower() != actor_name_lower
                ]
                
                # 如果还有其他演员，更新列表并保留场次
                if updated_actors:
                    ticket['related_to_actors'] = updated_actors
                    tickets_to_keep.append(ticket)
                else:
                    # 列表为空，移除该场次
                    tickets_removed_count += 1
            else:
                # 数据异常，保留场次
                tickets_to_keep.append(ticket)
        
        self.data["users"][user_id]["subscribe"]["subscribe_tickets"] = tickets_to_keep
        
        return {
            'actor_removed': actor_removed,
            'tickets_removed': tickets_removed_count
        }
    
    def subscribe_actors(self, user_id):
        """
        获取用户订阅的演员列表
        返回: [{actor: str, mode: int}, ...]
        """
        self.new_subscribe(user_id)
        return self.data["users"][user_id]["subscribe"]["subscribe_actors"]
    
    def add_actor_to_ticket_relation(self, user_id, ticket_id, actor_name):
        """
        为已存在的场次订阅添加演员关联
        
        Args:
            user_id: 用户ID
            ticket_id: 场次ID
            actor_name: 演员名
            
        Returns:
            bool: 是否成功添加关联
        """
        user_id = str(user_id)
        ticket_id = str(ticket_id)
        actor_name = str(actor_name).strip()
        
        tickets = self.data["users"][user_id]["subscribe"].get("subscribe_tickets", [])
        
        for ticket in tickets:
            if str(ticket.get('id')) == ticket_id:
                related_actors = ticket.get('related_to_actors')
                
                # 如果是None，创建新列表
                if related_actors is None:
                    ticket['related_to_actors'] = [actor_name]
                # 如果是列表，添加演员（避免重复）
                elif isinstance(related_actors, list):
                    actor_lower = actor_name.lower()
                    if not any(a.strip().lower() == actor_lower for a in related_actors):
                        related_actors.append(actor_name)
                
                return True
        
        return False
    
    def update_actor_subscribe_mode(self, user_id, actor_name, new_mode):
        """
        更新演员订阅模式
        """
        user_id = str(user_id)
        actor_name = str(actor_name).strip().lower()
        actors = self.data["users"][user_id]["subscribe"].get("subscribe_actors", [])
        for a in actors:
            if a.get('actor', '').strip().lower() == actor_name:
                a['mode'] = new_mode
                break

