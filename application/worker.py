import time
import threading
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from uuid import uuid4

from app.infrastructure.message_queue import MessageQueue, create_message_queue
from app.domain.models import UnifiedMemory
from app.application.services import LLMExtractor


class SimpleDataFilter:
    """简化的数据过滤器（临时替代）"""
    
    def stage1_format_preprocessing(self, text: str) -> str:
        return text.strip()
    
    def stage2_value_judgment(self, text: str) -> tuple[bool, float]:
        return True, 0.9
    
    def _extract_tags(self, text: str) -> List[str]:
        return []


class SlidingWindowProcessor:
    """滑动窗口消息处理器"""
    
    def __init__(
        self,
        message_queue: MessageQueue,
        llm_extractor: LLMExtractor,
        data_filter: Optional[SimpleDataFilter] = None,
        window_size: int = 10,  # 窗口大小（消息数）
        window_timeout: int = 300,  # 窗口超时（秒，默认5分钟）
        batch_extraction: bool = True,  # 是否批量抽取
    ):
        self.message_queue = message_queue
        self.llm_extractor = llm_extractor
        self.data_filter = data_filter or SimpleDataFilter()
        self.window_size = window_size
        self.window_timeout = window_timeout
        self.batch_extraction = batch_extraction
        
        self.current_window: List[Dict[str, Any]] = []
        self.last_message_time: Optional[float] = None
        self.lock = threading.Lock()
        self.running = False
        
        self.logger = logging.getLogger(__name__)
        logging.basicConfig(level=logging.INFO)
    
    def _should_process_window(self) -> bool:
        """判断是否应该处理当前窗口"""
        with self.lock:
            if len(self.current_window) >= self.window_size:
                return True
            if (self.current_window and 
                self.last_message_time and 
                (time.time() - self.last_message_time) > self.window_timeout):
                return True
            return False
    
    def _process_window(self):
        """处理当前窗口的所有消息"""
        with self.lock:
            if not self.current_window:
                return
            
            window = self.current_window.copy()
            self.current_window = []
            self.last_message_time = None
        
        self.logger.info(f"Processing window with {len(window)} messages")
        
        try:
            # 提取所有消息的内容
            messages = [msg.get("content", "") for msg in window]
            combined_context = "\n".join(messages)
            
            # 为当前窗口创建统一的 session_id
            session_id = uuid4()
            
            if self.batch_extraction and len(window) > 1:
                # 批量抽取：一次 LLM 调用处理整个窗口
                # 使用第一条消息的上下文信息作为整个窗口的上下文
                first_msg = window[0] if window else {}
                self.llm_extractor.extract_and_save(
                    context=combined_context,
                    session_id=session_id,
                    turn_id=1,
                    tags=self.data_filter._extract_tags(combined_context),
                    user_id=first_msg.get("sender_id"),
                    project_path=first_msg.get("chat_id"),  # 使用 chat_id 作为项目路径
                )
            else:
                # 逐个处理
                for i, msg in enumerate(window, 1):
                    content = msg.get("content", "")
                    self.llm_extractor.extract_and_save(
                        context=content,
                        session_id=session_id,
                        turn_id=i,
                        tags=self.data_filter._extract_tags(content),
                        user_id=msg.get("sender_id"),
                        project_path=msg.get("chat_id"),  # 使用 chat_id 作为项目路径
                    )
            
            self.logger.info(f"Successfully processed window with {len(window)} messages")
        except Exception as e:
            self.logger.error(f"Error processing window: {e}", exc_info=True)
    
    def _add_to_window(self, message: Dict[str, Any]):
        """将单条消息添加到窗口"""
        # 先经过数据过滤
        cleaned_content = self.data_filter.stage1_format_preprocessing(message.get("content", ""))
        valid, _ = self.data_filter.stage2_value_judgment(cleaned_content)
        
        if valid:
            with self.lock:
                self.current_window.append(message)
                self.last_message_time = time.time()
                self.logger.debug(f"Added message to window, current size: {len(self.current_window)}")
        else:
            self.logger.debug(f"Message filtered out, not added to window")
    
    def start(self):
        """启动 Worker 循环"""
        self.running = True
        self.logger.info(f"Worker started with window_size={self.window_size}, window_timeout={self.window_timeout}s")
        
        try:
            while self.running:
                # 从队列获取消息
                messages = self.message_queue.dequeue_batch(max_size=self.window_size)
                
                if messages:
                    self.logger.debug(f"Received {len(messages)} messages from queue")
                    for msg in messages:
                        self._add_to_window(msg)
                
                # 检查是否应该处理窗口
                if self._should_process_window():
                    self._process_window()
                
                # 短暂休眠，避免空转
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.logger.info("Worker interrupted by user")
            self.stop()
        except Exception as e:
            self.logger.error(f"Worker error: {e}", exc_info=True)
            self.stop()
    
    def stop(self):
        """停止 Worker"""
        self.running = False
        
        # 停止前处理剩余的消息
        with self.lock:
            if self.current_window:
                self.logger.info(f"Processing remaining {len(self.current_window)} messages before exit")
                self._process_window()
        
        self.message_queue.close()
        self.logger.info("Worker stopped")


def run_worker(
    queue_config: Optional[Dict[str, Any]] = None,
    llm_config: Optional[Dict[str, Any]] = None,
    window_size: int = 10,
    window_timeout: int = 300,
):
    """
    运行 Worker 主函数（可直接调用启动）
    
    Args:
        queue_config: 消息队列配置
        llm_config: LLM 配置
        window_size: 滑动窗口大小
        window_timeout: 窗口超时（秒）
    """
    # 创建消息队列
    mq = create_message_queue(queue_config)
    
    # 创建 LLM Extractor
    from app.infrastructure.llm_clients import DoubaoLLMClient, MockLLMClient
    from app.infrastructure.database import (
        create_session_factory, 
        SQLAlchemyMemoryRepository
    )
    from app.application.services import DefaultConflictDetector
    
    # 创建数据库会话和仓库
    session_factory = create_session_factory("sqlite:///./test.db")
    session = session_factory()
    repo = SQLAlchemyMemoryRepository(session)
    
    # 先创建 llm_client，再创建 conflict_detector（支持增量合并）
    use_mock = llm_config.get("use_mock", False) if llm_config else True
    if use_mock:
        llm_client = MockLLMClient()
    else:
        llm_client = DoubaoLLMClient(
            api_key=llm_config.get("api_key"),
            secret_key=llm_config.get("secret_key"),
        )
    
    conflict_detector = DefaultConflictDetector(repo, llm_client)
    extractor = LLMExtractor(llm_client, conflict_detector)
    
    # 创建并启动 Worker
    processor = SlidingWindowProcessor(
        message_queue=mq,
        llm_extractor=extractor,
        window_size=window_size,
        window_timeout=window_timeout,
    )
    
    processor.start()


if __name__ == "__main__":
    # 默认使用 Mock LLM 和内存队列（无需 Redis）
    run_worker(
        queue_config={"type": "memory"},
        llm_config={"use_mock": True},
        window_size=10,
        window_timeout=300,
    )
