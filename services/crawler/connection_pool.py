"""
智能连接池管理器 - Keep-Alive 优化
绕过拥塞的TCP握手阶段,复用已建立的连接

核心优势:
1. 连接复用 - 跳过 SYN/ACK 握手,直接发送数据
2. 连接预热 - 提前建立连接池,避免临时握手
3. 健康检查 - 剔除坏连接,避免在死连接上浪费时间
4. 智能负载 - 识别并避开拥塞的连接
"""

import asyncio
import aiohttp
import time
from typing import Optional, Dict, List, Set
from dataclasses import dataclass, field
from collections import defaultdict
import logging

log = logging.getLogger(__name__)


@dataclass
class ConnectionStats:
    """连接统计信息"""
    created_at: float = field(default_factory=time.time)
    requests_count: int = 0
    failures_count: int = 0
    last_used: float = field(default_factory=time.time)
    avg_response_time: float = 0.0
    
    # 健康指标
    is_healthy: bool = True
    consecutive_failures: int = 0
    
    def record_success(self, response_time: float):
        """记录成功请求"""
        self.requests_count += 1
        self.last_used = time.time()
        self.consecutive_failures = 0
        
        # 更新平均响应时间(指数移动平均)
        alpha = 0.3
        self.avg_response_time = (
            alpha * response_time + (1 - alpha) * self.avg_response_time
        )
        
        # 恢复健康
        if self.consecutive_failures == 0:
            self.is_healthy = True
    
    def record_failure(self):
        """记录失败请求"""
        self.failures_count += 1
        self.consecutive_failures += 1
        self.last_used = time.time()
        
        # 连续失败3次标记为不健康
        if self.consecutive_failures >= 3:
            self.is_healthy = False


class SmartConnectionPool:
    """智能连接池"""
    
    def __init__(
        self,
        target_url: str,
        pool_size: int = 5,
        max_requests_per_conn: int = 100,
        conn_ttl: float = 300.0,  # 连接存活时间(秒)
        health_check_interval: float = 30.0,
        keep_alive_timeout: float = 60.0,
    ):
        """
        Args:
            target_url: 目标URL(基础域名)
            pool_size: 连接池大小
            max_requests_per_conn: 每个连接最多处理多少请求
            conn_ttl: 连接最大存活时间
            health_check_interval: 健康检查间隔
            keep_alive_timeout: Keep-Alive 超时时间
        """
        self.target_url = target_url
        self.pool_size = pool_size
        self.max_requests_per_conn = max_requests_per_conn
        self.conn_ttl = conn_ttl
        self.health_check_interval = health_check_interval
        self.keep_alive_timeout = keep_alive_timeout
        
        # 连接池
        self._sessions: List[aiohttp.ClientSession] = []
        self._session_stats: Dict[int, ConnectionStats] = {}
        
        # 状态
        self._initialized = False
        self._health_check_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
    
    async def initialize(self):
        """初始化连接池"""
        if self._initialized:
            return
        
        log.info(f"初始化连接池,大小={self.pool_size}")
        
        # 创建连接器配置
        connector = aiohttp.TCPConnector(
            limit=self.pool_size,
            limit_per_host=self.pool_size,
            ttl_dns_cache=300,  # DNS缓存5分钟
            force_close=False,  # 重要: 启用连接复用
            enable_cleanup_closed=True,
        )
        
        # 超时配置
        timeout = aiohttp.ClientTimeout(
            total=30,
            connect=10,
            sock_connect=5,
            sock_read=20
        )
        
        # 预热连接池
        for i in range(self.pool_size):
            session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    'Connection': 'keep-alive',  # 关键: Keep-Alive
                    'Keep-Alive': f'timeout={int(self.keep_alive_timeout)}',
                }
            )
            
            self._sessions.append(session)
            self._session_stats[id(session)] = ConnectionStats()
            
            # 建立初始连接(预热)
            try:
                async with session.get(self.target_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    await resp.text()
                    self._session_stats[id(session)].record_success(1.0)
                    log.debug(f"连接池 {i+1}/{self.pool_size} 预热成功")
            except Exception as e:
                log.warning(f"连接池 {i+1} 预热失败: {e}")
                self._session_stats[id(session)].record_failure()
        
        self._initialized = True
        
        # 启动健康检查
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        log.info("连接池初始化完成")
    
    async def close(self):
        """关闭连接池"""
        log.info("关闭连接池")
        
        # 停止健康检查
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        # 关闭所有连接
        for session in self._sessions:
            try:
                await session.close()
            except:
                pass
        
        self._sessions.clear()
        self._session_stats.clear()
        self._initialized = False
    
    async def get_healthy_session(self) -> Optional[aiohttp.ClientSession]:
        """
        获取一个健康的Session
        
        策略:
        1. 优先选择响应时间快的
        2. 避开失败率高的
        3. 避开使用过度的(接近max_requests)
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            # 筛选健康的Session
            healthy_sessions = [
                (session, self._session_stats[id(session)])
                for session in self._sessions
                if self._session_stats[id(session)].is_healthy
                and self._session_stats[id(session)].requests_count < self.max_requests_per_conn
            ]
            
            if not healthy_sessions:
                log.warning("没有健康的连接,尝试重置...")
                # 重置所有连接的健康状态
                for stats in self._session_stats.values():
                    if stats.consecutive_failures < 10:  # 只重置不太严重的
                        stats.is_healthy = True
                        stats.consecutive_failures = 0
                
                # 再试一次
                healthy_sessions = [
                    (session, self._session_stats[id(session)])
                    for session in self._sessions
                    if self._session_stats[id(session)].is_healthy
                ]
                
                if not healthy_sessions:
                    return None
            
            # 按响应时间排序(快的优先)
            healthy_sessions.sort(
                key=lambda x: (
                    x[1].avg_response_time if x[1].avg_response_time > 0 else 999,
                    x[1].requests_count
                )
            )
            
            # 返回最优的Session
            return healthy_sessions[0][0]
    
    async def request(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> aiohttp.ClientResponse:
        """
        使用连接池发送请求
        
        Args:
            method: HTTP方法
            url: 完整URL
            **kwargs: 传递给session.request的参数
        
        Returns:
            响应对象
        """
        session = await self.get_healthy_session()
        
        if not session:
            raise Exception("连接池无可用连接")
        
        stats = self._session_stats[id(session)]
        start_time = time.time()
        
        try:
            # 发送请求(复用已有连接,无需握手!)
            response = await session.request(method, url, **kwargs)
            
            # 记录成功
            elapsed = time.time() - start_time
            stats.record_success(elapsed)
            
            return response
        
        except Exception as e:
            # 记录失败
            stats.record_failure()
            log.debug(f"请求失败(连接{id(session)}): {e}")
            raise
    
    async def _health_check_loop(self):
        """健康检查循环"""
        while True:
            try:
                await asyncio.sleep(self.health_check_interval)
                await self._perform_health_check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"健康检查异常: {e}")
    
    async def _perform_health_check(self):
        """执行健康检查"""
        log.debug("执行连接池健康检查...")
        
        current_time = time.time()
        
        for session in self._sessions:
            stats = self._session_stats[id(session)]
            
            # 检查是否超过TTL
            if current_time - stats.created_at > self.conn_ttl:
                log.info(f"连接{id(session)}超过TTL,重建...")
                # TODO: 重建连接
            
            # 检查是否长时间未使用
            if current_time - stats.last_used > self.keep_alive_timeout:
                log.debug(f"连接{id(session)}长时间未使用,发送心跳...")
                # 发送心跳请求
                try:
                    async with session.head(self.target_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        pass
                    stats.record_success(0.1)
                except:
                    stats.record_failure()
        
        # 输出统计
        healthy_count = sum(
            1 for s in self._session_stats.values() if s.is_healthy
        )
        log.debug(f"健康连接: {healthy_count}/{len(self._sessions)}")
    
    def get_stats(self) -> Dict:
        """获取连接池统计信息"""
        total_requests = sum(s.requests_count for s in self._session_stats.values())
        total_failures = sum(s.failures_count for s in self._session_stats.values())
        healthy_count = sum(1 for s in self._session_stats.values() if s.is_healthy)
        
        avg_response_times = [
            s.avg_response_time for s in self._session_stats.values()
            if s.avg_response_time > 0
        ]
        
        return {
            "pool_size": len(self._sessions),
            "healthy_connections": healthy_count,
            "total_requests": total_requests,
            "total_failures": total_failures,
            "success_rate": (
                (total_requests - total_failures) / total_requests
                if total_requests > 0 else 0
            ),
            "avg_response_time": (
                sum(avg_response_times) / len(avg_response_times)
                if avg_response_times else 0
            ),
        }


# 全局连接池管理器
_connection_pools: Dict[str, SmartConnectionPool] = {}


async def get_pool(target_url: str, **kwargs) -> SmartConnectionPool:
    """获取或创建连接池"""
    if target_url not in _connection_pools:
        pool = SmartConnectionPool(target_url, **kwargs)
        await pool.initialize()
        _connection_pools[target_url] = pool
    
    return _connection_pools[target_url]


async def close_all_pools():
    """关闭所有连接池"""
    for pool in _connection_pools.values():
        await pool.close()
    _connection_pools.clear()
