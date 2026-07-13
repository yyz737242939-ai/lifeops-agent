# Runtime 概念

本文档是 Runtime 的详细学习和面试手册。

本文档只记录已经随项目推进学到、实现过或正在用于当前阶段解释的概念。外部链接统一维护在 `docs/AGENT_LEARNING_LINKS.md`，本文档不直接维护 URL。

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

### 相关项目文件
```

## 必需章节

- Agent Loop
- Intent Layer
- Policy / Permission Layer
- Tool System
- Tool Authorization
- Write Safety
- LangGraph Orchestrator
- LangChain Adapter
- Planner
- Executor
- Plan / Execution State
- PlanRun vs Domain Facts
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

## 阶段 5 设计术语表

本节记录阶段 5 已确认并已用于 Skill、Tool、Research 与 Travel 实现的术语。

- `SkillDefinition`：Skill 的轻量声明，包含 ID、说明、routing metadata 和声明式资源索引；不是可执行工具。
- `PromptContribution`：selected Skill 提供给未来 Context/prompt assembly 的一段有来源、可预算的说明；不是完整 prompt，也不是业务事实。
- `AllowedToolSet`：selected Skill 业务候选（加空 `skill_ids` 的通用 Tool）与 Policy `allowed_effects` 求交后的本轮工具白名单。
- `ToolDefinition`：工具名称、schema、effect、risk 等静态契约。
- `ToolGateway`：所有工具通道统一经过的单次执行入口，负责 pre/post Guardrails、handler 调用和 evidence 输出。
- `GuardrailDecision`：工具执行前或执行后的结构化安全判断；不能扩大 `PolicyDecision` 已授予的权限。
- `ExecutionEvidence`：证明工具真实执行结果的结构化证据。assistant 文本、Planner 输出或 LLM summary 不是 evidence。
- `External Port`：Domain 声明的外部能力接口，例如天气或交通查询；fixture、MCP 和 HTTP adapter 可以分别实现它。
- `ExternalObservation`：某个 provider 在某时刻返回的临时观察，带 provenance 和有效期；它不是长期业务事实。
- `DomainContextProvider`：未来 Context Engine 获取 Domain 候选信息的共享窄接口；统一方法是 `query_context_candidates(...)`，Domain 不负责决定最终 prompt。
- `PlanningReadModel`：为 Planner 准备的只读、稳定、领域化快照；Planner 不读取 repository internals。
- `DomainMemoryCandidateProvider`：向未来 Memory 模块提供候选的共享只读接口；候选不会自动成为长期 Memory。
- `ResearchBriefDraft`：基于临时 source observation 生成的简报草案；只有用户确认保存后才成为 `ResearchBrief` 业务事实。
- `ItineraryDraft`：基于 Travel constraints 和外部 observation 生成的行程草案；只有用户确认并成功 WRITE 后才成为持久化 Itinerary。
- `Fixture Adapter`：使用固定测试数据实现 External Port 的 adapter，用于离线开发和 deterministic Eval；不是简单返回任意假值的无契约 mock。
- `PlanRun`：Planner 针对一个用户目标生成的跨 Domain 通用执行策略；可以持久化以支持恢复，但不是业务事实。
- `PlanStep`：跨 Domain 的通用执行步骤；具体字段以及如何匹配 Tool 留到 Planner 模块施工时设计。
- `Domain`：从业务角度划分 models、service、repository 和 tools 的逻辑边界；不是独立 Agent，也不拥有自己的通用 Planner / Executor。

阶段 5 的核心分离：

```text
Skill instructions       != Tool authorization
External observation     != Domain fact
Domain fact              != Context selection
Context selection        != Memory
Plan / draft             != confirmed WRITE
Framework adapter        != LifeOps safety boundary
Persisted PlanRun         != Domain fact
Checkpoint restore        != side-effect rollback
```

当前 Tool Guardrail 的最小语义：authorization 先把 Policy 转换为 `AllowedToolSet`；pre-Guardrail 只消费该集合，检查当前 Tool membership、注册、input schema，以及 WRITE 的 `ConfirmedAction` 是否绑定 run/call/tool/canonical arguments digest 且未过期，不重复读取 Policy；post-Guardrail 检查 call/result identity、成功状态、output schema 和 WRITE evidence。Guardrail 只能缩小或拒绝既有授权，不能新增 allowed tool。

`ToolGateway` 是唯一允许调用 registry handler 的运行时入口。它不重新计算 Policy 权限，只消费 `AllowedToolSet`，并保证任何 handler 调用都夹在 pre/post Guardrails 之间。handler exception 和 contract violation 被转换为紧凑 `ToolError`，内部异常文本不会进入返回值或语义 event。

Tool handler 接收完整 `ToolCall`，而不是只有 arguments；这样 handler 返回的 `ToolResult` 可以绑定原始 `call_id` 和 `tool_name`，post-Guardrail 能验证 result identity。Domain handler 仍只读取 `call.arguments` 作为业务输入，不能绕过 Gateway。

Research 与 Travel 已验证同一 Tool Runtime：外部 READ 先产生 request-local observation/candidate，后续 compare/draft 只消费当前 service 持有的稳定 ID；WRITE 只接受当前 observation/draft ID 与必要幂等 key，用户确认后才由 Domain repository 保存长期事实并产生 evidence。Travel 的 draft-based WRITE 会原子保存 Itinerary/items/decision，未安排时间的 Place item不伪造日程。Domain 差异留在 model/service/repository/Port，Policy、Authorization、Guardrail 和 Gateway 不按 Domain 分叉。

当前不实现 LangChain `StructuredTool` adapter。是否使用框架 adapter 的判断标准不是“框架提供了 Tool 类”，而是项目是否已有真实 LangChain 调用方，以及 adapter 是否能减少 schema/invocation glue。当前 LifeOps 已直接拥有 catalog、ToolCall、Gateway 和 Result；adapter 还必须注入 request-local authorization/confirmation/trace，因此净复杂度更高。未来若引入 agent 或 ToolNode，adapter 只能转换边界，不能成为新的 handler 入口或安全事实源。

Gateway 当前不写 SQLite；`ToolResult`、`ExecutionEvidence` 和语义 events 已足够支持单次调用解释。`tool_calls` 只有在 Inspector、Eval、Recovery 或产品历史查询出现明确的跨 Run 查询需求后才接入，避免为了未来索引提前绑定存储模型。

## 当前 runtime 项目参考

- `plans/RUNTIME_REFACTOR_PLAN.md`
- `docs/ARCHITECTURE.md`
- `docs/MIGRATION_INDEX.md`
- `docs/AGENT_LEARNING_LINKS.md`

## Skill System / Skill Routing

### 解决什么问题

Skill System 让 runtime 在不把所有领域说明永久塞进 prompt 的前提下，为当前请求选择并按需加载相关工作说明。Skill 是“如何处理某类任务”的上下文，不是工具、权限或业务事实。

### 核心概念

- Skill discovery：启动期只读取所有 `SKILL.md` 的 `name` 和 `description`。
- Skill routing：LLM 基于用户请求和全量 metadata 选择零到多个 Skill，LifeOps 再校验结构、重复 ID 和未知 ID。
- progressive loading：选中后才加载 Skill body；reference 只有被 manifest ID 明确请求时才加载。
- `PromptContribution`：已加载 Skill 对未来 prompt/context assembly 的输入，不是完整 system prompt。
- Skill 功能说明：解释如何处理某类任务，不声明或影响工具权限。

### 当前 runtime 实现

当前实现位于 `app/skills/`，并通过 LangGraph 的 `prepare_skills` node 接入 Policy allow 路径：

```text
Policy allow
-> LLM selects from all Skill metadata
-> LifeOps validates selected IDs
-> load selected SKILL.md body
-> build PromptContribution list
-> filtered Tool selection -> ToolGateway
```

`SkillService` 长期持有 `SkillRegistry` 和 `SkillSelectionClient`，像 Intent/Policy service 一样在 graph 构建时注入；每个 run 不同的 `TraceSink` 通过 `OrchestrationContext` 传入。Skill 永久启用，Runtime 不接受空 `SkillService`。GraphState 保存 selection 和 contributions；loaded IDs 可由 contributions 得出，不重复记录。生产 bootstrap 会发现内置 Skill，并组装 provider selection adapter；测试注入 deterministic fake client。

### 输入 / 输出 / 不负责什么

输入是 `RuntimeRequest`、全量 `SkillDefinition` metadata 和注入的 selection client。输出是 `SkillSelection`、loaded Skill IDs 与 `PromptContribution`。

Skill System 不执行工具、不授权写入、不决定 Context budget、不保存 Memory，也不把 LLM reason 或正文写入 event payload。

### 常见失败模式

- LLM 返回未知、重复或格式错误的 Skill ID。
- selected `SKILL.md` 缺失、为空或超过大小限制。
- reference ID 未声明、路径越界或正文超限。
- selection/load 失败后仍继续 Executor，造成缺少必要约束的执行。

当前实现把最后一种情况映射为 `runtime.skill_failed`，在 `execute_tool` 前终止 graph。

### 如何测试和观察

聚焦测试覆盖 metadata discovery、多 Skill 选择顺序、空选择、selection 结构校验、`.env` provider 配置、OpenAI-compatible JSON 请求、body/reference lazy loading、manifest 白名单、trace 脱敏、生产 bootstrap、allow 接入、失败阻断以及 confirmation/deny 分支隔离。`tests/fixtures/skills/` 使用带 `schema_version` 的固定 case 形状，为后续真实模型 Eval 保留稳定输入和 expected IDs。

### 面试解释

可以这样讲：LifeOps 兼容 Agent Skills 的文件与 progressive disclosure 思路，但 routing、结构校验和安全边界由自己实现。Skill 提供 instructions 并缩小业务候选 Tool，空 Skill 绑定的通用 Tool 独立加入候选；Policy 决定 effect 权限，Guardrail 和 Gateway 负责安全执行。Skill candidate 本身不是授权。

### 相关项目文件

- `app/skills/`
- `app/orchestration/`
- `plans/modules/SKILL_SYSTEM_PLAN.md`

## Runtime Core

### 解决什么问题

Runtime Core 固定单轮请求的入口、生命周期和返回边界。它回答“用户这一轮输入如何变成一个可追踪的 run，以及当前 run 为什么返回这个结果”。

### 核心概念

- `session_id`：短生命周期会话容器，可以包含多个 turn。
- `turn_id`：用户一轮输入。
- `run_id`：runtime 处理某个 turn 的一次执行尝试。
- `RuntimeRequest`：当前 run 的结构化输入。
- `RuntimeResult`：当前 run 的可展示输出，不是业务事实来源。

### 当前 runtime 实现

当前实现位于：

- `main.py`
- `app/runtime/models.py`
- `app/runtime/service.py`
- `app/runtime/bootstrap.py`
- `app/runtime/run_store.py`

`RuntimeService.handle(...)` 当前执行：

```text
RuntimeRequest
-> RuntimeOrchestrator / StateGraph
-> IntentService -> PolicyService
-> SkillService -> Direct Tool selection -> ToolGateway
-> RuntimeResult
```

传入 SQLite connection 时，它可以写入 `run_records`。传入 event log 或配置 `log_root` 时，它会把结构化 runtime event 写入 `events.jsonl`。当前已打通零或一个 ToolCall 的最小 Direct Executor；多步 ReAct loop 尚未实现。

### 输入 / 输出 / 不负责什么

输入是已经构造好的 `RuntimeRequest`。

输出是精简 `RuntimeResult`：run/session identity、status、message、可选 Tool result 与稳定 error code。Intent / Policy 解释属于语义事件或未来独立 explanation view，不在公共结果重复。

Runtime Core 不负责自然语言深度理解或授权写入；它委托 orchestration 和 Tool Gateway 执行业务工具，也不把 assistant final answer 升级为事实。

### 常见失败模式

- Intent classification 抛错。
- Policy evaluation 抛错。
- run record 或 trace event 写入失败。
- 把 `RuntimeResult.message` 误认为业务写入成功证据。

### 如何测试和观察

当前测试包括：

- `tests/test_runtime_service.py`

可以通过 `events.jsonl` 观察一次 run 的开始、Intent 分类、Policy 决策、route 和带最终 graph path 的完成或失败事件。需要关系查询时，`run_records` 仍可记录 run 状态。

### 面试解释

可以这样讲：本项目先把 agent runtime 的外壳做清楚。Runtime Core 不直接“聪明地回答问题”，而是负责把一轮输入变成 request、run、result 和 evidence。这样后续 LangGraph、Planner、Executor 都只是挂进明确生命周期里的模块，不会吞掉授权和事实来源边界。

### 相关项目文件

- 本项目：`app/runtime/`
- 本项目：`plans/modules/RUNTIME_CORE_PLAN.md`

## Intent Layer

### 解决什么问题

Intent Layer 判断用户大概想做什么，避免因为单个关键词误触发 planning 或 write。

### 核心概念

- `IntentType`：当前支持 `chat`、`read`、`write_request`、`plan_request`、`clarification_needed`、`unsupported`。
- `ClassifierResult`：某个 classifier 的单独判断信号。
- `IntentDecision`：`IntentService` 合成后的最终 intent 判断。

### 当前 runtime 实现

当前实现位于：

- `app/intent/models.py`
- `app/intent/classifiers.py`
- `app/intent/service.py`

`RuleBasedIntentClassifier` 是当前真实判断路径。它使用动作、对象和语气组合做保守判断。`LlmIntentClassifier` 当前是空实现，只返回 `not_available`，不调用真实模型。

### 输入 / 输出 / 不负责什么

输入是 `RuntimeRequest`。

输出是 `IntentDecision`。

Intent 不授权写入，不调用工具，不写 SQLite，不把 LLM classifier 结果升级成权限事实。

### 常见失败模式

- 规则过窄导致漏判。
- 裸关键词导致误触发。
- 用户一句话包含多个意图。
- LLM classifier 未来返回非法结构。

### 如何测试和观察

当前测试包括：

- `tests/test_intent_service.py`

重点样例包括：

- `我计划明天跑步` 不触发 `plan_request`。
- `帮我规划明天的安排` 返回 `plan_request`。
- `把明天跑步加入任务` 返回 `write_request` 和 write candidate。
- `计划一下` 返回 `clarification_needed`。

### 面试解释

可以这样讲：Intent 是语义层，只回答“用户可能想做什么”。它可以使用规则、LLM structured output 或相似样例检索，但这些都只是信号。是否允许写入必须交给 Policy。

### 相关项目文件

- 本项目：`app/intent/`
- 本项目：`plans/modules/INTENT_POLICY_PLAN.md`

## Policy / Permission Layer

### 解决什么问题

Policy / Permission Layer 判断系统现在被允许做什么。它把写入授权从 Planner、assistant 文本、LLM 输出和 checkpoint 中剥离出来，成为独立事实源。

### 核心概念

- `PolicyAction`：`allow`、`deny`、`requires_confirmation`。
- `PolicyDecision`：当前请求的授权判断；`allowed_effects` 只表达本轮允许 read / external_read / write，不枚举业务 Tool。

### 当前 runtime 实现

当前实现位于：

- `app/policy/models.py`
- `app/policy/service.py`

`PolicyService.evaluate(request, intent)` 只读取当前 `RuntimeRequest` 和 `IntentDecision`。READ 允许 read / external_read，明确且受支持的 WRITE request 只允许 write；疑似写入但对象不明确时返回 `requires_confirmation`，未知 intent 默认不 allow。具体业务 Tool 由 selected Skills 和 Registry 决定。

### 输入 / 输出 / 不负责什么

输入是 `RuntimeRequest` 和 `IntentDecision`。

输出是 `PolicyDecision`。

Policy 不调用工具，不调用 Planner，不写业务 repository，也不读取 LangGraph checkpoint 作为授权来源。

### 常见失败模式

- 把 LLM classifier 的 write signal 当成授权。
- 把 Planner 输出当成授权。
- 把 assistant final answer 的“已保存”当成事实。
- 写入对象不明确却默认 allow。

### 如何测试和观察

当前测试包括：

- `tests/test_policy_service.py`
- `tests/test_runtime_service.py`

测试验证非写入 intent 不产生 write authorization，LLM classifier / metadata / planner 模拟字段不能绕过 Policy，`requires_confirmation` 不声称已经写入。

### 面试解释

可以这样讲：Intent 判断“用户可能想干什么”，Policy 判断“系统现在被允许干什么”。即使未来 LLM classifier 很强，它也只能提供 intent signal。真正的写入授权来自 Policy，并且必须绑定当前用户输入。

### 相关项目文件

- 本项目：`app/policy/`
- 本项目：`plans/modules/INTENT_POLICY_PLAN.md`

## Write Safety

### 解决什么问题

Write Safety 防止系统在没有明确授权时修改用户数据，也防止 assistant 文本、Planner 输出或 checkpoint 被误读成写入事实。

### 核心概念

- 当前用户输入中的明确授权。
- Policy 明确点名的 WRITE Tool。
- 成功 WRITE tool result。
- 可复盘的 runtime evidence。

### 当前 runtime 实现

阶段 3 建立了授权模型和主链路；阶段 5 已让 `PolicyDecision.allowed_effects` 参与 Tool exposure intersection。Policy allow 仍不等于执行成功，真实结果必须来自 Gateway 返回的 `ToolResult` 和 WRITE evidence。

### 输入 / 输出 / 不负责什么

输入是当前 request、intent decision 和 policy decision。

输出是“是否允许继续”的授权判断。

Write Safety 不等于自然语言理解，不等于完整权限平台，也不等于多轮 confirmation 状态机。

### 常见失败模式

- 看到 `write_request` 就直接写入。
- `plan_request` 生成计划后自动创建任务。
- Recovery Context 自动 replay 写操作。
- LangGraph checkpoint 被当成授权状态。

### 如何测试和观察

当前测试通过 `tests/test_policy_service.py` 和 `tests/test_runtime_service.py` 验证 policy 边界。后续 Eval Harness 会把误触发样例沉淀成长期回归 case。

### 面试解释

可以这样讲：本项目把“理解用户想做什么”和“允许系统做什么”拆开。这样即使分类器或 Planner 猜错了，也不会自动变成写入权限。

### 相关项目文件

- 本项目：`docs/ARCHITECTURE.md`
- 本项目：`app/policy/`

## LangGraph Orchestrator

### 解决什么问题

LangGraph Orchestrator 把手写在 `RuntimeService` 中的 request lifecycle 变成显式 node、edge 和 conditional route，使执行路径可以测试、观察和逐步扩展，同时不让框架接管 Policy、事实来源或真实工具执行。

### 核心概念

- `StateGraph`：声明状态类型、节点和边，再编译成可执行 graph。
- node：一个 runtime 阶段，例如 Intent、Policy 或 stub result 构造。
- edge：固定的阶段顺序。
- conditional edge：根据当前 state 选择下一条路径。
- `GraphState`：本轮不断演进的 request-local 编排数据。
- runtime context：本轮节点共享、但不应进入 GraphState 的运行依赖。
- compiled graph：完成 wiring 后由 `invoke(...)` 启动的一次 graph execution。

### 当前 runtime 实现

当前实现位于：

- `app/orchestration/state.py`
- `app/orchestration/routes.py`
- `app/orchestration/nodes/`
- `app/orchestration/graph.py`

当前 graph 执行：

```text
START
-> classify_intent
-> decide_policy
-> allow / requires_confirmation / deny
-> 对应结果节点
-> finalize
-> END
```

`RuntimeOrchestrator.invoke(...)` 使用 compiled graph 的 `invoke(...)`。`GraphState` 在节点之间传递 intent、policy、route、result、error 和 graph path；节点返回更新，LangGraph 把逻辑上的最新状态提供给后续节点。

`OrchestrationContext` 是本项目定义的 dataclass，LangGraph 官方的 `context_schema` / `Runtime` 机制负责把它提供给节点。当前 context 只携带 `TraceSink`。`_with_runtime_trace(...)` 给普通 node 函数包一层，从 `runtime.context` 取出本轮 sink 并传入节点；它本身不写 event。

### 输入 / 输出 / 不负责什么

输入是 `RuntimeRequest`、Intent / Policy service 和可选的 request-local `TraceSink`。

输出是最终 `GraphState` 或其中的 `RuntimeResult`，以及实时追加的 Intent / Policy / route 语义事件和最终 graph path。

Orchestrator 不负责产生授权或直接调用 handler；它把 ToolCall 交给 Tool Gateway。业务 repository 只由受控 Domain handler 写入。Orchestrator也不保存长期 Memory，不把 graph checkpoint 当作事实来源。

### 常见失败模式

- 把 `GraphState` 做成包含长期 Memory、业务事实和 writer 的大状态容器。
- 把 Policy route 误解为新的授权判断；route 只能翻译已有 `PolicyDecision`。
- 把 Policy allow 或模型选择 Tool 误报为执行成功，而没有检查 Gateway `ToolResult` 和 WRITE evidence。
- Intent 失败后仍进入 Policy，或 Policy 失败后仍进入执行节点。
- 为了打 event，把所有非 Graph 关键阶段强行改造成 LangGraph node。

### 如何测试和观察

当前测试包括：

- `tests/test_orchestration_state.py`
- `tests/test_orchestration_nodes.py`
- `tests/test_orchestration_graph.py`
- `tests/test_runtime_service.py`

测试断言 allow、requires confirmation、deny 和失败路径的 graph path；同时证明 `intent.classified` / `policy.decided` 紧跟真实 Service 调用、失败事件不继续后续业务阶段，并验证 event payload 不包含原始用户输入或完整 GraphState。

### 面试解释

可以这样讲：项目先自建 Runtime、Intent、Policy、Storage 和 Observability 边界，再用 LangGraph 把这些阶段映射成 StateGraph，而不是用框架重写整个 runtime。GraphState 只表达本轮控制流，Policy 仍是授权事实源，应用自己的 TraceSink 可以同时覆盖 Graph 内外关键阶段。

### 相关项目文件

- 本项目：`app/orchestration/`
- 本项目：`app/runtime/service.py`
- 本项目：`plans/modules/LANGGRAPH_ORCHESTRATION_PLAN.md`

## LangGraph vs LangChain

### 解决什么问题

这一边界用于避免把两个框架的职责混在一起，或者为了“用了框架”而提前引入 chain、agent 和 tool abstraction。

### 核心概念

- LangGraph 偏向 orchestration runtime：state、node、edge、route、persistence、interrupt 和运行控制。
- LangChain 偏向模型、prompt、tool calling、structured output 和更高层 agent integration。
- LifeOps 自研 runtime 继续拥有 Policy、Context、Memory、Tool Safety、Executor、Trace 和业务事实来源。

### 当前 runtime 实现

阶段 4 只正式使用 LangGraph 的 `StateGraph`、node、edge、conditional edge、runtime context、compile 和 invoke。

当前没有引入 LangChain chain、agent 或 tool abstraction。LangChain 留给后续 Planner、Executor 和 Tool System 阶段按需要作为 adapter 使用。

### 输入 / 输出 / 不负责什么

LangGraph 当前输入 LifeOps 自己定义的 request、state 和 service，输出仍是 LifeOps 的 `RuntimeResult`。LangGraph 不重新定义业务模型。

LangChain 后续即使进入模型或工具层，也不能绕过 LifeOps Skill candidate / Policy effect intersection、Tool Safety 和成功执行证据。

### 常见失败模式

- 把 LangGraph 当成完整业务 runtime，让框架 state 变成事实数据库。
- 看到 LangGraph 依赖 `langchain-core`，就误以为项目已经采用 LangChain agent abstraction。
- 用 Planner、模型文本或 framework checkpoint 扩大写入权限。

### 如何测试和观察

当前依赖只显式声明 `langgraph`；测试从 LifeOps 的 `RuntimeService` 入口验证 graph 路径和原有 Policy 语义。后续引入 LangChain adapter 时，应继续用聚焦测试证明它没有改变授权和事实来源边界。

### 面试解释

可以这样讲：LangGraph 在本项目中是控制流映射层，LangChain 未来可能是模型和工具适配层。真正重要的不是框架名称，而是能解释框架 primitive 与自研 runtime 边界如何对应，以及哪些安全和事实职责不能外包给框架。

### 相关项目文件

- 本项目：`pyproject.toml`
- 本项目：`app/orchestration/`
- 本项目：`docs/ARCHITECTURE.md`

## ReAct Executor

### 解决什么问题

单次 Tool 选择无法处理“先查资料、根据结果再比较、最后生成回答”这类依赖 observation 的请求。ReAct Executor 提供一个通用、有界、跨 Domain 的 action → observation 循环，同时保持 Policy、Tool Gateway 和 Domain 事实边界不变。

### 核心概念

- Action：模型二选一返回一个 `ToolActionDecision` 或一个非空 `FinalAnswerDecision`。
- Observation：Gateway 返回的 `ToolResult` 安全投影，包含 call/tool identity、status、结构化 output/error 和 evidence。
- Bounded loop：每次 model decision 消耗一个 step，默认最多 `8`，合法范围 `1..16`。
- Stop reason：`final_answer`、`confirmation_required`、`limit_reached`、`safety_denied` 和明确的 model/input/internal failure。
- Private reasoning boundary：Executor 不定义 thought、reasoning 或 chain-of-thought 字段。

### 当前 runtime 实现

outer compiled graph 负责 Intent → Policy → Skill → Executor；独立 Executor compiled graph 负责 decide → execute Tool → observe → decide。Runtime 每个 run 只创建一个 `ToolRuntime`，整个循环复用同一 Registry/Gateway/Domain service scope。模型只看到 Policy 与 Skill 求交后的 filtered catalog；每个 ToolCall 仍必须经过 pre/post Guardrails。WRITE action 逐次请求 exact synchronous confirmation，不能跨 call 或 run 复用。

### 输入 / 输出 / 不负责什么

输入是 `RuntimeRequest`、Skill prompt contributions、固定 `AllowedToolSet`、request-local `ToolRuntime` 以及 empty/fake Context/Memory providers。输出是结构化 `ExecutorResult`，包含 status、stop reason、step count、ordered observations 和最后一个安全 ToolResult。

Executor 不授权、不持久化 GraphState、不自动 retry/replay WRITE、不拥有 Domain repository、不保存 provider response，也不把 final answer 当作副作用 evidence。

### 常见失败模式

- 模型返回 final answer 与 ToolCall 混合、多个 ToolCall、未知 Tool 或非法 arguments。
- 重复 call ID、catalog 外 Tool、伪造或跨 scope temporary ID。
- WRITE 缺少、过期或与 arguments 不匹配的 confirmation。
- Tool failure 回流后模型继续消耗 step，最终达到 limit。
- provider、Context/Memory provider 或 hook failure 被归一化为安全 error code。

### 如何测试和观察

`events.jsonl` 可以按 `seq` 看到 `executor.action.selected` → Gateway/Guardrail events → `executor.observation.recorded` → 下一 action → `executor.stopped`。`llm.jsonl` 按独立 interaction `seq` 保存 Skill selection 与每一步 Executor provider request/response；`application.log` 只保存异常诊断。

当前 deterministic/offline E2E 覆盖 Research 四步链、Travel search → compare → draft、跨 Domain sequence、confirmed/unconfirmed WRITE、failure recovery、limit、partial/expired result 和 idempotent retry。真实 provider E2E 不是强制 gate，provider 可用性风险与 LifeOps contract failure 分开判断。

### 面试解释

可以这样讲：我没有直接采用黑盒 agent helper，而是用两个 StateGraph 分离外层授权编排和内层 ReAct cycle。Executor 只负责有界控制流，Tool Gateway 仍是唯一执行入口；observation、confirmation、evidence 和 stop reason 都是自有 typed contract，因此可以独立测试安全、失败恢复和跨 Domain 行为。

### 相关项目文件

- `app/executor/`
- `app/orchestration/graph.py`
- `app/tools/gateway.py`
- `tests/test_executor_cross_domain_e2e.py`
- `tests/test_runtime_observability_e2e.py`
- `plans/modules/EXECUTOR_PLAN.md`

## Observability

### 解决什么问题

Observability 让 runtime 行为可以被解释和复盘。它回答“这次 run 经过了哪些阶段、哪里失败、LLM 原始请求和响应是什么”。

### 核心概念

- event log：少量必要字段，便于机器读取、Inspector 展示和 Eval 断言。
- LLM interaction log：保存 request / response JSON，便于人工排查。
- normal application log：普通程序日志，便于测试和 debug。
- Runtime evidence：能解释运行路径和结果的记录，但不自动等于业务事实。

### 当前 runtime 实现

当前实现位于：

- `app/observability/events.py`
- `app/observability/file_logs.py`
- `app/observability/logger.py`
- `app/orchestration/graph.py`
- `app/orchestration/nodes/`

`LogTraceEvent` 写入 `events.jsonl`。`LogLlmInteraction` 写入 `llm.jsonl`。Python 标准 `logging` 写入 `application.log`。三类日志默认在同一个 session log directory 下，但不混成一个文件。

`TraceSink` 是应用拥有的 request-local event 接口。RuntimeService 写 run 边界和最终 graph path；Intent / Policy node 写业务决策或失败事件；route 确定后写 `orchestration.route.selected`。Graph 外关键阶段未来可直接使用同一个 sink，不需要成为 LangGraph node。稳定事件契约不记录每个轻量 node 的 started/completed。

### 输入 / 输出 / 不负责什么

输入是 `run_id`、`seq`、事件类型、payload 或 LLM request-response。

输出是 append-only 文件日志，可按 `session_id` / `run_id` / `seq` 读取和复盘。

Observability 不负责授权写入，不负责改变业务状态，也不把 assistant 文本或 LLM response 自动升级成事实。

### 常见失败模式

- payload 不能 JSON 序列化。
- session log directory 不可写。
- application logger 重复添加 handler，导致重复日志。
- 原始 LLM log 过大或包含敏感字段，后续接入真实外部凭证前需要脱敏策略。
- 根据最终 state 事后补写“看似实时”的事件，导致时间语义不真实。
- 把完整 GraphState、原始用户输入或未来 tool args 写进 event payload。

### 如何测试和观察

当前测试包括：

- `tests/test_observability_file_logs.py`
- `tests/test_orchestration_graph.py`
- `tests/test_runtime_service.py`

它们验证 metadata、`events.jsonl`、`llm.jsonl`、`application.log`、单 active session handler、语义事件顺序、route、稳定 payload 字段和脱敏。graph path 只用于 graph 内部测试，不进入默认公共 event/result。

### 面试解释

可以这样讲：本项目把 observability 分成三条文件日志。event log 给系统和 Inspector 判断 runtime 路径，LLM log 给人回看原始模型交互，application log 给工程 debug。日志是观测材料，不绕过 policy，也不是业务写入授权来源；SQLite 主要留给业务事实和适合关系查询的数据。

### 相关项目文件

- 本项目：`app/observability/`
- 本项目：`plans/modules/OBSERVABILITY_LOGGING_PLAN.md`

## SQLite Local Persistence

### 解决什么问题

SQLite Local Persistence 为本地 runtime 提供轻量、可测试、可查询的业务事实和关系数据存储。

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

### 相关项目文件

- SQLite / Local Persistence 相关链接维护在 `docs/AGENT_LEARNING_LINKS.md`。
- 本项目：`app/storage/`
- 本项目：`plans/modules/STORAGE_SQLITE_PLAN.md`

## Domain Read Model 与 Candidate Provider

### 解决什么问题

Planner、Context Engine 和 Memory 都需要读取 Domain 数据，但如果它们直接扫描 Research SQLite 表，就会依赖内部 schema、绕过预算边界，并把业务事实与运行时选择混在一起。

### 核心概念

- Read Model：为特定消费者准备的紧凑、稳定、只读快照，不等同于完整 Domain model。
- Candidate Provider：按 query、limit 或 budget 返回候选；候选仍不是最终 Context 或 Memory。
- Fake consumer contract test：用最小假的消费者验证 Protocol 是否足够，不提前实现真正的下游模块。

### 当前 runtime 实现

共享 `DomainPlanningReadModel` 返回 Domain planning snapshot；`DomainContextProvider` 返回带 provenance 和 budget estimate 的 candidates；`DomainMemoryCandidateProvider` 只返回 Memory 评估候选。Research 用 Topic ID 实现 planning scope，并返回 Source / Note / Brief 相关类型。SQLite 查询由 `ResearchRepository` 持有，`ResearchReadService` 实现三个共享 Protocol。

### 输入 / 输出 / 不负责什么

输入是 topic ID，或 query 加 budget / limit。输出是 immutable snapshot 或 candidate tuple。它们不负责规划、不组装最终 Context、不写 Memory、不授权 Tool，也不读取 request-local raw HTML。

### 常见失败模式

- 下游模块直接依赖表结构。
- Context 查询没有预算上限。
- 把 candidate 自动升级成 Memory。
- 将未保存的临时 observation 混入长期候选。

### 如何测试和观察

使用 fake Planner / Context / Memory consumer 做 contract tests，并用 380 条 deterministic seed 验证分页和预算结果稳定。

### 面试解释

可以这样讲：Domain 保留事实所有权，同时为不同 runtime 消费者提供窄只读接口。Planner 得到的是规划快照，Context 得到的是预算内候选，Memory 得到的是可评估候选；三者都不能因为“读到了数据”就获得写入权限。

### 相关项目文件

- `app/domains/research/read_models.py`
- `app/domains/research/repository.py`
- `tests/test_research_read_models.py`
- `tests/test_research_long_term_fixtures.py`

## Source Identity 与 Fetch Snapshot

### 解决什么问题

同一个 URL 会被重复抓取且内容可能变化。如果把 URL identity、摘要、content hash 和 fetched time 放在一行里覆盖更新，旧 Brief 的来源会随最新抓取漂移，无法解释当时依据的版本。

### 核心概念

- Source identity：稳定的来源身份，包含 URL、source type 和标题。
- Fetch snapshot：一次抓取事实，包含 summary、content hash、fetched/published metadata 和 provenance。
- Pinned reference：Brief 保存时同时记录 `source_id` 和 `snapshot_id`。

### 当前 runtime 实现

schema v5 使用 `research_sources` 保存 identity，使用 `research_source_snapshots` 保存版本。同 URL 的新 content hash 追加 snapshot；重复 content hash 拒绝。`research_brief_sources.snapshot_id` 固定 Brief 创建时使用的版本。

### 输入 / 输出 / 不负责什么

输入是经过 manifest/Port 获取的 request-local observation；输出是 Source identity 和 snapshot 业务事实。该机制不保存 raw HTML，不自动抓取，也不替代 WRITE 授权。

### 常见失败模式

- 覆盖旧 snapshot，导致历史 Brief 来源漂移。
- 只按 URL 去重，无法识别相同内容的镜像或重复抓取。
- Brief 只引用 Source，不引用具体 snapshot。

### 如何测试和观察

v4→v5 migration test 验证旧数据生成 snapshot；repository test 验证同 URL 新内容追加 snapshot，且新旧 Brief 固定不同 snapshot。

### 面试解释

可以这样讲：Source 是“这是什么来源”，Snapshot 是“某次看到的具体版本”。Brief 固定引用 Snapshot，因此后续刷新不会改写历史事实。

### 相关项目文件

- `app/storage/schema.py`
- `app/domains/research/models.py`
- `app/domains/research/repository.py`
- `tests/test_storage_migrations.py`
- `tests/test_research_knowledge.py`
