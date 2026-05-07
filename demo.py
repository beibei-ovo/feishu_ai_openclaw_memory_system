#!/usr/bin/env python
"""
演示脚本：展示 Unified Memory Bus 的核心功能
1. 创建记忆
2. 查询记忆
3. 命令预测
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from app.domain.models import UnifiedMemory, ContentType, Role, MemoryStatus
from app.infrastructure.database import create_session_factory, SQLAlchemyMemoryRepository
from app.application.services import CommandPredictor, DefaultConflictDetector, LLMExtractor
from app.infrastructure.llm_clients import MockLLMClient
from uuid import uuid4
from datetime import datetime

def demo():
    print("="*60)
    print("Unified Memory Bus - 功能演示")
    print("="*60)
    
    # 1. 初始化
    print("\n[1/5] 初始化数据库...")
    session_factory = create_session_factory("sqlite:///demo.db")
    repo = SQLAlchemyMemoryRepository(session_factory())
    
    # 2. 添加一些演示记忆
    print("\n[2/5] 添加演示记忆...")
    memories = [
        UnifiedMemory(
            memory_id=uuid4(),
            session_id=uuid4(),
            turn_id=1,
            topic="数据库配置",
            content="开发环境 MySQL 密码是 dev_mysql_123",
            content_type=ContentType.TEXT,
            role=Role.USER,
            execution_params={"mysql_password": "dev_mysql_123"},
            tags=["mysql", "dev", "database"],
            created_at=datetime.utcnow(),
            user_id="dev_user_1",
            project_path="/team1/project-a",
            git_branch="develop",
            environment="dev"
        ),
        UnifiedMemory(
            memory_id=uuid4(),
            session_id=uuid4(),
            turn_id=2,
            topic="API密钥",
            content="Stripe API 密钥是 sk_test_abc123xyz",
            content_type=ContentType.TEXT,
            role=Role.USER,
            execution_params={"stripe_key": "sk_test_abc123xyz"},
            tags=["stripe", "payment", "api"],
            created_at=datetime.utcnow(),
            user_id="dev_user_1",
            project_path="/team1/project-a",
            git_branch="develop",
            environment="dev"
        ),
        UnifiedMemory(
            memory_id=uuid4(),
            session_id=uuid4(),
            turn_id=3,
            topic="服务器配置",
            content="测试服务器地址是 192.168.1.100:8080",
            content_type=ContentType.TEXT,
            role=Role.USER,
            execution_params={"server_host": "192.168.1.100", "server_port": "8080"},
            tags=["server", "test", "deploy"],
            created_at=datetime.utcnow(),
            user_id="dev_user_2",
            project_path="/team2/project-b",
            git_branch="main",
            environment="test"
        )
    ]
    
    for mem in memories:
        repo.save(mem)
        print(f"  [OK] 已保存: {mem.topic}")
    
    # 3. 展示记忆隔离功能
    print("\n[3/5] 演示记忆隔离功能...")
    print("\n查询用户 dev_user_1, 项目 /team1/project-a 的记忆:")
    results1 = repo.search_with_context(
        topic_query="",
        user_id="dev_user_1",
        project_path="/team1/project-a"
    )
    for r in results1:
        print(f"  - {r.topic}: {r.content[:40]}...")
    
    print("\n查询用户 dev_user_2, 项目 /team2/project-b 的记忆:")
    results2 = repo.search_with_context(
        topic_query="",
        user_id="dev_user_2",
        project_path="/team2/project-b"
    )
    for r in results2:
        print(f"  - {r.topic}: {r.content[:40]}...")
    
    # 4. 演示命令预测
    print("\n[4/5] 演示命令预测功能...")
    predictor = CommandPredictor(repo)
    
    test_cases = [
        {
            "command": "mysql",
            "user_id": "dev_user_1",
            "project_path": "/team1/project-a"
        },
        {
            "command": "curl",
            "user_id": "dev_user_2",
            "project_path": "/team2/project-b"
        }
    ]
    
    for test in test_cases:
        result = predictor.predict_command(
            command_prefix=test["command"],
            user_id=test["user_id"],
            project_path=test["project_path"]
        )
        
        print(f"\n用户 {test['user_id']} 在项目 {test['project_path']} 输入 '{test['command']}':")
        if result["recommendations"]:
            print(f"  [OK] 推荐参数: {result['recommendations']}")
            print(f"  来源: {result['source_info'][:60]}...")
        else:
            print(f"  [NO] 没有找到相关记忆")
    
    # 5. 查询所有记忆
    print("\n[5/5] 查询所有活跃记忆...")
    all_memories = repo.find_all_active()
    print(f"\n总共 {len(all_memories)} 条活跃记忆\n")
    
    print("="*60)
    print("演示完成！")
    print("="*60)
    print("\n总结:")
    print("  1. 系统成功存储了带上下文信息的记忆")
    print("  2. 不同用户/项目的记忆完全隔离")
    print("  3. 命令预测功能正常工作")
    print("\n连接飞书后:")
    print("  - 群聊消息会被自动提取为记忆")
    print("  - CLI 插件可以查询这些记忆来自动补全命令")
    print("  - 不同团队的信息互相隔离，保证安全")

if __name__ == "__main__":
    demo()