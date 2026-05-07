from sqlalchemy import create_engine, Column, String, DateTime, Enum, JSON, ForeignKey, Integer, Text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, relationship, Mapped, mapped_column
from uuid import uuid4, UUID as UUIDType
from datetime import datetime
from app.domain.models import MemoryStatus, Role, ContentType, CodeMeta, UnifiedMemory
from app.domain.interfaces import MemoryRepository
from typing import List, Optional, Any

class Base(DeclarativeBase):
    pass


class MemoryModel(Base):
    __tablename__ = "memories"

    memory_id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    session_id = Column(String, index=True, nullable=False)
    turn_id = Column(Integer, nullable=False, default=1)
    topic = Column(String, index=True, nullable=False)
    content = Column(Text, nullable=False)
    content_type = Column(Enum(ContentType), default=ContentType.TEXT, nullable=False)
    role = Column(Enum(Role), default=Role.USER, nullable=False)
    execution_params = Column(JSON, nullable=True)
    code_meta = Column(JSON, nullable=True)
    status = Column(Enum(MemoryStatus), default=MemoryStatus.ACTIVE, nullable=False)
    tags = Column(JSON, nullable=True)  # 用 JSON 代替 ARRAY，兼容 SQLite
    token_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    supersedes_id = Column(String, ForeignKey("memories.memory_id"), nullable=True)
    # 上下文环境字段 - 用于项目级记忆隔离
    user_id = Column(String, index=True, nullable=True)
    project_path = Column(String, index=True, nullable=True)
    git_branch = Column(String, index=True, nullable=True)
    environment = Column(String, index=True, nullable=True)

    superseded_memory = relationship(
        "MemoryModel",
        remote_side=[memory_id],
        backref="superseding_memory"
    )

    @classmethod
    def from_domain(cls, memory: UnifiedMemory) -> "MemoryModel":
        code_meta_dict = None
        if memory.code_meta:
            code_meta_dict = memory.code_meta.to_dict()

        return cls(
            memory_id=str(memory.memory_id),  # UUID 转字符串
            session_id=str(memory.session_id),  # UUID 转字符串
            turn_id=memory.turn_id,
            topic=memory.topic,
            content=memory.content,
            content_type=memory.content_type,
            role=memory.role,
            execution_params=memory.execution_params,
            code_meta=code_meta_dict,
            status=memory.status,
            tags=memory.tags,  # 直接存列表，JSON 字段会处理
            token_count=memory.token_count,
            created_at=memory.created_at,
            supersedes_id=str(memory.supersedes_id) if memory.supersedes_id else None,
            user_id=memory.user_id,
            project_path=memory.project_path,
            git_branch=memory.git_branch,
            environment=memory.environment,
        )

    def to_domain(self) -> UnifiedMemory:
        code_meta_obj = None
        if self.code_meta:
            code_meta_obj = CodeMeta.from_dict(self.code_meta)

        return UnifiedMemory(
            memory_id=UUIDType(self.memory_id),  # 字符串转 UUID
            session_id=UUIDType(self.session_id),  # 字符串转 UUID
            turn_id=self.turn_id,
            topic=self.topic,
            content=self.content,
            content_type=self.content_type,
            role=self.role,
            execution_params=self.execution_params or {},
            code_meta=code_meta_obj,
            status=self.status,
            tags=self.tags or [],
            token_count=self.token_count,
            created_at=self.created_at,
            supersedes_id=UUIDType(self.supersedes_id) if self.supersedes_id else None,
            user_id=self.user_id,
            project_path=self.project_path,
            git_branch=self.git_branch,
            environment=self.environment,
        )


class SQLAlchemyMemoryRepository(MemoryRepository):
    def __init__(self, session):
        self.session = session

    def save(self, memory: UnifiedMemory) -> UnifiedMemory:
        model = MemoryModel.from_domain(memory)
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return model.to_domain()

    def get_by_id(self, memory_id: UUIDType) -> Optional[UnifiedMemory]:
        model = self.session.query(MemoryModel).filter(
            MemoryModel.memory_id == memory_id
        ).first()
        return model.to_domain() if model else None

    def find_by_topic(self, topic: str) -> List[UnifiedMemory]:
        models = self.session.query(MemoryModel).filter(
            MemoryModel.topic == topic
        ).all()
        return [model.to_domain() for model in models]

    def find_active_by_topic(self, topic: str) -> Optional[UnifiedMemory]:
        model = self.session.query(MemoryModel).filter(
            MemoryModel.topic == topic,
            MemoryModel.status == MemoryStatus.ACTIVE
        ).first()
        return model.to_domain() if model else None

    def find_all_active(self) -> List[UnifiedMemory]:
        models = self.session.query(MemoryModel).filter(
            MemoryModel.status == MemoryStatus.ACTIVE
        ).all()
        return [model.to_domain() for model in models]

    def update_status(self, memory_id: UUIDType, status: MemoryStatus) -> UnifiedMemory:
        model = self.session.query(MemoryModel).filter(
            MemoryModel.memory_id == memory_id
        ).first()
        if not model:
            raise ValueError(f"Memory with id {memory_id} not found")
        model.status = status
        self.session.commit()
        self.session.refresh(model)
        return model.to_domain()

    def search_by_topic_fuzzy(self, query: str) -> List[UnifiedMemory]:
        models = self.session.query(MemoryModel).filter(
            MemoryModel.topic.ilike(f"%{query}%"),
            MemoryModel.status == MemoryStatus.ACTIVE
        ).all()
        return [model.to_domain() for model in models]

    def find_by_session(self, session_id: UUIDType) -> List[UnifiedMemory]:
        models = self.session.query(MemoryModel).filter(
            MemoryModel.session_id == session_id
        ).order_by(MemoryModel.turn_id).all()
        return [model.to_domain() for model in models]

    def find_by_tags(self, tags: List[str]) -> List[UnifiedMemory]:
        # 因为 tags 现在是 JSON，我们查询后在 Python 中过滤
        models = self.session.query(MemoryModel).filter(
            MemoryModel.status == MemoryStatus.ACTIVE
        ).all()
        
        # 在 Python 层面过滤有交集的标签
        result = []
        for model in models:
            model_tags = model.tags or []
            if any(tag in model_tags for tag in tags):
                result.append(model)
        
        return [model.to_domain() for model in result]
    
    def search_with_context(
        self,
        topic_query: Optional[str] = None,
        user_id: Optional[str] = None,
        project_path: Optional[str] = None,
        git_branch: Optional[str] = None,
        environment: Optional[str] = None,
        status: Optional[MemoryStatus] = MemoryStatus.ACTIVE,
    ) -> List[UnifiedMemory]:
        """基于上下文环境的记忆搜索 - 实现项目级/租户级隔离"""
        query = self.session.query(MemoryModel)
        
        # 状态过滤
        if status:
            query = query.filter(MemoryModel.status == status)
        
        # 主题模糊查询
        if topic_query:
            query = query.filter(MemoryModel.topic.ilike(f"%{topic_query}%"))
        
        # 上下文环境过滤 - 核心隔离逻辑
        # 注意：这里使用了 OR 逻辑，因为不同来源的记忆可能有不同的上下文字段
        # 但我们更倾向于匹配尽可能多的上下文字段
        filters = []
        
        if user_id:
            # 精确匹配 user_id，或者记忆没有 user_id（作为后备）
            filters.append((MemoryModel.user_id == user_id) | (MemoryModel.user_id.is_(None)))
        
        if project_path:
            filters.append((MemoryModel.project_path == project_path) | (MemoryModel.project_path.is_(None)))
        
        if git_branch:
            filters.append((MemoryModel.git_branch == git_branch) | (MemoryModel.git_branch.is_(None)))
        
        if environment:
            filters.append((MemoryModel.environment == environment) | (MemoryModel.environment.is_(None)))
        
        # 应用所有过滤器（AND 逻辑）
        for f in filters:
            query = query.filter(f)
        
        # 排序：优先匹配更多上下文字段的记忆，然后按最新时间排序
        # 这里我们简单地按创建时间倒序排序
        models = query.order_by(MemoryModel.created_at.desc()).all()
        
        return [model.to_domain() for model in models]


def create_session_factory(db_url: str):
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)