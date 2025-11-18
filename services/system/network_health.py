"""
网络健康检查与熔断器模块
防止DNS故障、网络断连等问题导致的服务雪崩
"""
import asyncio
import time
from enum import Enum
from typing import Optional, Callable
import aiohttp
from ncatbot.utils.logger import get_log

log = get_log()


class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"       # 正常状态
    OPEN = "open"           # 熔断状态(拒绝请求)
    HALF_OPEN = "half_open" # 半开状态(尝试恢复)


class NetworkHealthChecker:
    """网络健康检查器"""
    
    def __init__(self):
        self.is_healthy = True
        self.last_check_time = 0
        self.check_interval = 60  # 健康检查间隔(秒)
        self.dns_servers = ["8.8.8.8", "1.1.1.1"]  # 公共DNS
        self.test_urls = [
            "https://clubz.cloudsation.com",  # 呼啦圈域名
            "https://www.baidu.com"           # 备用测试
        ]
        self._check_task: Optional[asyncio.Task] = None
    
    async def start_health_check(self):
        """启动健康检查后台任务"""
        if self._check_task and not self._check_task.done():
            return
        
        self._check_task = asyncio.create_task(self._health_check_loop())
        log.info("🟢 网络健康检查已启动")
    
    async def stop_health_check(self):
        """停止健康检查"""
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        log.info("🔴 网络健康检查已停止")
    
    async def _health_check_loop(self):
        """健康检查循环"""
        while True:
            try:
                await asyncio.sleep(self.check_interval)
                await self.check_network_health()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"健康检查异常: {e}")
    
    async def check_network_health(self) -> bool:
        """
        检查网络健康状态
        Returns:
            bool: True=健康, False=故障
        """
        current_time = time.time()
        
        # 防止频繁检查
        if current_time - self.last_check_time < 10:
            return self.is_healthy
        
        self.last_check_time = current_time
        
        # 1. DNS解析测试
        dns_ok = await self._check_dns()
        
        # 2. HTTP连接测试
        http_ok = await self._check_http_connectivity()
        
        # 更新健康状态
        previous_state = self.is_healthy
        self.is_healthy = dns_ok and http_ok
        
        # 状态变化时记录日志
        if previous_state != self.is_healthy:
            if self.is_healthy:
                log.info("✅ 网络已恢复正常")
            else:
                log.error(f"❌ 网络异常 - DNS:{dns_ok}, HTTP:{http_ok}")
        
        return self.is_healthy
    
    async def _check_dns(self) -> bool:
        """检查DNS解析是否正常"""
        try:
            import socket
            for test_domain in ["clubz.cloudsation.com", "www.baidu.com"]:
                try:
                    # 设置DNS查询超时
                    loop = asyncio.get_event_loop()
                    await asyncio.wait_for(
                        loop.run_in_executor(None, socket.gethostbyname, test_domain),
                        timeout=5
                    )
                    return True  # 任意一个成功即认为DNS正常
                except (socket.gaierror, asyncio.TimeoutError):
                    continue
            
            log.warning("DNS解析失败")
            return False
        except Exception as e:
            log.error(f"DNS检查异常: {e}")
            return False
    
    async def _check_http_connectivity(self) -> bool:
        """检查HTTP连接是否正常"""
        connector = aiohttp.TCPConnector(
            limit=1,
            ttl_dns_cache=10,  # DNS缓存10秒
            family=0  # 同时支持IPv4/IPv6
        )
        
        timeout = aiohttp.ClientTimeout(
            total=10,
            connect=5,
            sock_read=5
        )
        
        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout
            ) as session:
                for url in self.test_urls:
                    try:
                        async with session.get(url) as resp:
                            if resp.status < 500:  # 5xx是服务器问题,不算网络故障
                                return True
                    except (aiohttp.ClientError, asyncio.TimeoutError):
                        continue
                
                log.warning("HTTP连接测试失败")
                return False
        except Exception as e:
            log.error(f"HTTP检查异常: {e}")
            return False


class CircuitBreaker:
    """熔断器 - 防止故障扩散"""
    
    def __init__(
        self, 
        failure_threshold: int = 5,      # 失败阈值
        timeout: int = 60,                # 熔断超时(秒)
        expected_exception: tuple = (Exception,)
    ):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = CircuitState.CLOSED
    
    def __call__(self, func: Callable):
        """装饰器用法"""
        async def wrapper(*args, **kwargs):
            return await self.call(func, *args, **kwargs)
        return wrapper
    
    async def call(self, func: Callable, *args, **kwargs):
        """执行函数调用(带熔断保护)"""
        
        # 检查是否需要从OPEN转到HALF_OPEN
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.timeout:
                log.info(f"🔄 熔断器进入半开状态: {func.__name__}")
                self.state = CircuitState.HALF_OPEN
            else:
                raise Exception(f"熔断器开启中,拒绝调用 {func.__name__}")
        
        try:
            result = await func(*args, **kwargs)
            
            # 成功调用,重置计数
            if self.state == CircuitState.HALF_OPEN:
                log.info(f"✅ 熔断器恢复正常: {func.__name__}")
                self.state = CircuitState.CLOSED
                self.failure_count = 0
            
            return result
        
        except self.expected_exception as e:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            # 达到阈值,开启熔断
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                log.error(f"🔥 熔断器开启: {func.__name__} (失败{self.failure_count}次)")
            
            raise


# 全局实例
network_health_checker = NetworkHealthChecker()


async def safe_http_request(
    url: str, 
    method: str = "GET",
    timeout: int = 15,
    max_retries: int = 3,
    **kwargs
) -> tuple[bool, any]:
    """
    安全的HTTP请求(带健康检查、重试、熔断)
    
    Returns:
        (success: bool, result: response_data or error_message)
    """
    
    # 1. 检查网络健康
    if not await network_health_checker.check_network_health():
        return False, "网络异常,请稍后重试"
    
    # 2. 配置超时和连接器
    timeout_config = aiohttp.ClientTimeout(
        total=timeout,
        connect=5,
        sock_connect=5,
        sock_read=timeout
    )
    
    connector = aiohttp.TCPConnector(
        limit=10,
        ttl_dns_cache=300,
        family=0
    )
    
    # 3. 重试逻辑(指数退避)
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout_config
            ) as session:
                async with session.request(method, url, **kwargs) as resp:
                    if resp.status >= 500:
                        # 服务器错误,可能需要重试
                        if attempt < max_retries - 1:
                            await asyncio.sleep(2 ** attempt)  # 指数退避
                            continue
                        return False, f"服务器错误: {resp.status}"
                    
                    # 成功
                    data = await resp.text()
                    return True, data
        
        except asyncio.TimeoutError:
            log.warning(f"请求超时 (尝试 {attempt + 1}/{max_retries}): {url}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            return False, "请求超时"
        
        except aiohttp.ClientConnectorError as e:
            # DNS错误或连接失败
            log.error(f"连接错误: {e}")
            return False, f"连接失败: {e}"
        
        except Exception as e:
            log.error(f"请求异常: {e}")
            return False, str(e)
    
    return False, "达到最大重试次数"
