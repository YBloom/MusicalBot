"""
高级爬虫客户端 - 集成所有优化策略
结合智能重试、连接池、健康探测,实现高成功率的爬取

使用示例:
    client = AdvancedCrawlerClient("https://example.com")
    await client.initialize()
    
    data = await client.fetch("/api/data")
    
    await client.close()
"""

import asyncio
import aiohttp
import time
from typing import Optional, Dict, Any
import logging

from .smart_retry import SmartRetryManager, RetryConfig, RetryStrategy
from .connection_pool import SmartConnectionPool
from .health_prober import ServerHealthProber

log = logging.getLogger(__name__)


class AdvancedCrawlerClient:
    """高级爬虫客户端"""
    
    def __init__(
        self,
        base_url: str,
        enable_connection_pool: bool = True,
        enable_health_probe: bool = True,
        enable_smart_retry: bool = True,
        pool_size: int = 5,
        max_retries: int = 10,
        user_agent: Optional[str] = None,
    ):
        """
        Args:
            base_url: 基础URL(如 https://example.com)
            enable_connection_pool: 是否启用连接池
            enable_health_probe: 是否启用健康探测
            enable_smart_retry: 是否启用智能重试
            pool_size: 连接池大小
            max_retries: 最大重试次数
            user_agent: 自定义User-Agent
        """
        self.base_url = base_url.rstrip('/')
        self.enable_connection_pool = enable_connection_pool
        self.enable_health_probe = enable_health_probe
        self.enable_smart_retry = enable_smart_retry
        
        # 提取域名
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        self.domain = parsed.netloc
        
        # 组件
        self.connection_pool: Optional[SmartConnectionPool] = None
        self.health_prober: Optional[ServerHealthProber] = None
        self.retry_manager: Optional[SmartRetryManager] = None
        
        # 配置
        self.pool_size = pool_size
        self.max_retries = max_retries
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
        
        # 统计
        self.stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "retries_count": 0,
        }
    
    async def initialize(self):
        """初始化客户端"""
        log.info(f"初始化高级爬虫客户端: {self.base_url}")
        
        # 初始化连接池
        if self.enable_connection_pool:
            self.connection_pool = SmartConnectionPool(
                target_url=self.base_url,
                pool_size=self.pool_size,
            )
            await self.connection_pool.initialize()
            log.info("✅ 连接池已启用")
        
        # 初始化健康探测
        if self.enable_health_probe:
            self.health_prober = ServerHealthProber(
                target_domain=self.domain,
                probe_interval=30.0,
            )
            await self.health_prober.start()
            log.info("✅ 健康探测已启用")
        
        # 初始化重试管理器
        if self.enable_smart_retry:
            retry_config = RetryConfig(
                max_retries=self.max_retries,
                base_delay=1.0,
                max_delay=30.0,
                jitter_factor=0.5,
                give_up_probability=0.15,
            )
            self.retry_manager = SmartRetryManager(retry_config)
            log.info("✅ 智能重试已启用")
        
        log.info("🚀 高级爬虫客户端初始化完成")
    
    async def close(self):
        """关闭客户端"""
        log.info("关闭高级爬虫客户端")
        
        if self.connection_pool:
            await self.connection_pool.close()
        
        if self.health_prober:
            await self.health_prober.stop()
        
        # 输出最终统计
        log.info(f"📊 最终统计: {self.get_stats()}")
    
    async def fetch(
        self,
        path: str,
        method: str = "GET",
        **kwargs
    ) -> str:
        """
        抓取数据
        
        Args:
            path: 路径(如 /api/data)
            method: HTTP方法
            **kwargs: 传递给request的参数
        
        Returns:
            响应文本
        """
        url = f"{self.base_url}{path}"
        
        # 准备请求
        async def _do_request():
            return await self._execute_request(method, url, **kwargs)
        
        # 使用智能重试
        if self.enable_smart_retry and self.retry_manager:
            def on_retry(attempt, exception):
                self.stats["retries_count"] += 1
                log.debug(f"重试 {attempt}/{self.max_retries}: {exception}")
            
            result = await self.retry_manager.retry_with_strategy(
                _do_request,
                strategy=RetryStrategy.LUCKY_USER,
                on_retry=on_retry,
            )
        else:
            result = await _do_request()
        
        return result
    
    async def _execute_request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> str:
        """执行单次请求"""
        self.stats["total_requests"] += 1
        
        # 设置Headers
        headers = kwargs.get('headers', {})
        headers.setdefault('User-Agent', self.user_agent)
        kwargs['headers'] = headers
        
        # 选择最佳节点(如果启用健康探测)
        target_ip = None
        if self.enable_health_probe and self.health_prober:
            best_node = self.health_prober.get_best_node()
            if best_node:
                target_ip = best_node.ip
                log.debug(f"使用最佳节点: {target_ip} (健康分{best_node.health_score:.1f})")
        
        # 使用连接池发送请求
        if self.enable_connection_pool and self.connection_pool:
            async with await self.connection_pool.request(method, url, **kwargs) as resp:
                text = await resp.text()
                self.stats["successful_requests"] += 1
                return text
        
        # 降级: 普通请求
        else:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(method, url, **kwargs) as resp:
                    text = await resp.text()
                    self.stats["successful_requests"] += 1
                    return text
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        result = {**self.stats}
        
        # 成功率
        if result["total_requests"] > 0:
            result["success_rate"] = (
                result["successful_requests"] / result["total_requests"]
            )
        else:
            result["success_rate"] = 0.0
        
        # 连接池统计
        if self.connection_pool:
            result["connection_pool"] = self.connection_pool.get_stats()
        
        # 健康探测统计
        if self.health_prober:
            result["health_prober"] = self.health_prober.get_stats()
        
        # 重试管理器统计
        if self.retry_manager:
            result["retry_manager"] = self.retry_manager.get_stats()
        
        return result


# 便捷函数
async def fetch_with_advanced_client(
    url: str,
    **client_kwargs
) -> str:
    """
    使用高级客户端抓取单个URL
    
    用法:
        data = await fetch_with_advanced_client(
            "https://example.com/api/data",
            max_retries=5
        )
    """
    from urllib.parse import urlparse
    
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    
    client = AdvancedCrawlerClient(base_url, **client_kwargs)
    
    try:
        await client.initialize()
        result = await client.fetch(path)
        return result
    finally:
        await client.close()
