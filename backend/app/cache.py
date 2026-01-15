"""
缓存系统，优先使用Redis，Redis不可用时回退到内存缓存
"""

import time
from typing import Any, Optional
from functools import wraps

# 导入Redis服务
from app.services.redis_service import redis_service

class SimpleCache:
    """缓存系统，优先使用Redis，Redis不可用时回退到内存缓存"""
    
    def __init__(self):
        # 内存缓存作为备选
        self._memory_cache = {}
        self._memory_expires = {}
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值，优先从Redis获取"""
        # 1. 尝试从Redis获取
        try:
            result = redis_service.get_json(key)
            if result is not None:
                return result
        except Exception as e:
            print(f"⚠️ Redis get 失败: {e}")
        
        # 2. 尝试从内存缓存获取
        if key not in self._memory_cache:
            return None
        if key in self._memory_expires and time.time() > self._memory_expires[key]:
            del self._memory_cache[key]
            del self._memory_expires[key]
            return None
        return self._memory_cache[key]
    
    def set(self, key: str, value: Any, ttl: int = 60):
        """设置缓存值，优先保存到Redis"""
        # 1. 保存到Redis
        try:
            redis_service.set_json(key, value, expire=ttl)
        except Exception as e:
            print(f"⚠️ Redis set 失败: {e}")
            # 2. 保存到内存缓存作为备选
            self._memory_cache[key] = value
            self._memory_expires[key] = time.time() + ttl
    
    def delete(self, key: str):
        """删除缓存"""
        # 1. 从Redis删除
        try:
            redis_service.delete(key)
        except Exception as e:
            print(f"⚠️ Redis delete 失败: {e}")
        
        # 2. 从内存缓存删除
        self._memory_cache.pop(key, None)
        self._memory_expires.pop(key, None)
    
    def clear(self):
        """清空所有缓存"""
        # 1. 清空Redis缓存（通过前缀匹配删除）
        try:
            keys = redis_service.get_keys("*")
            for key in keys:
                redis_service.delete(key)
        except Exception as e:
            print(f"⚠️ Redis clear 失败: {e}")
        
        # 2. 清空内存缓存
        self._memory_cache.clear()
        self._memory_expires.clear()
    
    def clear_prefix(self, prefix: str):
        """清除指定前缀的缓存"""
        # 1. 清除Redis中指定前缀的缓存
        try:
            keys = redis_service.get_keys(f"{prefix}*")
            for key in keys:
                redis_service.delete(key)
        except Exception as e:
            print(f"⚠️ Redis clear_prefix 失败: {e}")
        
        # 2. 清除内存缓存中指定前缀的缓存
        keys_to_delete = [k for k in self._memory_cache if k.startswith(prefix)]
        for key in keys_to_delete:
            self._memory_cache.pop(key, None)
            self._memory_expires.pop(key, None)


# 全局缓存实例
cache = SimpleCache()


# 缓存 key 前缀
CACHE_KEYS = {
    "stats": "stats:",           # 统计数据缓存
    "user": "user:",             # 用户信息缓存
    "creds": "creds:",           # 凭证列表缓存
    "quota": "quota:",           # 配额缓存
}


def cached(prefix: str, ttl: int = 30):
    """
    缓存装饰器
    用法：
    @cached("stats", ttl=10)
    async def get_stats():
        ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 生成缓存 key
            key = f"{prefix}:{func.__name__}:{hash(str(args) + str(kwargs))}"
            
            # 尝试从缓存获取
            result = cache.get(key)
            if result is not None:
                # 检查缓存结果是否为协程对象，如果是则重新执行函数
                if callable(getattr(result, "__await__", None)):
                    # 清除无效的协程对象缓存
                    cache.delete(key)
                else:
                    return result
            
            # 执行函数并缓存结果
            result = await func(*args, **kwargs)
            # 确保缓存的结果不是协程对象
            if not callable(getattr(result, "__await__", None)):
                cache.set(key, result, ttl)
            return result
        return wrapper
    return decorator


def invalidate_cache(prefix: str = None):
    """清除缓存"""
    if prefix:
        cache.clear_prefix(prefix)
    else:
        cache.clear()
