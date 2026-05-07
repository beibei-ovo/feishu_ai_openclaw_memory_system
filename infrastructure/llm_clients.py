import os
import json
import requests
from typing import Dict, Optional, Any
from app.domain.interfaces import LLMClient
from app.domain.models import UnifiedMemory


class DoubaoLLMClient(LLMClient):
    def __init__(self, api_key: Optional[str] = None, secret_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("DOUBAO_API_KEY")
        self.secret_key = secret_key or os.getenv("DOUBAO_SECRET_KEY")
        self.access_token = None
        self.token_expire_time = 0

        if not self.api_key or not self.secret_key:
            raise ValueError("DOUBAO_API_KEY and DOUBAO_SECRET_KEY must be set")

    def _get_access_token(self):
        import time
        if self.access_token and time.time() < self.token_expire_time:
            return self.access_token

        url = "https://aip.baidubce.com/oauth/2.0/token"
        params = {
            "grant_type": "client_credentials",
            "client_id": self.api_key,
            "client_secret": self.secret_key
        }

        response = requests.post(url, params=params)
        response.raise_for_status()
        data = response.json()

        self.access_token = data.get("access_token")
        self.token_expire_time = time.time() + data.get("expires_in", 3600) - 60

        return self.access_token

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """通用LLM调用方法"""
        access_token = self._get_access_token()
        url = "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions_pro"

        headers = {"Content-Type": "application/json"}
        payload = {
            "model": "completions_pro",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 2048
        }

        params = {"access_token": access_token}
        response = requests.post(url, headers=headers, params=params, json=payload)
        response.raise_for_status()
        data = response.json()
        
        return data.get("result", "")

    def extract_memory(self, context: str) -> Dict:
        prompt = f"""
        你是一个命令行参数提取专家。请从以下群聊上下文提取决策信息，并以JSON格式输出：

        群聊上下文：
        {context}

        输出格式要求（必须返回有效JSON）：
        {{
            "topic": "决策议题，简洁关键词",
            "content": "自然语言描述的决策原因和上下文",
            "content_type": "text或code或feedback或summary",
            "execution_params": {{
                "key1": "value1",
                "key2": "value2"
            }},
            "code_meta": {{
                "lang": "编程语言（如python, java, go）",
                "task": "任务类型（如api开发、数据库配置）",
                "snippet_id": "代码片段ID（如有）"
            }},
            "tags": ["标签1", "标签2"],
            "token_count": 预估token数
        }}

        说明：
        - content_type: text=普通文本, code=代码相关内容, feedback=反馈意见, summary=总结归纳
        - execution_params: 命令行参数的键值对，如{{"service": "mysql", "env": "test", "host": "192.168.1.1"}}
        - code_meta: 仅当content_type为code时填充
        - tags: 相关技术标签，如["MySQL", "Python", "API"]
        """

        try:
            result = self._call_llm("你是一个专业的命令行参数提取助手", prompt.strip())
            try:
                parsed_result = json.loads(result)
                return {
                    "topic": parsed_result.get("topic", "unknown"),
                    "content": parsed_result.get("content", parsed_result.get("semantic_context", "")),
                    "content_type": parsed_result.get("content_type", "text"),
                    "execution_params": parsed_result.get("execution_params", {}),
                    "code_meta": parsed_result.get("code_meta"),
                    "tags": parsed_result.get("tags", []),
                    "token_count": parsed_result.get("token_count", len(context) // 4),
                }
            except json.JSONDecodeError:
                return {
                    "topic": "unknown",
                    "content": result,
                    "content_type": "text",
                    "execution_params": {},
                    "code_meta": None,
                    "tags": [],
                    "token_count": len(context) // 4,
                }
        except Exception as e:
            return {
                "topic": "unknown",
                "content": f"LLM调用失败: {str(e)}",
                "content_type": "text",
                "execution_params": {},
                "code_meta": None,
                "tags": [],
                "token_count": 0,
            }

    def resolve_memory_conflict(self, old_memory: UnifiedMemory, new_memory: UnifiedMemory) -> Dict:
        prompt = f"""
        你是一个决策冲突解决专家。请分析新旧两条决策记忆，判断它们的关系，并给出最优解决方案。

        旧记忆（已存在）：
        - 话题: {old_memory.topic}
        - 内容: {old_memory.content}
        - 参数: {json.dumps(old_memory.execution_params, ensure_ascii=False)}

        新记忆（新产生）：
        - 话题: {new_memory.topic}
        - 内容: {new_memory.content}
        - 参数: {json.dumps(new_memory.execution_params, ensure_ascii=False)}

        请判断新旧记忆的关系，并以JSON格式输出结果：
        {{
            "conflict_type": "overwrite或merge或no_conflict",
            "explanation": "你做出此判断的原因",
            "merged_memory": {{
                "topic": "合并后的话题",
                "content": "合并后的内容描述",
                "execution_params": {{合并后的参数字典，保留所有有用的参数}},
                "tags": ["标签1", "标签2"]
            }}
        }}

        判断标准：
        1. overwrite: 新信息完全推翻旧信息（例如：旧说IP=1.1.1.1，新说IP=2.2.2.2）
        2. merge: 新信息是对旧信息的补充（例如：旧说IP=1.1.1.1，新说端口=6379）
        3. no_conflict: 两者完全不相关，可以共存

        merge类型的处理规则：
        - 保留旧记忆的所有参数
        - 添加新记忆的新参数
        - 如果同一参数新旧都有，以新记忆为准
        - content合并：综合新旧内容，形成完整描述
        - tags合并：合并去重
        """

        try:
            result = self._call_llm("你是一个专业的决策冲突解决专家", prompt.strip())
            try:
                parsed_result = json.loads(result)
                return {
                    "conflict_type": parsed_result.get("conflict_type", "merge"),
                    "explanation": parsed_result.get("explanation", ""),
                    "merged_memory": parsed_result.get("merged_memory", {
                        "topic": new_memory.topic,
                        "content": new_memory.content,
                        "execution_params": new_memory.execution_params,
                        "tags": new_memory.tags
                    })
                }
            except json.JSONDecodeError:
                # LLM 解析失败，简单合并参数
                merged_params = {**old_memory.execution_params, **new_memory.execution_params}
                merged_tags = list(set(old_memory.tags + new_memory.tags))
                return {
                    "conflict_type": "merge",
                    "explanation": "LLM解析失败，采用简单合并策略",
                    "merged_memory": {
                        "topic": new_memory.topic,
                        "content": f"{old_memory.content}; {new_memory.content}",
                        "execution_params": merged_params,
                        "tags": merged_tags
                    }
                }
        except Exception:
            # 网络错误等，同样采用简单合并
            merged_params = {**old_memory.execution_params, **new_memory.execution_params}
            merged_tags = list(set(old_memory.tags + new_memory.tags))
            return {
                "conflict_type": "merge",
                "explanation": "LLM调用失败，采用简单合并策略",
                "merged_memory": {
                    "topic": new_memory.topic,
                    "content": f"{old_memory.content}; {new_memory.content}",
                    "execution_params": merged_params,
                    "tags": merged_tags
                }
            }


class MockLLMClient(LLMClient):
    def extract_memory(self, context: str) -> Dict:
        """根据实际消息内容来提取记忆，而不是返回固定内容"""
        # 简单的 topic 提取：取前几个词
        topic = context[:20] if len(context) > 20 else context
        
        return {
            "topic": topic,
            "content": context,
            "content_type": "text",
            "execution_params": {},
            "code_meta": None,
            "tags": ["user-message"],
            "token_count": len(context) // 4,
        }

    def resolve_memory_conflict(self, old_memory: UnifiedMemory, new_memory: UnifiedMemory) -> Dict:
        """Mock LLM 冲突解决：智能判断"""
        
        # 判断是补充还是覆盖
        old_keys = set(old_memory.execution_params.keys())
        new_keys = set(new_memory.execution_params.keys())
        
        # 检查是否有相同key被覆盖
        overlapping_keys = old_keys & new_keys
        if overlapping_keys and any(
            old_memory.execution_params[k] != new_memory.execution_params[k] 
            for k in overlapping_keys
        ):
            conflict_type = "overwrite"
            explanation = f"检测到参数 {overlapping_keys} 发生变化，采用覆盖策略"
            merged_memory = {
                "topic": new_memory.topic,
                "content": new_memory.content,
                "execution_params": new_memory.execution_params,
                "tags": new_memory.tags
            }
        else:
            # 增量补充
            conflict_type = "merge"
            merged_params = {**old_memory.execution_params, **new_memory.execution_params}
            merged_tags = list(set(old_memory.tags + new_memory.tags))
            merged_content = f"{old_memory.content}; {new_memory.content}"
            explanation = "新信息是对旧信息的补充，采用合并策略"
            merged_memory = {
                "topic": new_memory.topic,
                "content": merged_content,
                "execution_params": merged_params,
                "tags": merged_tags
            }
        
        return {
            "conflict_type": conflict_type,
            "explanation": explanation,
            "merged_memory": merged_memory
        }