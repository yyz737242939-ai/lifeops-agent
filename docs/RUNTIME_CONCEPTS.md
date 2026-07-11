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
- Capability
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

本节记录阶段 5 已确认、正在用于模块计划的术语。它们是设计边界，不表示对应代码已经实现。

- `SkillDefinition`：Skill 的轻量声明，包含 ID、说明、routing metadata 和声明式资源索引；不是可执行工具。
- `PromptContribution`：selected Skill 提供给未来 Context/prompt assembly 的一段有来源、可预算的说明；不是完整 prompt，也不是业务事实。
- `SkillCapabilityHints`：Skill 建议当前请求可能需要哪些能力；最终可用工具仍需经过 registry、Policy、scope 和 confirmation 求交集。
- `ToolDefinition`：工具名称、schema、effect、risk、required scopes 等静态契约。
- `ToolGateway`：所有工具通道统一经过的单次执行入口，负责 pre/post Guardrails、handler 调用和 evidence 输出。
- `GuardrailDecision`：工具执行前或执行后的结构化安全判断；不能扩大 `PolicyDecision` 已授予的权限。
- `ExecutionEvidence`：证明工具真实执行结果的结构化证据。assistant 文本、Planner 输出或 LLM summary 不是 evidence。
- `External Port`：Domain 声明的外部能力接口，例如天气或交通查询；fixture、MCP 和 HTTP adapter 可以分别实现它。
- `ExternalObservation`：某个 provider 在某时刻返回的临时观察，带 provenance 和有效期；它不是长期业务事实。
- `DomainContextProvider`：未来 Context Engine 获取 Domain 候选信息的窄接口；Domain 不负责决定最终 prompt。
- `PlanningReadModel`：为 Planner 准备的只读、稳定、领域化快照；Planner 不读取 repository internals。
- `MemoryCandidateProvider`：向未来 Memory 模块提供候选的只读接口；候选不会自动成为长期 Memory。
- `ResearchBriefDraft`：基于临时 source observation 生成的简报草案；只有用户确认保存后才成为 `ResearchBrief` 业务事实。
- `ItineraryDraft`：基于 Travel constraints 和外部 observation 生成的行程草案；只有用户确认并成功 WRITE 后才成为持久化 Itinerary。
- `Fixture Adapter`：使用固定测试数据实现 External Port 的 adapter，用于离线开发和 deterministic Eval；不是简单返回任意假值的无契约 mock。
- `PlanRun`：Planner 针对一个用户目标生成的跨 Domain 通用执行策略；可以持久化以支持恢复，但不是业务事实。
- `PlanStep`：以 objective、dependencies、required capabilities、candidate tools、effect 和 status 描述的通用执行步骤；不继承具体 Domain 类型。
- `Domain`：从业务角度划分 models、service、repository 和 tools 的逻辑边界；不是独立 Agent，也不拥有自己的通用 Planner / Executor。

阶段 5 的核心分离：

```text
Skill instructions       != Tool execution
Capability hints         != Permission
External observation     != Domain fact
Domain fact              != Context selection
Context selection        != Memory
Plan / draft             != confirmed WRITE
Framework adapter        != LifeOps safety boundary
Persisted PlanRun         != Domain fact
Checkpoint restore        != side-effect rollback
```

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
- capability hints：Skill 对可能需要能力的声明式提示，不代表工具存在或已获授权。

### 当前 runtime 实现

当前实现位于 `app/skills/`，并通过 LangGraph 的 `prepare_skills` node 接入 Policy allow 路径：

```text
Policy allow
-> LLM selects from all Skill metadata
-> LifeOps validates selected IDs
-> load selected SKILL.md body
-> build PromptContribution list
-> stub execution
```

`SkillService` 长期持有 `SkillRegistry` 和 `SkillSelectionClient`，像 Intent/Policy service 一样在 graph 构建时注入；每个 run 不同的 `TraceSink` 才通过 `OrchestrationContext` 传入。selection、loaded IDs 和 contributions 是当前 run 的 `GraphState` 数据。当前默认 runtime 未配置真实 `SkillService`，因此安全地产生空选择。

### 输入 / 输出 / 不负责什么

输入是 `RuntimeRequest`、全量 `SkillDefinition` metadata 和注入的 selection client。输出是 `SkillSelection`、loaded Skill IDs 与 `PromptContribution`。

Skill System 不执行工具、不授权写入、不决定 Context budget、不保存 Memory，也不把 LLM reason 或正文写入 event payload。

### 常见失败模式

- LLM 返回未知、重复或格式错误的 Skill ID。
- selected `SKILL.md` 缺失、为空或超过大小限制。
- reference ID 未声明、路径越界或正文超限。
- selection/load 失败后仍继续 Executor，造成缺少必要约束的执行。

当前实现把最后一种情况映射为 `runtime.skill_failed`，在 `stub_execute` 前终止 graph。

### 如何测试和观察

聚焦测试覆盖 metadata discovery、多 Skill 选择顺序、空选择、selection 结构校验、body/reference lazy loading、manifest 白名单、trace 脱敏、allow 接入、失败阻断以及 confirmation/deny 分支隔离。

### 面试解释

可以这样讲：LifeOps 兼容 Agent Skills 的文件与 progressive disclosure 思路，但 routing、结构校验和安全边界由自己实现。LangGraph 只编排 `prepare_skills` 的位置；Skill 提供 instructions，Tool System 才负责 capability、Policy、Guardrail 和真实执行。

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
-> IntentService
-> PolicyService
-> RuntimeResult
```

传入 SQLite connection 时，它可以写入 `run_records`。传入 event log 或配置 `log_root` 时，它会把结构化 runtime event 写入 `events.jsonl`。当前 orchestration 和 tool execution 仍是 stub。

### 输入 / 输出 / 不负责什么

输入是已经构造好的 `RuntimeRequest`。

输出是 `RuntimeResult`，其中可以包含 intent / policy 摘要。

Runtime Core 不负责自然语言深度理解，不授权写入，不执行业务工具，不把 assistant final answer 升级为事实。

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
- `PermissionScope`：当前候选 scope，例如 `task.write_candidate`、`memory.write_candidate`、`wellbeing.write_candidate`。
- `PolicyDecision`：当前请求的授权判断。

### 当前 runtime 实现

当前实现位于：

- `app/policy/models.py`
- `app/policy/service.py`

`PolicyService.evaluate(request, intent)` 只读取当前 `RuntimeRequest` 和 `IntentDecision`。明确写入请求可以返回有限候选 scope；疑似写入但对象不明确时返回 `requires_confirmation`；未知 intent 默认不 allow。

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
- Policy 返回的有限 scope。
- 成功 WRITE tool result。
- 可复盘的 runtime evidence。

### 当前 runtime 实现

阶段 3 当前只建立授权模型和主链路。`PolicyDecision` 可以允许候选写 scope，但 Runtime Core 仍返回 `runtime.orchestration.stubbed`，不会执行真实 tool 或业务写入。

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

Orchestrator 不负责产生授权、不调用真实 tool、不写业务 repository、不保存长期 Memory，也不把 graph checkpoint 当作事实来源。

### 常见失败模式

- 把 `GraphState` 做成包含长期 Memory、业务事实和 writer 的大状态容器。
- 把 Policy route 误解为新的授权判断；route 只能翻译已有 `PolicyDecision`。
- `allow` 节点声称业务写入成功，而实际仍是 stub execution。
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

LangChain 后续即使进入模型或工具层，也不能绕过 LifeOps Policy、授权 scope、Tool Safety 和成功执行证据。

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

它们验证 metadata、`events.jsonl`、`llm.jsonl`、`application.log`、logging 幂等性、语义事件顺序、route、最终 graph path 和 payload 脱敏。

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
