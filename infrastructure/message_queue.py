import json
import time
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta


class MessageQueue(ABC):
    """消息队列抽象基类"""
    
    @abstractmethod
    def enqueue(self, message: Dict[str, Any]) -> str:
        """将消息推入队列"""
        pass
    
    @abstractmethod
    def dequeue_batch(self, max_size: int = 10) -> List[Dict[str, Any]]:
        """批量从队列获取消息"""
        pass
    
    @abstractmethod
    def get_queue_length(self) -> int:
        """获取队列当前长度"""
        pass
    
    @abstractmethod
    def close(self) -> None:
        """关闭连接"""
        pass


class RedisListQueue(MessageQueue):
    """基于 Redis List 的消息队列实现"""
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        queue_name: str = "feishu:messages",
    ):
        try:
            import redis
            self.redis_client = redis.from_url(redis_url)
            self.queue_name = queue_name
            self._connected = True
        except ImportError:
            raise ImportError("Redis not installed. Please install it with `pip install redis`")
    
    def enqueue(self, message: Dict[str, Any]) -> str:
        """将消息推入队列"""
        message["timestamp"] = time.time()
        message_id = str(int(time.time() * 1000)) + "-" + str(self.get_queue_length())
        message["id"] = message_id
        
        self.redis_client.rpush(self.queue_name, json.dumps(message))
        return message_id
    
    def dequeue_batch(self, max_size: int = 10) -> List[Dict[str, Any]]:
        """批量从队列获取消息（阻塞式，避免循环空转）"""
        messages = []
        
        # 使用阻塞弹出，避免空转浪费CPU
        for _ in range(max_size):
            try:
                result = self.redis_client.blpop(self.queue_name, timeout=1.0)
                if result:
                    _, message_json = result
                    message = json.loads(message_json)
                    messages.append(message)
                else:
                    break  # 超时，返回当前已获取的消息
            except Exception:
                break
        
        return messages
    
    def get_queue_length(self) -> int:
        """获取队列当前长度"""
        return self.redis_client.llen(self.queue_name)
    
    def close(self) -> None:
        """关闭连接"""
        if self._connected:
            self.redis_client.close()
            self._connected = False


class InMemoryQueue(MessageQueue):
    """简单的内存队列（用于本地测试，不需要 Redis）"""
    
    def __init__(self):
        import queue
        self.queue = queue.Queue()
        self._closed = False
    
    def enqueue(self, message: Dict[str, Any]) -> str:
        message["timestamp"] = time.time()
        message_id = str(int(time.time() * 1000))
        message["id"] = message_id
        self.queue.put(message)
        return message_id
    
    def dequeue_batch(self, max_size: int = 10) -> List[Dict[str, Any]]:
        messages = []
        for _ in range(max_size):
            try:
                msg = self.queue.get_nowait()
                messages.append(msg)
            except Exception:
                break
        return messages
    
    def get_queue_length(self) -> int:
        return self.queue.qsize()
    
    def close(self) -> None:
        self._closed = True


class RedisStreamQueue(MessageQueue):
    """基于 Redis Stream 的消息队列实现（支持多消费者组）"""
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        stream_name: str = "feishu:messages:stream",
        group_name: str = "feishu_consumer_group",
        consumer_name: str = "worker_1",
    ):
        try:
            import redis
            self.redis_client = redis.from_url(redis_url)
            self.stream_name = stream_name
            self.group_name = group_name
            self.consumer_name = consumer_name
            self._connected = True
            
            # 尝试创建消费者组（已存在则忽略）
            try:
                self.redis_client.xgroup_create(
                    name=self.stream_name,
                    groupname=self.group_name,
                    id="$",
                    mkstream=True
                )
            except redis.exceptions.ResponseError as e:
                if "already exists" not in str(e).lower():
                    raise
        except ImportError:
            raise ImportError("Redis not installed. Please install it with `pip install redis`")
    
    def enqueue(self, message: Dict[str, Any]) -> str:
        """将消息推入 Stream"""
        message["timestamp"] = time.time()
        # Redis Stream 的字段需要是字符串
        stream_fields = {k: str(v) if isinstance(v, (int, float)) else json.dumps(v) 
                         for k, v in message.items()}
        
        message_id = self.redis_client.xadd(self.stream_name, stream_fields)
        return message_id
    
    def dequeue_batch(self, max_size: int = 10, timeout_ms: int = 5000) -> List[Dict[str, Any]]:
        """从 Stream 消费一批消息"""
        messages = []
        
        try:
            result = self.redis_client.xreadgroup(
                groupname=self.group_name,
                consumername=self.consumer_name,
                streams={self.stream_name: ">"},
                count=max_size,
                block=timeout_ms
            )
            
            for stream, entries in result:
                for entry_id, fields in entries:
                    # 解析字段
                    message = {}
                    for k, v in fields.items():
                        try:
                            # 尝试解析 JSON
                            message[k.decode()] = json.loads(v.decode())
                        except (json.JSONDecodeError, AttributeError):
                            # 如果解析失败，保留原始字符串
                            message[k.decode()] = v.decode()
                    
                    message["_entry_id"] = entry_id
                    messages.append(message)
                    
                    # 确认消息已消费
                    self.redis_client.xack(self.stream_name, self.group_name, entry_id)
        except Exception:
            pass
        
        return messages
    
    def get_queue_length(self) -> int:
        """获取 Stream 当前长度"""
        try:
            info = self.redis_client.xinfo_stream(self.stream_name)
            return info.get("length", 0)
        except Exception:
            return 0
    
    def close(self) -> None:
        """关闭连接"""
        if self._connected:
            self.redis_client.close()
            self._connected = False


# 工厂函数，根据配置创建消息队列
def create_message_queue(config: Optional[Dict[str, Any]] = None) -> MessageQueue:
    """
    创建消息队列实例（自动降级：Redis 不可用时使用内存队列）
    
    Args:
        config: 配置字典，可包含：
            - type: "redis_list" (默认) 或 "redis_stream" 或 "memory"
            - redis_url: Redis 连接 URL
            - queue_name/stream_name: 队列/Stream 名称
            - group_name/consumer_name: 仅 stream 模式使用
    
    Returns:
        MessageQueue 实例
    """
    config = config or {}
    queue_type = config.get("type", "redis_list")
    
    if queue_type == "memory":
        print("Using in-memory queue for local testing")
        return InMemoryQueue()
    
    # 尝试创建 Redis 队列，如果失败则回退到内存队列
    try:
        if queue_type == "redis_list":
            return RedisListQueue(
                redis_url=config.get("redis_url", "redis://localhost:6379/0"),
                queue_name=config.get("queue_name", "feishu:messages")
            )
        elif queue_type == "redis_stream":
            return RedisStreamQueue(
                redis_url=config.get("redis_url", "redis://localhost:6379/0"),
                stream_name=config.get("stream_name", "feishu:messages:stream"),
                group_name=config.get("group_name", "feishu_consumer_group"),
                consumer_name=config.get("consumer_name", "worker_1")
            )
    except Exception as e:
        print(f"Warning: Redis not available ({e}), falling back to in-memory queue")
        return InMemoryQueue()
    
    raise ValueError(f"Unsupported queue type: {queue_type}")
