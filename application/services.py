from uuid import uuid4, UUID
from typing import Optional, Dict, List, Tuple
from app.domain.models import UnifiedMemory, MemoryStatus, Role, ContentType, CodeMeta
from app.domain.interfaces import (
    MemoryRepository, ConflictDetector, LLMClient
)
from app.infrastructure.message_queue import MessageQueue
from app.infrastructure.filtering import DataFilter


class SimpleDataFilter:
    """简化的数据过滤器（向后兼容）"""
    
    def stage1_format_preprocessing(self, text: str) -> str:
        return text.strip()
    
    def stage2_value_judgment(self, text: str) -> tuple[bool, float]:
        return True, 0.9
    
    def _extract_tags(self, text: str) -> list[str]:
        return []
    
    def stage3_content_purification(self, text: str) -> tuple[str, CodeMeta | None]:
        return text, None
    
    def stage4_metadata_cleanup(self, memory: UnifiedMemory) -> UnifiedMemory:
        return memory


class DefaultConflictDetector(ConflictDetector):
    def __init__(self, repository: MemoryRepository, llm_client: Optional[LLMClient] = None):
        self.repository = repository
        self.llm_client = llm_client

    def detect_conflict(self, topic: str) -> Optional[UnifiedMemory]:
        return self.repository.find_active_by_topic(topic)

    def resolve_conflict(self, new_memory: UnifiedMemory) -> UnifiedMemory:
        existing = self.detect_conflict(new_memory.topic)
        
        if not existing:
            # 无冲突，直接保存
            return self.repository.save(new_memory)
        
        if self.llm_client:
            # 使用 LLM 智能判断冲突类型
            conflict_result = self.llm_client.resolve_memory_conflict(existing, new_memory)
            conflict_type = conflict_result.get("conflict_type", "merge")
            explanation = conflict_result.get("explanation", "")
            
            if conflict_type == "merge":
                # 增量合并
                return self._do_merge(existing, new_memory, conflict_result.get("merged_memory", {}))
            elif conflict_type == "overwrite":
                # 完全覆盖
                return self._do_overwrite(existing, new_memory)
            else:
                # 无冲突，两者共存
                return self.repository.save(new_memory)
        else:
            # 无 LLM 客户端，采用简单覆盖策略（保持向后兼容）
            return self._do_overwrite(existing, new_memory)
    
    def _do_merge(self, old_memory: UnifiedMemory, new_memory: UnifiedMemory, merged_data: Dict) -> UnifiedMemory:
        """执行增量合并"""
        # 标记旧记忆为已替代
        self.repository.update_status(old_memory.memory_id, MemoryStatus.SUPERSEDED)
        
        # 从合并数据中提取信息
        topic = merged_data.get("topic", new_memory.topic)
        content = merged_data.get("content", f"{old_memory.content}; {new_memory.content}")
        execution_params = merged_data.get("execution_params", {**old_memory.execution_params, **new_memory.execution_params})
        tags = merged_data.get("tags", list(set(old_memory.tags + new_memory.tags)))
        
        # 保留上下文环境信息（优先使用新记忆的，回退到旧记忆）
        user_id = new_memory.user_id or old_memory.user_id
        project_path = new_memory.project_path or old_memory.project_path
        git_branch = new_memory.git_branch or old_memory.git_branch
        environment = new_memory.environment or old_memory.environment
        
        # 创建合并后的新记忆
        merged_memory = UnifiedMemory(
            memory_id=uuid4(),
            session_id=new_memory.session_id,
            turn_id=new_memory.turn_id,
            topic=topic,
            content=content,
            content_type=new_memory.content_type,
            role=Role.ASSISTANT,
            execution_params=execution_params,
            code_meta=new_memory.code_meta or old_memory.code_meta,
            tags=tags,
            token_count=new_memory.token_count,
            supersedes_id=old_memory.memory_id,
            user_id=user_id,
            project_path=project_path,
            git_branch=git_branch,
            environment=environment,
        )
        
        return self.repository.save(merged_memory)
    
    def _do_overwrite(self, old_memory: UnifiedMemory, new_memory: UnifiedMemory) -> UnifiedMemory:
        """执行完全覆盖（保持向后兼容）"""
        self.repository.update_status(old_memory.memory_id, MemoryStatus.SUPERSEDED)
        new_memory.supersedes_id = old_memory.memory_id
        return self.repository.save(new_memory)


class LLMExtractor:
    def __init__(self, llm_client: LLMClient, conflict_detector: ConflictDetector):
        self.llm_client = llm_client
        self.conflict_detector = conflict_detector
        
        # 如果 conflict_detector 是 DefaultConflictDetector 且尚未设置 llm_client，则设置
        if hasattr(conflict_detector, 'llm_client') and conflict_detector.llm_client is None:
            conflict_detector.llm_client = llm_client

    def extract_and_save(
        self,
        context: str,
        session_id: UUID,
        turn_id: int = 1,
        tags: Optional[List[str]] = None,
        # 新增：上下文环境参数
        user_id: Optional[str] = None,
        project_path: Optional[str] = None,
        git_branch: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> UnifiedMemory:
        extracted = self.llm_client.extract_memory(context)

        code_meta = None
        if extracted.get("code_meta"):
            code_meta = CodeMeta.from_dict(extracted["code_meta"])

        content_type_str = extracted.get("content_type", "text")
        try:
            content_type = ContentType(content_type_str)
        except ValueError:
            content_type = ContentType.TEXT

        memory = UnifiedMemory(
            memory_id=uuid4(),
            session_id=session_id,
            turn_id=turn_id,
            topic=extracted.get("topic", "unknown"),
            content=extracted.get("content", ""),
            content_type=content_type,
            role=Role.ASSISTANT,
            execution_params=extracted.get("execution_params", {}),
            code_meta=code_meta,
            tags=tags or [],
            token_count=extracted.get("token_count"),
            user_id=user_id,
            project_path=project_path,
            git_branch=git_branch,
            environment=environment,
        )

        return self.conflict_detector.resolve_conflict(memory)


class FeishuIngester:
    """飞书消息摄入器 - 支持同步和异步（消息队列）两种模式"""
    
    def __init__(
        self,
        extractor: Optional[LLMExtractor] = None,
        message_queue: Optional[MessageQueue] = None,
        default_session_id: Optional[UUID] = None,
        data_filter: Optional[DataFilter] = None,  # 修改：使用完整的 DataFilter
        use_async: bool = True,  # 默认使用异步模式
    ):
        self.extractor = extractor
        self.message_queue = message_queue
        self.default_session_id = default_session_id or uuid4()
        # 修改：使用完整的 DataFilter，支持语义向量检索
        self.data_filter = data_filter or DataFilter(use_vector_search=True)
        self.use_async = use_async
        
        # 同步模式用
        self.context_window = []
        self.window_size = 10
        self.turn_counter = 0
        self.filter_logs = []
        
        if self.use_async and not self.message_queue:
            raise ValueError("message_queue is required in async mode")

    def ingest_message(
        self,
        message: str,
        session_id: Optional[UUID] = None,
        apply_full_filter: bool = True,
        chat_id: Optional[str] = None,
        sender_id: Optional[str] = None,
    ) -> Optional[UnifiedMemory]:
        """
        摄入消息 - 根据模式决定是推入队列还是立即处理
        
        Args:
            message: 消息内容
            session_id: 会话ID
            apply_full_filter: 是否应用完整过滤
            chat_id: 群聊ID
            sender_id: 发送者ID
        
        Returns:
            同步模式返回 UnifiedMemory，异步模式返回 None
        """
        if self.use_async:
            return self._ingest_async(
                message=message,
                session_id=session_id,
                apply_full_filter=apply_full_filter,
                chat_id=chat_id,
                sender_id=sender_id,
            )
        else:
            return self._ingest_sync(
                message=message,
                session_id=session_id,
                apply_full_filter=apply_full_filter,
            )

    def _ingest_async(
        self,
        message: str,
        session_id: Optional[UUID] = None,
        apply_full_filter: bool = True,
        chat_id: Optional[str] = None,
        sender_id: Optional[str] = None,
    ) -> Optional[UnifiedMemory]:
        """异步模式：快速过滤，推入消息队列"""
        # 阶段1：格式预处理
        cleaned_message = self.data_filter.stage1_format_preprocessing(message)
        
        # 阶段2：快速价值判定（避免无效消息进入队列）
        if apply_full_filter:
            valid, reason = self.data_filter.stage2_value_judgment(cleaned_message)
            if not valid:
                self.filter_logs.append({"message": message, "stage": "stage2", "result": "rejected", "reason": reason})
                return None
        
        # 构建消息对象
        message_data = {
            "content": message,
            "cleaned_content": cleaned_message,
            "session_id": str(session_id) if session_id else str(self.default_session_id),
            "chat_id": chat_id,
            "sender_id": sender_id,
        }
        
        # 推入队列
        message_id = self.message_queue.enqueue(message_data)
        self.filter_logs.append({"message": message, "stage": "queued", "result": "accepted", "message_id": message_id})
        
        return None

    def _ingest_sync(
        self,
        message: str,
        session_id: Optional[UUID] = None,
        apply_full_filter: bool = True,
        chat_id: Optional[str] = None,
        sender_id: Optional[str] = None,
    ) -> Optional[UnifiedMemory]:
        """同步模式：立即处理（保持向后兼容）"""
        if not self.extractor:
            raise ValueError("extractor is required in sync mode")
        
        # 阶段1：格式预处理
        cleaned_message = self.data_filter.stage1_format_preprocessing(message)
        
        # 阶段2：价值判定（使用语义向量检索）
        if apply_full_filter:
            valid, reason = self.data_filter.stage2_value_judgment(cleaned_message)
            if not valid:
                self.filter_logs.append({"message": message, "stage": "stage2", "result": "rejected", "reason": reason})
                return None

        self.context_window.append(cleaned_message)
        if len(self.context_window) > self.window_size:
            self.context_window.pop(0)

        # 阶段3：内容提纯
        purified_content, code_meta = self.data_filter.stage3_content_purification(cleaned_message)
        
        if not purified_content:
            self.filter_logs.append({"message": message, "stage": "stage3", "result": "rejected", "reason": "无有效内容"})
            return None

        self.turn_counter += 1
        context = "\n".join(self.context_window)
        target_session = session_id or self.default_session_id
        
        # 提取标签
        tags = self.data_filter._extract_tags(purified_content)
        
        # 调用LLM提取记忆（传递上下文环境参数）
        memory = self.extractor.extract_and_save(
            context=context,
            session_id=target_session,
            turn_id=self.turn_counter,
            tags=tags,
            user_id=sender_id,
            project_path=chat_id,
        )
        
        # 阶段4：元信息规整
        memory = self.data_filter.stage4_metadata_cleanup(memory)
        
        # 设置code_meta（从内容提纯阶段获取）
        if code_meta and not memory.code_meta:
            memory.code_meta = code_meta
        
        # 更新content为提纯后的内容
        memory.content = purified_content
        
        self.filter_logs.append({"message": message, "stage": "completed", "result": "accepted", "memory_id": str(memory.memory_id)})
        
        return memory

    def get_filter_stats(self) -> Dict[str, int]:
        stats = {"total": len(self.filter_logs), "accepted": 0, "rejected": 0, "queued": 0}
        for log in self.filter_logs:
            if log["result"] == "accepted":
                if log["stage"] == "queued":
                    stats["queued"] += 1
                else:
                    stats["accepted"] += 1
            else:
                stats["rejected"] += 1
        return stats


class CommandPredictor:
    def __init__(self, repository: MemoryRepository):
        self.repository = repository

    def predict_command(
        self,
        command_prefix: str,
        session_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        # 新增：上下文环境参数 - 必须传入这些参数！
        user_id: Optional[str] = None,
        project_path: Optional[str] = None,
        git_branch: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> Dict:
        # 首先：使用上下文环境过滤进行记忆搜索
        # 这是防止不同团队信息泄露的核心机制
        
        # 策略1: 使用上下文过滤获取所有可能的记忆
        candidates = self.repository.search_with_context(
            topic_query="",  # 先不过滤主题
            user_id=user_id,
            project_path=project_path,
            git_branch=git_branch,
            environment=environment,
        )
        
        # 策略2: 补充基于会话和标签的搜索
        if session_id:
            session_memories = self.repository.find_by_session(session_id)
            filtered = [
                m for m in session_memories
                if self._memory_matches_context(m, user_id, project_path, git_branch, environment)
            ]
            candidates.extend(filtered)

        if tags:
            tag_memories = self.repository.find_by_tags(tags)
            filtered = [
                m for m in tag_memories
                if self._memory_matches_context(m, user_id, project_path, git_branch, environment)
            ]
            candidates.extend(filtered)

        if not candidates:
            return {
                "recommendations": {},
                "source_info": "",
                "confidence": 0.0,
                "memory_id": None,
            }

        # 从候选记忆中找出与命令最相关的
        best_memory = self._find_best_match(candidates, command_prefix)
        
        if not best_memory:
            return {
                "recommendations": {},
                "source_info": "",
                "confidence": 0.0,
                "memory_id": None,
            }

        return {
            "recommendations": best_memory.execution_params,
            "source_info": f"会话: {best_memory.session_id} | 轮次: {best_memory.turn_id} | 内容: {best_memory.content[:100]}...",
            "confidence": self._calculate_confidence(best_memory, command_prefix),
            "memory_id": str(best_memory.memory_id),
            "topic": best_memory.topic,
            "tags": best_memory.tags,
            # 返回记忆的上下文信息，便于客户端验证
            "context": {
                "user_id": best_memory.user_id,
                "project_path": best_memory.project_path,
                "git_branch": best_memory.git_branch,
                "environment": best_memory.environment,
            },
        }
    
    def _find_best_match(self, memories: List[UnifiedMemory], command: str) -> Optional[UnifiedMemory]:
        """从候选记忆中找出与命令最相关的"""
        scored = []
        for mem in memories:
            score = 0.0
            command_lower = command.lower()
            topic_lower = mem.topic.lower()
            content_lower = mem.content.lower()
            
            # 主题匹配得分
            if command_lower in topic_lower or topic_lower in command_lower:
                score += 0.5
            
            # 内容匹配得分
            if command_lower in content_lower:
                score += 0.3
            
            # 标签匹配得分
            for tag in mem.tags:
                if tag.lower() in command_lower:
                    score += 0.2
            
            if score > 0:
                scored.append((score, mem))
        
        if not scored:
            return None
        
        # 按得分排序，返回最高分
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]
    
    def _memory_matches_context(
        self,
        memory: UnifiedMemory,
        user_id: Optional[str],
        project_path: Optional[str],
        git_branch: Optional[str],
        environment: Optional[str],
    ) -> bool:
        """检查记忆是否与当前上下文环境匹配"""
        # 如果记忆没有设置任何上下文字段，则视为公共记忆（可选）
        # 但我们更倾向于只返回匹配上下文的记忆
        if not user_id and not project_path and not git_branch and not environment:
            return True
        
        # 检查各个上下文字段（有值则必须匹配，无值则忽略）
        if user_id and memory.user_id and memory.user_id != user_id:
            return False
        if project_path and memory.project_path and memory.project_path != project_path:
            return False
        if git_branch and memory.git_branch and memory.git_branch != git_branch:
            return False
        if environment and memory.environment and memory.environment != environment:
            return False
        
        return True

    def _extract_topics_from_command(self, command: str) -> List[str]:
        parts = command.split()
        return [part for part in parts if not part.startswith("-")]

    def _select_best_memory(self, memories: List[UnifiedMemory]) -> UnifiedMemory:
        return max(memories, key=lambda m: (m.turn_id, m.created_at))

    def _calculate_confidence(self, memory: UnifiedMemory, command: str) -> float:
        topic_match = 1.0 if memory.topic.lower() in command.lower() else 0.7
        recency_boost = 0.1 if memory.turn_id > 5 else 0.0
        return min(1.0, topic_match * 0.85 + recency_boost)