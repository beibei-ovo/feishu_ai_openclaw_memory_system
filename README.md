# Unified Memory Bus (ChatOps to DevEx)

## 项目概述

企业内研发决策（在飞书/Lark群聊中发生）与一线执行（在开发者 CLI 终端中发生）存在物理隔离。本项目构建一个"中央记忆路由层"，将飞书群聊中的非结构化决策，实时提取为结构化记忆，并下发给开发者的本地 CLI 终端，实现命令/参数的智能补全与拦截。

## 当前进度 ✅

### 已完成功能

1. ✅ **飞书机器人集成**
   - 接收飞书 Webhook 事件
   - 支持单聊和群聊
   - 自动回复功能
   - 记忆查询功能

2. ✅ **核心数据模型**
   - UnifiedMemory 完整实现
   - SQLAlchemy ORM 存储
   - 项目级记忆隔离

3. ✅ **5 阶段数据过滤流水线**
   - 阶段 1：格式预处理（清洗 HTML、Markdown、表情符号）
   - 阶段 2：价值判定（关键词匹配，语义向量检索可选）
   - 阶段 3：内容提纯（提取代码块）
   - 阶段 4：元信息规整（清理空标签）
   - 阶段 5：时效性/冗余过滤（哈希去重）

4. ✅ **增量合并机制**
   - LLM 智能判断冲突类型（overwrite/merge/no_conflict）
   - 增量合并：保留旧记忆参数，添加新参数
   - 完全覆盖：新信息完全推翻旧信息

5. ✅ **异步架构设计**
   - Redis 消息队列抽象（支持内存和 Redis 两种模式）
   - 滑动窗口处理器（SlidingWindowProcessor）
   - Worker 进程独立运行
   - 快速响应（< 100ms）

6. ✅ **历史决策卡片回复**
   - 标准格式回复
   - 动态匹配分数计算
   - 记忆查询展示

### 当前配置

- **异步模式**：默认关闭（USE_ASYNC_MODE=false）
- **LLM 模式**：默认使用 Mock LLM（USE_MOCK_LLM=true）
- **语义向量检索**：默认关闭（Windows 兼容性问题）
- **数据库**：SQLite（轻量级，开箱即用）

## 项目架构

```
f:\feishuai\
├── app/
│   ├── domain/                      # 领域层
│   │   ├── models.py                # UnifiedMemory, ContentType, CodeMeta, Role
│   │   └── interfaces.py            # MemoryRepository, ConflictDetector, LLMClient
│   ├── infrastructure/              # 基础设施层
│   │   ├── database.py              # SQLAlchemy ORM 实现
│   │   ├── llm_clients.py           # DoubaoLLMClient（豆包大模型）+ MockLLMClient
│   │   ├── filtering.py             # DataFilter（5阶段数据过滤）
│   │   ├── vector_search.py         # SemanticVectorSearch（语义向量检索）
│   │   ├── message_queue.py         # MessageQueue（Redis 消息队列抽象）
│   │   └── feishu_client.py         # Feishu API 客户端
│   ├── application/                 # 应用层
│   │   ├── services.py              # LLMExtractor, FeishuIngester, CommandPredictor
│   │   └── worker.py                # SlidingWindowProcessor（滑动窗口后台处理）
│   └── presentation/                # 表现层
│       ├── routers.py               # API 路由（飞书 Webhook 处理）
│       └── main.py                  # FastAPI 入口
├── requirements.txt                 # 依赖配置
└── test_merge.py                    # 增量合并测试脚本
```

## 项目级记忆隔离

### 解决的问题
原来的预测接口只接收命令前缀，会导致不同团队/项目的记忆交叉污染：
- **场景**: A团队Leader在飞书群聊中发了核心数据库密码，B团队实习生在终端敲 `mysql -u root` 时，系统可能把A团队的密码自动补全给他！
- **问题**: 缺乏租户/项目级的隔离机制

### 新的解决方案：强制上下文 + 空间过滤
系统现在要求客户端（CLI 插件）上报当前上下文环境，并在检索时进行严格过滤：

1. **强制参数**：`user_id`（执行者）、`project_path`（项目路径）、`git_branch`（当前分支）、`environment`（环境类型）
2. **检索过滤**：优先匹配相同上下文的记忆，再回退到无上下文的公共记忆
3. **数据模型扩展**：UnifiedMemory 新增上下文字段，并在数据库建立索引

### 新增 API 调用示例

```bash
curl -X POST http://localhost:8001/api/v1/predict_command \
  -H "Content-Type: application/json" \
  -d '{
    "command_prefix": "mysql -u root",
    "user_id": "user_123",
    "project_path": "/home/user/project-a",
    "git_branch": "main",
    "environment": "dev"
  }'
```

### 数据模型扩展（UnifiedMemory 新增字段）

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | str | 执行者ID（CLI用户或飞书发送者） |
| project_path | str | 项目路径（CLI项目或飞书chat_id） |
| git_branch | str | 当前Git分支 |
| environment | str | 环境类型：dev/test/prod |

## 增量合并机制

### 解决的问题
原来的简单覆盖策略会导致记忆丢失：
- **旧记忆**: Redis IP = 192.168.1.100
- **新记忆**: Redis PORT = 6380  
- **结果**: IP 被完全覆盖，丢失了！

### 新的解决方案：智能判断 + 增量合并
系统现在使用 LLM 智能判断新旧记忆的关系：

1. **overwrite（覆盖）**: 新信息完全推翻旧信息（如 IP 从 1.1.1.1 改为 2.2.2.2）
2. **merge（增量合并）**: 新信息是对旧信息的补充（如增加 PORT）
3. **no_conflict（无冲突）**: 两者完全不相关，可以共存

### 示例

#### 场景1：增量合并（补充端口）
```
旧记忆: topic=redis, params={"host": "1.1.1.1"}
新记忆: topic=redis, params={"port": "6380"}
结果: merge, params={"host": "1.1.1.1", "port": "6380"} ✅
```

#### 场景2：完全覆盖（更换数据库）
```
旧记忆: topic=database, params={"service": "mysql", "host": "prod.mysql.com"}
新记忆: topic=database, params={"service": "postgresql", "host": "prod.pg.com"}
结果: overwrite, params={"service": "postgresql", "host": "prod.pg.com"} ✅
```

## 异步架构设计

为了满足飞书 Webhook 3秒超时限制，系统采用异步解耦架构：

```
┌─────────────┐
│  飞书群聊    │
└──────┬──────┘
       │ 消息事件
       ▼
┌───────────────────┐    立即返回 200 OK
│  API Server       │    (< 100ms)
│  (FastAPI)        ├───────────┐
│  - 格式预处理     │           │
│  - 价值过滤       │           │
│  - 推入队列       │           │
└────────┬──────────┘           │
         │                      │
         ▼                      │
┌───────────────────┐            │
│  Redis Queue      │            │
│  (消息缓冲)       │            │
└────────┬──────────┘            │
         │                       │
         ▼                       │
┌───────────────────┐            │
│  Worker Process   │◄───────────┘
│  (滑动窗口)       │
│  - 凑满10条触发   │
│  - 或超时5分钟触发│
│  - LLM 提取记忆   │
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  数据库存储       │
└───────────────────┘
```

### 设计优势
1. **快速响应**：API 只做快速过滤和入队，响应时间 < 100ms
2. **避免重传**：不会触发飞书超时重传机制
3. **流量削峰**：Redis 作为缓冲，平滑突发流量
4. **滑动窗口**：凑满 10 条或 5 分钟超时触发批量处理，降低 LLM 调用成本

## 核心数据模型：UnifiedMemory

| 字段 | 类型 | 说明 |
|------|------|------|
| memory_id | UUID | 记忆唯一标识 |
| session_id | UUID | 会话唯一标识（区分不同代码任务会话） |
| turn_id | int | 单会话内的轮次编号（保证多轮顺序） |
| topic | str | 决策议题 |
| content | str | 核心内容（原 semantic_context） |
| content_type | ContentType | 枚举：TEXT, CODE, FEEDBACK, SUMMARY |
| role | Role | 枚举：USER, ASSISTANT |
| execution_params | Dict | CLI 参数键值对 |
| code_meta | CodeMeta | 代码专属元信息：lang, task, snippet_id |
| status | MemoryStatus | 枚举：ACTIVE, SUPERSEDED, DEPRECATED |
| tags | List[str] | 标签列表（用于检索） |
| token_count | int | token 数（用于上下文窗口控制） |
| created_at | datetime | 时间戳 |
| supersedes_id | UUID | 指向被覆写的旧记忆 |
| **user_id** | str | 执行者ID（CLI用户或飞书发送者） |
| **project_path** | str | 项目路径（CLI项目或飞书chat_id） |
| **git_branch** | str | 当前Git分支 |
| **environment** | str | 环境类型：dev/test/prod |

## 数据过滤流水线

### 5阶段过滤流程

| 阶段 | 功能 | 实现方式 |
|------|------|---------|
| **阶段1：格式预处理** | 清洗无意义噪点 | 移除HTML标签、Markdown格式、表情符号、连续空格 |
| **阶段2：价值判定** | 判断是否有保留意义 | 优先：语义向量检索 + 阈值判断<br>备选：关键词匹配（多职业覆盖） |
| **阶段3：内容提纯** | 提取代码场景核心信息 | 正则匹配代码块，保留核心价值内容 |
| **阶段4：元信息规整** | 过滤无效元数据 | 清理空标签、验证 code_meta 一致性 |
| **阶段5：时效性/冗余过滤** | 长期记忆专用 | 时效性过滤（默认30天）+ 哈希去重 |

### 语义向量检索（阶段2）

- 模型：`BAAI/bge-small-zh-v1.5`（智源研究院出品，专为中文优化）
- 内置决策意图模板：40+条（覆盖通用、技术、产品、运营、运维、测试、项目管理）
- 支持动态添加自定义意图模板
- 相似度阈值：0.5（可配置）
- 容错机制：向量检索失败自动降级到关键词匹配
- **注意**：Windows 上可能存在兼容性问题，默认使用关键词匹配

## 飞书机器人功能

### 基本使用

1. **发送消息**：直接在飞书聊天中发送消息
2. **查询记忆**：发送包含"查询"、"记忆"、"记得"等关键词的消息
3. **群聊支持**：将机器人拉入群聊，自动接收和处理群消息

### 历史决策卡片格式

```
历史决策卡片

主题: MVP 是否支持 AI 自动写入企业知识库
结论:
MVP 阶段只做带来源引用的知识库问答，不支持 AI 自动写入正式知识库。
理由:
自动写入存在模型幻觉污染知识库、追责困难、权限校验、审批流和版本回滚成本高等风险。
备选方案:支持 AI自动改写并写入知识库;允许 AI 生成内容但需审核后写入
反对意见:如果完全不支持写入，产品闭环不完整，用户可能仍需手动整理结论。
状态: 生效中
匹配分数: 0.3509
来源: OpenClaw 公网测试
触发问题: 这版要不要让 AI 直接把会议总结写回知识库?...
```

## 核心模块

### FeishuIngester
- 接收飞书 Webhook 事件
- 时间窗口聚合上下文（默认10条）
- 调用数据过滤流水线
- 提供过滤统计信息
- 支持同步和异步两种模式

### LLMExtractor
- 调用豆包大模型 API（或 Mock LLM）
- 提取为 UnifiedMemory 结构
- 内置冲突检测逻辑（同 Topic 已有 ACTIVE 记忆则标记为 SUPERSEDED）
- 支持增量合并

### CommandPredictor
- 多维检索：按 session_id, tags, topic（模糊）
- 排序：优先 ACTIVE, 高 turn_id, 最新时间
- 输出推荐补全参数 + 飞书决策来源说明

### SlidingWindowProcessor
- 滑动窗口消息处理
- 支持批量 LLM 调用
- 可配置窗口大小和超时时间

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/predict_command` | **核心端点** - 接收命令前缀，返回补全参数 |
| POST | `/api/v1/memories` | 创建记忆 |
| GET | `/api/v1/memories` | 查询记忆列表 |
| GET | `/api/v1/memories/{memory_id}` | 查询单个记忆 |
| POST | `/api/v1/feishu/webhook` | 飞书 Webhook 入口 |
| GET | `/` | 健康检查 |

## 状态机流转

```
ACTIVE ──(新记忆创建)──→ SUPERSEDED  
ACTIVE ──(手动标记)──→ DEPRECATED  
SUPERSEDED ──(手动标记)──→ DEPRECATED
```

## 快速开始

### 前置准备

无需特殊准备！开箱即用。

（可选）如果需要使用异步模式，需要：
1. **Redis**：用于消息队列
   - Windows：下载 [Redis for Windows](https://github.com/microsoftarchive/redis/releases)
   - macOS：`brew install redis && brew services start redis`
   - Linux：`sudo apt-get install redis-server && sudo service redis-server start`

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置环境变量

```bash
# 豆包 LLM 配置（可选，不配置则使用 Mock LLM）
DOUBAO_API_KEY=your-api-key
DOUBAO_SECRET_KEY=your-secret-key

# 异步模式配置（默认关闭，使用同步模式）
USE_ASYNC_MODE=false
REDIS_URL=redis://localhost:6379/0

# Worker 滑动窗口配置
WINDOW_SIZE=10           # 窗口大小（条）
WINDOW_TIMEOUT=300       # 窗口超时（秒）

# 使用 Mock LLM（无需豆包 Key，用于测试，默认开启）
USE_MOCK_LLM=true

# 语义向量检索（默认关闭，Windows 兼容性问题）
USE_VECTOR_SEARCH=false
```

### 启动服务

#### 方式一：开发/测试环境（推荐）

使用同步模式，单进程，无需 Redis：

```bash
python -m app.presentation.main
```

服务启动在：http://localhost:8001

#### 方式二：生产环境（异步模式）

需要启动两个进程：

**终端 1 - 启动 API 服务器**：
```bash
USE_ASYNC_MODE=true python -m app.presentation.main
```

**终端 2 - 启动 Worker 进程**：
```bash
python -m app.presentation.main worker
```

### 验证服务

访问 http://localhost:8001/ 查看健康检查：
```json
{
  "status": "healthy",
  "service": "Unified Memory Bus",
  "async_mode": false,
  "queue_length": 0
}
```

访问 http://localhost:8001/docs 查看 API 文档。

### 测试飞书机器人

1. 在飞书中添加机器人
2. 发送消息："我们决定使用 MySQL 数据库"
3. 查询记忆："查询记忆"

## 性能说明

| 阶段 | 首次运行 | 后续运行 |
|------|---------|---------|
| 模型加载（语义检索） | 10-40秒 | 0秒 |
| 单条消息过滤（关键词匹配） | 1-5ms | 1-5ms |
| 单条消息过滤（语义检索） | 80-150ms | 50-120ms |

### 模型说明
- 默认模型：`BAAI/bge-small-zh-v1.5`（智源研究院出品，专为中文优化，支持互联网黑话/中英混排）
- 备选模型：也支持 `m3e-base` 等其他中文语义模型

### 快速模式（禁用语义检索）

```python
# 在 filtering.py 中配置
filter = DataFilter(use_vector_search=False)
```
单条消息过滤耗时：1-5ms

## 部署到飞书

1. 访问 [飞书开放平台](https://open.feishu.cn) 创建企业自建应用
2. 配置机器人基本信息
3. 在「事件订阅」中配置请求网址：`https://your-domain/api/v1/feishu/webhook`
4. 订阅事件：`im.message.receive_v1`（接收消息）
5. 发布上线

**注意**：开发阶段可以使用 ngrok 等工具将本地服务暴露到公网。

## 扩展说明

### 添加自定义决策意图

```python
from app.infrastructure.filtering import DataFilter

filter = DataFilter()
filter.add_custom_intent("这个需求我们采用A方案")
filter.add_custom_intent("运营活动定在下周五")
```

### 自定义决策关键词（备选方案）

```python
custom_keywords = ["产品", "运营", "活动", "用户", "增长"]
filter = DataFilter(decision_keywords=custom_keywords, use_vector_search=False)
```

## 技术栈

- **Web框架**：FastAPI
- **数据模型**：Pydantic
- **ORM**：SQLAlchemy
- **数据库**：SQLite（默认）/ PostgreSQL（可选）
- **LLM**：豆包（ByteDance）+ Mock LLM
- **向量检索**：sentence-transformers
- **消息队列**：Redis（可选）+ 内存队列
- **语言**：Python 3.8+

## 已知问题和解决方案

### Windows 上语义向量检索初始化失败

**问题**：`Failed to initialize vector search: [WinError 14007]`

**解决方案**：默认使用关键词匹配（`use_vector_search=False`），无需语义检索也能正常工作。

### 飞书机器人不回复

**问题**：发送消息后机器人没有反应

**解决方案**：
1. 检查 Webhook 配置是否正确
2. 查看服务器日志
3. 确认机器人权限是否正确配置

## 下一步计划

- [ ] 完善 LLM 提取逻辑（当前使用 Mock LLM）
- [ ] 添加 CLI 插件
- [ ] 支持更多数据源（Slack、钉钉等）
- [ ] 优化语义向量检索在 Windows 上的兼容性
- [ ] 添加 Web 管理界面
- [ ] 支持记忆导出和导入
