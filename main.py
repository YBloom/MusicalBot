# ========= 导入必要模块 ==========
from ncatbot.core import BotClient, GroupMessage, PrivateMessage, BaseMessage
from ncatbot.utils import get_log
from ncatbot.adapter import Route
import os
import asyncio
import subprocess


# ========== 创建 BotClient ==========
bot = BotClient()
_log = get_log()

HELLOWORDS = ["哈咯","Hi","测试","哈喽","Hello","剧剧"]
VERSION = "1.0"
bot_qq = "3044829389"

# ========= 注册回调函数 ==========
@bot.group_event()
async def on_group_message(msg: GroupMessage):
    if int(msg.user_id) != int(bot_qq):
        _log.info(msg)

@bot.private_event()
async def on_private_message(msg: PrivateMessage):
    if int(msg.user_id) != int(bot_qq):
        _log.info(msg)
        

# ========== 启动 BotClient==========

if __name__ == "__main__":
    from ncatbot.utils import config
    # 设置 WebSocket 令牌
    #config.set_ws_token("ncatbot_ws_token")

    # Optimize NapCat OB11 configs without modifying dependencies
    try:
        from ncatbot.adapter.nc.install import get_napcat_dir
        import json, os
        import ncatbot.adapter.nc.start as nc_start
        _orig_config_napcat = nc_start.config_napcat

        def _patched_config_napcat():
            _orig_config_napcat()
            napcat_dir = get_napcat_dir()
            ob11_path = os.path.join(napcat_dir, "config", f"onebot11_{bot_qq}.json")
            try:
                with open(ob11_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                ws = data.setdefault("network", {}).setdefault("websocketServers", [{}])[0]
                ws["messagePostFormat"] = "array"
                ws["reportSelfMessage"] = False
                ws["heartInterval"] = 10000
                ws["reconnectInterval"] = 3000
                with open(ob11_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
            except Exception:
                pass
            # Enable file logging
            try:
                napcat_json = os.path.join(napcat_dir, "config", "napcat.json")
                if os.path.exists(napcat_json):
                    with open(napcat_json, "r", encoding="utf-8") as f:
                        ndata = json.load(f)
                else:
                    ndata = {}
                ndata["fileLog"] = True
                with open(napcat_json, "w", encoding="utf-8") as f:
                    json.dump(ndata, f, ensure_ascii=False, indent=4)
            except Exception:
                pass

        nc_start.config_napcat = _patched_config_napcat
        # Apply once immediately to avoid relying on internal calls
        _patched_config_napcat()
    except Exception:
        pass

    # Hook Route.post to catch NapCat send failures (retcode=1200 + "网络连接异常") and trigger system restart
    try:
        if hasattr(Route, "post"):
            _orig_route_post = Route.post

            async def _patched_route_post(self, *args, **kwargs):
                res = await _orig_route_post(self, *args, **kwargs)
                if isinstance(res, dict):
                    retcode = res.get("retcode")
                    msg = res.get("msg") or res.get("wording") or res.get("message") or ""
                    if str(retcode) == "1200" and "网络连接异常" in str(msg):
                        restart_cmd = os.environ.get("NAPCAT_RESTART_CMD", "systemctl restart napcat")
                        _log.warning("[auto-restart] detected send failure, executing: %s", restart_cmd)
                        try:
                            subprocess.Popen(
                                restart_cmd,
                                shell=True,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            # brief backoff to avoid rapid-fire restarts
                            await asyncio.sleep(3)
                        except Exception as e:
                            _log.error("[auto-restart] restart command failed: %s", e)
                return res

            Route.post = _patched_route_post
            _log.warning("[auto-restart] Route.post hooked for NapCat send failures")
        else:
            _log.warning("[auto-restart] Route.post not found; restart hook not installed")
    except Exception as e:
        _log.error("[auto-restart] failed to hook Route.post: %s", e)

    bot.run(bt_uin=bot_qq, root="3022402752", enable_webui_interaction=False) # 这里写 Bot 的 QQ 号