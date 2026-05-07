from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from typing import Dict, Optional, List
from uuid import UUID
from app.application.services import CommandPredictor, FeishuIngester
from app.domain.models import UnifiedMemory, MemoryStatus, Role, ContentType, CodeMeta
from app.domain.interfaces import MemoryRepository
from app.infrastructure.database import create_session_factory, SQLAlchemyMemoryRepository
from app.infrastructure.llm_clients import DoubaoLLMClient, MockLLMClient
from app.infrastructure.message_queue import MessageQueue, create_message_queue
from app.infrastructure.feishu_client import create_feishu_client
from app.infrastructure.filtering import DataFilter
from app.application.services import LLMExtractor, DefaultConflictDetector
import os

router = APIRouter(prefix="/api/v1")

# 简单的测试端点
@router.get("/test", tags=["Test"])
async def test_endpoint():
    print("Received test request!")
    return {"status": "ok", "message": "Test endpoint working"}

# 依赖注入配置
DATABASE_URL = "sqlite:///./test.db"
USE_MOCK_LLM = os.getenv("USE_MOCK_LLM", "true").lower() == "true"
USE_ASYNC_MODE = os.getenv("USE_ASYNC_MODE", "false").lower() == "true"  # 默认使用同步模式
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

session_factory = create_session_factory(DATABASE_URL)

# 消息队列实例（默认使用内存队列）
message_queue_instance: MessageQueue = None
if USE_ASYNC_MODE:
    try:
        message_queue_instance = create_message_queue({
            "type": "memory",  # 默认使用内存队列
        })
    except Exception:
        USE_ASYNC_MODE = False


def get_repository() -> MemoryRepository:
    session = session_factory()
    try:
        yield SQLAlchemyMemoryRepository(session)
    finally:
        session.close()


def get_predictor(repository: MemoryRepository = Depends(get_repository)) -> CommandPredictor:
    return CommandPredictor(repository)


def get_llm_client():
    if USE_MOCK_LLM:
        return MockLLMClient()
    return DoubaoLLMClient()


def get_message_queue():
    return message_queue_instance


def get_data_filter():
    """获取完整的数据过滤器（支持语义向量检索）"""
    # 注意：Windows 上语义向量检索可能失败，自动降级到关键词匹配
    return DataFilter(use_vector_search=False)


def get_ingester(
    repository: MemoryRepository = Depends(get_repository),
    llm_client=Depends(get_llm_client),
    message_queue: MessageQueue = Depends(get_message_queue),
    data_filter: DataFilter = Depends(get_data_filter),
):
    if USE_ASYNC_MODE and message_queue:
        return FeishuIngester(
            message_queue=message_queue,
            data_filter=data_filter,
            use_async=True,
        )
    else:
        conflict_detector = DefaultConflictDetector(repository, llm_client)
        extractor = LLMExtractor(llm_client, conflict_detector)
        return FeishuIngester(
            extractor=extractor,
            data_filter=data_filter,
            use_async=False,
        )


class CommandPredictRequest(BaseModel):
    command_prefix: str = Field(..., description="终端当前输入的命令前缀")
    session_id: Optional[UUID] = Field(None, description="会话唯一标识")
    tags: Optional[List[str]] = Field(None, description="标签列表")
    # 新增：强制要求的上下文环境参数 - 实现项目级/租户级隔离
    user_id: Optional[str] = Field(None, description="执行者ID（必填）")
    project_path: Optional[str] = Field(None, description="当前项目路径（必填）")
    git_branch: Optional[str] = Field(None, description="当前Git分支（必填）")
    environment: Optional[str] = Field(None, description="环境类型：dev/test/prod（必填）")


class CommandPredictResponse(BaseModel):
    recommendations: Dict[str, str] = Field(..., description="推荐的补全参数")
    source_info: str = Field(..., description="飞书决策来源说明")
    confidence: float = Field(..., description="推荐置信度")
    memory_id: Optional[str] = Field(None, description="关联记忆ID")
    topic: Optional[str] = Field(None, description="匹配主题")
    tags: Optional[List[str]] = Field(None, description="关联标签")
    context: Optional[Dict] = Field(None, description="匹配记忆的上下文信息，用于验证")


class CodeMetaRequest(BaseModel):
    lang: Optional[str] = None
    task: Optional[str] = None
    snippet_id: Optional[str] = None


class MemoryCreateRequest(BaseModel):
    session_id: UUID = Field(..., description="会话唯一标识")
    turn_id: int = Field(default=1, description="单会话内的轮次编号")
    topic: str = Field(..., description="决策议题")
    content: str = Field(..., description="核心内容")
    content_type: ContentType = Field(default=ContentType.TEXT, description="内容类型")
    role: Role = Field(default=Role.USER, description="角色")
    execution_params: Optional[Dict[str, str]] = Field(default=None, description="映射的CLI参数键值对")
    code_meta: Optional[CodeMetaRequest] = Field(default=None, description="代码专属元信息")
    tags: Optional[List[str]] = Field(default=None, description="标签列表")
    token_count: Optional[int] = Field(default=None, description="token数")
    # 新增：上下文环境参数
    user_id: Optional[str] = Field(None, description="创建者ID")
    project_path: Optional[str] = Field(None, description="关联项目路径")
    git_branch: Optional[str] = Field(None, description="关联Git分支")
    environment: Optional[str] = Field(None, description="关联环境：dev/test/prod")


class MemoryResponse(BaseModel):
    memory_id: UUID = Field(..., description="记忆UUID")
    session_id: UUID = Field(..., description="会话唯一标识")
    turn_id: int = Field(..., description="单会话内的轮次编号")
    topic: str = Field(..., description="决策议题")
    content: str = Field(..., description="核心内容")
    content_type: ContentType = Field(..., description="内容类型")
    role: Role = Field(..., description="角色")
    execution_params: Dict[str, str] = Field(..., description="映射的CLI参数键值对")
    code_meta: Optional[Dict] = Field(None, description="代码专属元信息")
    status: MemoryStatus = Field(..., description="状态机标识")
    tags: List[str] = Field(..., description="标签列表")
    token_count: Optional[int] = Field(None, description="token数")
    created_at: str = Field(..., description="时间戳")
    supersedes_id: Optional[UUID] = Field(None, description="指向被覆写旧记忆的UUID")
    # 新增：上下文环境字段
    user_id: Optional[str] = Field(None, description="创建者ID")
    project_path: Optional[str] = Field(None, description="关联项目路径")
    git_branch: Optional[str] = Field(None, description="关联Git分支")
    environment: Optional[str] = Field(None, description="关联环境：dev/test/prod")


class FeishuWebhookRequest(BaseModel):
    event_type: str = Field(..., description="飞书事件类型")
    message: str = Field(..., description="消息内容")
    sender: Dict[str, str] = Field(..., description="发送者信息")
    session_id: Optional[UUID] = Field(None, description="会话唯一标识")
    chat_id: Optional[str] = Field(None, description="群聊ID")


@router.post("/predict_command", response_model=CommandPredictResponse, tags=["CLI"])
def predict_command(
    request: CommandPredictRequest,
    predictor: CommandPredictor = Depends(get_predictor)
):
    # 验证是否提供了足够的上下文信息
    # 注意：我们这里不强制所有字段，但强烈建议提供
    has_context = any([
        request.user_id,
        request.project_path,
        request.git_branch,
        request.environment,
    ])
    
    # 如果没有提供任何上下文，我们可以返回警告（但暂时仍然允许请求）
    # 在生产环境中，你可能想要将这个设为强制性要求
    
    result = predictor.predict_command(
        command_prefix=request.command_prefix,
        session_id=request.session_id,
        tags=request.tags,
        user_id=request.user_id,
        project_path=request.project_path,
        git_branch=request.git_branch,
        environment=request.environment,
    )
    return CommandPredictResponse(**result)


@router.post("/memories", response_model=MemoryResponse, tags=["Memory"])
def create_memory(
    request: MemoryCreateRequest,
    repository: MemoryRepository = Depends(get_repository)
):
    from uuid import uuid4
    from datetime import datetime

    code_meta_obj = None
    if request.code_meta:
        code_meta_obj = CodeMeta(
            lang=request.code_meta.lang,
            task=request.code_meta.task,
            snippet_id=request.code_meta.snippet_id,
        )

    memory = UnifiedMemory(
        memory_id=uuid4(),
        session_id=request.session_id,
        turn_id=request.turn_id,
        topic=request.topic,
        content=request.content,
        content_type=request.content_type,
        role=request.role,
        execution_params=request.execution_params or {},
        code_meta=code_meta_obj,
        tags=request.tags or [],
        token_count=request.token_count,
        created_at=datetime.utcnow(),
        user_id=request.user_id,
        project_path=request.project_path,
        git_branch=request.git_branch,
        environment=request.environment,
    )

    saved = repository.save(memory)

    code_meta_dict = None
    if saved.code_meta:
        code_meta_dict = saved.code_meta.to_dict()

    return MemoryResponse(
        memory_id=saved.memory_id,
        session_id=saved.session_id,
        turn_id=saved.turn_id,
        topic=saved.topic,
        content=saved.content,
        content_type=saved.content_type,
        role=saved.role,
        execution_params=saved.execution_params,
        code_meta=code_meta_dict,
        status=saved.status,
        tags=saved.tags,
        token_count=saved.token_count,
        created_at=saved.created_at.isoformat(),
        supersedes_id=saved.supersedes_id,
        user_id=saved.user_id,
        project_path=saved.project_path,
        git_branch=saved.git_branch,
        environment=saved.environment,
    )


@router.get("/memories", response_model=List[MemoryResponse], tags=["Memory"])
def list_memories(
    topic: Optional[str] = None,
    status: Optional[MemoryStatus] = None,
    session_id: Optional[UUID] = None,
    # 新增：上下文过滤参数
    user_id: Optional[str] = None,
    project_path: Optional[str] = None,
    git_branch: Optional[str] = None,
    environment: Optional[str] = None,
    repository: MemoryRepository = Depends(get_repository)
):
    # 如果有任何上下文参数，使用新的 search_with_context 方法
    if user_id or project_path or git_branch or environment:
        memories = repository.search_with_context(
            topic_query=topic,
            user_id=user_id,
            project_path=project_path,
            git_branch=git_branch,
            environment=environment,
            status=status,
        )
    elif session_id:
        memories = repository.find_by_session(session_id)
    elif topic:
        memories = repository.find_by_topic(topic)
    else:
        memories = repository.find_all_active()

    if status and not (user_id or project_path or git_branch or environment):
        memories = [m for m in memories if m.status == status]

    return [
        MemoryResponse(
            memory_id=m.memory_id,
            session_id=m.session_id,
            turn_id=m.turn_id,
            topic=m.topic,
            content=m.content,
            content_type=m.content_type,
            role=m.role,
            execution_params=m.execution_params,
            code_meta=m.code_meta.to_dict() if m.code_meta else None,
            status=m.status,
            tags=m.tags,
            token_count=m.token_count,
            created_at=m.created_at.isoformat(),
            supersedes_id=m.supersedes_id,
            user_id=m.user_id,
            project_path=m.project_path,
            git_branch=m.git_branch,
            environment=m.environment,
        )
        for m in memories
    ]


@router.get("/memories/{memory_id}", response_model=MemoryResponse, tags=["Memory"])
def get_memory(
    memory_id: UUID,
    repository: MemoryRepository = Depends(get_repository)
):
    memory = repository.get_by_id(memory_id)
    if not memory:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Memory not found")

    return MemoryResponse(
        memory_id=memory.memory_id,
        session_id=memory.session_id,
        turn_id=memory.turn_id,
        topic=memory.topic,
        content=memory.content,
        content_type=memory.content_type,
        role=memory.role,
        execution_params=memory.execution_params,
        code_meta=memory.code_meta.to_dict() if memory.code_meta else None,
        status=memory.status,
        tags=memory.tags,
        token_count=memory.token_count,
        created_at=memory.created_at.isoformat(),
        supersedes_id=memory.supersedes_id,
        user_id=memory.user_id,
        project_path=memory.project_path,
        git_branch=memory.git_branch,
        environment=memory.environment,
    )


@router.post("/memories/by-tags", response_model=List[MemoryResponse], tags=["Memory"])
def get_memories_by_tags(
    tags: List[str],
    repository: MemoryRepository = Depends(get_repository)
):
    memories = repository.find_by_tags(tags)
    return [
        MemoryResponse(
            memory_id=m.memory_id,
            session_id=m.session_id,
            turn_id=m.turn_id,
            topic=m.topic,
            content=m.content,
            content_type=m.content_type,
            role=m.role,
            execution_params=m.execution_params,
            code_meta=m.code_meta.to_dict() if m.code_meta else None,
            status=m.status,
            tags=m.tags,
            token_count=m.token_count,
            created_at=m.created_at.isoformat(),
            supersedes_id=m.supersedes_id,
            user_id=m.user_id,
            project_path=m.project_path,
            git_branch=m.git_branch,
            environment=m.environment,
        )
        for m in memories
    ]


@router.post("/feishu/webhook", tags=["Feishu"])
async def handle_feishu_webhook(
    request: Request,  # 使用 FastAPI 的 Request 对象
    ingester: "FeishuIngester" = Depends(get_ingester),
    predictor: "CommandPredictor" = Depends(get_predictor),
    repo: "MemoryRepository" = Depends(get_repository),
):
    """
    飞书 Webhook 接口 - 快速响应（<100ms），消息异步处理
    
    Args:
        request: 飞书事件请求
    
    Returns:
        立即返回 200 OK
    """
    import json
    
    # 先获取原始 JSON 数据
    payload = await request.json()
    
    # 1. 处理飞书 URL 验证 (challenge)
    if "challenge" in payload:
        print("Challenge verification request received")
        return {"challenge": payload["challenge"]}
    
    # 安全打印，避免编码问题
    safe_payload = json.dumps(payload, ensure_ascii=True)
    print(f"Feishu raw request: {safe_payload[:500]}...")
    
    # 2. 处理普通消息事件
    # 兼容飞书的消息包装结构
    header = payload.get("header", {})
    event = payload.get("event", {})
    
    # 提取消息内容（飞书的消息内容在 event.message.content，是 JSON 字符串）
    message_content = ""
    message_obj = event.get("message", {})
    if isinstance(message_obj, dict):
        content_str = message_obj.get("content", "{}")
        try:
            content_json = json.loads(content_str)
            # 对于文本消息，content_json 通常有 "text" 字段
            message_content = content_json.get("text", "")
        except:
            message_content = str(content_str)
    
    # 提取发送者和会话信息
    sender = event.get("sender", {})
    # 修复：chat_id 在 message_obj 中，而不是 event 中
    chat_id = message_obj.get("chat_id", "")
    chat_type = message_obj.get("chat_type", "")  # 获取聊天类型：p2p 或 group
    sender_id = None
    if isinstance(sender, dict):
        sender_id = sender.get("sender_id", {}).get("open_id")
    
    # 安全打印，避免编码问题
    safe_content = message_content.encode('ascii', 'ignore').decode('ascii')
    print(f"Parsed - chat_id={chat_id}, sender_id={sender_id}, content={safe_content[:50]}...")
    
    # 只有当有实际消息内容时才处理
    if message_content:
        try:
            # 先处理消息（存储记忆）
            ingester.ingest_message(
                message=message_content,
                session_id=None,  # ingester 会用默认 session_id
                chat_id=chat_id,
                sender_id=sender_id,
            )
            safe_content = message_content.encode('ascii', 'ignore').decode('ascii')
            print(f"Message processed: {safe_content[:30]}...")
            
            # 生成回复
            reply_content = generate_reply(message_content, sender_id, chat_id, predictor, repo)
            
            # 发送回复
            feishu_client = create_feishu_client()
            if chat_type == "group" and chat_id:
                # 群聊：发送到群
                feishu_client.send_message(chat_id, reply_content, receive_id_type="chat_id")
            elif sender_id:
                # 单聊：发送给个人
                feishu_client.send_message(sender_id, reply_content)
                
        except Exception as e:
            # 记录错误但不影响响应
            print(f"Error processing message: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("Empty message, skipped")
    
    # 立即返回，避免飞书超时重传
    return {"status": "accepted", "message": "Message received and queued for processing"}


def generate_reply(message: str, sender_id: str, chat_id: str, predictor: CommandPredictor, repo: MemoryRepository) -> str:
    """基于消息和记忆生成回复 - 使用历史决策卡片格式"""
    
    # 先检查是否是查询记忆的请求
    if any(keyword in message.lower() for keyword in ["查询", "记得", "记忆", "what", "remember", "查询一下"]):
        # 查询所有记忆
        all_memories = repo.find_all_active()
        if all_memories:
            reply = "历史决策卡片\n\n"
            for i, mem in enumerate(all_memories, 1):
                # 计算这个记忆和查询词的匹配分数
                score = _calculate_simple_match_score(message, mem)
                reply += f"主题: {mem.topic}\n"
                reply += f"结论:\n{mem.content}\n"
                reply += "理由:\n用户在对话中提到的内容\n"
                reply += "状态: 生效中\n"
                reply += f"匹配分数: {score:.4f}\n"
                reply += "来源: 飞书对话\n"
                reply += f"触发问题: {mem.content[:50]}...\n"
                if i < len(all_memories):
                    reply += "\n────────────────────\n\n"
            return reply
        else:
            return "历史决策卡片\n\n暂无历史决策记录"
    
    # 尝试查询相关记忆
    try:
        prediction = predictor.predict_command(
            command_prefix=message,
            user_id=sender_id,
            project_path=chat_id,
        )
        
        if prediction.get("memory_id"):
            topic = prediction.get("topic", "")
            source_info = prediction.get("source_info", "")
            confidence = prediction.get("confidence", 0.0)
            reply = f"历史决策卡片\n\n"
            reply += f"主题: {topic}\n"
            reply += f"结论:\n{source_info}\n"
            reply += "理由:\n根据历史对话记录\n"
            reply += "状态: 生效中\n"
            reply += f"匹配分数: {confidence:.4f}\n"
            reply += "来源: 飞书对话\n"
            reply += f"触发问题: {message[:50]}...\n"
            return reply
    except Exception as e:
        print(f"Error predicting: {e}")
    
    # 默认回复 - 也使用卡片格式
    return f"历史决策卡片\n\n主题: {message[:20]}\n结论:\n已记录您的消息，正在处理中...\n理由:\n用户发送了新消息\n状态: 记录中\n匹配分数: 1.0000\n来源: 飞书对话\n触发问题: {message[:50]}..."


def _calculate_simple_match_score(query: str, memory) -> float:
    """智能计算查询和记忆的匹配分数 - 使用多维度匹配算法"""
    import re
    
    query_lower = query.lower()
    topic_lower = memory.topic.lower()
    content_lower = memory.content.lower()
    
    # 1. 提取查询关键词（去除停用词）
    stop_words = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这'}
    query_words = set(re.findall(r'[\u4e00-\u9fa5a-z0-9]+', query_lower))
    query_words = query_words - stop_words
    
    if not query_words:
        return 0.3  # 如果没有有效关键词，返回基础分数
    
    # 2. 计算主题匹配度（权重最高）
    topic_words = set(re.findall(r'[\u4e00-\u9fa5a-z0-9]+', topic_lower))
    topic_overlap = len(query_words & topic_words)
    topic_score = topic_overlap / len(query_words) if query_words else 0
    
    # 3. 计算内容匹配度
    content_words = set(re.findall(r'[\u4e00-\u9fa5a-z0-9]+', content_lower))
    content_overlap = len(query_words & content_words)
    content_score = content_overlap / len(query_words) if query_words else 0
    
    # 4. 计算精确匹配奖励（完整短语匹配）
    exact_match_bonus = 0.0
    if query_lower in topic_lower:
        exact_match_bonus += 0.2
    if query_lower in content_lower:
        exact_match_bonus += 0.1
    
    # 5. 综合评分（主题权重 0.5，内容权重 0.3，精确匹配 0.2）
    final_score = (
        topic_score * 0.5 +
        content_score * 0.3 +
        exact_match_bonus
    )
    
    # 6. 归一化到 0-1 范围
    return min(1.0, max(0.0, final_score))