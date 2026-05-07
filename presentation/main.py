from fastapi import FastAPI
from app.presentation.routers import router
import os

app = FastAPI(title="Unified Memory Bus", version="1.0.0")
app.include_router(router)

USE_MOCK_LLM = os.getenv("USE_MOCK_LLM", "true").lower() == "true"
USE_ASYNC_MODE = os.getenv("USE_ASYNC_MODE", "false").lower() == "true"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# 消息队列全局实例（供健康检查用）
message_queue_instance = None
if USE_ASYNC_MODE:
    try:
        from app.infrastructure.message_queue import create_message_queue
        message_queue_instance = create_message_queue({
            "type": "memory",  # 默认使用内存队列
        })
        print("Message queue initialized successfully")
    except Exception as e:
        print(f"Warning: Failed to initialize message queue: {e}")


@app.get("/")
def health_check():
    queue_length = 0
    if message_queue_instance:
        try:
            queue_length = message_queue_instance.get_queue_length()
        except Exception:
            pass
    
    return {
        "status": "healthy",
        "service": "Unified Memory Bus",
        "async_mode": USE_ASYNC_MODE,
        "queue_length": queue_length,
    }


@app.on_event("shutdown")
def shutdown_event():
    """应用关闭时清理资源"""
    global message_queue_instance
    if message_queue_instance:
        try:
            message_queue_instance.close()
            print("Message queue closed successfully")
        except Exception as e:
            print(f"Error closing message queue: {e}")


if __name__ == "__main__":
    import uvicorn
    import sys
    
    # 检查是否启动 Worker
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        from app.application.worker import run_worker
        print("Starting Worker process...")
        run_worker(
            queue_config={"type": "redis_list", "redis_url": REDIS_URL},
            llm_config={"use_mock": USE_MOCK_LLM},
            window_size=int(os.getenv("WINDOW_SIZE", "10")),
            window_timeout=int(os.getenv("WINDOW_TIMEOUT", "300")),
        )
    else:
        print(f"Starting API server (async_mode={USE_ASYNC_MODE})")
        uvicorn.run(app, host="0.0.0.0", port=8001)