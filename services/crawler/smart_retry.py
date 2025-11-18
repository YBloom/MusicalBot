"""
智能重试策略模块 - 模拟"幸运用户"行为
解决高负载服务器的概率性访问问题

核心思想:
1. 指数退避 + 随机抖动 - 避免"机器人特征"
2. 概率性重试 - 模拟人类的"放弃"行为
3. 时间窗口限制 - 避免无限重试
4. 动态调整 - 根据成功率自适应
"""

import asyncio
import random
import time
from typing import Optional, Callable, Any, Dict
from dataclasses import dataclass
from enum import Enum
import logging

log = logging.getLogger(__name__)


class RetryStrategy(Enum):
    """重试策略类型"""
    EXPONENTIAL_BACKOFF = "exponential"  # 指数退避
    FIBONACCI = "fibonacci"               # 斐波那契
    LINEAR_JITTER = "linear_jitter"      # 线性抖动
    LUCKY_USER = "lucky_user"            # 幸运用户模式(推荐)


@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 10                # 最大重试次数
    base_delay: float = 1.0              # 基础延迟(秒)
    max_delay: float = 60.0              # 最大延迟(秒)
    jitter_factor: float = 0.5           # 抖动系数(0-1)
    exponential_base: float = 2.0        # 指数基数
    timeout: float = 300.0               # 总超时时间(秒)
    
    # 概率性放弃参数
    give_up_probability: float = 0.15    # 每次失败后的放弃概率
    patience_threshold: int = 5          # 耐心阈值(连续失败多少次后增加放弃概率)
    
    # 成功率自适应
    adaptive: bool = True                # 是否启用自适应
    success_rate_window: int = 100       # 成功率统计窗口


class SmartRetryManager:
    """智能重试管理器"""
    
    def __init__(self, config: Optional[RetryConfig] = None):
        self.config = config or RetryConfig()
        
        # 统计数据
        self.total_attempts = 0
        self.total_successes = 0
        self.recent_results = []  # 最近的成功/失败记录
        
        # 自适应参数
        self.current_base_delay = self.config.base_delay
        self.current_give_up_prob = self.config.give_up_probability
    
    def calculate_delay(
        self, 
        attempt: int, 
        strategy: RetryStrategy = RetryStrategy.LUCKY_USER
    ) -> float:
        """
        计算下次重试的延迟时间
        
        Args:
            attempt: 当前是第几次尝试(从1开始)
            strategy: 重试策略
        
        Returns:
            延迟秒数
        """
        
        if strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            # 标准指数退避
            delay = min(
                self.current_base_delay * (self.config.exponential_base ** (attempt - 1)),
                self.config.max_delay
            )
        
        elif strategy == RetryStrategy.FIBONACCI:
            # 斐波那契退避
            fib = self._fibonacci(attempt)
            delay = min(
                self.current_base_delay * fib,
                self.config.max_delay
            )
        
        elif strategy == RetryStrategy.LINEAR_JITTER:
            # 线性抖动
            delay = min(
                self.current_base_delay * attempt,
                self.config.max_delay
            )
        
        elif strategy == RetryStrategy.LUCKY_USER:
            # 幸运用户模式(推荐) - 模拟真实用户的重试行为
            # 1. 基础延迟随尝试次数缓慢增长
            base = self.current_base_delay * (1 + (attempt - 1) * 0.3)
            
            # 2. 添加随机性"犹豫"时间(人类不会精确定时重试)
            human_hesitation = random.uniform(0.5, 3.0)
            
            # 3. 偶尔的"耐心爆发"(人类可能等更久)
            if random.random() < 0.1:  # 10%概率
                patience_bonus = random.uniform(5.0, 15.0)
            else:
                patience_bonus = 0
            
            delay = min(
                base + human_hesitation + patience_bonus,
                self.config.max_delay
            )
        
        else:
            delay = self.current_base_delay
        
        # 添加抖动(避免"整齐"的重试模式)
        jitter = delay * self.config.jitter_factor * (random.random() - 0.5)
        final_delay = max(0.1, delay + jitter)  # 至少0.1秒
        
        return final_delay
    
    def should_give_up(self, consecutive_failures: int) -> bool:
        """
        判断是否应该放弃重试(模拟人类的"算了,不试了"行为)
        
        Args:
            consecutive_failures: 连续失败次数
        
        Returns:
            True表示放弃,False表示继续
        """
        # 1. 基础放弃概率
        base_prob = self.current_give_up_prob
        
        # 2. 随失败次数增加
        if consecutive_failures > self.config.patience_threshold:
            # 每超过阈值1次,增加5%放弃概率
            extra_prob = (consecutive_failures - self.config.patience_threshold) * 0.05
            total_prob = min(base_prob + extra_prob, 0.8)  # 最多80%
        else:
            total_prob = base_prob
        
        # 3. 掷骰子
        return random.random() < total_prob
    
    async def retry_with_strategy(
        self,
        func: Callable,
        *args,
        strategy: RetryStrategy = RetryStrategy.LUCKY_USER,
        on_retry: Optional[Callable[[int, Exception], None]] = None,
        **kwargs
    ) -> Any:
        """
        使用智能策略执行重试
        
        Args:
            func: 要执行的异步函数
            strategy: 重试策略
            on_retry: 重试时的回调函数(attempt, exception)
        
        Returns:
            函数执行结果
        
        Raises:
            最后一次失败的异常
        """
        start_time = time.time()
        last_exception = None
        consecutive_failures = 0
        
        for attempt in range(1, self.config.max_retries + 1):
            try:
                # 检查总超时
                elapsed = time.time() - start_time
                if elapsed > self.config.timeout:
                    log.warning(f"总超时({self.config.timeout}s),放弃重试")
                    break
                
                # 执行函数
                result = await func(*args, **kwargs)
                
                # 成功!
                self._record_success()
                consecutive_failures = 0
                return result
            
            except Exception as e:
                last_exception = e
                consecutive_failures += 1
                self._record_failure()
                
                # 回调
                if on_retry:
                    try:
                        on_retry(attempt, e)
                    except:
                        pass
                
                # 是否放弃?
                if attempt < self.config.max_retries:
                    if self.should_give_up(consecutive_failures):
                        log.info(f"概率性放弃重试(连续失败{consecutive_failures}次)")
                        break
                    
                    # 计算延迟
                    delay = self.calculate_delay(attempt, strategy)
                    log.debug(
                        f"第{attempt}次失败: {type(e).__name__}, "
                        f"等待{delay:.2f}s后重试 (连续失败{consecutive_failures}次)"
                    )
                    
                    await asyncio.sleep(delay)
        
        # 所有重试都失败了
        log.error(f"重试{self.config.max_retries}次后仍失败")
        if last_exception:
            raise last_exception
        else:
            raise Exception("未知错误")
    
    def _record_success(self):
        """记录成功"""
        self.total_attempts += 1
        self.total_successes += 1
        self.recent_results.append(True)
        
        # 维护窗口大小
        if len(self.recent_results) > self.config.success_rate_window:
            self.recent_results.pop(0)
        
        # 自适应调整
        if self.config.adaptive:
            self._adjust_parameters()
    
    def _record_failure(self):
        """记录失败"""
        self.total_attempts += 1
        self.recent_results.append(False)
        
        if len(self.recent_results) > self.config.success_rate_window:
            self.recent_results.pop(0)
        
        if self.config.adaptive:
            self._adjust_parameters()
    
    def _adjust_parameters(self):
        """根据成功率自适应调整参数"""
        if len(self.recent_results) < 20:
            return  # 样本太少
        
        success_rate = sum(self.recent_results) / len(self.recent_results)
        
        # 成功率低 -> 增加延迟,降低放弃概率(给网站更多恢复时间)
        if success_rate < 0.3:
            self.current_base_delay = min(
                self.current_base_delay * 1.2,
                self.config.max_delay / 2
            )
            self.current_give_up_prob = max(
                self.current_give_up_prob * 0.8,
                0.05
            )
        
        # 成功率高 -> 可以略微激进
        elif success_rate > 0.7:
            self.current_base_delay = max(
                self.current_base_delay * 0.9,
                self.config.base_delay
            )
            self.current_give_up_prob = min(
                self.current_give_up_prob * 1.1,
                0.3
            )
    
    def get_success_rate(self) -> float:
        """获取当前成功率"""
        if not self.recent_results:
            return 0.0
        return sum(self.recent_results) / len(self.recent_results)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_attempts": self.total_attempts,
            "total_successes": self.total_successes,
            "overall_success_rate": (
                self.total_successes / self.total_attempts 
                if self.total_attempts > 0 else 0
            ),
            "recent_success_rate": self.get_success_rate(),
            "current_base_delay": self.current_base_delay,
            "current_give_up_prob": self.current_give_up_prob,
        }
    
    @staticmethod
    def _fibonacci(n: int) -> int:
        """计算斐波那契数"""
        if n <= 1:
            return n
        a, b = 0, 1
        for _ in range(n - 1):
            a, b = b, a + b
        return b


# 便捷的装饰器
def smart_retry(
    max_retries: int = 10,
    strategy: RetryStrategy = RetryStrategy.LUCKY_USER,
    **config_kwargs
):
    """
    智能重试装饰器
    
    用法:
        @smart_retry(max_retries=5)
        async def fetch_data():
            ...
    """
    def decorator(func):
        config = RetryConfig(max_retries=max_retries, **config_kwargs)
        manager = SmartRetryManager(config)
        
        async def wrapper(*args, **kwargs):
            return await manager.retry_with_strategy(
                func, *args, strategy=strategy, **kwargs
            )
        
        return wrapper
    return decorator
