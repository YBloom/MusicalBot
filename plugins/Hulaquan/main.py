"""Hulaquan plugin entry-point.

`Hulaquan` now retrieves its persistent state from
``services.compat.CompatContext``.  Production environments keep using the
legacy JSON ``DataManager`` singletons via :func:`get_default_context`, while
tests (and future service-backed deployments) can pass a custom context through
the plugin constructor.  The module-level ``User``, ``Alias`` … references are
updated through :func:`plugins.Hulaquan.data_managers.use_compat_context` so
command handlers keep receiving the same objects regardless of how the context
is provided.
"""

from datetime import timedelta
import traceback, time, asyncio, re
import functools

from ncatbot.plugin import BasePlugin, CompatibleEnrollment, Event
from ncatbot.core import GroupMessage, PrivateMessage, BaseMessage
from ncatbot.utils.logger import get_log

from services.compat import CompatContext

from .Exceptions import RequestTimeoutException
from plugins.Hulaquan.data_managers import (
    Saoju,
    Stats,
    Alias,
    Hlq,
    User,
    save_all,
    use_compat_context,
)
from plugins.Hulaquan.StatsDataManager import maxLatestReposCount
from .user_func_help import *
from .utils import parse_text_to_dict_with_mandatory_check, standardize_datetime, dateTimeToStr

bot = CompatibleEnrollment  # 兼容回调函数注册器

log = get_log()


def _install_context(context: CompatContext | None) -> CompatContext:
    return use_compat_context(context)



UPDATE_LOG = [
        {"version": "0.0.1", 
         "description": "初始公测版本", 
         "date":"2025-06-28"},
        
        {"version": "0.0.2", 
         "description": "1.修改了回流票的检测逻辑（之前可能是误检测）\n2.增加了对呼啦圈学生票待开票状态的检测\n3.添加了呼啦圈未开票的票的开票定时提醒功能（提前30分钟）\n4.增加了更新日志和版本显示",
         "date": "2025-07-01"
        },
        
        {"version": "0.0.3", 
         "description": """1.修改了一些缓存功能\n2.修复了一些bug\n3.添加了/hlq xx -R获取当下数据的功能
         """,
         "date": "2025-07-03"
        },
        {"version": "0.0.4", 
         "description": """1./date功能实现
         """,
         "date": "2025-07-05"
        },
        {"version": "0.0.5⭐", 
         "description": """
         1.学生票repo功能
         2.区别于呼啦圈系统中存在的剧，为不存在的那些剧也声明了eventid
         """,
         "date": "2025-07-10"
        },
    ]

def get_update_log(update_log=UPDATE_LOG):
    
    # 逆序列表
    update_log.reverse()
    
    log_text = ""
    for entry in update_log:
        version = entry.get("version")
        description = entry.get("description")
        date = entry.get("date")
        log_text += f"V {version} 更新内容：\n{description}\n更新时间：{date}\n\n"
    
    return log_text.strip()


def user_command_wrapper(command_name):
        def decorator(func):
            @functools.wraps(func)
            async def wrapper(this, *args, **kwargs):
                Stats.on_command(command_name)
                try:
                    return await func(this, *args, **kwargs)
                except Exception as e:
                    # 避免循环报错：先记录日志，再尝试通知
                    log.error(f"{command_name} 命令异常: {e}")
                    import traceback
                    log.error(traceback.format_exc())
                    
                    # 使用安全的错误通知(带死循环防护)
                    try:
                        from services.system.error_protection import safe_send_error_notification
                        await safe_send_error_notification(
                            api=this.api,
                            admin_id=str(User.admin_id),
                            error=e,
                            context=f"{command_name} 命令",
                            include_traceback=True
                        )
                    except Exception as notify_error:
                        # 如果通知失败，只记录日志，不再继续
                        log.error(f"安全错误通知失败: {notify_error}")
            return wrapper
        return decorator


class Hulaquan(BasePlugin):

    name = "Hulaquan"  # 插件名称
    version = "0.0.5"  # 插件版本
    author = "摇摇杯"  # 插件作者
    info = "与呼啦圈学生票相关的功能"  # 插件描述
    dependencies = {
        }  # 插件依赖，格式: {"插件名": "版本要求"}

    def __init__(self, *args, compat_context: CompatContext | None = None, **kwargs):
        self.compat_context = _install_context(compat_context)
        super().__init__(*args, **kwargs)
    
    # Notion 配置
    # 方案 1：直接设置帮助文档的公开链接（推荐）
    NOTION_HELP_URL = "https://www.notion.so/286de516043f80c3a177ce09dda22d96"  # 帮助文档页面
    
    # 方案 2：使用 API 动态创建（需要配置父页面 ID）
    NOTION_PARENT_PAGE_ID = None  # 设置为您的 Notion 父页面 ID
    _notion_help_page_id = "286de516-043f-80c3-a177-ce09dda22d96"  # 当前帮助文档页面 ID
    
    # Notion API Token（用于自动同步）
    # ⚠️ 重要：请在环境变量中配置
    # 配置方法：
    #   Linux/Mac:  export NOTION_TOKEN=ntn_your_integration_token
    #   Windows:    $env:NOTION_TOKEN="ntn_your_integration_token"
    _notion_token = ""
    
    async def on_load(self):
        # 插件加载时执行的操作
        print(f"{self.name} 插件已加载")
        print(f"插件版本: {self.version}")
        
        # 启动网络健康检查
        try:
            from services.system.network_health import network_health_checker
            await network_health_checker.start_health_check()
            print("✅ 网络健康检查已启动")
        except Exception as e:
            log.warning(f"网络健康检查启动失败: {e}")
        
        # 从环境变量加载 Notion Token
        import os
        self._notion_token = self._notion_token or os.getenv('NOTION_TOKEN')
        if self._notion_token:
            print(f"✅ Notion Token 已加载（自动同步功能可用）")
        else:
            print(f"⚠️  未配置 NOTION_TOKEN（自动同步功能不可用）")
        self._hulaquan_announcer_task = None
        self._hulaquan_announcer_interval = 120
        self._hulaquan_announcer_running = False
        self.register_hulaquan_announcement_tasks()
        self.register_hlq_query()
        self.start_hulaquan_announcer(self.data["config"].get("scheduled_task_time"))
        asyncio.create_task(User.update_friends_list(self))
        
    async def on_unload(self):
        print(f"{self.name} 插件已卸载")
        
        
    async def on_close(self, *arg, **kwd):
        self.remove_scheduled_task("呼啦圈上新提醒")
        self.stop_hulaquan_announcer()
        
        # 停止网络健康检查
        try:
            from services.system.network_health import network_health_checker
            await network_health_checker.stop_health_check()
            print("✅ 网络健康检查已停止")
        except Exception as e:
            log.warning(f"网络健康检查停止失败: {e}")
        
        await self.save_data_managers(on_close=True)
        return await super().on_close(*arg, **kwd)
    
    async def _hulaquan_announcer_loop(self):
        while self._hulaquan_announcer_running:
            try:
                await self.on_hulaquan_announcer()
            except Exception as e:
                await self.on_traceback_message(f"呼啦圈定时任务异常: {e}")
            try:
                await asyncio.sleep(int(self._hulaquan_announcer_interval))
            except Exception as e:
                await self.on_traceback_message(f"定时任务sleep异常: {e}")
            
    def start_hulaquan_announcer(self, interval=None):
        if interval:
            self._hulaquan_announcer_interval = interval
        if self._hulaquan_announcer_task and not self._hulaquan_announcer_task.done():
            return  # 已经在运行
        self._hulaquan_announcer_running = True
        self._hulaquan_announcer_interval = int(self._hulaquan_announcer_interval)
        self._hulaquan_announcer_task = asyncio.create_task(self._hulaquan_announcer_loop())
        log.info("呼啦圈检测定时任务已开启")

    def stop_hulaquan_announcer(self):
        self._hulaquan_announcer_running = False
        if self._hulaquan_announcer_task:
            self._hulaquan_announcer_task.cancel()
            self._hulaquan_announcer_task = None
            log.info("呼啦圈检测定时任务已关闭")


    def register_hulaquan_announcement_tasks(self):
        if "scheduled_task_switch" not in self.data:
            self.data["scheduled_task_switch"] = False
            
        self.register_user_func(
            name="帮助",
            handler=self.on_help,
            regex=r"^(?:[/#-](?:help|帮助)|help|帮助)[\s\S]*",
            description="查看帮助",
            usage="/help",
            examples=["/help", "/help example_plugin"],
        )
        
        self.register_user_func(
            name=HLQ_SWITCH_ANNOUNCER_MODE_NAME,
            handler=self.on_switch_scheduled_check_task,
            prefix="/呼啦圈通知",
            description=HLQ_SWITCH_ANNOUNCER_MODE_DESCRIPTION,
            usage=HLQ_SWITCH_ANNOUNCER_MODE_USAGE,
            examples=["/呼啦圈通知"],
            tags=["呼啦圈", "学生票", "查询", "hlq"],
            metadata={"category": "utility"}
        )
        
        self.register_admin_func(
                    name="开启/关闭呼啦圈定时检测功能（管理员）",
                    handler=self._on_switch_scheduled_check_task_for_users,
                    prefix="/呼啦圈检测",
                    description="开启/关闭呼啦圈定时检测功能（管理员）",
                    usage="/呼啦圈检测",
                    examples=["/呼啦圈检测"],
                    metadata={"category": "utility"}
        )
        
        self.register_admin_func(
                    name="更新帮助文档（管理员）",
                    handler=self.on_sync_notion_help,
                    prefix="/update-notion",
                    description="更新帮助文档",
                    usage="/update-notion",
                    examples=["/update-notion"],
                    metadata={"category": "utility"}
        )
        
        self.register_admin_func(
                    name="调试上新通知（管理员）",
                    handler=self.on_debug_announcer,
                    prefix="/debug通知",
                    description="调试上新通知功能（管理员）",
                    usage="/debug通知 [check|user|mock]",
                    examples=["/debug通知 check", "/debug通知 user", "/debug通知 mock"],
                    metadata={"category": "debug"}
        )
        
        
        
        self.register_config(
            key="scheduled_task_time",
            default=300,
            description="自动检测呼啦圈数据更新时间",
            value_type=int,
            allowed_values=[30, 60, 120, 180, 300, 600, 900, 1200, 1800, 3600],
            on_change=self.on_change_schedule_hulaquan_task_interval,
        )
        
        self.register_admin_func(
            name="保存数据（管理员）",
            handler=self.save_data_managers,
            prefix="/save",
            description="保存数据（管理员）",
            usage="/save",
            examples=["/save"],
            metadata={"category": "utility"}
        )
        
        self.register_admin_func(
            name="广播消息（管理员）",
            handler=self.on_broadcast,
            prefix="/广播",
            description="向所有用户和群聊发送广播消息（管理员）",
            usage="/广播 <消息内容>",
            examples=["/广播 系统维护通知：今晚22:00进行更新"],
            metadata={"category": "admin"}
        )
        
        self.add_scheduled_task(
            job_func=self.on_schedule_save_data, 
            name=f"自动保存数据", 
            interval="1h", 
            #max_runs=10, 
        )
        
        self.add_scheduled_task(
            job_func=self.on_schedule_friends_list_check, 
            name=f"好友列表更新", 
            interval="1h", 
            #max_runs=10, 
        )
    
    

    def register_hlq_query(self):
        self.register_user_func(
            name=HLQ_QUERY_NAME,
            handler=self.on_hlq_search,
            prefix="/hlq",
            description=HLQ_QUERY_DESCRIPTION,
            usage=HLQ_QUERY_USAGE,
            # 这里的 -I 是一个可选参数，表示忽略已售罄场次
            examples=["/hlq 连璧 -I -C"],
            tags=["呼啦圈", "学生票", "查询", "hlq"],
            metadata={"category": "utility"}
        )

        self.register_user_func(
            name="所有呼啦圈",
            handler=self.on_list_all_hulaquan_events,
            prefix="/所有呼啦圈",
            description="列出所有呼啦圈事件",
            usage="/所有呼啦圈",
            examples=["/所有呼啦圈"],
            tags=["呼啦圈", "学生票", "查询"],
            metadata={"category": "utility"}
        )
        
        self.register_admin_func(
            name="呼啦圈手动刷新（管理员）",
            handler=self.on_hulaquan_announcer_manual,
            prefix="/refresh",
            description="呼啦圈手动刷新（管理员）",
            usage="/refresh",
            examples=["/refresh"],
            tags=["呼啦圈", "学生票", "查询", "hlq"],
            metadata={"category": "utility"}
        )
        
        self.register_user_func(
            name=HLQ_DATE_NAME,
            handler=self.on_list_hulaquan_events_by_date,
            prefix="/date",
            description=HLQ_DATE_DESCRIPTION,
            usage=HLQ_DATE_USAGE,
            examples=["/date <日期> (城市)"],
            tags=["saoju"],
            metadata={"category": "utility"}
        )
        self.register_user_func(
            name="获取更新日志",
            handler=self.on_get_update_log,
            prefix="/版本",
            description="获取更新日志",
            usage="/版本",
            examples=["/版本"],
            tags=["version"],
            metadata={"category": "utility"}
        )
        self.register_user_func(
            name="设置剧目别名",
            handler=self.on_set_alias,
            prefix="/alias",
            description="为呼啦圈剧目设置别名，解决不同平台剧名不一致问题",
            usage="/alias <原剧名> <别名>",
            examples=["/alias lizzie 丽兹"],
            metadata={"category": "utility"}
        )
        self.register_user_func(
            name="呼啦圈别名列表",
            handler=self.on_list_aliases,
            prefix="/aliases",
            description="查看所有呼啦圈剧目别名",
            usage="/aliases",
            examples=["/aliases"],
            tags=["呼啦圈", "别名", "查询"],
            metadata={"category": "utility"}
        )
        
        self.register_user_func(
            name=HLQ_NEW_REPO_NAME,
            handler=self.on_hulaquan_new_repo,
            prefix="/新建repo",
            description=HLQ_NEW_REPO_DESCRIPTION,
            usage=HLQ_NEW_REPO_USAGE,
            examples=["/新建repo"],
            tags=["呼啦圈", "学生票", "查询"],
            metadata={"category": "utility"}
        )
        
        self.register_user_func(
            name=HLQ_GET_REPO_NAME,
            handler=self.on_hulaquan_get_repo,
            prefix="/查询repo",
            description=HLQ_GET_REPO_DESCRIPTION,
            usage=HLQ_GET_REPO_USAGE,
            examples=["/查询repo"],
            tags=["呼啦圈", "学生票", "查询"],
            metadata={"category": "utility"}
        )
        
        self.register_user_func(
            name=HLQ_MY_REPO_NAME,
            handler=self.on_hulaquan_my_repo,
            prefix="/我的repo",
            description=HLQ_MY_REPO_DESCRIPTION,
            usage=HLQ_MY_REPO_USAGE,
            examples=["/我的repo"],
            tags=["呼啦圈", "学生票", "查询"],
            metadata={"category": "utility"}
        )
        
        self.register_user_func(
            name=HLQ_REPORT_ERROR_NAME,
            handler=self.on_hulaquan_report_error,
            prefix="/报错repo",
            description=HLQ_REPORT_ERROR_DESCRIPTION,
            usage=HLQ_REPORT_ERROR_USAGE,
            examples=["/报错repo"],
            tags=["呼啦圈", "学生票", "查询"],
            metadata={"category": "utility"}
        )
        
        self.register_user_func(
            name=HLQ_MODIFY_REPO_NAME,
            handler=self.on_modify_self_repo,
            prefix="/修改repo",
            description=HLQ_MODIFY_REPO_DESCRIPTION,
            usage=HLQ_MODIFY_REPO_USAGE,
            examples=["/报错repo"],
            tags=["呼啦圈", "学生票", "查询"],
            metadata={"category": "utility"}
        )
        
        self.register_user_func(
            name=HLQ_DEL_REPO_NAME,
            handler=self.on_delete_self_repo,
            prefix="/删除repo",
            description=HLQ_DEL_REPO_DESCRIPTION,
            usage=HLQ_DEL_REPO_USAGE,
            examples=[""],
            tags=["呼啦圈", "学生票", "查询"],
            metadata={"category": "utility"}
        )
        
        self.register_user_func(
            name=HLQ_LATEST_REPOS_NAME,
            handler=self.on_get_latest_repos,
            prefix="/最新repo",
            description=HLQ_LATEST_REPOS_DESCRIPTION,
            usage=HLQ_LATEST_REPOS_USAGE,
            examples=[""],
            tags=["呼啦圈", "学生票", "查询"],
            metadata={"category": "utility"}
        )
        
        self.register_user_func(
            name=HLQ_QUERY_CO_CASTS_NAME,
            handler=self.on_get_co_casts,
            prefix="/同场演员",
            description=HLQ_QUERY_CO_CASTS_DESCRIPTION,
            usage=HLQ_QUERY_CO_CASTS_USAGE,
            examples=[""],
            tags=["呼啦圈", "学生票", "查询"],
            metadata={"category": "utility"}
        )
        
        self.register_user_func(
            name=HLQ_FOLLOW_TICKET_NAME,
            handler=self.on_follow_ticket,
            prefix="/关注学生票",
            description=HLQ_FOLLOW_TICKET_DESCRIPTION,
            usage=HLQ_FOLLOW_TICKET_USAGE,
            examples=[""],
            tags=["呼啦圈", "学生票", "查询"],
            metadata={"category": "utility"}
        )
        self.register_user_func(
            name=HLQ_UNFOLLOW_TICKET_NAME,
            handler=self.on_unfollow_ticket,
            prefix="/取消关注学生票",
            description=HLQ_UNFOLLOW_TICKET_DESCRIPTION,
            usage=HLQ_UNFOLLOW_TICKET_USAGE,
            examples=[""],
            tags=["呼啦圈", "学生票", "查询"],
            metadata={"category": "utility"}
        )
        self.register_user_func(
            name=HLQ_VIEW_FOLLOW_NAME,
            handler=self.on_view_follow,
            prefix="/查看关注",
            description=HLQ_VIEW_FOLLOW_DESCRIPTION,
            usage=HLQ_VIEW_FOLLOW_USAGE,
            examples=[""],
            tags=["呼啦圈", "学生票", "查询"],
            metadata={"category": "utility"}
        )
        
        self.register_pending_tickets_announcer()
        """
        {name}-{description}:使用方式 {usage}
        """
    
    async def _on_switch_scheduled_check_task_for_users(self, msg: BaseMessage):
        if self._hulaquan_announcer_running:
            self.stop_hulaquan_announcer()
            await msg.reply("（管理员）已关闭呼啦圈上新检测功能")
        else:
            self.start_hulaquan_announcer()
            await msg.reply("(管理员）已开启呼啦圈上新检测功能")
            
    async def on_get_update_log(self, msg: BaseMessage):
        m = f"当前版本：{self.version}\n\n版本更新日志：\n{get_update_log()}"
        await msg.reply(m)
    
    # 呼啦圈刷新    
    @user_command_wrapper("hulaquan_announcer")
    async def on_hulaquan_announcer(self, test=False, manual=False, announce_admin_only=False):
        """
        用户可以选择关注ticketID、eventID
        针对全部events/某eventID/某ticketID，有几种关注模式：
            0 不关注
            1 只推送上新/补票
            2 额外关注回流票
            3 额外关注票增/票减
            
        功能逻辑：
            1.先从hlq获取所有更新数据
        """
        MODE = {
            "add": 1,
            "new": 1,
            "pending": 1,
            "return": 2,
            "back": 3,
            "sold": 3,
        }
        start_time = time.time()
        try:
            result = await Hlq.compare_to_database_async()
            event_id_to_ticket_ids = result["events"]
            event_msgs = result["events_prefixes"]
            PREFIXES = result["prefix"]
            categorized = result["categorized"]
            tickets = result['tickets']
        except RequestTimeoutException as e:
            raise
        if len(categorized["new"]) >= 400:
            log.error(f"呼啦圈数据刷新出现异常，存在{len(categorized['new'])}条数据刷新")
            if not announce_admin_only:
                return
        elapsed_time = round(time.time() - start_time, 2)
        if not announce_admin_only:
            _users = User.users()
        else:
            _users = {User.admin_id: User.users()[User.admin_id]}
        for user_id, user in _users.items():
            messages = self.__generate_announce_text(MODE, event_id_to_ticket_ids, event_msgs, PREFIXES, categorized, tickets, user_id, user)
            for i in messages:
                m = "\n\n".join(i)
                r = await self.api.post_private_msg(user_id, m)
                if r['retcode'] == 1200:
                    User.delete_user(user_id)
                    break
        if not announce_admin_only:
            for group_id, group in User.groups().items():
                messages = self.__generate_announce_text(MODE, event_id_to_ticket_ids, event_msgs, PREFIXES, categorized, tickets, group_id, group, is_group=True)
                for i in messages:
                    m = "\n\n".join(i)
                    await self.api.post_group_msg(group_id, m)
        if len(categorized["pending"]) > 0:
            self.register_pending_tickets_announcer()
        return True

    def __generate_announce_text(self, MODE, event_id_to_ticket_ids, event_msgs, PREFIXES, categorized, tickets, user_id, user, is_group=False):
        announce = {} # event_id: {ticket_id: msg}, ...
        all_mode = int(user.get("attention_to_hulaquan", 0))
        if not is_group:
            fo_events = User.subscribe_events(user_id)
            fo_tickets = User.subscribe_tickets(user_id)
            for event in fo_events:
                eid = event['id']
                e_mode = int(event['mode'])
                if eid in event_id_to_ticket_ids:
                    announce.setdefault(eid, {})
                    for tid in event_id_to_ticket_ids[eid]:
                        ticket = tickets[tid]
                        stat = ticket['categorized']
                        if e_mode >= MODE.get(stat, 99):
                            announce[eid].setdefault(stat, set())
                            announce[eid][stat].add(tid)
            for t in fo_tickets:
                tid = t['id']
                e_mode = int(t['mode'])
                if tid in tickets.keys():
                    ticket = tickets[tid]
                    eid = ticket['event_id']
                    stat = ticket['categorized']
                    if e_mode >= MODE.get(stat, 99):
                        announce.setdefault(eid, {})
                        announce[eid].setdefault(stat, set())
                        announce[eid][stat].add(tid)
        for stat, tid_s in categorized.items():
            if all_mode >= MODE.get(stat, 99):
                for tid in tid_s:
                    ticket = tickets[tid]
                    eid = ticket['event_id']
                    stat = ticket['categorized']
                    announce.setdefault(eid, {})
                    announce[eid].setdefault(stat, set())
                    announce[eid][stat].add(tid)
        messages = []
        for eid, stats in announce.items():
            if not len(stats.keys()):
                continue
            messages.append([])
            event_prefix = event_msgs[eid]
            messages[-1].append(event_prefix)
            stats_ps = []
            for stat, t_ids in stats.items():
                t_ids = list(t_ids)
                t_ids.sort(key=int)
                stat_pfx = PREFIXES[stat]
                stats_ps.append(stat_pfx)
                t_m = [tickets[t]['message'] for t in t_ids]
                joined_messages = "\n".join(t_m)
                m = f"{stat_pfx}提醒：\n{joined_messages}"
                messages[-1].append(m)
            messages[-1][0] = f"{'|'.join(stats_ps)}提醒：\n" + messages[-1][0]
        return messages
        
    def register_pending_tickets_announcer(self):
        for valid_from, events in Hlq.data["pending_events"].items():
            if not valid_from or valid_from == "NG":
                continue
            for eid, text in events.items():
                eid = str(eid)
                job_id = f"{valid_from}_{eid}"
                _exist = self._time_task_scheduler.get_job_status(job_id)
                if _exist:
                    continue
                valid_date = standardize_datetime(valid_from, False)
                valid_date = dateTimeToStr(valid_date - timedelta(minutes=30))
                self.add_scheduled_task(
                    job_func=self.on_pending_tickets_announcer,
                    name=job_id,
                    interval=valid_from,
                    kwargs={"eid":eid, "message":text, "valid_from":valid_from},
                    max_runs=1,
                )
    
    @user_command_wrapper("pending_announcer")
    async def on_pending_tickets_announcer(self, eid:str, message: str, valid_from:str):
        message = f"【即将开票】呼啦圈开票提醒：\n{message}"
        for user_id, user in User.users().items():
            mode = user.get("attention_to_hulaquan")
            if mode == "1" or mode == "2":
                await self.api.post_private_msg(user_id, message)
        for group_id, group in User.groups().items():
            mode = group.get("attention_to_hulaquan")
            if mode == "1" or mode == "2":
                await self.api.post_group_msg(group_id, message)
        del Hlq.data["pending_events"][valid_from][eid]
        if len(Hlq.data["pending_events"][valid_from]) == 0:
            del Hlq.data["pending_events"][valid_from]
            
    @user_command_wrapper("switch_mode")
    async def on_switch_scheduled_check_task(self, msg: BaseMessage, group_switch_verify=False):
        user_id = msg.user_id
        group_id = None
        all_args = self.extract_args(msg)
        query_id = msg.group_id if isinstance(msg, GroupMessage) else msg.user_id
        
        # 获取当前模式
        if isinstance(msg, GroupMessage):
            current_user = User.groups().get(str(query_id), {})
        else:
            current_user = User.users().get(str(query_id), {})
        
        current_mode = current_user.get("attention_to_hulaquan", 0) if current_user else 0
        
        # 模式说明
        mode_desc = {
            0: "❌ 不接受通知",
            1: "🆕 只推送上新/补票",
            2: "🆕🔄 推送上新/补票/回流",
            3: "🆕🔄📊 推送上新/补票/回流/增减票"
        }
        
        # 如果没有参数，显示当前状态
        if not all_args["text_args"]:
            status_msg = [
                "📊 当前呼啦圈通知状态：",
                f"当前模式: 模式{current_mode} - {mode_desc.get(int(current_mode), '未知')}",
                "",
                "💡 若要设置，请使用：",
                f"{HLQ_SWITCH_ANNOUNCER_MODE_USAGE}"
            ]
            return await msg.reply("\n".join(status_msg))
        
        # 验证模式参数
        if all_args.get("text_args")[0] not in ["0", "1", "2", "3"]:
            return await msg.reply(f"请输入存在的模式（0-3）\n用法：{HLQ_SWITCH_ANNOUNCER_MODE_USAGE}")
        
        mode = all_args.get("text_args")[0]
        
        # 设置模式
        if isinstance(msg, GroupMessage):
            group_id = msg.group_id
            if group_switch_verify and User.is_op(user_id):
                User.switch_attention_to_hulaquan(group_id, mode, is_group=True)
            else:
                return await msg.reply("权限不足！需要管理员权限才能切换群聊的推送设置")
        else:
            User.switch_attention_to_hulaquan(user_id, mode)
        
        # 返回设置结果
        if mode == "2":
            await msg.reply("✅ 已设置为模式2\n已关注呼啦圈的上新/补票/回流通知")
        elif mode == "1":
            await msg.reply("✅ 已设置为模式1\n已关注呼啦圈的上新/补票通知")
        elif mode == "3":
            await msg.reply("✅ 已设置为模式3\n已关注呼啦圈的上新/补票/回流/增减票通知")
        elif mode == "0":
            await msg.reply("✅ 已设置为模式0\n已关闭呼啦圈上新推送")
            

    @user_command_wrapper("hulaquan_search")
    async def on_hlq_search(self, msg: BaseMessage):
        # 呼啦圈查询处理函数
        all_args = self.extract_args(msg)
        if not all_args["text_args"]:
            await msg.reply_text(f"请提供剧名，用法：{HLQ_QUERY_USAGE}")
            return
        event_name = all_args["text_args"][0]
        args = all_args["mode_args"]
        if "-r" in args:
            await msg.reply_text("【因数据自动刷新间隔较短，目前已不支持-R参数】")
        if isinstance(msg, PrivateMessage):
            await msg.reply_text("查询中，请稍后…")
        pattern = r"-(\d+)"
        extra_ids = [re.search(pattern, item).group(1) for item in args if re.search(pattern, item)]
        extra_id = int(extra_ids[0]) if extra_ids else None
        result = await Hlq.on_message_tickets_query(event_name, show_cast=("-c" in args), ignore_sold_out=("-i" in args), refresh=False, show_ticket_id=('-t' in args), extra_id=extra_id)
        await msg.reply_text(result if result else "未找到相关信息，请尝试更换搜索名")
        

    def extract_args(self, msg):
        command = [arg for arg in msg.raw_message.split(" ") if arg] 
        args = {"command":command[0], "mode_args":[arg for arg in command[1:] if arg[0] == '-'], "text_args":[arg for arg in command[1:] if arg[0] != '-']}
        for i in range(len(args["mode_args"])):
            args["mode_args"][i] = args["mode_args"][i].lower() # 小写处理-I -i
        return args
    
    async def on_change_schedule_hulaquan_task_interval(self, value, msg: BaseMessage):
        if not User.is_op(msg.user_id):
            await msg.reply_text(f"修改失败，暂无修改查询时间的权限")
            return
        self.stop_hulaquan_announcer()
        self._hulaquan_announcer_interval = int(value)
        self.start_hulaquan_announcer(interval=int(value))
        await msg.reply_text(f"已修改至{value}秒更新一次")
    
    def _get_help(self):
        """自动生成帮助文档"""
        text = {"user":"", "admin":""}
        for func in self._funcs:
            if func.permission == "user":
                text["user"] += f"👉功能描述：{func.description}\n★用法：{func.usage}\n\n"
            else:
                text["admin"] += f"👉功能描述：{func.description}\n★用法：{func.usage}\n\n"
        #for conf in self._configs:
        #    text += f"{conf.key}--{conf.description}: 类型 {conf.value_type}, 默认值 {conf.default}\n"
        return text
    
    @user_command_wrapper("query_co_casts")
    async def on_get_co_casts(self, msg: BaseMessage):
        args = self.extract_args(msg)  
        if not args["text_args"]:
            await msg.reply_text("【缺少参数】以下是/同场演员 的用法"+HLQ_QUERY_CO_CASTS_USAGE)
            return
        casts = args["text_args"]
        show_others = "-o" in args["mode_args"]
        use_hulaquan = "-h" in args["mode_args"]
        
        # -H 模式：通过扫剧查询同场，再映射到呼啦圈
        if use_hulaquan:
            # 1. 先用扫剧查询同场数据
            saoju_events = await Saoju.request_co_casts_data(casts, show_others=show_others)
            
            if not saoju_events:
                await msg.reply_text(f"❌ 在扫剧系统中未找到 {' '.join(casts)} 的同场演出")
                return
            
            # 2. 将扫剧的剧目标题映射到呼啦圈事件ID
            hlq_matches = []  # [(saoju_event, hlq_event_id, hlq_title)]
            
            for saoju_event in saoju_events:
                saoju_title = saoju_event['title']
                
                # 使用 extract_title_info 提取标题信息（包括城市）
                from .utils import extract_title_info
                title_info = extract_title_info(saoju_title)
                clean_title = title_info['title']  # 提取《》内的标题
                saoju_city = title_info.get('city') or saoju_event.get('city', '上海')
                
                # 尝试用标题在呼啦圈中查找（使用别名系统）
                search_names = Hlq.get_ordered_search_names(title=clean_title)
                
                hlq_event_id = None
                hlq_title = None
                
                for search_name in search_names:
                    # 尝试通过search_name获取event_id
                    eid = Alias.get_event_id_by_name(search_name)
                    if eid and str(eid) in Hlq.data.get('events', {}):
                        hlq_event_id = str(eid)
                        hlq_title = Hlq.title(event_id=hlq_event_id, keep_brackets=True)
                        break
                
                # 如果别名系统找不到，尝试模糊搜索
                if not hlq_event_id:
                    # 使用已提取的 clean_title 进行模糊匹配
                    for eid, event_data in Hlq.data.get('events', {}).items():
                        event_title = event_data.get('title', '')
                        # 提取呼啦圈标题的《》内容进行对比
                        from .utils import extract_text_in_brackets
                        hlq_clean_title = extract_text_in_brackets(event_title, keep_brackets=False)
                        
                        if clean_title.lower() in hlq_clean_title.lower() or hlq_clean_title.lower() in clean_title.lower():
                            hlq_event_id = str(eid)
                            hlq_title = event_title
                            break
                
                if hlq_event_id:
                    hlq_matches.append((saoju_event, hlq_event_id, hlq_title))
            
            if not hlq_matches:
                await msg.reply_text(f"❌ 在扫剧中找到 {len(saoju_events)} 场演出，但均未在呼啦圈系统中找到对应学生票")
                return
            
            # 3. 生成消息（与非-h格式一致）
            messages = []
            messages.append(" ".join(casts) + f" 同场的音乐剧演出，在呼啦圈系统中找到 {len(hlq_matches)} 场有学生票的演出。")
            
            for saoju_event, hlq_event_id, hlq_title in hlq_matches:
                date_str = saoju_event['date']
                city = saoju_event.get('city', '上海')
                
                # 格式化同场其他演员
                others_str = ""
                if show_others and 'others' in saoju_event:
                    others_list = saoju_event['others']
                    if isinstance(others_list, str):
                        others_list = others_list.split()
                    if others_list:
                        others_str = "\n同场其他演员：" + " ".join(others_list)
                
                # 组装消息（格式与非-h一致）
                msg_line = f"{date_str} {city} {hlq_title}{others_str}"
                messages.append(msg_line)
            
            await msg.reply("\n".join(messages))
        else:
            # 原有逻辑：使用扫剧系统
            messages = await Saoju.match_co_casts(casts, show_others=show_others)
            await msg.reply("\n".join(messages))
    
       
    @user_command_wrapper("search_by_date") 
    async def on_list_hulaquan_events_by_date(self, msg: BaseMessage):
        # 最多有12小时数据延迟
        args = self.extract_args(msg)
        if not args["text_args"]:
            await msg.reply_text("【缺少日期】以下是/date的用法\n"+HLQ_DATE_USAGE)
            return
        date = args["text_args"][0]
        city = args["text_args"][1] if len(args["text_args"])>1 else None
        mode_args = args["mode_args"]
        result = await Hlq.on_message_search_event_by_date(date, city, ignore_sold_out=("-i" in mode_args))
        await msg.reply(result)
        
    async def on_hulaquan_announcer_manual(self, msg: BaseMessage):
        try:
            await self.on_hulaquan_announcer(manual=True)
            await msg.reply_text("刷新成功")
        except Exception as e:
            print(e)
            await msg.reply_text()

    async def on_schedule_save_data(self):
        await self.save_data_managers()
    
    async def on_schedule_friends_list_check(self):
        await User.update_friends_list(self)
        
    @user_command_wrapper("help")
    async def on_help(self, msg: BaseMessage):
        """
        显示帮助文档
        用法：
          /help        - 发送 Notion 帮助文档链接（推荐）
          /help -t     - 显示文本格式
          /help -i     - 显示图片格式（需要 Pillow）
          /help -r     - 强制刷新缓存
          /help -n     - 强制使用 Notion 并同步
        """
        try:
            from .user_func_help import get_help_v2
            
            # 安全地解析参数
            msg_text = ""
            try:
                if hasattr(msg, 'raw_message'):
                    msg_text = msg.raw_message
                elif hasattr(msg, 'text'):
                    msg_text = msg.text
                else:
                    msg_text = str(msg)
            except Exception as e:
                log.warning(f"无法获取消息文本，使用默认模式: {e}")
                msg_text = ""
            
            text_mode = "-t" in msg_text or "--text" in msg_text
            image_mode = "-i" in msg_text or "--image" in msg_text
            force_refresh = "-r" in msg_text or "--refresh" in msg_text
            force_notion = "-n" in msg_text or "--notion" in msg_text
            
            # 优先尝试 Notion 模式（除非明确要求文本或图片）
            if not text_mode and not image_mode:
                # 尝试获取或创建 Notion 页面
                try:
                    notion_url = await self._get_or_create_notion_help(force_sync=force_notion or force_refresh)
                    if notion_url:
                        await msg.reply(
                            f"📖 呼啦圈学生票机器人 - 帮助文档\n"
                            f"🔗 点击查看完整帮助：\n{notion_url}\n\n"
                            f"💡 提示：\n"
                            f"  • 使用 /help -t 查看文本版本\n"
                            f"  • 使用 /help -i 查看图片版本\n"
                            f"  • 使用 /help -n 强制刷新 Notion"
                        )
                        return
                    else:
                        log.warning("Notion 帮助文档获取失败，回退到文本模式")
                        text_mode = True
                except Exception as e:
                    log.error(f"Notion 模式失败: {e}")
                    text_mode = True
            
            # 文本模式
            if text_mode:
                help_content = get_help_v2(force_refresh=force_refresh, as_image=False)
                await msg.reply(help_content)
                return
            
            # 图片模式
            if image_mode:
                help_image = get_help_v2(force_refresh=force_refresh, as_image=True)
                if isinstance(help_image, bytes):
                    # 成功生成图片
                    try:
                        # 保存临时文件并发送
                        import tempfile
                        import os
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp_file:
                            tmp_file.write(help_image)
                            tmp_path = tmp_file.name
                        
                        try:
                            await msg.reply_image(tmp_path)
                        finally:
                            # 清理临时文件
                            try:
                                os.unlink(tmp_path)
                            except:
                                pass
                    except Exception as e:
                        log.error(f"发送帮助图片失败：{e}，回退到文本模式")
                        help_text = get_help_v2(force_refresh=force_refresh, as_image=False)
                        await msg.reply(help_text)
                else:
                    # 图片生成失败，已经返回文本
                    await msg.reply(help_image)
        
        except Exception as e:
            # 最终的安全回退：发送基本错误信息
            log.error(f"帮助命令完全失败: {e}")
            try:
                await msg.reply_text(
                    "❌ 帮助文档加载失败\n\n"
                    "请联系管理员或稍后重试。"
                )
            except:
                # 如果连错误消息都发不出去，只能放弃
                pass
    
    async def _get_or_create_notion_help(self, force_sync=False):
        """
        获取 Notion 帮助文档链接
        
        Args:
            force_sync: 是否强制重新同步（暂时忽略）
        
        Returns:
            str: Notion 页面的 URL，失败返回 None
        """
        # 方案 1：直接返回预设的 URL（最简单）
        if self.NOTION_HELP_URL:
            return self.NOTION_HELP_URL
        
        # 方案 2：尝试使用 API 创建（需要额外配置）
        if not self.NOTION_PARENT_PAGE_ID:
            log.debug("未配置 NOTION_HELP_URL 或 NOTION_PARENT_PAGE_ID")
            return None
        
        try:
            # TODO: 实现 MCP Notion API 调用
            # 这里可以调用 Notion API 创建或更新页面
            log.info("Notion API 同步功能待实现")
            return None
            
        except Exception as e:
            log.error(f"获取 Notion 帮助文档失败: {e}")
            return None

    @user_command_wrapper("auto_save")
    async def save_data_managers(self, msg=None, on_close=False):
        while Hlq.updating:
            await asyncio.sleep(0.1)
        success = await save_all(on_close)
        status = "成功" if success else "失败"
            
        log.info("🟡呼啦圈数据保存"+status)
        if msg:
            await msg.reply_text("保存"+status)
        else:
            pass
    
    @user_command_wrapper("broadcast")
    async def on_broadcast(self, msg: BaseMessage):
        """管理员广播消息到所有用户和群聊"""
        # 提取广播内容
        all_args = self.extract_args(msg)
        
        if not all_args["text_args"]:
            await msg.reply_text("❌ 请提供广播内容\n用法：/广播 <消息内容>")
            return
        
        # 组合所有文本参数作为广播内容
        broadcast_message = " ".join(all_args["text_args"])
        
        # 确认广播
        confirm_msg = [
            "📢 广播消息预览：",
            "━━━━━━━━━━━━━━━━",
            broadcast_message,
            "━━━━━━━━━━━━━━━━",
            "",
            f"将发送给：",
            f"👤 用户数：{len(User.users())}",
            f"👥 群聊数：{len(User.groups())}",
            "",
            "⚠️ 确认发送吗？请回复 '确认' 以继续"
        ]
        
        await msg.reply_text("\n".join(confirm_msg))
        
        # 等待确认（简化版，实际应该监听下一条消息）
        # 这里我们直接发送，如果需要确认机制需要额外实现
        
        # 发送广播
        await self._do_broadcast(broadcast_message, msg)
    
    async def _do_broadcast(self, message: str, original_msg: BaseMessage):
        """执行广播操作"""
        success_users = 0
        failed_users = 0
        success_groups = 0
        failed_groups = 0
        
        # 添加广播标识
        full_message = f"📢 系统广播\n━━━━━━━━━━━━━━━━\n{message}"
        
        # 向所有用户发送
        await original_msg.reply_text("📤 开始向用户发送...")
        for user_id in User.users_list():
            try:
                r = await self.api.post_private_msg(user_id, full_message)
                if r.get('retcode') == 0:
                    success_users += 1
                else:
                    failed_users += 1
                    log.warning(f"向用户 {user_id} 发送广播失败: {r.get('retcode')}")
                # 避免发送过快
                await asyncio.sleep(0.5)
            except Exception as e:
                failed_users += 1
                log.error(f"向用户 {user_id} 发送广播异常: {e}")
        
        # 向所有群聊发送
        await original_msg.reply_text("📤 开始向群聊发送...")
        for group_id in User.groups_list():
            try:
                r = await self.api.post_group_msg(group_id, full_message)
                if r.get('retcode') == 0:
                    success_groups += 1
                else:
                    failed_groups += 1
                    log.warning(f"向群聊 {group_id} 发送广播失败: {r.get('retcode')}")
                # 避免发送过快
                await asyncio.sleep(0.5)
            except Exception as e:
                failed_groups += 1
                log.error(f"向群聊 {group_id} 发送广播异常: {e}")
        
        # 发送结果统计
        result_msg = [
            "✅ 广播发送完成！",
            "",
            "📊 发送统计：",
            f"👤 用户：成功 {success_users} / 失败 {failed_users}",
            f"👥 群聊：成功 {success_groups} / 失败 {failed_groups}",
            f"📈 总成功率：{((success_users + success_groups) / (len(User.users_list()) + len(User.groups_list())) * 100):.1f}%"
        ]
        
        await original_msg.reply_text("\n".join(result_msg))
        log.info(f"📢 [广播完成] 用户:{success_users}/{len(User.users_list())}, 群聊:{success_groups}/{len(User.groups_list())}")
    
    @user_command_wrapper("sync_notion_help")
    async def on_sync_notion_help(self, msg: BaseMessage):
        """同步帮助文档到 Notion（管理员命令）"""
        if not User.is_op(msg.user_id):
            await msg.reply_text("❌ 此命令仅管理员可用")
            return
        
        if not self._notion_help_page_id:
            await msg.reply_text("❌ 未配置 Notion 页面 ID")
            return
        
        if not self._notion_token:
            error_msg = [
                "❌ 未配置 NOTION_TOKEN",
                "",
                "请按以下步骤配置：",
                "1. 创建 Notion Integration:",
                "   https://www.notion.so/my-integrations",
                "2. 获取 Internal Integration Token",
                "3. 将 Token 配置为环境变量:",
                "   Windows: $env:NOTION_TOKEN=\"ntn_xxx\"",
                "   Linux/Mac: export NOTION_TOKEN=ntn_xxx",
                "4. 重启机器人",
                "",
                "⚠️ 注意：Integration Token 需要有页面的编辑权限"
            ]
            await msg.reply_text("\n".join(error_msg))
            return
        
        await msg.reply_text("🔄 开始同步帮助文档到 Notion...")
        
        try:
            from .user_func_help import HELP_SECTIONS, HELP_DOC_VERSION, BOT_VERSION, HELP_DOC_UPDATE_DATE
            from .notion_help_manager_v2 import NotionHelpManager
            
            # 生成 Notion blocks
            mgr = NotionHelpManager()
            blocks = mgr.generate_notion_blocks(
                HELP_SECTIONS,
                {
                    'version': HELP_DOC_VERSION,
                    'bot_version': BOT_VERSION,
                    'update_date': HELP_DOC_UPDATE_DATE
                }
            )
            
            await msg.reply_text(f"✅ 生成了 {len(blocks)} 个 blocks\n⏳ 正在上传到 Notion...")
            
            # 上传到 Notion
            result = await mgr.upload_to_notion(
                page_id=self._notion_help_page_id,
                blocks=blocks,
                notion_token=self._notion_token
            )
            
            if result['success']:
                success_msg = [
                    "✅ 帮助文档同步成功！",
                    "",
                    f"📊 Blocks 数量: {result['blocks_added']}",
                    f"📄 页面 ID: {self._notion_help_page_id}",
                    f"🔗 页面链接: {self.NOTION_HELP_URL}",
                    "",
                    "💡 提示: 确保页面已设置为 'Share to web' 以便用户访问"
                ]
                await msg.reply_text("\n".join(success_msg))
                log.info(f"✅ [Notion同步成功] 上传了 {result['blocks_added']} 个 blocks")
            else:
                error_msg = [
                    "❌ 帮助文档同步失败",
                    "",
                    f"错误信息: {result['message']}",
                    f"已上传: {result['blocks_added']} blocks",
                    "",
                    "请检查:",
                    "1. NOTION_TOKEN 是否正确",
                    "2. Integration 是否有页面编辑权限",
                    "3. 页面 ID 是否正确"
                ]
                await msg.reply_text("\n".join(error_msg))
                log.error(f"❌ [Notion同步失败] {result['message']}")
            
        except Exception as e:
            error_msg = f"❌ 同步失败: {str(e)}"
            await msg.reply_text(error_msg)
            log.error(f"❌ [Notion同步失败] {e}")
            import traceback
            log.error(traceback.format_exc())
            
    @user_command_wrapper("traceback")            
    async def on_traceback_message(self, context="", announce_admin=True):
        #log.error(f"呼啦圈上新提醒失败：\n" + traceback.format_exc())
        error_msg = f"{context}：\n" + traceback.format_exc()
        log.error(error_msg)
        if announce_admin:
            await self.api.post_private_msg(User.admin_id, error_msg)
    
    @user_command_wrapper("add_alias")        
    async def on_set_alias(self, msg: BaseMessage):
        args = self.extract_args(msg)
        if len(args["text_args"]) < 2:
            await msg.reply_text("用法：/alias <搜索名> <别名>")
            return
        search_name, alias = args["text_args"][0], args["text_args"][1]
        result = await self.get_event_id_by_name(search_name, msg)
        if result:
            event_id = result[0]
            Alias.add_alias(event_id, alias)
            Alias.add_search_name(event_id, search_name)
            await msg.reply_text(f"已为剧目 {result[1]} 添加别名：{alias}，对应搜索名：{search_name}")
            return
        
    async def get_event_id_by_name(self, search_name: str, msg: BaseMessage=None, msg_prefix: str="", notFoundAndRegister=False, foundInState=False, extra_id=None):
        # return :: (event_id, event_name) or False
        result = await Hlq.get_event_id_by_name(search_name, None, extra_id=extra_id)
        if not result[0]:
            if notFoundAndRegister:
                event_id = Stats.register_event(search_name)
                await msg.reply_text(msg_prefix+f"未在呼啦圈系统中找到该剧目，已为您注册此剧名以支持更多功能：{search_name}")
                return (event_id, search_name)
            if foundInState:
                if eid := Stats.get_event_id(search_name):
                    return (eid, Stats.get_event_title(eid))
            if msg:
                await msg.reply_text(msg_prefix+(result[1] if result[1] else "未找到该剧目"))
            return False
        return (result[0], search_name)

    @user_command_wrapper("on_list_aliases")    
    async def on_list_aliases(self, msg: BaseMessage):
        # 直接从 AliasManager 获取别名信息
        alias_to_event = Alias.data.get("alias_to_event", {})
        event_to_names = Alias.data.get("event_to_names", {})
        events = Hlq.data.get("events", {})
        if not alias_to_event:
            await msg.reply_text("暂无别名记录。")
            return
        lines = []
        for alias, event_id in alias_to_event.items():
            event_name = events.get(event_id, {}).get("title", "未知剧目")
            search_names = ", ".join(event_to_names.get(event_id, []))
            lines.append(f"{alias}（{event_name}）: {search_names}")
        if not lines:
            await msg.reply_text("暂无别名记录。")
        else:
            await msg.reply_text("当前别名列表：\n" + "\n".join(lines))
    
    @user_command_wrapper("new_repo")    
    async def on_hulaquan_new_repo(self, msg: BaseMessage):
        if isinstance(msg, GroupMessage):
            if not User.is_op(msg.user_id):
                return await msg.reply_text("此功能当前仅限私聊使用。")
        
        match, mandatory_check = parse_text_to_dict_with_mandatory_check(msg.raw_message, HLQ_NEW_REPO_INPUT_DICT ,with_prefix=True)
        if mandatory_check:
            return await msg.reply_text(f"缺少以下必要字段：{' '.join(mandatory_check)}\n{HLQ_NEW_REPO_USAGE}")
        user_id = msg.user_id if not match["user_id"] else match["user_id"]
        title = match["title"]
        date = match["date"]
        seat = match["seat"]
        price = match["price"]
        content = match["content"]
        category = match["category"]
        payable = match["payable"]
        
        print(f"{user_id}上传了一份repo：剧名: {title}\n日期: {date}\n座位: {seat}\n价格: {price}\n描述: {content}\n")
        result = await self.get_event_id_by_name(title, msg, notFoundAndRegister=True)
        event_id = result[0]
        title = result[1]
        if not event_id:
            event_id = Stats.register_event(title) 
        report_id = Stats.new_repo(
            title=title,
            price=price,
            seat=seat,
            date=date,
            payable=payable,
            user_id=user_id,
            content=content,
            event_id=event_id,
            category=category,
        )
        await msg.reply_text(f"学生票座位记录已创建成功！\nrepoID：{report_id}\n剧名: {title}\n类型: {category}\n日期: {date}\n座位: {seat}\n实付: {price}\n原价：{payable}\n描述: {content}\n感谢您的反馈！")
        
    @user_command_wrapper("get_repo")
    async def on_hulaquan_get_repo(self, msg: BaseMessage):
        args = self.extract_args(msg)
        if not args["text_args"]:
            if "-l" in args["mode_args"]:
                messages = Stats.get_repos_list()
                await msg.reply_text("\n".join(messages))
                return
            await msg.reply_text("请提供剧名，用法："+HLQ_GET_REPO_USAGE)
            return
        event_name = args["text_args"][0]
        event_price = args["text_args"][1] if len(args["text_args"]) > 1 else None
        event = await self.get_event_id_by_name(event_name, msg, foundInState=True)
        if not event:
            return
        event_id = event[0]
        event_title = event[1]
        result = Stats.get_event_student_seat_repo(event_id, event_price)
        if not result:
            await msg.reply_text(f"未找到剧目 {event_title} 的学生票座位记录，快来上传吧！")
            return
        await self.output_messages_by_pages(result, msg, page_size=10)

    @user_command_wrapper("report_error_repo")
    async def on_hulaquan_report_error(self, msg: BaseMessage):
        if isinstance(msg, GroupMessage):
            return
        args = self.extract_args(msg)
        if not args["text_args"]:
            await msg.reply_text("缺少参数！\n"+HLQ_REPORT_ERROR_USAGE)
            return
        report_id = args["text_args"][0]
        error_content = " ".join(args["text_args"][1:])
        if len(error_content) > 500:
            await msg.reply_text("错误反馈内容过长，请控制在500字以内。")
            return
        # 这里可以添加将错误反馈保存到数据库或发送给管理员的逻辑
        message = Stats.report_repo_error(report_id, msg.user_id)
        await msg.reply_text(f"{message}\n感谢您的反馈，我们会尽快处理！")
    
    @user_command_wrapper("my_repo")
    async def on_hulaquan_my_repo(self, msg: BaseMessage):
        if isinstance(msg, GroupMessage):
            return
        user_id = msg.user_id
        if User.is_op(user_id):
            args = self.extract_args(msg)
            user_id = args["text_args"][0] if args["text_args"] else user_id
        repos = Stats.get_users_repo(user_id)
        if not repos:
            await msg.reply_text("您还没有提交过任何学生票座位记录。")
            return
        await self.output_messages_by_pages(repos, msg, page_size=15)
        
    @user_command_wrapper("modify_repo")
    async def on_modify_self_repo(self, msg: BaseMessage):
        if isinstance(msg, GroupMessage):
            return
        
        match, mandatory_check = parse_text_to_dict_with_mandatory_check(msg.raw_message, HLQ_MODIFY_REPO_INPUT_DICT ,with_prefix=True)
        if mandatory_check:
            return await msg.reply_text(f"缺少以下必要字段：{' '.join(mandatory_check)}")
        repoID = match["repoID"]
        date = match["date"]
        seat = match["seat"]
        price = match["price"]
        content = match["content"]
        category = match["category"]
        payable = match["payable"]
        repos = Stats.modify_repo(
            msg.user_id,
            repoID, 
            date=date, 
            seat=seat, 
            price=price, 
            content=content, 
            category=category,
            payable=payable,
            isOP=User.is_op(msg.user_id)
        )
        if not repos:
            await msg.reply_text("未找到原记录或无修改权限，请输入/我的repo查看正确的repoID")
            return
        await msg.reply_text("修改成功！现repo如下：\n"+repos[0])
    
    @user_command_wrapper("del_repo")
    async def on_delete_self_repo(self, msg: BaseMessage):
        args = self.extract_args(msg)
        if not args["text_args"]:
            await msg.reply_text("需填写要删除的repoID\n")
            return
        messages = []
        for report_id in args["text_args"]:
            repo = Stats.del_repo(report_id.strip(), msg.user_id)
            if not repo:
                messages.append(f"{report_id}删除失败！未找到对应的repo或你不是这篇repo的主人。")
            else:
                messages.append("删除成功！原repo如下：\n"+repo[0])
        await msg.reply_text("\n".join(messages))
        
    @user_command_wrapper("latest_repos")
    async def on_get_latest_repos(self, msg: BaseMessage):
        args = self.extract_args(msg)
        count = 10
        if args["text_args"]:
            if args["text_args"][0] > maxLatestReposCount:
                return await msg.reply_text(f"数字必须小于{maxLatestReposCount}")
            else:
                count = int(args["text_args"][0])
        repos = Stats.show_latest_repos(count)
        if not repos:
            await msg.reply_text("暂无数据")
            return
        await self.output_messages_by_pages(repos, msg, page_size=15)
        


    async def output_messages_by_pages(self, messages, msg: BaseMessage, page_size=10):
        # 分页输出消息
        total_pages = (len(messages) + page_size - 1) // page_size
        for i in range(total_pages):
            start = i * page_size
            end = start + page_size
            page_messages = messages[start:end]
            await msg.reply_text("\n".join(page_messages))
            
    @user_command_wrapper("list_all_events")
    async def on_list_all_hulaquan_events(self, msg: BaseMessage):
        events = Hlq.data.get("events", {})
        if not events:
            await msg.reply_text("当前无呼啦圈事件数据。")
            return
        lines = []
        index = 1
        for eid, event in events.items():
            title = event.get("title", "未知剧名")
            lines.append(f"{index}. {title}")
            index += 1
        await self.output_messages_by_pages(lines, msg, page_size=40)
            
    @user_command_wrapper("follow_ticket")        
    async def on_follow_ticket(self, msg: BaseMessage):
        args = self.extract_args(msg)
        if not args["text_args"]:
            return await msg.reply_text(f"请提供场次id或剧目名，用法：\n{HLQ_FOLLOW_TICKET_USAGE}")
        mode_args = args["mode_args"]
        user_id = str(msg.user_id)
        target_values = {"-1", "-2", "-3"}

        # 检查模式
        setting_mode = next((item for item in mode_args if item in target_values), None)
        if not setting_mode:
            return await msg.reply_text("缺少指定的模式（命令需带有-1，-2，-3其中之一）：\n" + HLQ_FOLLOW_TICKET_USAGE)
        setting_mode = int(setting_mode[1])
        
        # 0. 按演员名关注（-A 模式）
        if "-a" in mode_args:
            actor_names = args["text_args"]
            
            # 解析剧目筛选参数
            include_events = None
            exclude_events = None
            for item in mode_args:
                if item.startswith('-i'):  # -I event1,event2
                    # 提取事件名列表
                    event_str = item[2:] if len(item) > 2 else ""
                    if event_str:
                        include_events = [e.strip() for e in event_str.split(',')]
                elif item.startswith('-x'):  # -X event1,event2
                    event_str = item[2:] if len(item) > 2 else ""
                    if event_str:
                        exclude_events = [e.strip() for e in event_str.split(',')]
            
            # 将事件名转换为事件ID
            include_eids = None
            exclude_eids = None
            if include_events:
                include_eids = []
                for e_name in include_events:
                    result = await self.get_event_id_by_name(e_name)
                    if result:
                        include_eids.append(result[0])
            if exclude_events:
                exclude_eids = []
                for e_name in exclude_events:
                    result = await self.get_event_id_by_name(e_name)
                    if result:
                        exclude_eids.append(result[0])
            
            # 为每个演员检索现有场次并关注
            total_tickets_added = 0
            actor_summary = []
            all_ticket_details = []  # 存储所有场次的详细信息
            
            for actor in actor_names:
                # 检索该演员的所有场次
                matched_tickets = await Hlq.find_tickets_by_actor_async(actor, include_eids, exclude_eids)
                ticket_ids = list(matched_tickets.keys())
                
                if ticket_ids:
                    # 检查哪些场次已关注
                    subscribed = User.subscribe_tickets(user_id)
                    subscribed_ids = {str(t['id']) for t in subscribed} if subscribed else set()
                    
                    new_tickets = []
                    existing_tickets = []
                    
                    for tid in ticket_ids:
                        tid_str = str(tid)
                        if tid_str in subscribed_ids:
                            # 场次已关注，添加演员关联
                            User.add_actor_to_ticket_relation(user_id, tid_str, actor)
                            existing_tickets.append(tid_str)
                        else:
                            # 新场次，添加时标记演员关联
                            new_tickets.append(tid_str)
                    
                    # 关注新场次（带演员关联）
                    if new_tickets:
                        User.add_ticket_subscribe(user_id, new_tickets, setting_mode, related_to_actors=[actor])
                    
                    total_tickets_added += len(new_tickets)
                    
                    # 统计信息
                    if new_tickets and existing_tickets:
                        actor_summary.append(f"{actor}(新增{len(new_tickets)}场，已关注{len(existing_tickets)}场)")
                    elif new_tickets:
                        actor_summary.append(f"{actor}({len(new_tickets)}场)")
                    else:
                        actor_summary.append(f"{actor}(0场新增，{len(existing_tickets)}场已关注)")
                    
                    # 收集所有关注的场次详细信息
                    for tid in ticket_ids:
                        event_id = matched_tickets[tid]
                        ticket = Hlq.ticket(tid, event_id)
                        if ticket:
                            ticket_info = await Hlq.build_single_ticket_info_str(
                                ticket, 
                                show_cast=True, 
                                city="上海", 
                                show_ticket_id=True
                            )
                            all_ticket_details.append(ticket_info[0])
                
                # 保存演员订阅（用于后续新排期匹配）
                User.add_actor_subscribe(user_id, [actor], setting_mode, include_eids, exclude_eids)
            
            # 构建输出消息
            txt = f"✅ 已为您关注以下演员的演出场次：\n{chr(10).join(actor_summary)}\n"
            if total_tickets_added > 0:
                txt += f"\n📊 共新增关注 {total_tickets_added} 个场次，有票务变动会提醒您。\n"
            if include_eids:
                txt += f"（仅关注指定剧目）\n"
            elif exclude_eids:
                txt += f"（已排除指定剧目）\n"
            txt += f"\n💡 当有新排期上架时，系统会自动补充关注这些演员的新场次。"
            
            # 添加场次详细信息
            if all_ticket_details:
                txt += f"\n\n{'='*30}\n📋 关注的场次详情：\n"
                txt += "\n".join(all_ticket_details)
            
            await msg.reply_text(txt)
            return
        
        # 1. 按场次ID关注
        if "-t" in mode_args:
            ticket_id_list = args["text_args"]
            ticket_id_list, denial = Hlq.verify_ticket_id(ticket_id_list)
            txt = ""
            if denial:
                txt += f"未找到以下场次id：{' '.join(denial)}\n"
            # 检查已关注
            already = []
            to_subscribe = []
            mode_updated = []
            subscribed = User.subscribe_tickets(user_id)
            subscribed_dict = {str(t['id']): str(t.get('mode', '')) for t in subscribed} if subscribed else {}
            for tid in ticket_id_list:
                tid_str = str(tid)
                if tid_str in subscribed_dict:
                    # 如果模式不同则更新
                    if subscribed_dict[tid_str] != setting_mode:
                        User.update_ticket_subscribe_mode(user_id, tid_str, setting_mode)
                        mode_updated.append(tid_str)
                    else:
                        already.append(tid_str)
                else:
                    to_subscribe.append(tid_str)
            if to_subscribe:
                User.add_ticket_subscribe(user_id, to_subscribe, setting_mode)
                txt += f"已成功关注以下场次,有票务变动会提醒您：{' '.join(to_subscribe)}\n"
            if mode_updated:
                txt += f"以下场次已关注，但已更新关注模式：{' '.join(mode_updated)}\n"
            if already:
                txt += f"以下场次已关注：{' '.join(already)}\n"
            if not to_subscribe and not already and not mode_updated:
                txt += "没有可关注的场次ID。\n"
            await msg.reply_text(txt.strip())
            return

        # 2. 按剧目名关注（-E 或默认）
        event_names = args["text_args"]
        
        # 检查是否为虚拟事件模式
        is_virtual_mode = "-v" in mode_args
        
        # 解析 -数字 参数用于多结果选择
        extra_id = None
        for item in mode_args:
            if item.startswith('-') and item[1:].isdigit():
                extra_id = int(item[1:])
                break
        
        no_response = []
        event_ids = []
        already_events = []
        to_subscribe_events = []
        mode_updated_events = []
        subscribed_events = User.subscribe_events(user_id)
        subscribed_eids_modes = {str(e['id']): str(e.get('mode', '')) for e in subscribed_events} if subscribed_events else {}
        for e in event_names:
            # 虚拟事件模式：直接创建虚拟事件ID
            if is_virtual_mode:
                virtual_id, is_new = Stats.register_virtual_event(e)
                eid = str(virtual_id)
                if is_new:
                    to_subscribe_events.append((eid, f"{e}(虚拟剧目)"))
                else:
                    # 检查是否已关注
                    if eid in subscribed_eids_modes:
                        if subscribed_eids_modes[eid] != setting_mode:
                            User.update_event_subscribe_mode(user_id, eid, setting_mode)
                            mode_updated_events.append(f"{e}(虚拟)")
                        else:
                            already_events.append(f"{e}(虚拟)")
                    else:
                        to_subscribe_events.append((eid, f"{e}(虚拟剧目)"))
                continue
            
            # 正常模式：查询呼啦圈系统
            result = await self.get_event_id_by_name(e, msg=msg, msg_prefix="", extra_id=extra_id)
            if not result:
                no_response.append(e)
                continue
            eid = str(result[0])
            event_ids.append(eid)
            if eid in subscribed_eids_modes:
                if subscribed_eids_modes[eid] != setting_mode:
                    User.update_event_subscribe_mode(user_id, eid, setting_mode)
                    mode_updated_events.append(e)
                else:
                    already_events.append(e)
            else:
                to_subscribe_events.append((eid, e))
        txt = "" if not no_response else f"未找到以下剧目：\n{chr(10).join(no_response)}\n\n"
        if to_subscribe_events:
            User.add_event_subscribe(user_id, [eid for eid, _ in to_subscribe_events], setting_mode)
            txt += f"已成功关注以下剧目,有票务变动会提醒您：\n{chr(10).join([e for _, e in to_subscribe_events])}\n"
        if mode_updated_events:
            txt += f"以下剧目已关注，但已更新关注模式：\n{chr(10).join(mode_updated_events)}\n"
        if already_events:
            txt += f"以下剧目已关注：\n{chr(10).join(already_events)}\n"
        if not to_subscribe_events and not already_events and not mode_updated_events:
            txt += "没有可关注的剧目。\n"
        await msg.reply_text(txt.strip())
    
    @user_command_wrapper("view_follow")
    async def on_view_follow(self, msg: BaseMessage):
        user_id = str(msg.user_id)
        events = User.subscribe_events(user_id)
        _tickets = User.subscribe_tickets(user_id)
        actors = User.subscribe_actors(user_id)
        lines = []
        MODES = ["模式0-不接受通知", "模式1-上新/补票", "模式2-上新/补票/回流", "模式3-上新/补票/回流/增减票"]
        lines.append(f"您目前对剧目的通用通知设置为：\n{MODES[int(User.attention_to_hulaquan(user_id))]}\n可通过/呼啦圈通知 模式编号修改")
        
        # 自动清理已过期的场次
        expired_tickets = []
        
        if events:
            lines.append("【关注的剧目】")
            i = 0
            for e in events:
                i += 1
                eid = str(e['id'])
                title = Hlq.title(event_id=eid, keep_brackets=True)
                lines.append(f"{i}.{title} {MODES[int(e['mode'])]}")
        
        if actors:
            lines.append("\n【关注的演员】")
            i = 0
            for a in actors:
                i += 1
                actor_name = a.get('actor', '')
                mode = int(a.get('mode', 1))
                include_events = a.get('include_events', [])
                exclude_events = a.get('exclude_events', [])
                
                filter_text = ""
                if include_events:
                    event_names = [Hlq.title(event_id=eid, keep_brackets=True) for eid in include_events]
                    filter_text = f" [仅关注: {', '.join(event_names)}]"
                elif exclude_events:
                    event_names = [Hlq.title(event_id=eid, keep_brackets=True) for eid in exclude_events]
                    filter_text = f" [排除: {', '.join(event_names)}]"
                
                lines.append(f"{i}.{actor_name} {MODES[mode]}{filter_text}")
        
        if _tickets:
            lines.append("\n【关注的场次】")
            tickets = sorted(_tickets, key=lambda x: int(x['id']))
            from itertools import groupby
            tickets = {
                key: sorted(list(group), key=lambda x: int(x['id']))
                for key, group in groupby(_tickets, key=lambda x: x['mode'])
            }
            for mode in tickets:
                lines.append(MODES[int(mode)])
                for t in tickets[mode]:
                    tid = str(t['id'])
                    try:
                        ticket = Hlq.ticket(tid, default=None)
                        if ticket is None:
                            # 场次已不存在（可能已过期或被删除）
                            lines.append(f"  ❌ [已过期] 场次ID: {tid}")
                            expired_tickets.append(tid)
                            continue
                        text = (await Hlq.build_single_ticket_info_str(ticket, show_cast=True, show_ticket_id=True))[0]
                        lines.append(text)
                    except (KeyError, Exception) as e:
                        # 捕获任何错误，显示友好提示
                        lines.append(f"  ⚠️ [无法获取] 场次ID: {tid}")
                        log.warning(f"获取场次 {tid} 信息失败: {e}")
        
        # 自动清理已过期的场次
        if expired_tickets:
            for tid in expired_tickets:
                User.remove_ticket_subscribe(user_id, tid)
            lines.append(f"\n✅ 已自动清理 {len(expired_tickets)} 个过期场次")
        
        if not events and not _tickets and not actors:
            await msg.reply_text("你还没有关注任何剧目、场次或演员。")
            return
        await self.output_messages_by_pages(lines, msg, page_size=40)

    async def on_unfollow_ticket(self, msg: BaseMessage):
        args = self.extract_args(msg)
        if not args["text_args"]:
            return await msg.reply_text(f"请提供场次id、剧目名或演员名，用法：\n{HLQ_UNFOLLOW_TICKET_USAGE}")
        mode_args = args["mode_args"]
        user_id = str(msg.user_id)
        
        # 0. 按演员名取消关注（-A 模式）
        if "-a" in mode_args:
            actor_names = args["text_args"]
            removed = []
            not_found = []
            tickets_removed_summary = []
            
            actors = User.subscribe_actors(user_id)
            subscribed_actors_lower = {a.get('actor', '').strip().lower() for a in actors} if actors else set()
            
            for actor in actor_names:
                actor_lower = actor.strip().lower()
                if actor_lower in subscribed_actors_lower:
                    # 移除演员订阅并清理关联场次
                    result = User.remove_actor_subscribe(user_id, actor)
                    removed.append(actor)
                    
                    # 记录清理的场次数量
                    if result['tickets_removed'] > 0:
                        tickets_removed_summary.append(f"{actor}({result['tickets_removed']}场)")
                else:
                    not_found.append(actor)
            
            txt = ""
            if removed:
                txt += f"✅ 已取消关注以下演员：{' '.join(removed)}\n"
                if tickets_removed_summary:
                    txt += f"🎫 同时移除了因关注演员而关注的场次：\n{chr(10).join(tickets_removed_summary)}\n"
                    txt += "💡 提示：仅移除了因关注这些演员而自动关注的场次，手动关注的场次保留。"
                else:
                    txt += "💡 提示：未移除任何场次（可能这些演员的场次是手动关注的，或与其他演员共享）。"
            if not_found:
                txt += f"\n❌ 以下演员未关注：{' '.join(not_found)}"
            await msg.reply_text(txt.strip())
            return
        
        # 1. 按场次ID取消关注
        if "-t" in mode_args:
            ticket_id_list = args["text_args"]
            ticket_id_list, denial = Hlq.verify_ticket_id(ticket_id_list)
            txt = ""
            if denial:
                txt += f"未找到以下场次id：{' '.join(denial)}\n"
            removed = []
            not_found = []
            tickets = User.subscribe_tickets(user_id)
            tickets_ids = {str(t['id']) for t in tickets} if tickets else set()
            for tid in ticket_id_list:
                if str(tid) in tickets_ids:
                    User.remove_ticket_subscribe(user_id, str(tid))
                    removed.append(str(tid))
                else:
                    not_found.append(str(tid))
            if removed:
                txt += f"已取消关注以下场次：{' '.join(removed)}\n"
            if not_found:
                txt += f"以下场次未关注：{' '.join(not_found)}\n"
            await msg.reply_text(txt.strip())
            return
        # 2. 按剧目名取消关注（-E 或默认）
        event_names = args["text_args"]
        no_response = []
        removed_events = []
        not_found_events = []
        events = User.subscribe_events(user_id)
        events_ids = {str(e['id']) for e in events} if events else set()
        for e in event_names:
            result = await self.get_event_id_by_name(e)
            if not result:
                no_response.append(e)
                continue
            eid = str(result[0])
            if eid in events_ids:
                User.remove_event_subscribe(user_id, eid)
                removed_events.append(e)
            else:
                not_found_events.append(e)
        txt = "" if not no_response else f"未找到以下剧目：\n{chr(10).join(no_response)}\n\n"
        if removed_events:
            txt += f"已取消关注以下剧目：\n{chr(10).join(removed_events)}\n"
        if not_found_events:
            txt += f"以下剧目未关注：\n{chr(10).join(not_found_events)}\n"
        await msg.reply_text(txt.strip())
    
    @user_command_wrapper("debug_announcer")
    async def on_debug_announcer(self, msg: BaseMessage):
        """调试上新通知功能"""
        from plugins.Hulaquan.debug_announcer import AnnouncerDebugger
        
        args = self.extract_args(msg)
        command = args["text_args"][0] if args["text_args"] else "help"
        
        debugger = AnnouncerDebugger(self)
        
        if command == "check":
            # 检查任务状态
            info = []
            info.append("⏰ 定时任务状态：")
            info.append(f"运行状态: {'✅ 运行中' if self._hulaquan_announcer_running else '❌ 已停止'}")
            info.append(f"检测间隔: {self._hulaquan_announcer_interval} 秒")
            if self._hulaquan_announcer_task:
                info.append(f"任务完成: {'是' if self._hulaquan_announcer_task.done() else '否'}")
            await msg.reply_text("\n".join(info))
            
        elif command == "user":
            # 查看用户设置
            user_id = str(msg.user_id)
            user = User.get_user(user_id)
            if not user:
                await msg.reply_text(f"❌ 用户 {user_id} 不存在")
                return
            
            info = []
            info.append(f"👤 用户 {user_id} 的关注设置：")
            
            all_mode = user.get("attention_to_hulaquan", 0)
            mode_desc = {
                0: "❌ 不接受通知",
                1: "🆕 只推送上新/补票",
                2: "🆕🔄 上新/补票/回流",
                3: "🆕🔄📊 上新/补票/回流/增减票"
            }
            info.append(f"全局模式: {mode_desc.get(int(all_mode), '未知')}")
            
            events = User.subscribe_events(user_id)
            if events:
                info.append(f"\n📋 关注的剧目 ({len(events)}个):")
                for event in events[:5]:  # 只显示前5个
                    info.append(f"  EventID: {event['id']}, 模式: {event.get('mode', 'N/A')}")
                if len(events) > 5:
                    info.append(f"  ... 还有 {len(events)-5} 个")
            else:
                info.append("\n📋 关注的剧目: 无")
            
            tickets = User.subscribe_tickets(user_id)
            if tickets:
                info.append(f"\n🎫 关注的场次 ({len(tickets)}个):")
                for ticket in tickets[:5]:
                    info.append(f"  TicketID: {ticket['id']}, 模式: {ticket.get('mode', 'N/A')}")
                if len(tickets) > 5:
                    info.append(f"  ... 还有 {len(tickets)-5} 个")
            else:
                info.append("\n🎫 关注的场次: 无")
            
            await msg.reply_text("\n".join(info))
            
        elif command == "mock":
            # 测试模拟数据
            await msg.reply_text("🧪 开始模拟上新通知测试...")
            
            # 创建模拟数据
            mock_tickets = [
                debugger.create_mock_ticket("99001", "9001", "new", "测试剧目A", "2025-10-20", "A区1排1座", "100"),
                debugger.create_mock_ticket("99002", "9001", "new", "测试剧目A", "2025-10-21", "A区1排2座", "100"),
                debugger.create_mock_ticket("99003", "9002", "add", "测试剧目B", "2025-10-22", "B区2排1座", "150"),
                debugger.create_mock_ticket("99004", "9003", "return", "测试剧目C", "2025-10-23", "C区3排1座", "200"),
            ]
            
            mock_result = debugger.create_mock_result(mock_tickets)
            
            # 测试消息生成
            user_id = str(msg.user_id)
            messages = debugger.test_generate_announce_text(mock_result, user_id)
            
            if not messages:
                await msg.reply_text(
                    "⚠️ 没有生成任何消息！\n\n"
                    "可能的原因：\n"
                    "1. 你的全局模式为0（不接受通知）\n"
                    "2. 你没有关注相关剧目/场次\n"
                    "3. 票务变动类型不在你的关注范围内\n\n"
                    "请使用 /debug通知 user 查看你的设置"
                )
            else:
                result_info = [
                    f"✅ 成功生成 {len(messages)} 组消息",
                    f"\n模拟数据统计：",
                    f"- 上新: {len(mock_result['categorized']['new'])} 张",
                    f"- 补票: {len(mock_result['categorized']['add'])} 张",
                    f"- 回流: {len(mock_result['categorized']['return'])} 张",
                    f"\n以下是生成的消息预览："
                ]
                await msg.reply_text("\n".join(result_info))
                
                # 发送生成的消息预览
                for idx, msg_group in enumerate(messages[:2], 1):  # 只发送前2组
                    preview = "\n\n".join(msg_group)
                    await msg.reply_text(f"【消息组 #{idx}】\n{preview}")
                
                if len(messages) > 2:
                    await msg.reply_text(f"... 还有 {len(messages)-2} 组消息未显示")
        
        elif command == "log":
            # 查看最近的日志
            await msg.reply_text("📋 查看日志功能开发中...")
            
        else:
            # 帮助信息
            help_text = """
🔍 呼啦圈上新通知调试工具

可用命令：
/debug通知 check - 检查定时任务状态
/debug通知 user - 查看你的关注设置
/debug通知 mock - 使用模拟数据测试通知

调试步骤建议：
1. 先用 check 确认定时任务是否运行
2. 用 user 查看你的关注模式是否正确
3. 用 mock 测试消息生成逻辑
4. 如果 mock 没有生成消息，说明你的模式设置有问题
5. 如果 mock 能生成消息，但实际没收到，说明数据比对或发送环节有问题
"""
            await msg.reply_text(help_text)