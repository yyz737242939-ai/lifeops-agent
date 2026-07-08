# Runtime 概念

本文档是 Runtime 的详细学习和面试手册。

每个概念使用以下模板：

```markdown
## <概念 / 模块>

### 解决什么问题

### 核心概念

### 当前 runtime 实现

### 输入 / 输出 / 不负责什么

### 常见失败模式

### 如何测试和观察

### 面试解释

### 延伸学习
- 官方文档
- 框架文档
- 项目文件
```

## 必需章节

- Agent Loop
- Intent Layer
- Policy / Permission Layer
- Tool System
- Capability
- Write Safety
- LangGraph Orchestrator
- LangChain Adapter
- Planner
- Executor
- Task State
- Task vs Plan
- Context Engine
- Memory
- Recovery
- MCP
- Calendar External Tool
- DAG Scheduler
- Eval Harness
- Inspector / Debugger
- Observability
- SQLite Local Persistence

## 官方参考

LangGraph 和 LangChain：

- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
- LangGraph low-level concepts: https://langchain-ai.github.io/langgraph/concepts/low_level/
- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph interrupts: https://docs.langchain.com/oss/python/langgraph/interrupts
- LangChain overview: https://docs.langchain.com/oss/python/langchain/overview
- LangChain tools: https://docs.langchain.com/oss/python/langchain/tools

MCP：

- MCP introduction: https://modelcontextprotocol.io/docs/getting-started/intro
- MCP specification: https://modelcontextprotocol.io/specification
- MCP tools: https://modelcontextprotocol.io/docs/concepts/tools
- MCP resources: https://modelcontextprotocol.io/docs/concepts/resources

当前 runtime 项目参考：

- `plans/RUNTIME_REFACTOR_PLAN.md`
- `docs/ARCHITECTURE.md`
- `docs/MIGRATION_INDEX.md`

## Observability

### 解决什么问题

Observability 让 runtime 行为可以被解释和复盘。它回答“这次 run 经过了哪些阶段、哪里失败、LLM 原始请求和响应是什么”。

### 核心概念

- 结构化 trace log：少量必要字段，便于机器读取和 Inspector 展示。
- 原始 LLM interaction log：保存 request / response JSON，便于人工排查。
- Runtime evidence：能证明运行路径和结果的持久化记录，但不自动等于业务事实。

### 当前 runtime 实现

当前实现位于：

- `app/observability/events.py`
- `app/observability/trace_store.py`
- `app/observability/llm_log_store.py`

`LogTraceEvent` 写入 `trace_events`。`LogLlmInteraction` 写入 `llm_interactions`。两类日志分表保存。

### 输入 / 输出 / 不负责什么

输入是 `run_id`、`seq`、事件类型、payload 或 LLM request-response。

输出是可按 `run_id` 读取、按 `seq` 排序的日志对象。

Observability 不负责授权写入，不负责改变业务状态，也不把 assistant 文本或 LLM response 自动升级成事实。

### 常见失败模式

- 缺少对应 `run_records`，外键写入失败。
- payload 不能 JSON 序列化。
- 测试 fixture 未提交，导致事务边界冲突。
- 原始 LLM log 过大或包含敏感字段，后续接入真实外部凭证前需要脱敏策略。

### 如何测试和观察

当前测试包括：

- `tests/test_observability_trace_store.py`
- `tests/test_observability_llm_log_store.py`

它们验证 append / list、run_id 过滤、seq 排序、外键约束和 JSON 序列化失败。

### 面试解释

可以这样讲：本项目把 observability 分成结构化 trace 和原始 LLM interaction 两条线。trace 给系统和 Inspector 判断 runtime 路径，LLM log 给人回看原始模型交互。两者都是 evidence，但不绕过 policy，也不是业务写入授权来源。

### 延伸学习

- 本项目：`app/observability/`
- 本项目：`app/storage/schema.py`
- 后续对照：OpenTelemetry / LangSmith

## SQLite Local Persistence

### 解决什么问题

SQLite Local Persistence 为本地 runtime 提供轻量、可测试、可查询的事实和 evidence 存储。

### 核心概念

- schema migration：管理数据库表结构版本，不迁移旧业务数据。
- repository / store：负责读写特定表。
- unit of work：管理一组写入的 commit / rollback。
- test database：测试使用 `:memory:` 或临时文件数据库，不触碰真实用户数据。

### 当前 runtime 实现

当前实现位于：

- `config/default.json`
- `app/common/config.py`
- `app/storage/sqlite.py`
- `app/storage/schema.py`
- `app/storage/migrations.py`
- `app/storage/unit_of_work.py`

默认数据库路径由 `config/default.json` 的 `database.path` 声明，当前是 `data/lifeops.sqlite3`。

### 输入 / 输出 / 不负责什么

输入是配置中的数据库路径或测试显式传入的 SQLite path。

输出是配置好的 SQLite connection、已应用的 schema version 和可被 store 使用的基础表。

Storage 不负责 intent、policy、planning、tool execution 或业务语义。

### 常见失败模式

- 配置缺少 `database.path`。
- 数据库路径不可写。
- 数据库 schema version 比当前代码更新。
- migration 中途失败。
- 在已有事务里再次开启 unit of work。

### 如何测试和观察

当前测试包括：

- `tests/test_common.py`
- `tests/test_storage_sqlite.py`
- `tests/test_storage_migrations.py`
- `tests/test_storage_unit_of_work.py`
- `tests/test_helpers.py`

测试数据库 helper 位于 `tests/helpers.py`。

### 面试解释

可以这样讲：本项目不用 ORM，先用 Python 标准库 `sqlite3` 建一个透明的本地持久层。启动时先连接数据库，再跑 schema migration，之后 repository / store 假设表结构已经准备好。写入通过 unit of work 统一 commit 或 rollback，避免半截运行证据落库。

### 延伸学习

- Python sqlite3: https://docs.python.org/3/library/sqlite3.html
- 本项目：`app/storage/`
- 本项目：`plans/modules/STORAGE_SQLITE_PLAN.md`
