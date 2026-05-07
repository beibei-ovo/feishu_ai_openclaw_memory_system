#!/usr/bin/env python3
"""简单测试 FastAPI 依赖注入"""

print("Testing FastAPI setup...")

try:
    from app.presentation.routers import (
        router,
        get_repository,
        get_predictor,
        get_ingester,
        CommandPredictor,
        MemoryRepository,
        FeishuIngester,
    )
    
    print("Imports OK")
    
    # 测试依赖生成
    print("\nTesting repository dependency...")
    repo_gen = get_repository()
    repo = next(repo_gen)
    assert isinstance(repo, MemoryRepository), "Repository should be MemoryRepository"
    print("Repository OK")
    
    print("\nTesting predictor dependency...")
    pred = get_predictor(repo)
    assert isinstance(pred, CommandPredictor), "Predictor should be CommandPredictor"
    print("Predictor OK")
    
    print("\nAll tests passed! You can start your server now.")
    
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
