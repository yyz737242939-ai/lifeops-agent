# 当前状态

本文档是 LifeOps Agent 的当前状态地图。

## 目的

通过本文档了解当前项目事实：

- 当前启用的架构是什么；
- 哪些模块已经存在；
- 哪些模块已经规划但尚未实现；
- 当前阶段哪些命令和测试是有效的；
- 哪些已知限制是有意保留的。

对于当前工作，本文档取代旧 `legacy_v0/docs/PROJECT_CONTEXT_legacy.md` 的角色。

## 当前阶段

项目已完成 Runtime 重构的阶段 2：Storage / SQLite 基础设施。

项目已完成阶段 3：Runtime Core / Intent / Policy 初版，当前准备进入阶段 4：LangGraph Orchestration 骨架。

当前状态：

- 当前基础设施代码已经完成阶段 2 初版。
- Runtime Core / Intent / Policy 已完成阶段 3 初版。
- 旧 runtime 已归档到 `legacy_v0/app/`。
- 当前代码放在 `app/`。
- 当前计划放在 `plans/`。
- 当前文档放在 `docs/`。
- 旧 V0 代码、数据、日志、测试、输出、MCP demo server、旧计划和旧文档都作为历史参考保存在 `legacy_v0/`，默认不读取。

已实现的当前 runtime 基础设施：

- `app/common/`：配置读取、ID、UTC 时间、项目错误类型和 JSON 序列化。
- `app/storage/`：SQLite 连接、schema migration、基础 evidence / LLM log 表和 `SqliteUnitOfWork`。
- `app/observability/`：结构化 trace log 和原始 LLM request-response log 的模型与 SQLite store。
- `app/runtime/`：`RuntimeRequest`、`RuntimeSession`、`RuntimeResult`、`RuntimeService`、run record 写入 helper 和启动 bootstrap。
- `app/intent/`：intent models、规则 classifier、LLM classifier 空实现和 `IntentService`。
- `app/policy/`：policy models、permission scope 和 `PolicyService`。
- `config/default.json`：声明默认数据库路径 `data/lifeops.sqlite3`。
- `main.py`：当前 CLI 骨架入口，负责 config、SQLite、migration、runtime service bootstrap 和单轮输入输出。
- `tests/`：基础设施、Intent、Policy 和 Runtime Core 聚焦测试，以及测试数据库 helper。

## 当前 Runtime

旧根入口已归档：

- `legacy_v0/entrypoints/main_legacy.py`
- `legacy_v0/entrypoints/log_viewer_legacy.py`
- `legacy_v0/entrypoints/product_ui_legacy.py`

如果需要按重构前的状态运行旧根入口，请使用 legacy checkpoint branch。

当前 CLI 骨架入口是：

```powershell
uv run python main.py
```

`main.py` 已存在，但仍是阶段 3 runtime skeleton，不是完整产品 CLI。

当前 `main.py` 已接入 `config/default.json`、SQLite migration 和 `RuntimeService`。`RuntimeService` 当前只执行：

```text
RuntimeRequest
-> IntentService
-> PolicyService
-> RuntimeResult
```

阶段 3 仍是 stub execution：policy `allow` 只表示当前请求通过授权判断，不代表已经执行真实 tool 或业务写入。测试中使用 `:memory:` SQLite 和 migration helper，不读写真实 `data/lifeops.sqlite3`。

进入下一阶段前的状态：

- 阶段 2 Storage / SQLite 已完成初版。
- 阶段 3 Runtime Core / Intent / Policy 已完成初版。
- `docs/ARCHITECTURE.md` 已记录 Runtime Core、Intent / Policy 和 stub execution 边界。
- `docs/RUNTIME_CONCEPTS.md` 已记录 Runtime Core、Intent Layer、Policy / Permission Layer 和 Write Safety 学习章节。
- `plans/modules/STORAGE_SQLITE_PLAN.md`、`plans/modules/RUNTIME_CORE_PLAN.md` 和 `plans/modules/INTENT_POLICY_PLAN.md` 已记录完成状态。
- 下一阶段应创建并施工 `plans/modules/LANGGRAPH_ORCHESTRATION_PLAN.md`，开始阶段 4：LangGraph Orchestration 骨架。

当前有效测试命令：

```powershell
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'; uv run python -m unittest discover -s tests -v
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'; uv run python -m compileall app tests
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'; uv run python -m unittest tests.test_intent_service tests.test_policy_service tests.test_runtime_service -v
```

## 目标架构

目标 runtime 链路是：

```text
User Input
-> Intent
-> Policy / Permission
-> LangGraph Orchestrator
-> Context / Memory / State Assembly
-> Planner or Direct Executor
-> Tool / Domain / External Integration
-> Execution Feedback
-> Trace / Inspector / Eval
-> Final Answer
```

详细总计划是：

```text
plans/RUNTIME_REFACTOR_PLAN.md
```

## 当前文档规则

默认阅读顺序：

```text
1. README.md
2. docs/CURRENT_STATE.md
3. plans/RUNTIME_REFACTOR_PLAN.md
4. 当前模块对应的 plans/modules/*_PLAN.md
5. 与任务直接相关的代码、测试和文档
```

默认不要读取 `legacy_v0/docs/PROJECT_CONTEXT_legacy.md`、`legacy_v0/docs/LEARNING_PROGRESS_legacy.md` 或 `legacy_v0/plans/*.md`。
