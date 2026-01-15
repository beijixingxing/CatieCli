from typing import Optional, Any
import asyncio
from concurrent.futures import ThreadPoolExecutor
from app.config import settings

# 尝试导入 redis，如果失败则使用内存缓存作为备选
redis = None
try:
    import redis as redis_module
    redis = redis_module
    print("✅ 成功导入 redis 模块")
except ImportError as e:
    print(f"⚠️ 无法导入 redis 模块: {e}")
    print("   将使用内存缓存作为备选")


class RedisService:
    """
    Redis服务封装类
    支持配置驱动，可通过环境变量控制是否启用
    如果Redis不可用，自动降级为内存缓存
    """
    
    def __init__(self):
        # 基本配置
        self.enabled = settings.redis_enabled and redis is not None
        self.redis_url = settings.redis_url
        self.redis_password = settings.redis_password
        self.redis_db = settings.redis_db
        self.key_prefix = settings.redis_key_prefix
        
        # Redis 集群配置
        self.redis_cluster = settings.redis_cluster
        self.redis_cluster_nodes = settings.redis_cluster_nodes
        
        # Redis客户端和连接状态
        self.client = None
        self.connected = False
        
        # 线程池，用于执行同步Redis操作
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # 内存缓存作为备选
        self.memory_cache = {}
        self.memory_expires = {}
    
    def _get_key(self, key: str) -> str:
        """
        获取带前缀的完整键名
        """
        return f"{self.key_prefix}{key}"
    
    async def init_redis(self):
        """
        初始化Redis连接
        """
        print(f"🔍 开始初始化Redis...")
        print(f"   启用状态: {self.enabled}")
        print(f"   Redis URL: {self.redis_url}")
        print(f"   数据库: {self.redis_db}")
        print(f"   集群模式: {self.redis_cluster}")
        print(f"   集群节点: {self.redis_cluster_nodes}")
        
        if not self.enabled:
            print("⏭️ Redis已禁用，将使用内存缓存")
            self.connected = False
            return False
        
        try:
            print("   正在连接Redis...")
            
            if self.redis_cluster:
                # Redis集群模式
                print("   正在创建Redis集群客户端...")
                
                try:
                    from redis.cluster import RedisCluster
                    
                    # 从URL解析集群节点
                    if not self.redis_cluster_nodes:
                        # 从主节点URL创建基本节点列表
                        import urllib.parse
                        parsed_url = urllib.parse.urlparse(self.redis_url)
                        self.redis_cluster_nodes = [
                            f"redis://{parsed_url.hostname}:{parsed_url.port or 6379}"
                        ]
                        print(f"   自动生成集群节点: {self.redis_cluster_nodes}")
                    
                    # 解析第一个节点的主机和端口
                    import urllib.parse
                    parsed_node = urllib.parse.urlparse(self.redis_cluster_nodes[0])
                    host = parsed_node.hostname
                    port = parsed_node.port or 6379
                    
                    # 创建Redis集群客户端（使用更兼容的方式）
                    self.client = RedisCluster(
                        host=host,
                        port=port,
                        password=self.redis_password,
                        encoding="utf-8",
                        decode_responses=True,
                        skip_full_coverage_check=True  # 跳过完整覆盖检查，适合一主多从模式
                    )
                    print("   ✅ 成功创建RedisCluster客户端")
                except AttributeError as e:
                    # 如果from_urls方法不存在，回退到单节点模式
                    print(f"   ⚠️ RedisCluster.from_urls方法不存在，回退到单节点模式: {e}")
                    # 创建单节点客户端作为备选
                    self.client = redis.from_url(
                        self.redis_url,
                        password=self.redis_password,
                        db=self.redis_db,
                        encoding="utf-8",
                        decode_responses=True
                    )
                except Exception as e:
                    # 其他错误，回退到单节点模式
                    print(f"   ⚠️ 创建RedisCluster客户端失败，回退到单节点模式: {e}")
                    # 创建单节点客户端作为备选
                    self.client = redis.from_url(
                        self.redis_url,
                        password=self.redis_password,
                        db=self.redis_db,
                        encoding="utf-8",
                        decode_responses=True
                    )
            else:
                # 单机Redis模式
                print("   正在创建Redis单机客户端...")
                # 创建Redis客户端
                self.client = redis.from_url(
                    self.redis_url,
                    password=self.redis_password,
                    db=self.redis_db,
                    encoding="utf-8",
                    decode_responses=True
                )
            
            # 测试连接
            print("   正在测试连接...")
            # 使用线程池执行同步ping操作
            pong = await asyncio.get_event_loop().run_in_executor(
                self.executor, self.client.ping
            )
            
            if pong:
                self.connected = True
                print(f"✅ Redis连接成功! PONG: {pong}")
                print(f"   客户端类型: {type(self.client).__name__}")
                return True
            else:
                print("❌ Redis PING返回False")
                self.connected = False
                return False
        except Exception as e:
            print(f"❌ Redis连接失败: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            self.connected = False
            return False
    
    async def close_redis(self):
        """
        关闭Redis连接
        """
        if self.client and self.connected:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    self.executor, self.client.close
                )
                print("✅ Redis连接已关闭")
            except Exception as e:
                print(f"⚠️ 关闭Redis连接失败: {e}")
        
        # 关闭线程池
        self.executor.shutdown(wait=True)
    
    # ---------------------------
    # Redis操作方法 - 支持异步调用
    # ---------------------------
    
    async def get(self, key: str) -> Optional[str]:
        """
        获取Redis缓存值
        如果Redis不可用，使用内存缓存
        """
        full_key = self._get_key(key)
        
        # 如果Redis可用，尝试从Redis获取
        if self.connected:
            try:
                return await asyncio.get_event_loop().run_in_executor(
                    self.executor, self.client.get, full_key
                )
            except Exception as e:
                print(f"⚠️ Redis get 失败: {e}")
        
        # Redis不可用，使用内存缓存
        import time
        current_time = time.time()
        if full_key in self.memory_expires and current_time > self.memory_expires[full_key]:
            # 缓存已过期
            del self.memory_cache[full_key]
            del self.memory_expires[full_key]
            return None
        return self.memory_cache.get(full_key)
    
    async def set(self, key: str, value: str, expire: Optional[int] = None) -> bool:
        """
        设置Redis缓存值
        如果Redis不可用，使用内存缓存
        """
        full_key = self._get_key(key)
        
        # 如果Redis可用，尝试设置到Redis
        if self.connected:
            try:
                if expire:
                    await asyncio.get_event_loop().run_in_executor(
                        self.executor, self.client.setex, full_key, expire, value
                    )
                else:
                    await asyncio.get_event_loop().run_in_executor(
                        self.executor, self.client.set, full_key, value
                    )
                return True
            except Exception as e:
                print(f"⚠️ Redis set 失败: {e}")
        
        # Redis不可用，使用内存缓存
        import time
        self.memory_cache[full_key] = value
        if expire:
            self.memory_expires[full_key] = time.time() + expire
        return True
    
    async def delete(self, key: str) -> bool:
        """
        删除Redis缓存值
        如果Redis不可用，删除内存缓存
        """
        full_key = self._get_key(key)
        
        # 如果Redis可用，尝试从Redis删除
        if self.connected:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    self.executor, self.client.delete, full_key
                )
                return True
            except Exception as e:
                print(f"⚠️ Redis delete 失败: {e}")
        
        # Redis不可用，删除内存缓存
        if full_key in self.memory_cache:
            del self.memory_cache[full_key]
        if full_key in self.memory_expires:
            del self.memory_expires[full_key]
        return True
    
    async def get_json(self, key: str) -> Optional[Any]:
        """
        获取JSON格式的Redis缓存
        """
        import json
        value = await self.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return None
    
    async def set_json(self, key: str, value: Any, expire: Optional[int] = None) -> bool:
        """
        设置JSON格式的Redis缓存
        """
        import json
        json_value = json.dumps(value, ensure_ascii=False)
        return await self.set(key, json_value, expire)
    
    async def exists(self, key: str) -> bool:
        """
        检查键是否存在
        """
        full_key = self._get_key(key)
        
        # 如果Redis可用，尝试从Redis检查
        if self.connected:
            try:
                return await asyncio.get_event_loop().run_in_executor(
                    self.executor, self.client.exists, full_key
                ) > 0
            except Exception as e:
                print(f"⚠️ Redis exists 失败: {e}")
        
        # Redis不可用，检查内存缓存
        import time
        current_time = time.time()
        if full_key in self.memory_expires and current_time > self.memory_expires[full_key]:
            # 缓存已过期
            del self.memory_cache[full_key]
            del self.memory_expires[full_key]
            return False
        return full_key in self.memory_cache


# 创建全局Redis服务实例
redis_service = RedisService()
