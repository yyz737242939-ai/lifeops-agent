# LifeOps Agent

LifeOps Agent 是一个本地 Python 项目，用来学习和构建 Agent Runtime 机制，同时逐步沉淀一个早期的个人生活管理助手。

当前仓库处于 Runtime 重构。V0 代码、数据、日志、测试、旧计划和旧入口统一保存在 `legacy_v0/`，作为历史对照。当前工作使用清爽的 `app/`、`docs/` 和 `plans/` 结构。

当前进度：阶段 0-5、阶段 6 ReAct Executor、阶段 7 Plan-and-Execute Planner、阶段 8 Research External Interfaces / Hugging Face MCP 与整个 Stage 9 Context / Memory 均已完成。Stage 9A 提供 session JSONL conversation、rolling summary、一次请求一份 bounded `ContextAssembly`，以及 Direct、Planning 和 PlanStep 的共享 projection；Stage 9B 提供只读 Profile、immutable Memory files + SQLite metadata index、verified retrieval、duplicate/conflict、update/archive lifecycle、memory Skill、5 个 Tool、Policy/confirmation/Gateway/evidence、生产 Context provider 和隐私事件。Stage 9A/9B 各 5 条真实 LLM paths、各 8 个 compiled E2E、最终 `561` 项统一离线测试零失败（`14` 项显式 live/platform gates 跳过）、`compileall`、`git diff --check` 与架构审计均通过；Stage 9B 结论为 `go`，整个 Stage 9 已关闭。

Stage 10 Execution Feedback / Recovery 已完成并通过 `go` gate：Direct与Planning执行会在Runtime最终输出前形成durable canonical `ExecutionFeedback`，使用structured claims/evidence校验模型成功声明，并通过独立、session-scoped、deterministic-only的`RecoveryRuntime`在重启后只读解释completed/partial/failed/denied/requires-confirmation/not-run事实。Feedback ArtifactReference、validation/stop/evidence RuntimeReport projection、Recovery `recovery_of` link和零执行Recovery topology均已接入LifeOps Trace Contract v1。真实Direct success、Planning completed、Tool failure/confirmation denial和Planning partial smoke通过；统一离线回归`696/696`通过（`21`项环境开关测试跳过）。本阶段不包含checkpoint、replay、resume、rollback、time travel或权限恢复。

Stage 11A Inspector / Runtime Debugger V1 已完成并通过 `go` gate：独立只读`app/inspection`通过shared `TraceReader + RuntimeReportBuilder + RuntimeReport`提供结构化查询、tree/timeline/details/dependency graph、evidence/integrity/annotation views和10条deterministic diagnosis rules；默认不读取敏感artifact内容，不解析raw JSONL，不触发任何执行或授权路径。compiled E2E `10/10`、Inspector/shared聚焦回归`44/44`与此前统一离线回归均通过。正式serial DAG Scheduler仍未实现，其compiled artifact在未来DAG模块完成后作为Inspector兼容性回归，不阻塞已关闭的Stage 11A。

Stage 11B Eval Harness V0 已完成并通过 `go` gate：独立 `app/evals` 提供严格 versioned manifests、isolated per-case workspace、typed target/fact adapters、10类 deterministic graders、shared evaluation annotations、text/JSON report、稳定 exit contract、11条 compiled E2E、历史 regression suite 与显式 `--live` real-LLM composition。最终统一离线回归 `787` 项零失败（`22` 项 live/platform gates 跳过），Direct READ、Planning preview/confirm、Recovery explain、Policy stop 四份 real-LLM Eval 报告全部通过。Eval 不读取真实用户数据、不授权或执行额外动作、不建设 hosted platform，也未实现通用 LLM-as-judge；正式 DAG Scheduler 仍是后续独立模块。

## 项目目标

LifeOps Agent 有两个目标：

- 构建一个小而清晰、可解释、适合学习和面试讲解的 Agent Runtime 项目。
- 保留继续演进成真实本地个人生活管理助手的路径。

项目应优先体现 runtime 边界、工具执行、上下文管理、权限控制、可观察性、恢复能力和可测试行为。

## 当前阅读路径

处理当前工作时，按以下顺序开始：

1. `README.md`
2. `docs/PROGRESS_LOG.md`
3. `docs/ARCHITECTURE.md`
4. `plans/RUNTIME_REFACTOR_PLAN.md`
5. 当前模块对应的 `plans/modules/*_PLAN.md`
6. 与任务直接相关的代码、测试和文档

默认不要读取归档的 V0 文档。`legacy_v0/` 只用于迁移、历史对照和追溯旧行为。

## 文档地图

- `AGENTS.md`：仅记录 Codex 协作规则。
- `docs/PROGRESS_LOG.md`：递增推进记录，只记录已经完成、已经学到、已经验证的项目演进事实。
- `docs/ARCHITECTURE.md`：当前 runtime 架构快照、模块边界、依赖方向和 runtime 不变量；该文件随实现推进覆盖更新，不作为历史流水账。
- `docs/RUNTIME_CONCEPTS.md`：伴随项目推进沉淀的学习笔记和面试解释，不直接维护外部链接。
- `docs/AGENT_LEARNING_LINKS.md`：已经学到或当前阶段正在学习的权威文档和官方学习链接索引，递增维护，不提前收录未学习主题。
- `docs/MIGRATION_INDEX.md`：V0 到当前实现的迁移、重写、归档和延后记录。
- `plans/RUNTIME_REFACTOR_PLAN.md`：总路线图。
- `plans/DOMAIN_CONTRACT_STANDARD.md`：Research、Travel 和未来业务 Domain 共享的 Port、Tool、只读接口、安全与测试规范。
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

CLI 入口是：

```powershell
uv run python main.py
```

本地 compiled Eval：

```powershell
uv run python main.py eval --suite runtime_core
```

真实模型 Eval 必须显式启用 gate，并建议通过单 case hard-timeout runner 运行：

```powershell
$env:LIFEOPS_RUN_EVAL_REAL_LLM_SMOKE='1'
uv run python tests/run_eval_live_smoke.py live-direct-read --timeout-seconds 300
```

## 当前方向

当前 runtime 将使用：

- `app/` 存放 runtime 代码；
- `docs/` 存放当前推进记录、架构快照、概念和学习链接；
- `plans/` 存放总计划和模块计划；
- SQLite 主要存放业务事实和适合关系查询的数据；event / LLM / normal 程序日志默认走文件。
- CLI + Inspector + Eval 作为第一版 demo 界面。
