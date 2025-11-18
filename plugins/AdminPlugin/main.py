"""Administrative commands that rely on the compat facade for state access.

The module now consumes :class:`services.compat.CompatContext` so that unit
tests or future service layers can inject SQLite-backed implementations.  When
no context is provided the plugin falls back to ``get_default_context`` which
wraps the legacy JSON ``UsersManager`` singleton.
"""

import os
import html

from ncatbot.plugin import BasePlugin, CompatibleEnrollment, Event
from ncatbot.core import GroupMessage, PrivateMessage, BaseMessage
from ncatbot.utils.logger import get_log

from services.compat import CompatContext, get_default_context

bot = CompatibleEnrollment  # 兼容回调函数注册器
log = get_log()

class AdminPlugin(BasePlugin):
    name = "AdminPlugin"  # 插件名称
    version = "0.0.1"  # 插件版本
    author = "摇摇杯"  # 插件作者
    info = "Users Administration"  # 插件描述
    dependencies = {}  # 插件依赖，格式: {"插件名": "版本要求"}

    def __init__(self, *args, compat_context: CompatContext | None = None, **kwargs):
        self.compat_context = compat_context or get_default_context()
        super().__init__(*args, **kwargs)

    async def on_load(self):
        # 插件加载时执行的操作
        print(f"{self.name} 插件已加载")
        print(f"插件版本: {self.version}")
        self.data.setdefault("ops_list", [])
        # 注册功能示例
        self.users_manager = self.compat_context.users

        self.register_admin_func(
            name="op",
            handler=self._on_add_op,
            prefix="/op",
            description="op",
            usage="/op",
            examples=["/op xxxxx"],
            tags=["op"],
            metadata={"category": "utility"}
        )
        
        self.register_admin_func(
            name="exec",
            handler=self._on_execute,
            prefix="/exec",
            description="exec",
            usage="/exec",
            examples=["/exec xxxxx"],
            tags=["exec"],
            metadata={"category": "utility"}
        )
        
        self.register_admin_func(
            name="debug",
            handler=self._on_debug,
            prefix="/debug",
            description="debug",
            usage="/debug",
            examples=["/debug xxxxx"],
            tags=["debug"],
            metadata={"category": "utility"}
        )
        
        self.register_admin_func(
            name="deop",
            handler=self._on_de_op,
            prefix="/deop",
            description="deop",
            usage="/deop",
            examples=["/deop xxxxx"],
            tags=["deop"],
            metadata={"category": "utility"}
        )
        
        self.register_admin_func(
            name="群发",
            handler=self._on_global_message,
            prefix="/群发",
            description="群发",
            usage="/群发",
            examples=["/群发 xxxxx"],
            tags=["群发"],
            metadata={"category": "utility"}
        )

    async def add_send_managers_task(self, data=None):
        self.add_scheduled_task(
            job_func=self.on_send_pass_managers_event, 
            name=f"send_pass_managers_event", 
            interval="1s", 
            #max_runs=10, 
            conditions=[lambda: not self.is_all_plugins_get_managers()]
        )
    async def on_send_pass_managers_event(self):
        await self._event_bus.publish_async(self.pass_managers_event)
        
    async def _on_global_message(self, msg:BaseMessage):
        message = msg.split(" ")[1]
        for i in self.users_manager.users():
            await self.api.post_private_msg(i, message)
        await msg.reply("群发成功")
        
    async def _on_execute(self, msg: BaseMessage):
        cmd = msg.raw_message.replace("/exec ", "")
        cmd = html.unescape(cmd)  # 解码HTML实体
        try:
            exec(cmd)
            await msg.reply(f"命令执行了")
        except Exception as e:
            await msg.reply(f"命令执行失败：{str(e)}")
            
    async def _on_debug(self, msg: BaseMessage):
        cmd = msg.raw_message.replace("/debug ", "")
        cmd = html.unescape(cmd)  # 解码HTML实体
        print(f"Debugging command: {cmd}")
        try:
            print(eval(cmd))
        except Exception as e:
            print(f"命令执行失败：{str(e)}")
        
    async def _on_add_op(self, msg: BaseMessage):
        command = msg.raw_message.split(" ")
        if len(command) < 2:
            await msg.reply(f"需输入目标账号")
            return
        user_id = command[1]
        self.data["ops_list"].append(user_id)
        if self.users_manager.add_op(user_id):
            await msg.reply(f"已成功赋予用户{user_id}管理员权限。")
        else:
            await msg.reply(f"赋权失败！用户{user_id}已经拥有管理员权限。")
    
        
        
        
    async def _on_de_op(self, msg: BaseMessage):
        command = msg.raw_message.split(" ")
        if len(command) < 2:
            await msg.reply(f"需输入目标账号")
            return
        user_id = command[1]
        
        if self.users_manager.de_op(user_id):
            await msg.reply(f"已成功撤销用户{user_id}的管理员权限。")
        else:
            await msg.reply(f"撤销失败！用户{user_id}无管理员权限。")
            

        
            
            
    @bot.private_event()
    async def on_private_message(self, msg: PrivateMessage):
        self.users_manager.add_user(msg.user_id)
        self.users_manager.add_chats_count(msg.user_id)
            
    @bot.request_event()
    async def handle_request(self, msg):
        comment = msg.comment
        if msg.is_friend_add(): 
            await msg.reply(True)
        else:
            await msg.reply(True)
            

        
    async def on_unload(self):
        print(f"{self.name} 插件已卸载")
    
