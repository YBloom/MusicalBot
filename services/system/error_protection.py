"""
错误报告防护模块
防止错误报告本身触发新错误导致死循环
"""
import asyncio
import time
import traceback
from collections import deque
from typing import Optional
from ncatbot.utils.logger import get_log

log = get_log()


class ErrorReportThrottle:
    """错误报告节流器 - 防止死循环"""
    
    def __init__(
        self,
        max_errors_per_minute: int = 5,
        max_same_error_count: int = 3,
        cooldown_seconds: int = 300  # 冷却期5分钟
    ):
        self.max_errors_per_minute = max_errors_per_minute
        self.max_same_error_count = max_same_error_count
        self.cooldown_seconds = cooldown_seconds
        
        # 错误时间戳队列(用于计数)
        self.error_timestamps = deque(maxlen=100)
        
        # 相同错误计数器 {error_signature: (count, first_time)}
        self.error_signatures = {}
        
        # 冷却状态
        self.in_cooldown = False
        self.cooldown_start_time = 0
        
        # 待发送的错误队列(冷却期间积累)
        self.pending_errors = deque(maxlen=10)
    
    def _get_error_signature(self, error: Exception, context: str = "") -> str:
        """生成错误签名(用于去重)"""
        error_type = type(error).__name__
        error_msg = str(error)[:100]  # 只取前100字符
        return f"{context}:{error_type}:{error_msg}"
    
    def should_report(self, error: Exception, context: str = "") -> tuple[bool, str]:
        """
        判断是否应该报告此错误
        
        Returns:
            (should_report: bool, reason: str)
        """
        current_time = time.time()
        
        # 1. 检查冷却期
        if self.in_cooldown:
            if current_time - self.cooldown_start_time < self.cooldown_seconds:
                return False, "错误报告冷却中"
            else:
                # 冷却期结束
                self.in_cooldown = False
                self.error_signatures.clear()
                log.info("✅ 错误报告冷却期结束")
        
        # 2. 检查每分钟错误数
        # 移除1分钟前的时间戳
        while self.error_timestamps and current_time - self.error_timestamps[0] > 60:
            self.error_timestamps.popleft()
        
        if len(self.error_timestamps) >= self.max_errors_per_minute:
            self._enter_cooldown("每分钟错误数超限")
            return False, f"错误频率过高(>{self.max_errors_per_minute}/分钟)"
        
        # 3. 检查相同错误重复次数
        signature = self._get_error_signature(error, context)
        
        if signature in self.error_signatures:
            count, first_time = self.error_signatures[signature]
            self.error_signatures[signature] = (count + 1, first_time)
            
            if count + 1 >= self.max_same_error_count:
                self._enter_cooldown(f"相同错误重复{count + 1}次")
                return False, f"相同错误重复过多({count + 1}次)"
        else:
            self.error_signatures[signature] = (1, current_time)
        
        # 4. 记录此次错误
        self.error_timestamps.append(current_time)
        
        return True, "允许报告"
    
    def _enter_cooldown(self, reason: str):
        """进入冷却期"""
        if not self.in_cooldown:
            self.in_cooldown = True
            self.cooldown_start_time = time.time()
            log.warning(f"⚠️ 错误报告进入冷却期({self.cooldown_seconds}秒): {reason}")


# 全局节流器实例
error_throttle = ErrorReportThrottle()


async def safe_send_error_notification(
    api,
    admin_id: str,
    error: Exception,
    context: str = "",
    include_traceback: bool = True
) -> bool:
    """
    安全地发送错误通知(带死循环防护)
    
    Returns:
        bool: 是否成功发送
    """
    
    # 1. 节流检查
    should_report, reason = error_throttle.should_report(error, context)
    if not should_report:
        log.debug(f"跳过错误报告: {reason}")
        return False
    
    # 2. 构建错误消息
    error_msg = f"❌ 系统错误\n"
    error_msg += f"上下文: {context}\n" if context else ""
    error_msg += f"错误类型: {type(error).__name__}\n"
    error_msg += f"错误信息: {str(error)}\n"
    
    if include_traceback:
        tb = traceback.format_exc()
        # 截断过长的traceback
        if len(tb) > 500:
            tb = tb[:250] + "\n...(省略)...\n" + tb[-250:]
        error_msg += f"\n堆栈:\n{tb}"
    
    # 3. 尝试发送(带超时保护)
    try:
        result = await asyncio.wait_for(
            api.post_private_msg(admin_id, error_msg),
            timeout=10  # 10秒超时
        )
        
        if result.get('retcode') == 0:
            return True
        else:
            log.error(f"错误通知发送失败: retcode={result.get('retcode')}")
            return False
    
    except asyncio.TimeoutError:
        log.error("错误通知发送超时")
        return False
    
    except Exception as e:
        # 发送错误通知本身失败,只记录日志,不再尝试发送
        log.error(f"错误通知发送异常: {e}")
        return False
