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

项目已完成阶段 4：LangGraph Orchestration 骨架。

阶段 5 已完成：Skill System、Tool System、Research / Personal Knowledge 与 Travel Domain 完整初版均已验证关闭。下一步是在创建并确认 `plans/modules/EXECUTOR_PLAN.md` 后进入阶段 6 ReAct Executor。

- Skill System 已完成核心模型、错误、metadata registry 和原生 discovery / validation；当前严格支持 `name`、`description` frontmatter 子集，不引入 Deep Agents / LangChain loader 或 middleware。
- discovery 只扫描根目录的直接 Skill 子目录，只读取 `SKILL.md` metadata；完整 body 和附属资源仍保持未加载。
- `app/skills/research/SKILL.md` 和 `app/skills/travel/SKILL.md` 已从初始 skeleton 演进为当前领域 workflow 说明，继续只描述候选能力与事实边界，不声明工具权限。
- Skill selector 已通过 `SkillSelectionClient` 薄接口接收 `RuntimeRequest + 全量 Skill metadata`，支持零到多个 Skill；LifeOps 校验严格输出字段、非空 reason、重复 ID 和未知 ID，不依赖框架 selector。
- selected Skill body 已支持按需加载；reference 只能通过 `references/manifest.json` 中的稳定 ID 读取相对 Skill root 的 Markdown 文件，并校验 traversal、文件类型、空正文和大小限制。
- Skill trace 只记录 selection、body load、reference load 的成功或失败语义事件；不记录机械文件 lifecycle，不泄漏用户原文、LLM selection reason、Skill body 或 reference 正文。
- prompt contribution assembler 已实现：只从 selected-and-loaded Skills 生成 `PromptContribution`，保留选择顺序并拒绝重复 Skill ID；core rules、工具描述、Context budget 和最终 prompt 排序仍不属于 Skill System。
- LangGraph allow 路径已接入 request-local `prepare_skills` 和 `execute_tool`：Policy allow 后执行 Skill selection、selected body loading、contribution assembly、filtered Tool selection 和 Gateway；确认与拒绝分支不调用 selector。
- `SkillService` 已收敛为与 Intent/Policy service 对称的构造依赖：它长期持有 `SkillRegistry` 和 `SkillSelectionClient`，并在 graph 构建时注入；只有每个 run 不同的 `TraceSink` 留在 `OrchestrationContext`。GraphState 只保存后续节点需要的 selection 和 contributions；loaded IDs、AllowedToolSet、ToolCall、ToolResult 不重复保存在 GraphState。
- Skill 阶段失败返回 `runtime.skill_failed`，不会继续 `execute_tool`。
- 生产 bootstrap 已调用 `discover_skills(config.skill_root)`，构建 `SkillRegistry`、`SkillSelectionClient()` 和 `SkillService` 后注入 Runtime；`config/default.json` 只负责 Skill root，模型与 OpenAI-compatible provider 地址由 client 直接从 `.env` 读取。
- `SkillSelectionClient` 使用 OpenAI-compatible Chat Completions JSON 输出，只发送用户请求与全量 Skill ID/description，不发送未选中的 body；provider 输出经过 Pydantic 解析和 LifeOps 业务校验。当前只记录关键 Skill event，原始 provider interaction 等统一 LLM Gateway 出现后再集中写入 `llm.jsonl`，不在 `SkillService` 参数中逐层传递日志对象。
- Skill 永久启用，不再提供 `selection_enabled` 配置或 `SkillService is None` 分支；Runtime、Orchestrator 和 graph 都要求显式注入 `SkillService`。
- `tests/fixtures/skills/` 已建立 schema version 1 的长期 Eval case 形状，覆盖 Research、Travel、跨 Domain、零 Skill，以及未知 ID、重复 ID、空 reason 等结构失败。
- Agent Skills specification 和 Deep Agents Skills 仅作为格式、命名约束与 progressive disclosure 的实现参考；框架 adapter 保留为未来边界。
- Tool System 采用 LifeOps 原生安全核心与可选 LangChain adapter；所有工具经过统一 Tool Gateway 和 pre/post Guardrails。
- Tool System 第一步已完成框架无关的核心模型：Tool definition 与 handler 分离，并定义 call/result/error、execution evidence 和结构化 pre/post guardrail decision。
- Tool System 第二步已完成原生 `ToolRegistry` 与 V1 JSON Schema 子集递归校验：definition/handler 在 registry 绑定，重复和未知工具返回 typed error，模型 catalog 不暴露 handler 或授权信息。
- Tool System 第三步已调整为两维 Tool exposure intersection：selected Skills 选出 `ToolDefinition.skill_ids` 匹配的业务候选，空 `skill_ids` 的通用 Tool 始终作为候选；Policy `allowed_effects` 再按 read / external_read / write 过滤并生成 `AllowedToolSet`。Skill 不授权，Policy 不枚举业务 Tool 名，filtered model catalog 只暴露最终集合。
- Tool System 第四步已完成 framework-independent pre/post Guardrails：pre 只消费 authorization 生成的 `AllowedToolSet`，检查当前 Tool membership、注册、WRITE Tool 名确认和递归 input schema，不重复读取 Policy，参数摘要不保留原始值；post 检查 result identity、成功状态、递归 output schema 和 WRITE evidence。当前 confirmation 只绑定 Tool 名，参数摘要、过期和跨 run token 留到后续 Interaction Safety State。
- Tool System 第五步已完成原生 `ToolGateway` 和语义 events：拒绝/确认不触达 handler，handler exception、非法返回和 post 拒绝统一收敛为安全 `ToolResult`；event 不记录原始 arguments、output 或异常文本。当前没有跨 Run 查询消费者，Gateway 不提前写 `tool_calls`；该表仅作为阶段 2 migration 的历史兼容结构保留。
- Tool System 第六步已完成最小 Research Source 纵向切片：handler contract 接收完整 `ToolCall`；Research tools 绑定 Research Skill，fixture-backed READ 产生 request-local observation 且不落库；受控 WRITE 只按当前 observation ID 保存，不能从参数伪造 provenance，并经过 Policy write effect、Gateway confirmation、SQLite transaction 和 post-Guardrail evidence。
- Research Domain 实施步骤 1-2 已完成：补齐 `ResearchTopic`、`ResearchNote`、`ResearchBriefDraft`、`ResearchBrief`、`KnowledgeLink`、`ResearchRevision` 模型与 SQLite migration；repository/service 已支持 Topic、Note、Brief-Source 引用、受目标存在性检查的 KnowledgeLink 和 append-only Revision。Brief draft 与 Source observation 一样保持 request-local，相关新能力尚未接入 Tool Runtime。
- Research Domain 实施步骤 3 已完成：Research Skill 声明 `hf_daily_papers` / `hf_blog` 两个稳定 source key；严格 JSON manifest loader 会拒绝未知 key、路径逃逸、schema 不匹配、非 HTTPS/非 Hugging Face host 和精确 allowlist 外 URL。该步骤只加载可信元数据，不执行网络抓取。
- Research Domain 实施步骤 4 已完成：新增 typed `ResearchContentPort` 与 Hugging Face HTML adapter，抓取前必须解析可信 manifest 声明，抓取时限制 status、redirect、content type、响应大小和 timeout；raw HTML 只保存在 request-local `FetchedSourceDocument`。Papers / Blog parse、URL/title dedupe 和 score/source-order rank 已改为 typed、deterministic、无副作用函数，并通过 fixture、失败路径及现有 Source Tool 回归验证；尚未接入新 Tools 或 compiled Graph。
- Research Domain 实施步骤 5 已完成：`research.fetch_briefing_source`、`research.parse_items`、`research.rank_items`、`research.build_brief_draft` 已注册为 Research Skill 的 EXTERNAL_READ / READ Tools，输出不暴露 raw HTML，并通过 request-local document/item-set ID 传递可信中间状态。中文 draft 包含来源链接和“基于 Hugging Face 列表页可见信息”边界，整个链路不写 SQLite。当前 Direct Executor 每个 run 只执行一个 Tool，完整四步模型循环等待阶段 6 ReAct Executor；当前已通过同一 service、Registry 和 Gateway 的链路测试。
- Research Domain 实施步骤 6 已完成：`research.save_source`、`research.save_brief`、`research.create_note` 均经过 Policy write effect、Gateway confirmation、SQLite transaction 和 post-Guardrail evidence。Brief 只按 request-local `draft_id` 保存，并要求 draft 中每个列表页 source URL 已经独立保存为 `ResearchSource`；缺失来源时 fail-closed，不隐式创建 Source。Note 保存确认后的 title/body。当前 confirmation 仍只绑定 Tool 名，参数摘要、过期和跨 run token 仍是后续 Interaction Safety State 范围。
- Research Domain 实施步骤 7 已完成：`ResearchReadService` 实现仓库共享的 `DomainPlanningReadModel`、`DomainContextProvider`、`DomainMemoryCandidateProvider`。fake consumers 已验证 Planner 读取 Topic 覆盖快照、Context 按预算读取带 provenance candidates、Memory 只读取确认保存的 Note / Brief candidates；消费者不直接写 SQL 或提前实现后续模块。另补充稳定排序的 saved-item limit/offset 分页接口。
- Research、Travel 和未来业务 Domain 已统一采用 `plans/DOMAIN_CONTRACT_STANDARD.md`；共享 Port/Tool/Planning/Context/Memory/安全/测试规范。Research 与 Travel 均已实现 `app/domains/contracts.py` 的三个共享只读 Protocol，Travel scope 固定为 Trip ID。
- Research Domain 实施步骤 8 已按确认范围完成：schema version 1 fixture 可 deterministic 生成 120 Source、240 Note、20 Brief，共 380 条长期数据；已覆盖分页稳定/不重叠、Context budget 稳定、timeout、HTTP 503、empty parse、missing link、unsaved Brief source 和 duplicate Source。用户明确允许跳过的 prompt injection / 恶意内容 fixtures 未实现。
- Research Domain 实施步骤 9 已完成并关闭阶段 5 完整初版：补齐 `list_topics`、`research.search_knowledge`、topic filter、unresolved questions、Source metadata/content-hash 去重和 Source/Snapshot 分离。schema v5 可从 v4 迁移旧 Source/Brief 引用；Brief 固定 snapshot，新抓取可为同 URL 追加 snapshot。compiled Graph 已调用真实 briefing handler 且不暴露 raw HTML，catalog 外 WRITE 继续由 Guardrail 拒绝。仓库全量 182 项 unittest 通过。
- Travel Domain 完整初版已完成：schema v8 保存 Trip、constraints、Itinerary/items/decision 和稳定 KnowledgeReference；五个 typed fixture-backed Ports/Tools 统一表达 success/no-results/partial-failure/failed；compare/draft 只消费 request-local IDs；`travel.save_itinerary` 只按当前 draft ID 与 idempotency key 经 confirmation/transaction/evidence 保存长期事实。旧聚合 option 路径已删除，Tool Runtime 未增加 Travel 特例。
- Tool System 第八步已完成 LangChain adapter 评估并决定当前不实现：本地 `langchain-core 1.4.9` 的 `StructuredTool` 可以包装 callable 与 args schema，但当前没有 LangChain agent/ToolNode 调用方，LifeOps 已有直接 catalog 和完整 Gateway 语义；adapter 反而需要重复 schema/错误转换并桥接 `AllowedToolSet`、confirmation、trace。未来只有出现真实调用方时再以窄 adapter 和 contract tests 接入。
- Tool System 第九步已完成 compiled Graph 的最小 Direct Executor：V1 选择零或一个 ToolCall，并始终经过 filtered catalog、pre/post Guardrails 和 Gateway；完整 ReAct loop 留到阶段 6。
- 阶段 5 E2E 已证明 compiled Graph 可从 START 经过 Skill、Policy、filtered catalog 和两阶段 Guardrail 调用真实 Research 与 Travel handlers；Travel `search_places` 返回 typed observation/candidate，catalog 外 WRITE Tool 被 Guardrail 以 `tool_not_allowed` 拒绝且 SQLite 无写入。
- 两个内部 Domain 从原路线图的 Tasks + Wellbeing 调整为 Research / Personal Knowledge + Travel。
- Research 首个外部只读场景是 Hugging Face Daily Papers / Blog briefing；临时结果不自动保存为知识或 Memory。
- Travel 先定义 typed external Ports 并使用 fixture adapters；真实 Calendar MCP 仍在阶段 10 接入。
- 阶段 5 后的施工顺序已调整为：阶段 6 ReAct Executor、阶段 7 Plan-and-Execute Planner、阶段 8 Context / Memory、阶段 9 Recovery / Feedback，再进入 Calendar MCP 与 Inspector / Eval / DAG。Executor / Planner 先建立外层控制框架和窄扩展接口，后续状态模块通过接口接入。
- Domain 已明确为业务 models/service/repository/tools 的逻辑分组，不是独立 Agent 或执行边界；同一通用 PlanRun 可以交叉调用 Research 与 Travel tools。
- 简单请求未来走 ReAct Executor；复杂、多步骤或有依赖请求走 Planner → Executor。PlanStep 的字段和 Tool 匹配方式留到 Planner 模块施工时设计，WRITE 默认逐 action / step 授权。
- PlanRun / PlanStep 可为跨进程恢复而持久化，但不是业务事实；跨 Domain 部分成功时不做全局回滚，保留成功 evidence，从失败 step 恢复或 bounded replan。
- LangGraph checkpoint 是未来保存 graph/thread state、interrupt、fault tolerance 和 time travel 的候选机制，不负责撤销已经提交的 Domain WRITE 或外部副作用。

当前状态：

- 当前基础设施代码已经完成阶段 2 初版。
- Runtime Core / Intent / Policy 已完成阶段 3 初版。
- Observability 文件日志已完成阶段 3.5 初版。
- LangGraph Orchestration 已完成阶段 4 初版。
- 阶段 5 的 Skill System、Tool System、Research 与 Travel 完整初版均已完成；Travel 聚焦测试 33 项、仓库全量 unittest 216 项通过。
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
- `app/policy/`：policy models 和 `PolicyService`；`allowed_effects` 是动作授权结果。
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

`main.py` 已存在并接入阶段 5 最小 Direct Executor，但还不是包含 ReAct、Planner、Context 和 Memory 的完整产品 CLI。

当前 `main.py` 已接入 `config/default.json`、SQLite migration 和 `RuntimeService`。`RuntimeService` 当前执行：

```text
RuntimeRequest
-> RuntimeOrchestrator
-> classify_intent
-> decide_policy
-> policy conditional route
-> prepare_skills -> execute_tool / requires_confirmation / deny
-> finalize
-> RuntimeResult
```

阶段 5 已用真实 Gateway 替换 stub：policy `allow` 后仍需经过 Skill candidate、Policy effect、filtered catalog、pre/post Guardrails 才能执行 Tool。`RuntimeService` 仍是外部入口并负责 transaction、run record 和 event writer；LangGraph 接管 request-local orchestration。测试使用 `:memory:` SQLite 和 fixture providers，不读写真实 `data/lifeops.sqlite3`。

阶段 4 完成后的状态：

- 阶段 2 Storage / SQLite 已完成初版。
- 阶段 3 Runtime Core / Intent / Policy 已完成初版。
- 阶段 3.5 Observability 文件日志校正已完成初版。
- 阶段 4 LangGraph Orchestration 已完成初版。
- `docs/ARCHITECTURE.md` 已记录 Runtime Core、Intent / Policy、LangGraph Orchestration、Skill、Tool Gateway、Guardrails 和 Domain 纵向切片边界。
- `docs/RUNTIME_CONCEPTS.md` 已记录 Runtime Core、Intent Layer、Policy / Permission Layer、Write Safety、LangGraph Orchestrator、LangGraph vs LangChain、Observability 和 SQLite Local Persistence 学习章节。
- `plans/modules/STORAGE_SQLITE_PLAN.md`、`plans/modules/RUNTIME_CORE_PLAN.md`、`plans/modules/INTENT_POLICY_PLAN.md`、`plans/modules/OBSERVABILITY_LOGGING_PLAN.md` 和 `plans/modules/LANGGRAPH_ORCHESTRATION_PLAN.md` 已记录完成状态。
- 下一施工入口是创建并确认 `plans/modules/EXECUTOR_PLAN.md`，随后进入阶段 6 ReAct Executor。

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
