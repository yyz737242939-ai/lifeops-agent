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

项目正在进入 Runtime 重构的存储与基础设施阶段。

当前状态：

- 当前基础设施代码已经开始实现。
- 旧 runtime 已归档到 `legacy_v0/app/`。
- 当前代码放在 `app/`。
- 当前计划放在 `plans/`。
- 当前文档放在 `docs/`。
- 旧 V0 代码、数据、日志、测试、输出、MCP demo server、旧计划和旧文档都作为历史参考保存在 `legacy_v0/`，默认不读取。

已实现的当前 runtime 基础设施：

- `app/common/`：配置读取、ID、UTC 时间、项目错误类型和 JSON 序列化。
- `app/storage/`：SQLite 连接、schema migration、基础 evidence / LLM log 表和 `SqliteUnitOfWork`。
- `app/observability/`：结构化 trace log 和原始 LLM request-response log 的模型与 SQLite store。
- `config/default.json`：声明默认数据库路径 `data/lifeops.sqlite3`。
- `tests/`：基础设施聚焦测试和测试数据库 helper。

## 当前 Runtime

旧根入口已归档：

- `legacy_v0/entrypoints/main_legacy.py`
- `legacy_v0/entrypoints/log_viewer_legacy.py`
- `legacy_v0/entrypoints/product_ui_legacy.py`

如果需要按重构前的状态运行旧根入口，请使用 legacy checkpoint branch。

未来入口是：

```powershell
uv run python main.py
```

`main.py` 尚不存在。

当前存储入口尚未接入 `main.py`。测试中使用 `:memory:` SQLite 和 migration helper，不读写真实 `data/lifeops.sqlite3`。

当前有效测试命令：

```powershell
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'; uv run python -m unittest discover -s tests -v
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'; uv run python -m compileall app tests
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
