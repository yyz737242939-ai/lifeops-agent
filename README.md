# LifeOps Agent

LifeOps Agent 是一个本地 Python 项目，用来学习和构建 Agent Runtime 机制，同时逐步沉淀一个早期的个人生活管理助手。

当前仓库正在进入 Runtime 重构。V0 代码、数据、日志、测试、旧计划和旧入口统一保存在 `legacy_v0/`，作为历史对照。当前工作使用清爽的 `app/`、`docs/` 和 `plans/` 结构。

## 项目目标

LifeOps Agent 有两个目标：

- 构建一个小而清晰、可解释、适合学习和面试讲解的 Agent Runtime 项目。
- 保留继续演进成真实本地个人生活管理助手的路径。

项目应优先体现 runtime 边界、工具执行、上下文管理、权限控制、可观察性、恢复能力和可测试行为。

## 当前阅读路径

处理当前工作时，按以下顺序开始：

1. `README.md`
2. `docs/CURRENT_STATE.md`
3. `plans/RUNTIME_REFACTOR_PLAN.md`
4. 当前模块对应的 `plans/modules/*_PLAN.md`
5. 与任务直接相关的代码、测试和文档

默认不要读取归档的 V0 文档。`legacy_v0/` 只用于迁移、历史对照和追溯旧行为。

## 文档地图

- `AGENTS.md`：仅记录 Codex 协作规则。
- `docs/CURRENT_STATE.md`：当前项目状态、有效命令、已实现模块和已知限制。
- `docs/ARCHITECTURE.md`：runtime 架构、模块边界、依赖方向和 runtime 不变量。
- `docs/RUNTIME_CONCEPTS.md`：学习笔记、官方链接和面试解释。
- `docs/AGENT_LEARNING_LINKS.md`：Agent 核心概念的权威文档和官方学习链接索引。
- `docs/INTERVIEW_DEMO_GUIDE.md`：demo 脚本和讲解路径。
- `docs/MIGRATION_INDEX.md`：V0 到当前实现的迁移、重写、归档和延后记录。
- `docs/decisions/*.md`：架构决策。
- `plans/RUNTIME_REFACTOR_PLAN.md`：总路线图。
- `plans/modules/*_PLAN.md`：聚焦的模块实施计划。
- `CHANGELOG.md`：里程碑历史，只在明确要求时更新。

## Legacy 归档

旧根入口已作为 V0 参考归档：

- `legacy_v0/entrypoints/main_legacy.py`
- `legacy_v0/entrypoints/log_viewer_legacy.py`
- `legacy_v0/entrypoints/product_ui_legacy.py`

V0 runtime 包、测试、数据、日志、MCP demo server、输出、旧文档和旧实施计划也都归档在 `legacy_v0/` 下。

如果需要按重构前的状态运行旧根入口，请使用 legacy checkpoint branch。

## 计划入口

未来 CLI 入口是：

```powershell
uv run python main.py
```

## 当前方向

当前 runtime 将使用：

- `app/` 存放 runtime 代码；
- `docs/` 存放当前状态、架构、概念和面试文档；
- `plans/` 存放总计划和模块计划；
- SQLite 作为本地事实和 runtime evidence 的存储；
- CLI + Inspector + Eval 作为第一版 demo 界面。
