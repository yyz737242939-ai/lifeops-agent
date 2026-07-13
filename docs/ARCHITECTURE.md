# Runtime 架构

本文档记录当前架构快照和当前架构边界。它故意比模块实施计划更高层。

本文档不是递增历史。随着 runtime 推进，过时的架构描述应被替换为当前事实；项目演进过程记录在 `docs/PROGRESS_LOG.md`。

## 核心边界

当前 runtime 将职责拆分为显式层次：

```text
runtime
intent
policy
orchestration
context
memory
planning
execution
tools
domains
integrations
recovery
observability
inspector
evals
dag
storage
common
```

## 新代码根目录

当前代码放在：

```text
app/
```

Legacy 代码保留在：

```text
legacy_v0/app/
```

当前 runtime 不应隐式依赖 legacy 的 `legacy_v0/app/agents/agent.py`。

## 依赖方向

允许的高层依赖方向：

```text
main
-> runtime
-> orchestration
-> intent / policy
-> context / planning / execution / inspector
-> tools / domains / memory / recovery / integrations
-> storage / observability / common
```

默认禁止：

- domain 模块依赖 orchestration；
- policy 执行工具；
- planner 授权写入；
- inspector 修改 runtime 或业务状态；
- evals 使用真实用户数据；
- storage 依赖 domain service。

## Runtime Core

Runtime Core 是当前单轮 request lifecycle 的入口层，当前实现位于：

- `main.py`
- `app/runtime/models.py`
- `app/runtime/service.py`
- `app/runtime/bootstrap.py`
- `app/runtime/run_store.py`

`RuntimeRequest` 是当前 turn/run 的结构化输入，包含 `session_id`、`turn_id`、`run_id` 和 `user_input`。它不是长期 conversation memory。

`RuntimeResult` 是本轮可展示结果，只包含 run/session identity、status、message、可选 Tool result 和稳定 error code。Intent、Policy 与执行路径由语义事件解释，不在公共结果中重复，也不暴露内部异常文本。

当前 `RuntimeService.handle(...)` 的链路是：

```text
RuntimeRequest
-> RuntimeOrchestrator
-> StateGraph
-> classify_intent
-> decide_policy
-> policy conditional route
-> prepare_skills -> execute_executor / requires_confirmation / deny
-> finalize
-> RuntimeResult
```

传入 SQLite connection 时，Runtime Core 可以写入 `run_records`。传入 event log 或配置 `log_root` 时，Runtime Core 会把 runtime event 写入 `events.jsonl`。未传入 connection 时，它仍可通过文件 event log 记录运行路径，也可以保持 request-local 纯内存运行，便于聚焦测试。

Policy allow 路径当前调用通用 `ReactExecutor`：根据 selected Skills 与 Policy effects 生成固定 `AllowedToolSet`，只向模型暴露过滤后的 catalog，并在独立 compiled Executor graph 中执行有界 action → observation 循环。每次 ToolCall 仍只经过统一 Gateway。

## LangGraph Orchestration

LangGraph Orchestration 当前实现位于：

- `app/orchestration/state.py`
- `app/orchestration/routes.py`
- `app/orchestration/nodes/`
- `app/orchestration/graph.py`

`RuntimeService` 仍是唯一外部入口，负责 run lifecycle record、按 session 隔离的 event/application log、Domain WRITE transaction 闭合和最终 `RuntimeResult`。run record 先独立提交；Intent/Skill/LLM/external read 不占用 SQLite 写 transaction。`RuntimeOrchestrator` 负责 outer compiled `StateGraph` 的 Intent、Policy、Skill preparation 和 Executor route；注入的 `ReactExecutor` 拥有独立、无 checkpointer 的 compiled cycle，最终只把 `ExecutorResult` 映射为 `RuntimeResult`。

当前 graph 路径是：

```text
START
-> classify_intent
-> decide_policy
-> allow -----------------> prepare_skills -> execute_executor \
-> requires_confirmation -> requires_confirmation --+-> finalize -> END
-> deny ------------------> deny -------------------/
```

Intent、Policy 或 Skill preparation 失败时，graph 在对应节点后直接进入 `END`。Skill 失败不会进入 `execute_executor`；Policy-level 确认和拒绝分支不会调用 Skill selector 或 Executor。

`GraphState` 只保存当前 request 的编排数据：request、intent、policy、route、Skill selection、prompt contributions、result、结构化 error stage/code 和 graph-internal path。已加载 Skill ID 可由 prompt contributions 得出，不在 GraphState 重复保存。它不保存 trace summary、`SkillService`、Skill registry/client、长期 Memory、Domain 事实、Tool arguments/result cache 或授权替代来源。

`IntentService`、`PolicyService` 和 `SkillService` 是 graph 构建期依赖。`SkillService` 长期持有 `SkillRegistry` 与 `SkillSelectionClient`，统一执行 selection、lazy loading 和 contribution assembly。`OrchestrationContext` 只携带每个 run 不同的应用 `TraceSink`；它通过 LangGraph `context_schema` / `Runtime` 提供给节点，不进入 `GraphState` 或 checkpoint。Intent / Policy node 在真实 service 返回后分别写 `intent.classified` / `policy.decided`，失败时写对应 failed event；Policy 分支确定后写 `orchestration.route.selected`。机械化的 graph/node started/completed 不进入稳定事件契约。

LangGraph 不负责 Policy 决策、业务事实、工具安全、真实执行或持久化；这些边界仍由 LifeOps 自研 runtime 拥有。

## Skill System

Skill System 当前实现位于 `app/skills/`。`SkillDefinition`、`LoadedSkill`、`SkillSelection`、`SkillReferenceDefinition` 和 `PromptContribution` 是框架无关的 LifeOps 类型；`SkillRegistry` 提供确定性 metadata 查询和重复 ID 防护。

`discover_skills(root)` 使用 LifeOps 原生薄实现扫描根目录的直接子目录。当前只读取每个 `SKILL.md` frontmatter 中的 `name` 和 `description`，校验 Agent Skills 命名约束、父目录同名、必填项和未知字段；不读取 Markdown body、reference、script 或 asset。Deep Agents / LangChain Skills 只作为文件约定和 progressive disclosure 参考，不是 runtime 依赖。

当前内置 Skills 是 `research` 和 `travel`。它们的 `SKILL.md` body 描述领域用途、临时结果与持久化事实边界以及当前 workflow；Skill 只提供候选能力说明，实际 Tool 暴露仍由 selected Skill 与 Policy effect 求交。

`select_skills(request, skill_metadata, llm)` 把 `RuntimeRequest` 和全量 Skill metadata 交给 `SkillSelectionClient`。该 client 在初始化时从 `.env` 读取 `OPENROUTER_API_KEY`、`OPENROUTER_BASE_URL` 和 `MODEL`，通过 OpenAI-compatible Chat Completions 请求 JSON 结果；请求只包含用户请求以及全部 Skill ID/description。provider 返回值先经过 Pydantic 结构解析，随后由 LifeOps 校验只能包含 `selected_skill_ids` 和非空 `reason`，并拒绝重复或未知 ID。该接口不预先按 Intent、关键词或 Domain 缩小候选集，也不依赖 Agent 框架。

`load_skill(definition)` 只在选中后读取对应 `SKILL.md` body。`read_skill_reference(definition, reference_id)` 只接受 `references/manifest.json` 白名单中的稳定 ID，并限制为 Skill root 内的 Markdown 相对路径。body/reference 均有空内容和字符数上限校验；正文不进入 trace payload。

`build_prompt_contributions(loaded_skills)` 按 selection/load 顺序把 `LoadedSkill.body` 转换为独立 `PromptContribution`。它只消费实际已加载的 Skill，拒绝重复 Skill ID；不拼接 core rules、工具描述或最终 system prompt，也不决定 Context budget 和最终排列顺序。

当前 request-local Skill 链路是：

```text
Skill root
-> direct child SKILL.md
-> strict metadata validation
-> SkillDefinition
-> SkillRegistry
-> LLM selection + LifeOps validation
-> selected body / declared reference lazy loading
-> PromptContribution list
-> filtered catalog -> zero or one ToolCall -> ToolGateway
```

生产 bootstrap 根据 `config/default.json` 的 `skills.root` 总是执行 discovery，并直接构造 `SkillSelectionClient()`、Registry、必需的 `SkillService` 与使用 OpenAI-compatible adapter 的 `ReactExecutor`；模型和 provider 地址不通过 JSON 配置逐层传参。不存在 Skill 开关或空 service 分支。`prepare_skills` 只位于 Policy allow 路径。稳定 Skill events 只包含 selection/body/reference 语义边界。LLM selection reason 保留在 request-local `SkillSelection` 中，不写 event payload。Skill selection 会参与业务候选 Tool 筛选，但不提供授权；Policy effect 才是动作权限来源。prompt contributions 已进入每步 Executor model input；完整 Context assembly 留到阶段 8。

## Tool System

Tool System 当前已完成阶段 5 闭环，位于 `app/tools/`。`ToolDefinition` 是代码配置的不可变契约，只描述 input/output schema、effect 和 risk，不直接持有 handler。`ToolRegistry` 在启动配置阶段递归校验 V1 支持的 JSON Schema 子集，再把 definition 与 callable handler 绑定；重复注册、未知工具、非法 handler 和非法 schema 使用 typed Tool errors。

`resolve_allowed_tools(selected_skill_ids, policy, registry)` 生成 request-local `AllowedToolSet`。`ToolDefinition.skill_ids` 声明业务绑定：与 selected Skill 匹配的 Tool 成为业务候选，空 `skill_ids` 的通用 Tool 不依赖 Skill、始终是候选；候选随后与 Policy `allowed_effects` 求交。Skill selection 只缩小业务范围、不能授权；Policy 只决定 read / external_read / write 动作权限、不枚举业务 Tool 名。Policy deny、requires-confirmation 或空 effects 都产生空集合。

模型可见 catalog 只包含稳定排序的 name、description 和 input schema，并返回 schema 深拷贝，不暴露 handler 或 risk 等执行信息；传入 `AllowedToolSet.tool_names` 后只返回当前集合内工具。当前模型层还定义了 `ToolCall`、结构化 `ToolResult` / `ToolError`、精简 `ExecutionEvidence`、`ConfirmedAction`，以及 pre/post 两阶段的 `GuardrailDecision`。`evaluate_pre_execution(...)` 只消费 authorization 已生成的 `AllowedToolSet`，检查 membership、注册状态、递归 input schema，以及 WRITE confirmation 是否匹配 run/call/tool/canonical arguments digest 且未过期；它不直接读取 Policy、不读取 Skill 功能元数据，也不建立第二套授权。`evaluate_post_execution(...)` 检查 call/result identity、成功状态、递归 output schema，以及 WRITE 成功 evidence。Guardrails 不依赖 LangChain 或 LangGraph。

原生 `ToolGateway.execute(...)` 已把 `AllowedToolSet -> pre-Guardrail -> registered handler -> post-Guardrail` 串成单次调用闭环。pre 拒绝或要求确认时 handler 不会执行；handler exception、非 `ToolResult` 返回和 post 拒绝都会转换为不泄露内部异常的结构化 `ToolResult`。Gateway 实时写 `tool.call.requested`、`tool.guardrail.decided`、`tool.call.completed` / `failed` 语义事件，payload 只包含 call/tool identity、stage、action、reason code、status、error code 和 evidence count，不包含原始 arguments、output 或异常文本。

Gateway 当前不写 `tool_calls`。该表保留为阶段 2 migration 的历史兼容结构，但 Inspector、Eval、Recovery 和产品历史查询尚无真实消费者，因此不提前绑定摘要字段或 transaction。outer compiled Graph 已通过 `execute_executor` 调用 `ReactExecutor`，后者全循环复用 Runtime 创建的同一个 execution scope 并通过真实 Gateway 接入 Research / Travel handlers；跨 run scope 隔离。Domain WRITE 在 handler/repository 开始写入时进入短 SQLite transaction，external read 与 LLM 不持有写 transaction。

LangChain Tool adapter 已在本地 `langchain-core 1.4.9` 上完成 API 评估，当前不保留实现。`StructuredTool` 能包装 callable 和 Pydantic/JSON args schema，但 LifeOps 已直接拥有模型 catalog、ToolCall、schema validation、Gateway、ToolResult 和错误语义；当前也没有 LangChain agent/ToolNode 调用方。此时 adapter 需要额外桥接 request-local `AllowedToolSet`、confirmation 和 trace，增加了可绕过 Gateway 的 callable 表面，没有减少 glue。未来真实 LangChain 调用方出现时只增加窄 adapter，并用 contract test 保证 invocation 必须回到 Gateway。

## Intent / Policy

Intent Layer 当前实现位于：

- `app/intent/models.py`
- `app/intent/classifiers.py`
- `app/intent/service.py`

Intent 判断用户可能想做什么，例如 `chat`、`read`、`write_request`、`plan_request`、`clarification_needed`。`IntentService` 会调用规则 classifier 和 LLM classifier 接口。当前 `LlmIntentClassifier` 是空实现，只返回 `not_available`，不调用真实模型。

Policy / Permission Layer 当前实现位于：

- `app/policy/models.py`
- `app/policy/service.py`

Policy 判断系统现在被允许做什么。它只基于当前 `RuntimeRequest` 和 `IntentDecision` 产出 `PolicyDecision`，不能从 Planner、assistant 文本、LLM classifier、Recovery Context 或 LangGraph checkpoint 获得写入授权。

`PolicyDecision.allowed_effects` 是动作授权结果：READ intent 允许 read / external_read，明确且受支持的 WRITE request 只允许 write，其他 allow 分支默认不暴露 Tool effect。具体 Tool 来自 selected Skill 业务候选和通用 Tool，再由 Registry effect 求交；Policy allow 仍不代表真实工具已经执行。

## 基础设施层

`common`、`storage` 和 `observability` 是当前 runtime 的基础设施层：

- `common` 提供配置读取、ID、时间、错误和 JSON 序列化，不依赖业务模块。
- `storage` 提供 SQLite 连接、schema migration 和 transaction boundary，不依赖 domain service。
- `observability` 提供 event / LLM / normal 程序日志的写入和读取，不负责业务状态变更。

真实数据库默认路径由 `config/default.json` 的 `database.path` 声明。当前默认值是：

```text
data/lifeops.sqlite3
```

测试必须使用 `:memory:` 或临时文件数据库，不复用真实用户数据库。

真实日志默认根目录由 `config/default.json` 的 `logs.root` 声明。当前默认值是：

```text
logs/sessions
```

## 事实来源

Runtime 的事实来源是：

- 基于 SQLite 的业务 repository；
- 成功的 WRITE tool result；
- 用户明确授权且由成功 ToolResult / ExecutionEvidence 支持的 Domain WRITE。

不是事实来源：

- assistant final answer 文本；
- Planner 输出；
- LangGraph checkpoint state；
- Recovery Context；
- conversation summary。
- 原始 LLM request-response log。

## Observability

当前 observability 分成三类日志：

- `events.jsonl`：结构化 runtime event，只保存少量必要字段和紧凑 payload，用于解释 runtime 路径和失败层级。
- `llm.jsonl`：按 request 独立编号的 LLM / agent provider interaction，记录 provider、model、实际 request、结构化 response、status 和安全 error code，用于人工排查模型输入输出；不作为业务事实或写入授权来源。
- `application.log`：当前 active session 的本地异常与诊断日志；不镜像 routine 语义事件。

三类日志默认写入 `logs/sessions/session_<timestamp>_<session_id>/`。event writer 按 session 隔离；application logger 同一时刻只保留一个 active session FileHandler，切换或 `RuntimeService.close()` 时关闭旧 handler。SQLite 不再默认承载 runtime event log 或 LLM log。

`RuntimeService` 为每个 request 建立 `RequestLlmLog`，通过 request-local orchestration context 传给 Skill selection 和 `ReactExecutor`，不进入 outer `GraphState` 或 `ExecutorState`。Skill selection 记录实际 chat-completions request 与 content；Executor adapter 记录每一步 Responses request，以及 final text 或 function-call identity/arguments。provider/config/contract failure 记录 stable error code，不写 exception text；日志 writer 自身失败只进入 `application.log`，不能改变 model decision、Tool evidence 或 RuntimeResult。deterministic file-backed E2E 已验证一次 current Runtime run 能按顺序生成完整 `events.jsonl` 和三次 Skill/Executor `llm.jsonl` interaction。

`TraceSink` 是应用拥有的 request-local event 接口。outer Graph node 与 `ReactExecutor` 通过 runtime context / service 参数复用同一个 sink；Tool Safety、repository 或 integration 关键阶段也可以直接写同一个 sink，不需要为了可观察性变成 LangGraph node。Event 在真实逻辑边界实时追加，不根据最终 state 事后补写。

Executor 稳定语义事件包含 `executor.action.selected`、`executor.observation.recorded`、`executor.stopped`；hook failure 使用安全的 `executor.hook.failed`。这些 payload 只记录 step、decision type、call/tool identity、status、error code、retryable、evidence count 和 stop reason，不复制 Gateway 已记录的 arguments/output/Guardrail 明细，也不包含 prompt、Context/Memory content、provider response 或异常文本。Feedback sink 与 Recovery hook 是可选观察消费者；失败时不改写 ExecutorResult、Tool evidence 或业务事实。

## Runtime 不变量

- 用户数据安全优先。业务写入必须来自用户当前输入中的明确授权。
- Intent 只提供语义信号，不授权写入。
- Policy 是当前写入授权事实源；Executor 只能执行 Policy 通过 `AllowedToolSet` 允许的操作。
- 不能只凭 assistant 文本判断成功。Runtime 状态和成功的 WRITE action 才是“已保存”或“已更新”的事实来源。
- Skill、Tool authorization、Context、Runtime State、业务数据和长期 Memory 必须保持分离。
- Conversation Summary 不是 Long-term Memory。Context compaction 结果不能自动升级为长期记忆。
- LangGraph checkpoint state、Planner 输出和 Recovery Context 不是业务事实来源，也不是写入授权来源。
- `TraceSink` 是运行依赖，不进入 `GraphState`；event payload 不写完整 GraphState 或原始用户输入。
- 修改 Runtime 行为、Context 处理、Memory、写入安全或工具执行时，需要聚焦的回归测试。

## PlanRun vs Domain Facts

`PlanRun` / `PlanStep` 是跨 Domain 的通用 runtime 执行策略。它们可以为了暂停、恢复、fault tolerance 和审计而持久化，但不会因此成为 Research 或 Travel 业务事实。

Research / Travel 是业务逻辑分组：各自拥有 models、service、repository 和 tools。Planner / Executor 位于 Domain 之上，一个 PlanRun 可以交叉调用多个 Domain 的 tools。

Research 位于 `app/domains/research/`。当前领域模型与 SQLite 基础已包含 Source、SourceSnapshot、Topic、Note、Brief、固定 snapshot 的 Brief-Source 引用、KnowledgeLink 和 append-only Revision；KnowledgeLink / Revision 的多类型引用由 repository 在写入前检查目标存在性。`ResearchBriefDraft` 与 `ExternalObservation` 保持 request-local，只有 service 当前持有的临时对象才能进入后续保存路径。

Research Source 纵向切片已接入 Tool Runtime。Research Tool 绑定 `skill_ids=("research",)`；`FixtureResearchSourcePort` 只接受显式声明的 source key，返回带 content hash、fetched time 和 fixture provenance 的 request-local `ExternalObservation`。`ResearchService` 暂存 observation，未确认时不写 SQLite。`research.save_source` 只接收当前 execution scope 内 service 已持有的 observation ID，经 Research Skill candidate、Policy write effect、结构化 `ConfirmedAction` 和短 SQLite transaction 后由 `ResearchRepository` 保存 `ResearchSource`，并返回 `research_source_saved` evidence。模型不能通过 Tool 参数自行提供 provenance。

schema v5 将稳定的 Source identity（URL、source type、title）与每次抓取的 snapshot（summary、content hash、fetched/published metadata、provenance）分表。同 URL 新内容追加 snapshot；全局重复 content hash fail-closed。`research_brief_sources` 同时固定 `source_id` 与保存 Brief 时的 `snapshot_id`，因此后续 Source 刷新不会改变旧 Brief 的引用事实。当前没有删除 Tool；未来若增加删除能力，必须采用归档/软删除并保持这些引用。

Research Skill 当前在 `app/skills/research/sources/` 声明 `hf_daily_papers` 和 `hf_blog`。`load_research_source(...)` 只把稳定 source key 解析成经过 traversal、schema、HTTPS host 和精确 URL allowlist 校验的 `ResearchSourceDefinition`；加载声明不等于执行网络访问，HTTP adapter 与 manifest loader 保持分离。

Research external-read 的 typed 边界已实现为 `ResearchContentPort` / `HuggingFaceResearchContentPort`。adapter 先加载可信 source declaration，再限制 HTTP status、最终 URL redirect、HTML content type、响应大小、timeout 和解码失败，返回含 raw HTML、hash、fetched time 和 provenance 的 request-local `FetchedSourceDocument`。`ResearchService` 只按当前 request 已取得的 `document_id` 调用解析；raw HTML 不进入 SQLite。`parse_research_items`、`dedupe_research_items`、`rank_research_items` 是无网络、无存储副作用的 deterministic 函数，输出 typed `ResearchItem`。

临时 briefing 已暴露 `research.fetch_briefing_source`、`research.parse_items`、`research.rank_items`、`research.build_brief_draft` 四个 Tool，并统一经过 Skill candidate、Policy effect、Guardrail 和 Gateway。rank 支持 deterministic topic filter。Tool 输出不包含 raw HTML；document、item set 和 `ResearchBriefDraft` 都只存在于 request-local `ResearchService`。Draft 保存来源 URL，而不是把临时 item ID 冒充长期 Source ID；保存 Brief 时 repository 只接受已经存在于 `research_sources` 的 URL。当前 `ReactExecutor` 已在跨 Domain compiled E2E 中验证同一 execution scope 连续调度 Research 多步 Tool、Travel 多步 Tool，以及 Research READ → Travel READ sequence。

Research WRITE 当前包含 `research.save_source`、`research.save_brief` 和 `research.create_note`。briefing fetch 会为同一个 list-page document 生成 request-local observation，使 Source 可以先经过独立 WRITE 保存；Brief WRITE 只接收 request-local `draft_id`，repository 会把 draft 的 source URL 解析到已经保存的 `research_sources`，任何缺失来源都会 fail-closed，不能由 Brief WRITE 隐式创建 Source。Note WRITE 接收 title/body。三个 WRITE 都经过 Policy write effect、结构化 `ConfirmedAction`、短 transaction 和 post-Guardrail evidence；临时 ID 不能跨 execution scope 使用。

所有业务 Domain 遵守 `plans/DOMAIN_CONTRACT_STANDARD.md`，共享 `DomainPlanningReadModel.get_planning_snapshot(scope_id)`、`DomainContextProvider.query_context_candidates(...)` 和 `DomainMemoryCandidateProvider.query_memory_candidates(...)`。统一的是方法语义和安全边界，snapshot/candidate 业务类型仍归各 Domain 所有。

Research 的 `ResearchReadService` 实现三个共享 contract：planning snapshot 返回 Topic 的资料覆盖计数、最近 Brief 标题和以 `KnowledgeLink(relation="unresolved_question")` 表达的未解决问题；Context 按 query 与字符预算返回带 provenance / estimated size 的 Source、Note、Brief candidates；Memory 只返回用户确认保存的 Note / Brief candidates，不包含 Source，也不写 Memory。Research planning/context/memory scope 是 Topic ID；Context/Memory 同时支持全局和 Topic scoped query，未知 Topic 明确失败。SQL 保持在 `ResearchRepository` 内。Domain 另提供稳定排序的 `list_topics`、`search_saved_items(..., limit, offset)` 和模型可见 `research.search_knowledge` READ Tool。

Travel 位于 `app/domains/travel/`，当前已有 Trip / TravelConstraint 长期事实、五个 typed external Ports 和 fixture-backed EXTERNAL_READ Tools。`travel.check_calendar_availability`、`travel.get_weather`、`travel.search_transport`、`travel.search_lodging`、`travel.search_places` 统一返回 request-local `ExternalLookupResult`，其中 observation 携带 provider、source reference、observed/expires time 和 provenance；candidate 只能引用当前 observation ID，success/no-results/partial-failure/failed 与 retryable provider failure 保持结构化。聚合 `travel.search_options` 已从 Tool Registry 删除，不再与五个细分 Tool 重复暴露。

`travel.compare_options` 只接受当前 request-local observation IDs，把候选按保存的 Trip destination / budget constraints 生成 `CandidateAssessment` 和 `TravelComparison`；无法判断的约束保持 unresolved，不伪装成匹配。`travel.build_itinerary_draft` 再只接受该 comparison 中的 candidate IDs，拒绝伪造、冲突或过期候选，并为同一 Trip 生成 request-local 递增 version。comparison / draft 都不写 SQLite，也不代表 booking。

Itinerary WRITE 已迁移为 draft-based 保存：`travel.save_itinerary` 只接受当前 request-local `draft_id` 与显式 idempotency key，经 Travel Skill candidate、Policy write effect、结构化 `ConfirmedAction` 和短 transaction 原子保存 `Itinerary`、`ItineraryItem` 与 itinerary `TravelDecision`，成功返回 `travel_itinerary_saved` evidence。保存前重新验证 quote expiry；相同 key + draft 已成功时返回同一长期事实，即使 quote 后来过期，不同 draft 复用 key fail-closed。未安排时间的 Place item 保持空时间，不伪造日程。旧 `CandidateOption`、`TravelOptionPort` 和聚合 `search_options()` 路径已删除。Travel 接入没有修改 Tool Runtime 核心。

跨 Domain 资料引用使用 `app/domains/references.py` 的通用 `KnowledgeReference` 与 `KnowledgeReferenceResolver`。Travel 的 `travel_knowledge_refs` 只保存稳定 reference ID、domain、item kind 和 item ID，不复制 Research 正文，也不 import Research repository。resolver 以 structured `resolved/unavailable` 返回只读摘要；解析失败不会阻止读取 Trip 主体。

`TravelReadService` 实现共享 `DomainPlanningReadModel`、`DomainContextProvider` 和 `DomainMemoryCandidateProvider`，scope ID 固定为 Trip ID。Planning snapshot 只表达持久化约束覆盖、缺失约束、已保存 itinerary 与待决策项，不泄漏 request-local candidate/draft；Context candidates 受 budget 限制并携带 provenance；Memory candidates 只来自显式保存的 transport/lodging/other constraints，不从历史 itinerary 自动推断偏好。

PlanStep 不自动转换成长期 Task。只有绑定当前用户授权、通过 Tool Guardrails、成功执行并产生 evidence 的 Domain WRITE，才能创建或修改 Source、Note、ResearchBrief、Trip、Itinerary 等长期事实。

LangGraph checkpoint 保存 graph/thread state，可用于恢复和 time travel；已经提交到 Domain repository 或外部系统的副作用不会因为恢复旧 checkpoint 而自动回滚。

## 架构维护规则

- 当前架构事实写在本文档。
- 历史推进和完成状态写在 `docs/PROGRESS_LOG.md`。
- 学习解释写在 `docs/RUNTIME_CONCEPTS.md`。
- 外部学习链接写在 `docs/AGENT_LEARNING_LINKS.md`。
