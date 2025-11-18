"""
测试客户端 - 对比普通爬虫 vs 高级爬虫
验证优化策略的有效性
"""

import asyncio
import aiohttp
import time
import sys
import os
from typing import Dict, List

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from services.crawler.advanced_client import AdvancedCrawlerClient
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


class NaiveCrawler:
    """普通爬虫(暴力重试)"""
    
    def __init__(self, base_url: str, max_retries: int = 10):
        self.base_url = base_url
        self.max_retries = max_retries
        
        self.stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
        }
    
    async def fetch(self, path: str = "/") -> str:
        """暴力抓取"""
        url = f"{self.base_url}{path}"
        
        for attempt in range(1, self.max_retries + 1):
            self.stats["total_requests"] += 1
            
            try:
                # 简单粗暴: 立即重试
                timeout = aiohttp.ClientTimeout(total=5)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url) as resp:
                        text = await resp.text()
                        self.stats["successful_requests"] += 1
                        return text
            
            except Exception as e:
                if attempt == self.max_retries:
                    self.stats["failed_requests"] += 1
                    raise
                
                # 立即重试(无延迟)
                continue
        
        raise Exception("Failed after all retries")


async def benchmark_naive_crawler(target_url: str, num_requests: int = 10):
    """基准测试: 普通爬虫"""
    log.info("="*60)
    log.info("🔴 基准测试: 普通爬虫(暴力重试)")
    log.info("="*60)
    
    crawler = NaiveCrawler(target_url, max_retries=10)
    
    success_count = 0
    failed_count = 0
    total_time = 0
    
    for i in range(num_requests):
        start = time.time()
        try:
            result = await crawler.fetch()
            success_count += 1
            elapsed = time.time() - start
            total_time += elapsed
            log.info(f"✅ 请求 {i+1}/{num_requests} 成功 (耗时{elapsed:.2f}s)")
        
        except Exception as e:
            failed_count += 1
            elapsed = time.time() - start
            total_time += elapsed
            log.error(f"❌ 请求 {i+1}/{num_requests} 失败 (耗时{elapsed:.2f}s)")
    
    # 统计
    success_rate = success_count / num_requests * 100 if num_requests > 0 else 0
    avg_time = total_time / num_requests if num_requests > 0 else 0
    
    log.info("")
    log.info("📊 普通爬虫统计:")
    log.info(f"   成功: {success_count}/{num_requests} ({success_rate:.1f}%)")
    log.info(f"   失败: {failed_count}/{num_requests}")
    log.info(f"   平均耗时: {avg_time:.2f}s")
    log.info(f"   总HTTP请求: {crawler.stats['total_requests']}")
    log.info("")
    
    return {
        "success_rate": success_rate,
        "avg_time": avg_time,
        "total_http_requests": crawler.stats['total_requests'],
    }


async def benchmark_advanced_crawler(target_url: str, num_requests: int = 10):
    """基准测试: 高级爬虫"""
    log.info("="*60)
    log.info("🟢 基准测试: 高级爬虫(智能策略)")
    log.info("="*60)
    
    client = AdvancedCrawlerClient(
        target_url,
        enable_connection_pool=True,
        enable_health_probe=False,  # 本地测试不需要
        enable_smart_retry=True,
        pool_size=3,
        max_retries=10,
    )
    
    await client.initialize()
    
    success_count = 0
    failed_count = 0
    total_time = 0
    
    for i in range(num_requests):
        start = time.time()
        try:
            result = await client.fetch("/")
            success_count += 1
            elapsed = time.time() - start
            total_time += elapsed
            log.info(f"✅ 请求 {i+1}/{num_requests} 成功 (耗时{elapsed:.2f}s)")
        
        except Exception as e:
            failed_count += 1
            elapsed = time.time() - start
            total_time += elapsed
            log.error(f"❌ 请求 {i+1}/{num_requests} 失败 (耗时{elapsed:.2f}s): {e}")
    
    # 统计
    success_rate = success_count / num_requests * 100 if num_requests > 0 else 0
    avg_time = total_time / num_requests if num_requests > 0 else 0
    
    stats = client.get_stats()
    
    log.info("")
    log.info("📊 高级爬虫统计:")
    log.info(f"   成功: {success_count}/{num_requests} ({success_rate:.1f}%)")
    log.info(f"   失败: {failed_count}/{num_requests}")
    log.info(f"   平均耗时: {avg_time:.2f}s")
    log.info(f"   总HTTP请求: {stats['total_requests']}")
    log.info(f"   重试次数: {stats['retries_count']}")
    
    if 'retry_manager' in stats:
        rm_stats = stats['retry_manager']
        log.info(f"   智能重试成功率: {rm_stats['recent_success_rate']*100:.1f}%")
    
    if 'connection_pool' in stats:
        cp_stats = stats['connection_pool']
        log.info(f"   连接池统计: {cp_stats}")
    
    log.info("")
    
    await client.close()
    
    return {
        "success_rate": success_rate,
        "avg_time": avg_time,
        "total_http_requests": stats['total_requests'],
        "retries": stats['retries_count'],
    }


async def run_comparison_test():
    """运行对比测试"""
    # 目标URL(测试服务器)
    target_url = "http://localhost:8080"
    num_requests = 20  # 每个客户端发送20次请求
    
    log.info("\n" + "🎯 开始对比测试...")
    log.info(f"目标: {target_url}")
    log.info(f"每个客户端请求次数: {num_requests}\n")
    
    # 等待服务器启动
    log.info("等待测试服务器启动(5秒)...")
    await asyncio.sleep(5)
    
    # 测试1: 普通爬虫
    naive_results = await benchmark_naive_crawler(target_url, num_requests)
    
    # 等待一下
    await asyncio.sleep(3)
    
    # 测试2: 高级爬虫
    advanced_results = await benchmark_advanced_crawler(target_url, num_requests)
    
    # 对比分析
    log.info("="*60)
    log.info("📈 对比分析")
    log.info("="*60)
    
    log.info(f"\n成功率对比:")
    log.info(f"  普通爬虫: {naive_results['success_rate']:.1f}%")
    log.info(f"  高级爬虫: {advanced_results['success_rate']:.1f}%")
    log.info(f"  提升: {advanced_results['success_rate'] - naive_results['success_rate']:.1f}%")
    
    log.info(f"\n平均耗时对比:")
    log.info(f"  普通爬虫: {naive_results['avg_time']:.2f}s")
    log.info(f"  高级爬虫: {advanced_results['avg_time']:.2f}s")
    
    log.info(f"\nHTTP请求数对比:")
    log.info(f"  普通爬虫: {naive_results['total_http_requests']} 次")
    log.info(f"  高级爬虫: {advanced_results['total_http_requests']} 次")
    
    if advanced_results['success_rate'] > naive_results['success_rate']:
        log.info(f"\n✅ 高级爬虫胜出! 成功率提升 {advanced_results['success_rate'] - naive_results['success_rate']:.1f}%")
    else:
        log.info(f"\n⚠️  测试结果不理想,可能需要调整参数")
    
    log.info("\n" + "="*60)


async def quick_test():
    """快速测试单个请求"""
    target_url = "http://localhost:8080"
    
    log.info("快速测试: 发送单个请求")
    
    client = AdvancedCrawlerClient(
        target_url,
        enable_connection_pool=True,
        enable_health_probe=False,
        enable_smart_retry=True,
        max_retries=5,
    )
    
    await client.initialize()
    
    try:
        result = await client.fetch("/")
        log.info(f"✅ 成功! 响应: {result[:200]}...")
    except Exception as e:
        log.error(f"❌ 失败: {e}")
    
    stats = client.get_stats()
    log.info(f"统计: {stats}")
    
    await client.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "quick":
        # 快速测试
        asyncio.run(quick_test())
    else:
        # 完整对比测试
        asyncio.run(run_comparison_test())
