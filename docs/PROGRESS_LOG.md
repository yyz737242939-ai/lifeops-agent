# 推进日志

本文档是 LifeOps Agent 的递增推进记录。

## 目的

通过本文档追溯项目已经完成、已经验证、已经学到的演进过程：

- 哪些模块已经存在；
- 哪些模块已经规划但尚未实现；
- 当前阶段哪些命令和测试是有效的；
- 哪些已知限制是有意保留的。

本文档只记录已经发生的事实和已经沉淀的学习点。不记录尚未学习的概念，不替代当前架构快照；当前 runtime 边界以 `docs/ARCHITECTURE.md` 为准。

## 当前阶段

项目已完成 Runtime 重构的阶段 2：Storage / SQLite 基础设施。

项目已完成阶段 3：Runtime Core / Intent / Policy 初版。

项目已完成阶段 3.5：Observability 文件日志校正。

项目已完成阶段 4：LangGraph Orchestration 骨架，当前准备进入阶段 5：Skill System / Tool System 与 Domains。

阶段 5 已完成计划收敛，并已开始 Skill System 的分步实现：

- Skill System 已完成核心模型、错误、metadata registry 和原生 discovery / validation；当前严格支持 `name`、`description` frontmatter 子集，不引入 Deep Agents / LangChain loader 或 middleware。
- discovery 只扫描根目录的直接 Skill 子目录，只读取 `SKILL.md` metadata；完整 body 和附属资源仍保持未加载。
- `app/skills/research/SKILL.md` 和 `app/skills/travel/SKILL.md` skeleton 已建立，记录各自适用场景、事实边界和 planned workflow；尚未实现的工具与 capability 不伪装成可用能力。
- Skill selector 已通过 `SkillSelectionClient` 薄接口接收 `RuntimeRequest + 全量 Skill metadata`，支持零到多个 Skill；LifeOps 校验严格输出字段、非空 reason、重复 ID 和未知 ID，不依赖框架 selector。
- selected Skill body 已支持按需加载；reference 只能通过 `references/manifest.json` 中的稳定 ID 读取相对 Skill root 的 Markdown 文件，并校验 traversal、文件类型、空正文和大小限制。
- Skill trace 只记录 selection、body load、reference load 的成功或失败语义事件；不记录机械文件 lifecycle，不泄漏用户原文、LLM selection reason、Skill body 或 reference 正文。
- prompt contribution assembler 已实现：只从 selected-and-loaded Skills 生成 `PromptContribution`，保留选择顺序并拒绝重复 Skill ID；core rules、工具描述、Context budget 和最终 prompt 排序仍不属于 Skill System。
- LangGraph allow 路径已接入 request-local `prepare_skills`：Policy allow 后执行 Skill selection、selected body loading 和 contribution assembly，再进入现有 stub execution；确认与拒绝分支不调用 selector。
- `SkillService` 已收敛为与 Intent/Policy service 对称的构造依赖：它长期持有 `SkillRegistry` 和 `SkillSelectionClient`，并在 graph 构建时注入；只有每个 run 不同的 `TraceSink` 留在 `OrchestrationContext`。GraphState 只保存当前 run 的 selection、loaded IDs 和 contributions。
- Skill 阶段失败返回 `runtime.skill_failed`，不会继续 stub execution。
- 生产 bootstrap 已调用 `discover_skills(config.skill_root)`，构建 `SkillRegistry`、`SkillSelectionClient()` 和 `SkillService` 后注入 Runtime；`config/default.json` 只负责 Skill root，模型与 OpenAI-compatible provider 地址由 client 直接从 `.env` 读取。
- `SkillSelectionClient` 使用 OpenAI-compatible Chat Completions JSON 输出，只发送用户请求与全量 Skill ID/description，不发送未选中的 body；provider 输出经过 Pydantic 解析和 LifeOps 业务校验。当前只记录关键 Skill event，原始 provider interaction 等统一 LLM Gateway 出现后再集中写入 `llm.jsonl`，不在 `SkillService` 参数中逐层传递日志对象。
- Skill 永久启用，不再提供 `selection_enabled` 配置或 `SkillService is None` 分支；Runtime、Orchestrator 和 graph 都要求显式注入 `SkillService`。
- `tests/fixtures/skills/` 已建立 schema version 1 的长期 Eval case 形状，覆盖 Research、Travel、跨 Domain、零 Skill，以及未知 ID、重复 ID、空 reason 等结构失败。
- Agent Skills specification 和 Deep Agents Skills 仅作为格式、命名约束与 progressive disclosure 的实现参考；框架 adapter 保留为未来边界。
- Tool System 采用 LifeOps 原生安全核心与可选 LangChain adapter；所有工具经过统一 Tool Gateway 和 pre/post Guardrails。
- Tool System 第一步已完成框架无关的核心模型：Tool definition 与 handler 分离，并定义 capability、call/result/error、execution evidence 和结构化 pre/post guardrail decision；registry、capability intersection 与 gateway 尚未实现。
- 两个内部 Domain 从原路线图的 Tasks + Wellbeing 调整为 Research / Personal Knowledge + Travel。
- Research 首个外部只读场景是 Hugging Face Daily Papers / Blog briefing；临时结果不自动保存为知识或 Memory。
- Travel 先定义 typed external Ports 并使用 fixture adapters；真实 Calendar MCP 仍在阶段 8 接入。
- 阶段 5 模块计划已记录 Context、Memory、Planner、Executor、Recovery、MCP、DAG、Inspector、Eval 的未来接入边界。
- Domain 已明确为业务 models/service/repository/tools 的逻辑分组，不是独立 Agent 或执行边界；同一通用 PlanRun 可以交叉调用 Research 与 Travel tools。
- 简单单工具请求未来走 Direct Executor；复杂、多步骤或有依赖请求走 Planner → Executor。PlanStep 绑定 objective/capability/candidate tools，WRITE 默认逐 step 授权。
- PlanRun / PlanStep 可为跨进程恢复而持久化，但不是业务事实；跨 Domain 部分成功时不做全局回滚，保留成功 evidence，从失败 step 恢复或 bounded replan。
- LangGraph checkpoint 是未来保存 graph/thread state、interrupt、fault tolerance 和 time travel 的候选机制，不负责撤销已经提交的 Domain WRITE 或外部副作用。

当前状态：

- 当前基础设施代码已经完成阶段 2 初版。
- Runtime Core / Intent / Policy 已完成阶段 3 初版。
- Observability 文件日志已完成阶段 3.5 初版。
- LangGraph Orchestration 已完成阶段 4 初版。
- 旧 runtime 已归档到 `legacy_v0/app/`。
- 当前代码放在 `app/`。
- 当前计划放在 `plans/`。
- 当前文档放在 `docs/`。
- 旧 V0 代码、数据、日志、测试、输出、MCP demo server、旧计划和旧文档都作为历史参考保存在 `legacy_v0/`，默认不读取。

已实现的当前 runtime 基础设施：

- `app/common/`：配置读取、ID、UTC 时间、项目错误类型和 JSON 序列化。
- `app/storage/`：SQLite 连接、schema migration、`run_records` / `tool_calls` 基础表和 `SqliteUnitOfWork`。
- `app/observability/`：event JSONL、LLM JSONL、application log 的文件日志模型和 writer。
- `app/runtime/`：`RuntimeRequest`、`RuntimeSession`、`RuntimeResult`、`RuntimeService`、run record 写入 helper 和启动 bootstrap。
- `app/intent/`：intent models、规则 classifier、LLM classifier 空实现和 `IntentService`。
- `app/policy/`：policy models、permission scope 和 `PolicyService`。
- `app/orchestration/`：`GraphState`、policy route、普通 node 函数、compiled `StateGraph`、`RuntimeOrchestrator` 和 Intent / Policy / route 语义事件。
- `app/observability/logger.py`：应用拥有的 request-local `TraceSink` 接口；Graph 外关键阶段可继续使用同一事件边界。
- `config/default.json`：声明默认数据库路径 `data/lifeops.sqlite3` 和默认日志根目录 `logs/sessions`。
- `main.py`：当前 CLI 骨架入口，负责 config、SQLite、migration、文件日志 bootstrap 和单轮输入输出。
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

`main.py` 已存在，但仍是阶段 4 runtime skeleton，不是完整产品 CLI。

当前 `main.py` 已接入 `config/default.json`、SQLite migration 和 `RuntimeService`。`RuntimeService` 当前执行：

```text
RuntimeRequest
-> RuntimeOrchestrator
-> classify_intent
-> decide_policy
-> policy conditional route
-> stub_execute / requires_confirmation / deny
-> finalize
-> RuntimeResult
```

阶段 4 仍是 stub execution：policy `allow` 只表示当前请求通过授权判断，不代表已经执行真实 tool 或业务写入。`RuntimeService` 仍是外部入口并负责 transaction、run record 和 event writer；LangGraph 只接管 request-local orchestration。测试中使用 `:memory:` SQLite 和 migration helper，不读写真实 `data/lifeops.sqlite3`。

阶段 4 完成后的状态：

- 阶段 2 Storage / SQLite 已完成初版。
- 阶段 3 Runtime Core / Intent / Policy 已完成初版。
- 阶段 3.5 Observability 文件日志校正已完成初版。
- 阶段 4 LangGraph Orchestration 已完成初版。
- `docs/ARCHITECTURE.md` 已记录 Runtime Core、Intent / Policy、LangGraph Orchestration、文件日志和 stub execution 边界。
- `docs/RUNTIME_CONCEPTS.md` 已记录 Runtime Core、Intent Layer、Policy / Permission Layer、Write Safety、LangGraph Orchestrator、LangGraph vs LangChain、Observability 和 SQLite Local Persistence 学习章节。
- `plans/modules/STORAGE_SQLITE_PLAN.md`、`plans/modules/RUNTIME_CORE_PLAN.md`、`plans/modules/INTENT_POLICY_PLAN.md`、`plans/modules/OBSERVABILITY_LOGGING_PLAN.md` 和 `plans/modules/LANGGRAPH_ORCHESTRATION_PLAN.md` 已记录完成状态。
- 下一阶段是阶段 5：Skill System / Tool System 与 Domains；施工前应先创建或确认对应模块计划。

当前有效测试命令：

```powershell
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'; uv run python -m unittest discover -s tests -v
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'; uv run python -m compileall app tests
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'; uv run python -m unittest tests.test_orchestration_state tests.test_orchestration_nodes tests.test_orchestration_graph tests.test_intent_service tests.test_policy_service tests.test_runtime_service -v
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
2. docs/PROGRESS_LOG.md
3. docs/ARCHITECTURE.md
4. plans/RUNTIME_REFACTOR_PLAN.md
5. 当前模块对应的 plans/modules/*_PLAN.md
6. 与任务直接相关的代码、测试和文档
```

默认不要读取 `legacy_v0/docs/PROJECT_CONTEXT_legacy.md`、`legacy_v0/docs/LEARNING_PROGRESS_legacy.md` 或 `legacy_v0/plans/*.md`。
