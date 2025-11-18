"""
本地测试服务器 - 模拟高负载、不稳定的服务器
用于测试爬虫策略的有效性

特性:
1. 随机拒绝连接(模拟拥塞)
2. 随机超时(模拟假死节点)
3. 多进程模拟负载均衡集群
4. 可调节的故障率
"""

from aiohttp import web
import asyncio
import random
import time
import logging
from typing import Dict, List

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


class UnstableServer:
    """不稳定服务器模拟器"""
    
    def __init__(
        self,
        port: int = 8080,
        failure_rate: float = 0.7,  # 失败率70%(模拟高负载)
        timeout_rate: float = 0.3,  # 超时率30%
        slow_response_rate: float = 0.4,  # 慢响应率40%
        max_delay: float = 10.0,  # 最大延迟
    ):
        self.port = port
        self.failure_rate = failure_rate
        self.timeout_rate = timeout_rate
        self.slow_response_rate = slow_response_rate
        self.max_delay = max_delay
        
        # 统计
        self.stats = {
            "total_requests": 0,
            "rejected": 0,
            "timeout": 0,
            "slow": 0,
            "success": 0,
        }
        
        self.app = web.Application()
        self.app.router.add_get('/', self.handle_request)
        self.app.router.add_get('/{path:.*}', self.handle_request)
        self.runner = None
    
    async def handle_request(self, request):
        """处理请求"""
        self.stats["total_requests"] += 1
        
        # 1. 随机拒绝连接(模拟拥塞)
        if random.random() < self.failure_rate:
            self.stats["rejected"] += 1
            log.debug(f"❌ 拒绝连接 (拥塞模拟) - 总请求{self.stats['total_requests']}")
            raise web.HTTPServiceUnavailable(
                text="Server is congested, please try again later"
            )
        
        # 2. 随机超时(模拟假死)
        if random.random() < self.timeout_rate:
            self.stats["timeout"] += 1
            log.debug(f"⏱️  超时 (假死模拟) - 总请求{self.stats['total_requests']}")
            await asyncio.sleep(30)  # 长时间不响应
            raise web.HTTPRequestTimeout()
        
        # 3. 随机慢响应
        delay = 0
        if random.random() < self.slow_response_rate:
            delay = random.uniform(2.0, self.max_delay)
            self.stats["slow"] += 1
            log.debug(f"🐌 慢响应 {delay:.1f}s - 总请求{self.stats['total_requests']}")
            await asyncio.sleep(delay)
        
        # 4. 成功响应
        self.stats["success"] += 1
        
        response_data = {
            "status": "success",
            "message": "You are lucky!",
            "request_number": self.stats["total_requests"],
            "delay": delay,
            "server_port": self.port,
            "stats": self.stats,
        }
        
        log.info(
            f"✅ 成功响应 (成功率: {self.stats['success']}/{self.stats['total_requests']} = "
            f"{self.stats['success']/self.stats['total_requests']*100:.1f}%)"
        )
        
        return web.json_response(response_data)
    
    async def start(self):
        """启动服务器"""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '0.0.0.0', self.port)
        await site.start()
        log.info(f"🚀 不稳定服务器启动在端口 {self.port}")
        log.info(f"   故障率: {self.failure_rate*100:.0f}%")
        log.info(f"   超时率: {self.timeout_rate*100:.0f}%")
        log.info(f"   慢响应率: {self.slow_response_rate*100:.0f}%")
    
    async def stop(self):
        """停止服务器"""
        if self.runner:
            await self.runner.cleanup()
        log.info(f"❌ 服务器停止 (端口 {self.port})")


class LoadBalancedCluster:
    """负载均衡集群模拟"""
    
    def __init__(
        self,
        num_servers: int = 3,
        base_port: int = 8080,
        healthy_servers: int = 1,  # 健康服务器数量
    ):
        """
        Args:
            num_servers: 总服务器数量
            base_port: 起始端口
            healthy_servers: 健康服务器数量(其余为故障节点)
        """
        self.num_servers = num_servers
        self.base_port = base_port
        self.healthy_servers = healthy_servers
        
        self.servers: List[UnstableServer] = []
    
    async def start(self):
        """启动集群"""
        log.info(f"🌐 启动负载均衡集群 ({self.num_servers}台服务器)")
        
        for i in range(self.num_servers):
            port = self.base_port + i
            
            # 前面几台是健康的,后面是故障的
            if i < self.healthy_servers:
                # 健康服务器: 低故障率
                server = UnstableServer(
                    port=port,
                    failure_rate=0.3,  # 30%失败率(模拟"幸运"可进)
                    timeout_rate=0.1,
                    slow_response_rate=0.2,
                )
                log.info(f"   服务器 {i+1} (端口{port}): ✅ 健康节点")
            else:
                # 故障服务器: 高故障率
                server = UnstableServer(
                    port=port,
                    failure_rate=0.95,  # 95%失败率(几乎死亡)
                    timeout_rate=0.6,
                    slow_response_rate=0.3,
                )
                log.info(f"   服务器 {i+1} (端口{port}): ❌ 故障节点")
            
            await server.start()
            self.servers.append(server)
        
        log.info(f"✅ 集群启动完成 ({self.healthy_servers}台健康/{self.num_servers}台总计)")
    
    async def stop(self):
        """停止集群"""
        log.info("停止集群...")
        for server in self.servers:
            await server.stop()
    
    def get_stats(self) -> Dict:
        """获取集群统计"""
        total_stats = {
            "total_requests": 0,
            "rejected": 0,
            "timeout": 0,
            "slow": 0,
            "success": 0,
        }
        
        for server in self.servers:
            for key in total_stats:
                total_stats[key] += server.stats[key]
        
        return total_stats


# 测试脚本
async def run_test_server():
    """运行测试服务器"""
    # 方案1: 单服务器测试
    # server = UnstableServer(port=8080, failure_rate=0.7)
    # await server.start()
    
    # 方案2: 集群测试(推荐)
    cluster = LoadBalancedCluster(
        num_servers=3,
        base_port=8080,
        healthy_servers=1,  # 只有1台健康
    )
    await cluster.start()
    
    try:
        log.info("\n" + "="*50)
        log.info("测试服务器运行中...")
        log.info("访问: http://localhost:8080")
        log.info("按 Ctrl+C 停止")
        log.info("="*50 + "\n")
        
        # 保持运行
        while True:
            await asyncio.sleep(10)
            
            # 输出统计
            stats = cluster.get_stats()
            if stats["total_requests"] > 0:
                success_rate = stats["success"] / stats["total_requests"] * 100
                log.info(
                    f"📊 集群统计: 总请求{stats['total_requests']}, "
                    f"成功{stats['success']}, "
                    f"成功率{success_rate:.1f}%"
                )
    
    except KeyboardInterrupt:
        log.info("\n收到停止信号")
    
    finally:
        await cluster.stop()


if __name__ == "__main__":
    asyncio.run(run_test_server())
