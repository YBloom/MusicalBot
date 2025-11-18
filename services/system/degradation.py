"""
服务降级策略
在网络故障时提供降级服务,而非完全不可用
"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import json
import os


class ServiceDegradation:
    """服务降级管理器"""
    
    def __init__(self, cache_dir: str = "./cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        
        # 缓存策略配置
        self.cache_ttl = {
            "hulaquan_events": 3600 * 12,  # 呼啦圈数据缓存12小时
            "saoju_data": 3600 * 24,       # 扫剧数据缓存24小时
        }
    
    def save_cache(self, key: str, data: Any) -> bool:
        """保存缓存数据"""
        try:
            cache_file = os.path.join(self.cache_dir, f"{key}.json")
            cache_data = {
                "timestamp": datetime.now().isoformat(),
                "data": data
            }
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"缓存保存失败: {e}")
            return False
    
    def load_cache(self, key: str, max_age_seconds: Optional[int] = None) -> Optional[Any]:
        """
        加载缓存数据
        
        Args:
            key: 缓存键
            max_age_seconds: 最大缓存时间(秒),None表示使用默认TTL
        
        Returns:
            缓存数据或None(如果缓存不存在或过期)
        """
        try:
            cache_file = os.path.join(self.cache_dir, f"{key}.json")
            
            if not os.path.exists(cache_file):
                return None
            
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # 检查缓存时效
            cached_time = datetime.fromisoformat(cache_data["timestamp"])
            age_seconds = (datetime.now() - cached_time).total_seconds()
            
            ttl = max_age_seconds if max_age_seconds is not None else self.cache_ttl.get(key, 3600)
            
            if age_seconds > ttl:
                return None
            
            return cache_data["data"]
        
        except Exception as e:
            print(f"缓存加载失败: {e}")
            return None
    
    def get_cached_or_stale(self, key: str) -> tuple[Optional[Any], bool]:
        """
        获取缓存数据(即使过期也返回)
        
        Returns:
            (data, is_stale): 数据和是否过期的标志
        """
        try:
            cache_file = os.path.join(self.cache_dir, f"{key}.json")
            
            if not os.path.exists(cache_file):
                return None, True
            
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            # 检查是否过期
            cached_time = datetime.fromisoformat(cache_data["timestamp"])
            age_seconds = (datetime.now() - cached_time).total_seconds()
            ttl = self.cache_ttl.get(key, 3600)
            
            is_stale = age_seconds > ttl
            
            return cache_data["data"], is_stale
        
        except Exception as e:
            print(f"缓存加载失败: {e}")
            return None, True


# 全局降级管理器
degradation_manager = ServiceDegradation()


def degradation_notice(is_stale: bool, cache_age: str = "") -> str:
    """生成降级提示文本"""
    if is_stale:
        return (
            f"\n\n⚠️ 当前网络异常，以上为缓存数据{cache_age}\n"
            "数据可能已过期，请稍后重试获取最新信息"
        )
    else:
        return (
            f"\n\n💡 当前网络异常，以上为缓存数据{cache_age}\n"
            "数据在有效期内，但可能不是最新的"
        )
