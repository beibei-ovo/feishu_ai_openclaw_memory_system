from abc import ABC, abstractmethod
from uuid import UUID
from typing import List, Optional, Dict
from enum import Enum
from .models import UnifiedMemory, MemoryStatus


class ConflictType(Enum):
    """冲突类型枚举"""
    OVERWRITE = "overwrite"    # 完全覆盖
    MERGE = "merge"            # 增量合并
    NO_CONFLICT = "no_conflict"  # 无冲突


class MemoryRepository(ABC):
    @abstractmethod
    def save(self, memory: UnifiedMemory) -> UnifiedMemory:
        pass

    @abstractmethod
    def get_by_id(self, memory_id: UUID) -> Optional[UnifiedMemory]:
        pass

    @abstractmethod
    def find_by_topic(self, topic: str) -> List[UnifiedMemory]:
        pass

    @abstractmethod
    def find_active_by_topic(self, topic: str) -> Optional[UnifiedMemory]:
        pass

    @abstractmethod
    def find_all_active(self) -> List[UnifiedMemory]:
        pass

    @abstractmethod
    def update_status(self, memory_id: UUID, status: MemoryStatus) -> UnifiedMemory:
        pass

    @abstractmethod
    def search_by_topic_fuzzy(self, query: str) -> List[UnifiedMemory]:
        pass

    @abstractmethod
    def find_by_session(self, session_id: UUID) -> List[UnifiedMemory]:
        pass

    @abstractmethod
    def find_by_tags(self, tags: List[str]) -> List[UnifiedMemory]:
        pass
    
    @abstractmethod
    def search_with_context(
        self,
        topic_query: Optional[str] = None,
        user_id: Optional[str] = None,
        project_path: Optional[str] = None,
        git_branch: Optional[str] = None,
        environment: Optional[str] = None,
        status: Optional[MemoryStatus] = MemoryStatus.ACTIVE,
    ) -> List[UnifiedMemory]:
        """
        基于上下文环境的记忆搜索 - 实现项目级/租户级隔离
        
        Args:
            topic_query: 主题关键词（模糊查询）
            user_id: 用户ID
            project_path: 项目路径
            git_branch: Git分支
            environment: 环境（dev/test/prod）
            status: 记忆状态，默认只查找活跃的
        """
        pass


class ConflictDetector(ABC):
    @abstractmethod
    def detect_conflict(self, topic: str) -> Optional[UnifiedMemory]:
        pass

    @abstractmethod
    def resolve_conflict(self, new_memory: UnifiedMemory) -> UnifiedMemory:
        pass


class LLMClient(ABC):
    @abstractmethod
    def extract_memory(self, context: str) -> Dict:
        pass
    
    @abstractmethod
    def resolve_memory_conflict(self, old_memory: UnifiedMemory, new_memory: UnifiedMemory) -> Dict:
        """
        解决新旧记忆冲突
        
        Returns:
            Dict containing:
                - conflict_type: ConflictType (overwrite/merge/no_conflict)
                - merged_memory: 合并后的记忆 Dict (仅 merge 类型需要)
                - explanation: 冲突解决解释
        """
        pass


class FeishuWebhookHandler(ABC):
    @abstractmethod
    def handle_webhook(self, event: Dict) -> Optional[str]:
        pass