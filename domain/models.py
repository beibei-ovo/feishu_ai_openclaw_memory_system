from enum import Enum
from uuid import UUID
from datetime import datetime
from typing import Optional, Dict, List


class MemoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DEPRECATED = "DEPRECATED"


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ContentType(str, Enum):
    TEXT = "text"
    CODE = "code"
    FEEDBACK = "feedback"
    SUMMARY = "summary"


class CodeMeta:
    def __init__(
        self,
        lang: Optional[str] = None,
        task: Optional[str] = None,
        snippet_id: Optional[str] = None,
    ):
        self.lang = lang
        self.task = task
        self.snippet_id = snippet_id

    def to_dict(self) -> Dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Dict) -> "CodeMeta":
        return cls(
            lang=data.get("lang"),
            task=data.get("task"),
            snippet_id=data.get("snippet_id"),
        )


class UnifiedMemory:
    def __init__(
        self,
        memory_id: UUID,
        session_id: UUID,
        turn_id: int,
        topic: str,
        content: str,
        content_type: ContentType = ContentType.TEXT,
        role: Role = Role.USER,
        execution_params: Optional[Dict[str, str]] = None,
        code_meta: Optional[CodeMeta] = None,
        status: MemoryStatus = MemoryStatus.ACTIVE,
        tags: Optional[List[str]] = None,
        token_count: Optional[int] = None,
        created_at: Optional[datetime] = None,
        supersedes_id: Optional[UUID] = None,
        # 上下文环境字段 - 用于项目级记忆隔离
        user_id: Optional[str] = None,
        project_path: Optional[str] = None,
        git_branch: Optional[str] = None,
        environment: Optional[str] = None,  # dev/test/prod
    ):
        self.memory_id = memory_id
        self.session_id = session_id
        self.turn_id = turn_id
        self.topic = topic
        self.content = content
        self.content_type = content_type
        self.role = role
        self.execution_params = execution_params or {}
        self.code_meta = code_meta
        self.status = status
        self.tags = tags or []
        self.token_count = token_count
        self.created_at = created_at or datetime.utcnow()
        self.supersedes_id = supersedes_id
        # 上下文环境
        self.user_id = user_id
        self.project_path = project_path
        self.git_branch = git_branch
        self.environment = environment

    def __eq__(self, other):
        if not isinstance(other, UnifiedMemory):
            return False
        return self.memory_id == other.memory_id

    def __hash__(self):
        return hash(self.memory_id)