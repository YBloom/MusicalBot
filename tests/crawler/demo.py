"""
简单演示 - 展示高级爬虫的威力
运行此脚本可以快速看到效果
"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from services.crawler.advanced_client import AdvancedCrawlerClient
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


async def demo():
    """演示脚本"""
    
    print("\n" + "="*60)
    print("🎯 高级爬虫演示")
    print("="*60)
    
    print("\n⚙️  配置:")
    print("   - 启用连接池: ✅")
    print("   - 启用智能重试: ✅")
    print("   - 启用健康探测: ❌ (本地测试不需要)")
    print("   - 最大重试: 10次")
    print("   - 连接池大小: 3")
    
    # 创建客户端
    client = AdvancedCrawlerClient(
        base_url="http://localhost:8080",
        enable_connection_pool=True,
        enable_health_probe=False,
        enable_smart_retry=True,
        pool_size=3,
        max_retries=10,
    )
    
    print("\n🚀 初始化客户端...")
    await client.initialize()
    
    print("\n📡 开始发送请求...")
    
    # 发送5次请求
    for i in range(1, 6):
        print(f"\n第 {i} 次请求:")
        try:
            result = await client.fetch("/")
            print(f"   ✅ 成功!")
            
            # 解析响应
            import json
            try:
                data = json.loads(result)
                print(f"   📊 服务器统计: 成功{data['stats']['success']}, "
                      f"拒绝{data['stats']['rejected']}, "
                      f"超时{data['stats']['timeout']}")
            except:
                pass
        
        except Exception as e:
            print(f"   ❌ 失败: {type(e).__name__}")
    
    # 获取统计
    print("\n" + "="*60)
    print("📊 客户端统计")
    print("="*60)
    
    stats = client.get_stats()
    
    print(f"\n总请求数: {stats['total_requests']}")
    print(f"成功请求: {stats['successful_requests']}")
    print(f"失败请求: {stats['failed_requests']}")
    print(f"成功率: {stats['success_rate']*100:.1f}%")
    print(f"重试次数: {stats['retries_count']}")
    
    if 'retry_manager' in stats:
        rm = stats['retry_manager']
        print(f"\n智能重试统计:")
        print(f"   当前基础延迟: {rm['current_base_delay']:.2f}s")
        print(f"   当前放弃概率: {rm['current_give_up_prob']*100:.1f}%")
        print(f"   近期成功率: {rm['recent_success_rate']*100:.1f}%")
    
    if 'connection_pool' in stats:
        cp = stats['connection_pool']
        print(f"\n连接池统计:")
        print(f"   池大小: {cp['pool_size']}")
        print(f"   健康连接: {cp['healthy_connections']}")
        print(f"   平均响应: {cp['avg_response_time']:.2f}s")
    
    # 关闭
    print("\n🛑 关闭客户端...")
    await client.close()
    
    print("\n" + "="*60)
    print("✅ 演示完成!")
    print("="*60 + "\n")


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║     高负载服务器爬虫解决方案 - 演示脚本                  ║
║                                                          ║
║  确保测试服务器已启动:                                    ║
║  python tests/crawler/test_server.py                    ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    asyncio.run(demo())
