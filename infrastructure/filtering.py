import re
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
from app.domain.models import UnifiedMemory, ContentType, CodeMeta

try:
    from .vector_search import DecisionIntentClassifier
    VECTOR_SEARCH_AVAILABLE = True
except ImportError:
    VECTOR_SEARCH_AVAILABLE = False


class DataFilter:
    def __init__(
        self,
        decision_keywords: Optional[List[str]] = None,
        min_content_length: int = 5,
        max_content_length: int = 5000,
        retention_days: int = 30,
        max_turns_per_session: int = 10,
        use_vector_search: bool = True,
        similarity_threshold: float = 0.5,
    ):
        self.use_vector_search = use_vector_search and VECTOR_SEARCH_AVAILABLE
        self.similarity_threshold = similarity_threshold
        
        # 保留关键词作为备选方案
        self.decision_keywords = decision_keywords or self._build_default_keywords()
        
        # 初始化语义分类器
        self.intent_classifier = None
        if self.use_vector_search:
            try:
                self.intent_classifier = DecisionIntentClassifier()
            except Exception as e:
                print(f"Failed to initialize vector search: {e}")
                self.use_vector_search = False
        
        self.min_content_length = min_content_length
        self.max_content_length = max_content_length
        self.retention_days = retention_days
        self.max_turns_per_session = max_turns_per_session
        self.processed_hashes = set()

    def _build_default_keywords(self) -> List[str]:
        """构建覆盖多职业角色的关键词白名单（备选方案）"""
        keywords = []
        
        # 通用决策关键词
        keywords.extend([
            "决定", "确定", "选择", "同意", "批准", "确认", "采纳", "执行",
            "决议", "共识", "方案", "计划", "安排", "建议", "意见", "结论",
            "目标", "需求", "要求", "任务", "职责", "分工", "优先级", "时间",
        ])
        
        # 技术开发相关
        keywords.extend([
            "使用", "配置", "参数", "服务器", "环境", "连接", "部署", "运行",
            "启动", "测试", "调试", "开发", "修复", "优化", "重构", "集成",
            "接口", "API", "数据库", "缓存", "日志", "监控", "告警", "发布",
            "版本", "分支", "合并", "回滚", "构建", "打包", "依赖", "升级",
        ])
        
        # 产品经理相关
        keywords.extend([
            "需求", "功能", "迭代", "版本", "原型", "设计", "评审", "排期",
            "用户", "调研", "分析", "竞品", "策略", "规划", "路线图", "里程碑",
            "埋点", "数据", "指标", "复盘", "验收", "上线", "反馈", "迭代",
            "优先级", "资源", "成本", "收益", "方案", "文档", "PRD", "MRD",
        ])
        
        # 运营相关
        keywords.extend([
            "活动", "推广", "渠道", "投放", "流量", "用户", "增长", "留存",
            "转化", "拉新", "促活", "召回", "裂变", "社群", "内容", "文案",
            "策划", "预算", "KPI", "ROI", "数据", "报表", "分析", "复盘",
            "合作", "资源", "品牌", "曝光", "触达", "复购", "口碑", "传播",
        ])
        
        # 运维相关
        keywords.extend([
            "运维", "监控", "告警", "故障", "恢复", "备份", "容灾", "迁移",
            "扩容", "缩容", "性能", "优化", "安全", "合规", "审计", "日志",
            "配置", "自动化", "脚本", "定时", "巡检", "维护", "升级", "补丁",
            "集群", "容器", "编排", "网络", "存储", "权限", "访问", "策略",
        ])
        
        # 测试相关
        keywords.extend([
            "测试", "用例", "覆盖", "缺陷", "BUG", "回归", "自动化", "接口",
            "性能", "安全", "压力", "负载", "冒烟", "验收", "环境", "数据",
            "报告", "跟踪", "重现", "修复", "验证", "评审", "计划", "进度",
        ])
        
        # 项目管理相关
        keywords.extend([
            "项目", "进度", "风险", "资源", "范围", "时间", "成本", "质量",
            "里程碑", "甘特图", "周报", "月报", "会议", "同步", "协调", "沟通",
            "风险", "问题", "阻塞", "依赖", "变更", "评审", "验收", "交付",
        ])
        
        return keywords

    def stage1_format_preprocessing(self, content: str) -> str:
        """阶段1：格式预处理 - 清洗无意义噪点"""
        if not content:
            return ""

        # 移除HTML标签
        content = re.sub(r"<[^>]*>", "", content)
        
        # 移除Markdown格式符号（保留代码块标记）
        content = re.sub(r"^\s*[#*>-]+\s*", "", content, flags=re.MULTILINE)
        content = re.sub(r"\*\*(.*?)\*\*", r"\1", content)
        content = re.sub(r"\*(.*?)\*", r"\1", content)
        content = re.sub(r"~~(.*?)~~", r"\1", content)
        
        # 移除连续的换行和空格
        content = re.sub(r"\n{3,}", "\n\n", content)
        content = re.sub(r" {2,}", " ", content)
        
        # 移除表情符号和特殊字符
        content = re.sub(r"[\u263a-\u26ff\u2700-\u27bf\u1f300-\u1f5ff]", "", content)
        
        # 移除多余的空白字符
        content = content.strip()
        
        return content

    def stage2_value_judgment(self, content: str) -> Tuple[bool, str]:
        """阶段2：价值判定 - 判断是否有保留意义"""
        if not content:
            return False, "内容为空"
        
        # 长度判断
        if len(content) < self.min_content_length:
            return False, f"内容过短（{len(content)}字符）"
        
        if len(content) > self.max_content_length:
            return False, f"内容过长（{len(content)}字符）"
        
        # 语义向量检索（优先）或关键词匹配（备选）
        if self.use_vector_search and self.intent_classifier:
            is_relevant, similarity, intent_desc = self.intent_classifier.classify(
                content, self.similarity_threshold
            )
            if not is_relevant:
                return False, f"语义相似度不足（{similarity:.2f}，阈值{self.similarity_threshold}）"
        else:
            # 备选方案：关键词匹配
            if not any(keyword in content for keyword in self.decision_keywords):
                return False, "未包含决策关键词"
        
        # 排除纯表情/符号消息
        if re.match(r"^[\s.,!?;:、。！？；：]+$", content):
            return False, "纯符号消息"
        
        # 排除无意义重复字符
        if re.match(r"^(.)\1{5,}$", content):
            return False, "重复字符消息"
        
        return True, "通过"

    def stage3_content_purification(self, content: str) -> Tuple[str, Optional[CodeMeta]]:
        """阶段3：内容提纯 - 提取代码场景核心信息"""
        code_meta = None
        code_blocks = []
        
        # 匹配代码块
        code_pattern = re.compile(
            r"```(\w+)?\n(.*?)```",
            re.DOTALL
        )
        
        matches = code_pattern.findall(content)
        for lang, code in matches:
            code_blocks.append(code.strip())
            if lang:
                code_meta = CodeMeta(lang=lang.lower().strip(), task="code_snippet")
        
        # 如果有代码块，提取代码并保留简短上下文
        if code_blocks:
            code_content = "\n".join(code_blocks)
            
            # 提取代码前后的描述文字
            context_pattern = re.compile(
                r"(.*?)```\w*\n.*?```(.*)",
                re.DOTALL
            )
            context_match = context_pattern.search(content)
            context = ""
            if context_match:
                context = (context_match.group(1) + " " + context_match.group(2)).strip()[:200]
            
            purified = f"{context}\n\n{code_content}" if context else code_content
            return purified.strip(), code_meta
        
        # 无代码块，保留原始内容但清理冗余
        return content, None

    def stage4_metadata_cleanup(self, memory: UnifiedMemory) -> UnifiedMemory:
        """阶段4：元信息规整 - 过滤无效元数据"""
        # 清理空标签
        if memory.tags:
            memory.tags = [tag.strip() for tag in memory.tags if tag and len(tag.strip()) > 1]
        
        # 清理无效代码元信息
        if memory.code_meta:
            if not memory.code_meta.lang and not memory.code_meta.task:
                memory.code_meta = None
        
        # 确保content_type正确
        if memory.content_type == ContentType.CODE and not memory.code_meta:
            memory.code_meta = CodeMeta()
        
        return memory

    def stage5_temporal_and_redundancy_filter(
        self,
        memory: UnifiedMemory,
        session_memories: Optional[List[UnifiedMemory]] = None
    ) -> Tuple[bool, str]:
        """阶段5：时效性/冗余过滤 - 长期记忆专用"""
        # 时效性过滤
        if memory.created_at:
            age = datetime.utcnow() - memory.created_at
            if age > timedelta(days=self.retention_days):
                return False, f"已过期（{age.days}天前）"
        
        # 同会话轮次限制
        if session_memories:
            session_turns = [m.turn_id for m in session_memories if m.session_id == memory.session_id]
            if session_turns and max(session_turns) > self.max_turns_per_session:
                return False, "超过会话最大轮次限制"
        
        # 冗余检测（哈希去重）
        content_hash = hashlib.md5(memory.content.encode()).hexdigest()
        if content_hash in self.processed_hashes:
            return False, "重复内容"
        
        self.processed_hashes.add(content_hash)
        return True, "通过"

    def process(
        self,
        content: str,
        session_memories: Optional[List[UnifiedMemory]] = None,
        apply_stage5: bool = False
    ) -> Tuple[Optional[UnifiedMemory], str]:
        """完整过滤流程"""
        # 阶段1：格式预处理
        cleaned_content = self.stage1_format_preprocessing(content)
        
        # 阶段2：价值判定（使用语义向量检索）
        valid, reason = self.stage2_value_judgment(cleaned_content)
        if not valid:
            return None, f"阶段2失败: {reason}"
        
        # 阶段3：内容提纯
        purified_content, code_meta = self.stage3_content_purification(cleaned_content)
        
        # 创建临时memory对象用于后续处理
        from uuid import uuid4
        memory = UnifiedMemory(
            memory_id=uuid4(),
            session_id=uuid4(),
            turn_id=1,
            topic="",
            content=purified_content,
            content_type=ContentType.CODE if code_meta else ContentType.TEXT,
            code_meta=code_meta,
            tags=self._extract_tags(purified_content),
        )
        
        # 阶段4：元信息规整
        memory = self.stage4_metadata_cleanup(memory)
        
        # 阶段5：时效性/冗余过滤（可选）
        if apply_stage5:
            valid, reason = self.stage5_temporal_and_redundancy_filter(memory, session_memories)
            if not valid:
                return None, f"阶段5失败: {reason}"
        
        return memory, "全部通过"

    def _extract_tags(self, content: str) -> List[str]:
        """从内容中提取标签"""
        tech_keywords = [
            "Python", "Java", "Go", "JavaScript", "TypeScript", "Rust", "C++", "PHP",
            "MySQL", "PostgreSQL", "Redis", "MongoDB", "Elasticsearch",
            "API", "REST", "GraphQL", "gRPC",
            "Docker", "Kubernetes", "CI/CD", "DevOps",
            "前端", "后端", "数据库", "缓存", "服务器", "环境"
        ]
        
        tags = []
        for keyword in tech_keywords:
            if keyword.lower() in content.lower():
                tags.append(keyword)
        
        return list(set(tags))

    def batch_filter(
        self,
        contents: List[str],
        session_memories: Optional[List[UnifiedMemory]] = None,
        apply_stage5: bool = False
    ) -> List[Tuple[Optional[UnifiedMemory], str]]:
        """批量过滤"""
        results = []
        for content in contents:
            memory, reason = self.process(content, session_memories, apply_stage5)
            results.append((memory, reason))
        return results

    def add_custom_intent(self, intent_text: str):
        """添加自定义决策意图模板到语义分类器"""
        if self.intent_classifier:
            self.intent_classifier.add_custom_intent(intent_text)