"""
服务器健康探测器 - 识别并避开假死节点
通过主动探测和负载均衡识别,避免请求被路由到故障服务器

核心功能:
1. 多IP探测 - 识别负载均衡后的不同服务器节点
2. 健康评分 - 量化每个节点的健康程度
3. 智能路由 - 优先使用健康节点
4. 动态恢复 - 定期重新探测故障节点
"""

import asyncio
import aiohttp
import time
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from collections import deque
import socket
import logging

log = logging.getLogger(__name__)


@dataclass
class ServerNode:
    """服务器节点信息"""
    ip: str
    port: int = 443
    
    # 健康指标
    health_score: float = 100.0  # 健康分数(0-100)
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    
    # 性能指标
    avg_response_time: float = 0.0
    response_times: deque = field(default_factory=lambda: deque(maxlen=10))
    
    # 统计
    total_requests: int = 0
    total_failures: int = 0
    last_check_time: float = 0.0
    last_success_time: float = 0.0
    
    # 状态
    is_alive: bool = True
    is_congested: bool = False  # 是否拥塞
    quarantine_until: float = 0.0  # 隔离到什么时候
    
    def update_response_time(self, rt: float):
        """更新响应时间"""
        self.response_times.append(rt)
        if len(self.response_times) > 0:
            self.avg_response_time = sum(self.response_times) / len(self.response_times)
        
        # 判断是否拥塞(响应时间过长)
        if rt > 10.0:  # 超过10秒认为拥塞
            self.is_congested = True
        elif self.avg_response_time < 3.0:
            self.is_congested = False
    
    def record_success(self, response_time: float):
        """记录成功"""
        self.total_requests += 1
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_success_time = time.time()
        self.last_check_time = time.time()
        
        # 更新响应时间
        self.update_response_time(response_time)
        
        # 提升健康分数
        self.health_score = min(100.0, self.health_score + 5.0)
        self.is_alive = True
        
        # 连续成功3次解除隔离
        if self.consecutive_successes >= 3:
            self.quarantine_until = 0.0
    
    def record_failure(self, is_timeout: bool = False):
        """记录失败"""
        self.total_requests += 1
        self.total_failures += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_check_time = time.time()
        
        # 降低健康分数
        if is_timeout:
            penalty = 20.0  # 超时惩罚更重
            self.is_congested = True
        else:
            penalty = 10.0
        
        self.health_score = max(0.0, self.health_score - penalty)
        
        # 连续失败3次标记为死亡
        if self.consecutive_failures >= 3:
            self.is_alive = False
            # 隔离60秒
            self.quarantine_until = time.time() + 60.0
    
    def is_available(self) -> bool:
        """是否可用"""
        # 检查隔离
        if time.time() < self.quarantine_until:
            return False
        
        # 检查健康分数
        if self.health_score < 30.0:
            return False
        
        # 检查是否存活
        if not self.is_alive:
            return False
        
        return True
    
    def get_priority(self) -> float:
        """
        获取优先级分数(越高越好)
        综合考虑健康分数、响应时间、拥塞状态
        """
        score = self.health_score
        
        # 响应时间惩罚
        if self.avg_response_time > 0:
            time_penalty = min(50.0, self.avg_response_time * 5)
            score -= time_penalty
        
        # 拥塞惩罚
        if self.is_congested:
            score -= 30.0
        
        # 失败率惩罚
        if self.total_requests > 0:
            failure_rate = self.total_failures / self.total_requests
            score -= failure_rate * 50.0
        
        return max(0.0, score)


class ServerHealthProber:
    """服务器健康探测器"""
    
    def __init__(
        self,
        target_domain: str,
        probe_interval: float = 30.0,
        max_nodes: int = 10,
    ):
        """
        Args:
            target_domain: 目标域名
            probe_interval: 探测间隔(秒)
            max_nodes: 最多跟踪多少个节点
        """
        self.target_domain = target_domain
        self.probe_interval = probe_interval
        self.max_nodes = max_nodes
        
        # 节点池
        self.nodes: Dict[str, ServerNode] = {}
        
        # 探测任务
        self._probe_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """启动探测器"""
        if self._running:
            return
        
        log.info(f"启动服务器健康探测器: {self.target_domain}")
        self._running = True
        
        # 初始发现节点
        await self._discover_nodes()
        
        # 启动探测循环
        self._probe_task = asyncio.create_task(self._probe_loop())
    
    async def stop(self):
        """停止探测器"""
        log.info("停止服务器健康探测器")
        self._running = False
        
        if self._probe_task:
            self._probe_task.cancel()
            try:
                await self._probe_task
            except asyncio.CancelledError:
                pass
    
    async def _discover_nodes(self):
        """发现服务器节点(通过DNS解析多个IP)"""
        try:
            # 解析域名获取所有IP
            loop = asyncio.get_event_loop()
            addr_info = await loop.getaddrinfo(
                self.target_domain,
                443,
                family=socket.AF_INET,
                type=socket.SOCK_STREAM
            )
            
            ips = set(info[4][0] for info in addr_info)
            log.info(f"发现 {len(ips)} 个IP: {ips}")
            
            # 创建节点
            for ip in ips:
                if ip not in self.nodes:
                    self.nodes[ip] = ServerNode(ip=ip, port=443)
        
        except Exception as e:
            log.error(f"节点发现失败: {e}")
    
    async def _probe_loop(self):
        """探测循环"""
        while self._running:
            try:
                await asyncio.sleep(self.probe_interval)
                await self._probe_all_nodes()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"探测循环异常: {e}")
    
    async def _probe_all_nodes(self):
        """探测所有节点"""
        log.debug(f"探测 {len(self.nodes)} 个节点...")
        
        # 并发探测
        tasks = [
            self._probe_node(node)
            for node in self.nodes.values()
        ]
        
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # 输出统计
        available = sum(1 for n in self.nodes.values() if n.is_available())
        log.info(f"可用节点: {available}/{len(self.nodes)}")
    
    async def _probe_node(self, node: ServerNode):
        """探测单个节点"""
        url = f"https://{node.ip}/"
        
        # 构造请求(直接指定IP,绕过DNS)
        connector = aiohttp.TCPConnector(
            force_close=False,
            limit=1,
        )
        
        timeout = aiohttp.ClientTimeout(total=10, connect=5)
        
        start_time = time.time()
        
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                # 关键: 使用Host头欺骗,让服务器认为我们访问的是域名
                headers = {'Host': self.target_domain}
                
                async with session.get(url, headers=headers, ssl=False) as resp:
                    await resp.text()
                    elapsed = time.time() - start_time
                    
                    # 记录成功
                    node.record_success(elapsed)
                    log.debug(f"节点 {node.ip} 健康 (响应{elapsed:.2f}s, 分数{node.health_score:.1f})")
        
        except asyncio.TimeoutError:
            node.record_failure(is_timeout=True)
            log.debug(f"节点 {node.ip} 超时")
        
        except Exception as e:
            node.record_failure(is_timeout=False)
            log.debug(f"节点 {node.ip} 失败: {type(e).__name__}")
    
    def get_best_node(self) -> Optional[ServerNode]:
        """获取最佳节点"""
        available_nodes = [
            node for node in self.nodes.values()
            if node.is_available()
        ]
        
        if not available_nodes:
            # 没有可用节点,返回分数最高的(即使不可用)
            if self.nodes:
                return max(self.nodes.values(), key=lambda n: n.health_score)
            return None
        
        # 按优先级排序
        available_nodes.sort(key=lambda n: n.get_priority(), reverse=True)
        
        return available_nodes[0]
    
    def get_healthy_nodes(self, min_score: float = 50.0) -> List[ServerNode]:
        """获取所有健康节点"""
        return [
            node for node in self.nodes.values()
            if node.is_available() and node.health_score >= min_score
        ]
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        if not self.nodes:
            return {}
        
        total_requests = sum(n.total_requests for n in self.nodes.values())
        total_failures = sum(n.total_failures for n in self.nodes.values())
        
        available_count = sum(1 for n in self.nodes.values() if n.is_available())
        congested_count = sum(1 for n in self.nodes.values() if n.is_congested)
        
        avg_health = sum(n.health_score for n in self.nodes.values()) / len(self.nodes)
        
        return {
            "total_nodes": len(self.nodes),
            "available_nodes": available_count,
            "congested_nodes": congested_count,
            "avg_health_score": avg_health,
            "total_requests": total_requests,
            "total_failures": total_failures,
            "success_rate": (
                (total_requests - total_failures) / total_requests
                if total_requests > 0 else 0
            ),
        }


# 全局探测器管理
_probers: Dict[str, ServerHealthProber] = {}


async def get_prober(domain: str, **kwargs) -> ServerHealthProber:
    """获取或创建探测器"""
    if domain not in _probers:
        prober = ServerHealthProber(domain, **kwargs)
        await prober.start()
        _probers[domain] = prober
    
    return _probers[domain]


async def stop_all_probers():
    """停止所有探测器"""
    for prober in _probers.values():
        await prober.stop()
    _probers.clear()
