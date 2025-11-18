"""System updater plugin that now consumes the compat context for auth checks."""

import asyncio
import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from ncatbot.plugin import BasePlugin, CompatibleEnrollment
from ncatbot.core import BaseMessage

from services.compat import CompatContext, get_default_context

# 兼容回调函数注册器（与项目其它插件保持一致风格）
bot = CompatibleEnrollment


def _repo_root() -> Path:
    # plugins/SystemUpdater/main.py -> repo root two levels up
    return Path(__file__).resolve().parents[2]


def _python_exec(repo: Path) -> str:
    venv_py = repo / "env" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return "python3"


def _log_file(repo: Path) -> Path:
    log_dir = repo / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "self_update.log"


def _is_op_safe(user_id: str, context: CompatContext | None = None) -> bool:
    """Check admin privileges via the compat context (fallback to env vars)."""

    compat = context or get_default_context()
    try:
        users = compat.users
        return users.is_op(str(user_id))  # type: ignore[attr-defined]
    except Exception:
        ops = os.environ.get("SYSUPDATER_OPS", "").split(",")
        ops = [x.strip() for x in ops if x.strip()]
        return str(user_id) in ops


def _parse_args(text: str) -> Tuple[bool, Optional[str]]:
    # Extract flags after prefix
    try:
        parts = shlex.split(text)
    except Exception:
        parts = text.split()
    # drop command token
    if parts and parts[0].startswith("/sys-update"):
        parts = parts[1:]
    napcat = False
    qq: Optional[str] = None
    i = 0
    while i < len(parts):
        p = parts[i]
        if p == "--napcat":
            napcat = True
            if i + 1 < len(parts) and parts[i + 1].isdigit():
                qq = parts[i + 1]
                i += 1
        i += 1
    return napcat, qq


def _detect_qq(repo: Path) -> Optional[str]:
    for k in ("BOT_QQ", "NCAT_BOT_QQ", "BOT_UIN"):
        v = os.environ.get(k)
        if v and v.isdigit():
            return v
    cfg = repo / "napcat" / "config"
    if cfg.is_dir():
        for p in cfg.iterdir():
            digits = "".join(ch for ch in p.name if ch.isdigit())
            if digits:
                return digits
    return None


def _bash_script(repo: Path, parent_pid: int, napcat: bool, qq: Optional[str]) -> str:
        log = _log_file(repo)
        main_py = repo / "main.py"
        py = _python_exec(repo)
        status = repo / "logs" / "self_update.status"

        header = f"""
set -e
(
    while kill -0 {parent_pid} 2>/dev/null; do sleep 0.5; done
) || true
cd {shlex.quote(str(repo))}
TS=$(date '+%Y-%m-%d %H:%M:%S')
echo "==== $TS: updater start (napcat={str(napcat).lower()}) ====" >> {shlex.quote(str(log))} 2>&1
STATUS_FILE={shlex.quote(str(status))}
rm -f "$STATUS_FILE" 2>/dev/null || true
""".strip()

        if napcat:
                qq_arg = f" {shlex.quote(qq)}" if qq else ""
                body = f"""
# NapCat mode: no git, only napcat restart then bot
{{ napcat restart{qq_arg} ; }} >> {shlex.quote(str(log))} 2>&1 || echo "[WARN] napcat restart failed" >> {shlex.quote(str(log))}
# 状态记录（napcat 执行结果无法可靠判定，这里仅标注模式）
echo "NAPCAT_MODE" > "$STATUS_FILE"
# 前台运行机器人（输出同时到终端和日志，可用 Ctrl+C 退出）
{shlex.quote(py)} {shlex.quote(str(main_py))} 2>&1 | tee -a {shlex.quote(str(log))}
""".strip()
        else:
                body = f"""
# Normal mode: git ff-only pull main; timeout and conflicts tolerated (skip update)
GIT_TIMEOUT=30
{{ git --version ; }} >> {shlex.quote(str(log))} 2>&1 || echo "[WARN] git not found" >> {shlex.quote(str(log))}
if timeout $GIT_TIMEOUT git fetch origin >> {shlex.quote(str(log))} 2>&1 ; then
        echo "[INFO] git fetch ok" >> {shlex.quote(str(log))}
else
        echo "TIMEOUT_FETCH" > "$STATUS_FILE"
        echo "[WARN] git fetch timeout/fail" >> {shlex.quote(str(log))}
fi
if git rev-parse --verify main >/dev/null 2>&1; then
    echo "[INFO] pulling ff-only origin/main (timeout=$GIT_TIMEOUT s)" >> {shlex.quote(str(log))}
    if timeout $GIT_TIMEOUT git pull --ff-only origin main >> {shlex.quote(str(log))} 2>&1; then
        echo "[INFO] git pull success" >> {shlex.quote(str(log))}
        echo "OK" > "$STATUS_FILE"
    else
        echo "PULL_FAIL_OR_CONFLICT" > "$STATUS_FILE"
        echo "[WARN] git pull timeout/fail or conflict; skip update" >> {shlex.quote(str(log))}
    fi
else
    echo "[WARN] local branch 'main' missing; skip update" >> {shlex.quote(str(log))}
    echo "NO_LOCAL_MAIN" > "$STATUS_FILE"
fi
# 前台运行机器人（输出同时到终端和日志，可用 Ctrl+C 退出）
{shlex.quote(py)} {shlex.quote(str(main_py))} 2>&1 | tee -a {shlex.quote(str(log))}
""".strip()

        return header + "\n" + body + "\n"


class SystemUpdater(BasePlugin):
    name = "SystemUpdater"
    version = "0.1.0"
    author = "摇摇杯"
    info = "系统自更新与重启：/sys-update 与 --napcat 模式"
    dependencies = {}

    def __init__(self, *args, compat_context: CompatContext | None = None, **kwargs):
        self.compat_context = compat_context or get_default_context()
        super().__init__(*args, **kwargs)

    async def on_load(self):
        # 模仿现有插件的注册风格，补充描述/用法/示例
        self.register_admin_func(
            name="系统更新与重启（管理员）",
            handler=self._on_sys_update,
            prefix="/sys-update",
            description="退出后后台执行自更新并重启；或使用 --napcat [QQ] 先重启 NapCat 再重启机器人（不做 git）",
            usage="/sys-update | /sys-update --napcat [QQ]",
            examples=["/sys-update", "/sys-update --napcat 123456"],
            metadata={"category": "system"}
        )

    async def on_unload(self):
        print(f"{self.name} 插件已卸载")

    async def _on_sys_update(self, msg: BaseMessage):
        # 权限校验
        if not _is_op_safe(str(msg.user_id), self.compat_context):
            await msg.reply("权限不足：仅管理员可用 /sys-update")
            return

        text = getattr(msg, "text", "") or getattr(msg, "raw_message", "") or ""
        text = text.strip()
        napcat, qq_cli = _parse_args(text)

        repo = _repo_root()
        log = _log_file(repo)
        qq_final = _detect_qq(repo) if napcat and not qq_cli else qq_cli

        script = _bash_script(repo, os.getpid(), napcat, qq_final)
        script_path = repo / "logs" / "self_update.sh"
        try:
            script_path.write_text(script, encoding="utf-8")
        except Exception:
            _log_file(repo)
            script_path.write_text(script, encoding="utf-8")

        # 后台启动
        cmd = [
            "bash", "-lc",
            f"nohup bash {shlex.quote(str(script_path))} >> {shlex.quote(str(log))} 2>&1 & disown"
        ]
        try:
            subprocess.Popen(cmd, cwd=str(repo))
        except Exception as e:
            await msg.reply(f"启动更新器失败: {e}")
            return

        if napcat:
            if qq_final:
                await msg.reply(f"已开始 NapCat 重启（QQ={qq_final}），随后重启机器人。即将安全退出…")
            else:
                await msg.reply("已开始 NapCat 重启（未能自动识别QQ，将尝试默认），随后重启机器人。即将安全退出…")
        else:
            await msg.reply("已开始后台更新 main 分支（若超时或冲突将跳过），随后重启机器人。即将安全退出…")

        # 稍等以确保消息发送完成，然后优雅退出（触发 on_close）
        await asyncio.sleep(0.5)
        try:
            import signal
            # 优先 SIGTERM（更安静，不产生 KeyboardInterrupt 痕迹）
            os.kill(os.getpid(), signal.SIGTERM)
        except Exception:
            # 回退方案：抛出 SystemExit，让上层框架捕获并触发关闭流程
            raise SystemExit(0)
