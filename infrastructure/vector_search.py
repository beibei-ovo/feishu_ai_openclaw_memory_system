import numpy as np
from typing import List, Dict, Optional, Tuple
from sentence_transformers import SentenceTransformer, util


class SemanticVectorSearch:
    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5"):
        """
        初始化语义向量检索器
        
        Args:
            model_name: 预训练模型名称，默认使用对中文支持极好的 bge-small-zh-v1.5
        """
        self.model = SentenceTransformer(model_name)
        self.embeddings = np.array([])
        self.documents = []
        self.document_metadata = []
    
    def add_documents(
        self,
        documents: List[str],
        metadata: Optional[List[Dict]] = None
    ):
        """
        添加文档到向量库
        
        Args:
            documents: 文档列表
            metadata: 文档元数据列表，与documents一一对应
        """
        if not documents:
            return
        
        new_embeddings = self.model.encode(documents, convert_to_numpy=True)
        
        if self.embeddings.size == 0:
            self.embeddings = new_embeddings
        else:
            self.embeddings = np.vstack([self.embeddings, new_embeddings])
        
        self.documents.extend(documents)
        
        if metadata:
            self.document_metadata.extend(metadata)
        else:
            self.document_metadata.extend([{} for _ in documents])
    
    def search(
        self,
        query: str,
        top_k: int = 5,
        similarity_threshold: float = 0.5
    ) -> List[Dict]:
        """
        语义搜索
        
        Args:
            query: 搜索查询
            top_k: 返回前k个结果
            similarity_threshold: 相似度阈值，低于此值的结果不返回
        
        Returns:
            匹配结果列表，包含document、similarity、metadata
        """
        if self.embeddings.size == 0:
            return []
        
        query_embedding = self.model.encode(query, convert_to_numpy=True)
        similarities = util.cos_sim(query_embedding, self.embeddings)[0].cpu().numpy()
        
        # 获取排序后的索引
        sorted_indices = np.argsort(similarities)[::-1]
        
        results = []
        for idx in sorted_indices[:top_k]:
            similarity = float(similarities[idx])
            if similarity >= similarity_threshold:
                results.append({
                    "document": self.documents[idx],
                    "similarity": similarity,
                    "metadata": self.document_metadata[idx],
                })
        
        return results
    
    def is_relevant(
        self,
        query: str,
        similarity_threshold: float = 0.5
    ) -> Tuple[bool, float, Optional[Dict]]:
        """
        判断查询是否与向量库中的内容相关
        
        Args:
            query: 查询文本
            similarity_threshold: 相似度阈值
        
        Returns:
            (是否相关, 最高相似度, 最相似文档信息)
        """
        results = self.search(query, top_k=1, similarity_threshold=similarity_threshold)
        
        if results:
            return (True, results[0]["similarity"], results[0])
        return (False, 0.0, None)
    
    def clear(self):
        """清空向量库"""
        self.embeddings = np.array([])
        self.documents = []
        self.document_metadata = []
    
    def get_stats(self) -> Dict:
        """获取向量库统计信息"""
        return {
            "document_count": len(self.documents),
            "embedding_dimension": self.embeddings.shape[1] if self.embeddings.size > 0 else 0,
        }


class DecisionIntentClassifier:
    """决策意图分类器 - 使用语义向量判断是否为决策类消息"""
    
    def __init__(self):
        self.vector_search = SemanticVectorSearch()
        self._initialize_intent_templates()
    
    def _initialize_intent_templates(self):
        """初始化决策意图模板"""
        decision_templates = [
            # 通用决策
            "我们决定使用这个方案",
            "确定选择A方案",
            "同意这个提议",
            "批准执行计划",
            "达成共识",
            "结论是这样的",
            "任务分配如下",
            "优先级确定为",
            
            # 技术决策
            "使用MySQL数据库",
            "配置测试环境",
            "部署到生产服务器",
            "启动服务",
            "修复这个bug",
            "开发新功能",
            "升级依赖版本",
            "回滚到上一版本",
            
            # 产品决策
            "需求确认",
            "设计方案评审通过",
            "排期确定",
            "用户调研结果",
            "功能优先级排序",
            "上线时间确定",
            "PRD文档确认",
            
            # 运营决策
            "活动策划方案",
            "推广渠道选择",
            "预算分配",
            "KPI目标设定",
            "活动复盘",
            "用户增长策略",
            
            # 运维决策
            "监控告警配置",
            "故障恢复方案",
            "备份策略",
            "性能优化",
            "安全审计",
            "自动化脚本",
            
            # 项目决策
            "项目进度确认",
            "风险评估",
            "资源分配",
            "里程碑计划",
            "会议结论",
        ]
        
        self.vector_search.add_documents(decision_templates)
    
    def classify(
        self,
        text: str,
        threshold: float = 0.5
    ) -> Tuple[bool, float, str]:
        """
        分类文本是否为决策意图
        
        Args:
            text: 待分类文本
            threshold: 相似度阈值
        
        Returns:
            (是否为决策意图, 相似度分数, 匹配意图描述)
        """
        is_relevant, similarity, result = self.vector_search.is_relevant(text, threshold)
        
        intent_desc = ""
        if result:
            intent_desc = result["document"]
        
        return (is_relevant, similarity, intent_desc)
    
    def add_custom_intent(self, intent_text: str, metadata: Optional[Dict] = None):
        """添加自定义决策意图模板"""
        self.vector_search.add_documents([intent_text], [metadata] if metadata else None)