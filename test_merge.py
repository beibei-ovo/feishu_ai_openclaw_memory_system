#!/usr/bin/env python3
"""测试增量合并功能"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from uuid import uuid4
from app.domain.models import UnifiedMemory, MemoryStatus, Role, ContentType
from app.infrastructure.llm_clients import MockLLMClient
from app.infrastructure.database import MemoryRepositoryImpl
from app.application.services import DefaultConflictDetector


def test_merge_scenario():
    """测试增量合并场景"""
    print("=" * 60)
    print("测试增量合并场景")
    print("=" * 60)
    
    # 创建组件
    repo = MemoryRepositoryImpl()
    llm_client = MockLLMClient()
    conflict_detector = DefaultConflictDetector(repo, llm_client)
    
    session_id = uuid4()
    
    # 1. 创建第一个记忆（IP=1.1.1.1）
    memory1 = UnifiedMemory(
        memory_id=uuid4(),
        session_id=session_id,
        turn_id=1,
        topic="redis",
        content="测试环境Redis IP设为1.1.1.1",
        content_type=ContentType.TEXT,
        role=Role.ASSISTANT,
        execution_params={"service": "redis", "host": "1.1.1.1"},
        tags=["Redis", "测试环境"],
    )
    saved1 = repo.save(memory1)
    print(f"\n1. 创建第一个记忆（IP=1.1.1.1")
    print(f"   ID: {saved1.memory_id}")
    print(f"   参数: {saved1.execution_params}")
    print(f"   状态: {saved1.status}")
    
    # 2. 创建第二个记忆（补充端口
    memory2 = UnifiedMemory(
        memory_id=uuid4(),
        session_id=session_id,
        turn_id=2,
        topic="redis",
        content="测试环境Redis端口设为6380",
        content_type=ContentType.TEXT,
        role=Role.ASSISTANT,
        execution_params={"service": "redis", "port": "6380"},
        tags=["Redis", "测试环境"],
    )
    
    print(f"\n2. 创建第二个记忆（补充端口=6380）")
    print(f"   ID: {memory2.memory_id}")
    print(f"   参数: {memory2.execution_params}")
    
    saved2 = conflict_detector.resolve_conflict(memory2)
    print(f"\n3. 合并后记忆")
    print(f"   ID: {saved2.memory_id}")
    print(f"   参数: {saved2.execution_params}")
    print(f"   状态: {saved2.status}")
    print(f"   替代: {saved2.supersedes_id}")
    
    # 检查结果
    assert "host" in saved2.execution_params, "IP应该被丢失了！"
    assert saved2.execution_params["host"] == "1.1.1.1"
    assert saved2.execution_params["port"] == "6380"
    print("\n✅ 增量合并测试通过！IP和端口都保留了！")
    
    # 验证旧记忆被标记为SUPERSEDED
    old_memory = repo.get_by_id(saved1.memory_id)
    assert old_memory.status == MemoryStatus.SUPERSEDED
    print("✅ 旧记忆已标记为 SUPERSEDED")


def test_overwrite_scenario():
    """测试完全覆盖场景"""
    print("\n" + "=" * 60)
    print("测试完全覆盖场景")
    print("=" * 60)
    
    repo = MemoryRepositoryImpl()
    llm_client = MockLLMClient()
    conflict_detector = DefaultConflictDetector(repo, llm_client)
    
    session_id = uuid4()
    
    # 1. 旧记忆
    memory1 = UnifiedMemory(
        memory_id=uuid4(),
        session_id=session_id,
        turn_id=1,
        topic="database",
        content="生产环境使用MySQL",
        content_type=ContentType.TEXT,
        role=Role.ASSISTANT,
        execution_params={"service": "mysql", "host": "prod.mysql.com"},
        tags=["MySQL", "生产环境"],
    )
    repo.save(memory1)
    print(f"\n1. 创建第一个记忆（MySQL）")
    
    # 2. 新记忆覆盖（覆盖旧记忆
    memory2 = UnifiedMemory(
        memory_id=uuid4(),
        session_id=session_id,
        turn_id=2,
        topic="database",
        content="生产环境改用PostgreSQL",
        content_type=ContentType.TEXT,
        role=Role.ASSISTANT,
        execution_params={"service": "postgresql", "host": "prod.pg.com"},
        tags=["PostgreSQL", "生产环境"],
    )
    print(f"\n2. 创建第二个记忆（PostgreSQL，覆盖MySQL）")
    
    saved2 = conflict_detector.resolve_conflict(memory2)
    print(f"\n3. 覆盖后记忆")
    print(f"   参数: {saved2.execution_params}")
    assert saved2.execution_params["service"] == "postgresql"
    assert saved2.execution_params["host"] == "prod.pg.com"
    print("\n✅ 完全覆盖测试通过！")


if __name__ == "__main__":
    try:
        test_merge_scenario()
        test_overwrite_scenario()
        
        print("\n" + "=" * 60)
        print("🎉 所有测试通过！")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
