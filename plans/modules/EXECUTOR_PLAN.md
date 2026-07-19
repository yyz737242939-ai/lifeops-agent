# 阶段 6 ReAct Executor 模块计划

## 当前状态

阶段 0-5 功能与稳定化均已完成，`STAGE5_STABILIZATION_PLAN.md` 已给出 Stage 6 `go`。本计划已于 2026-07-13 获用户确认，实施步骤 1-12 全部完成。Stage 6 ReAct Executor 结论为 `go`，下一阶段可以创建并确认 `PLANNER_PLAN.md`，但本计划不提前实施 Stage 7。

本阶段在已冻结的 Runtime、Intent / Policy、LangGraph Orchestration、Skill、Tool Gateway 与 Research / Travel Domain 之上，增加一个 LifeOps 自己拥有的通用 ReAct Executor。它负责有界的 action → observation 循环，但不接管授权、安全、业务事实或长期状态。

## 1. 目标

- 把当前“模型最多选择并执行一个 Tool”的 Direct Executor，升级为 `model decision -> ToolCall -> ToolResult/Observation -> next decision` 的有界循环。
- 让同一个 run 可以连续调用 Research、Travel 或通用 Tool，并始终复用 Runtime 创建的同一个 execution scope。
- 允许模型在没有 Tool、Tool 成功或 Tool 失败后生成最终回答；最终回答不替代 Tool evidence，也不证明副作用成功。
- 为阶段 7 Planner 提供可复用的 `ReactExecutor` 公共入口，而不是把循环只写死在当前 outer graph node 中。
- 为阶段 9 Context / Memory 和阶段 10 Recovery / Feedback 预留窄 Protocol，并以 empty/no-op/fake 实现证明可插拔性；本阶段不实现这些模块。Stage 8 已在 2026-07-15 重排为 Research MCP，但继续复用现有 Tool/Gateway 边界。
- 保持 deterministic、离线、可分层测试；任何模型、Tool、confirmation 或 loop failure 都收敛成结构化 stop reason 与安全 Runtime 结果。

本阶段成功的标准不是“循环次数更多”，而是多步执行仍然遵守前五阶段已经建立的事实源、授权源、状态所有权、Gateway 和 observability 边界。

## 2. V0 参考

本阶段默认不读取 `legacy_v0/`。当前 Runtime、Tool Gateway、Domain workflows 和冻结契约已经足以定义 Stage 6。

只有当前计划明确需要迁移 V0 某项 Executor 行为，而现行代码、测试和文档无法给出语义时，才按最小范围读取对应历史文件。V0 旧 agent loop 不能成为恢复聚合 Agent、全局 mutable state、自动 WRITE replay、超大 prompt 或绕过 Gateway 的理由。

## 3. 当前范围

### 3.1 本次做

- 新建 `app/executor/`，定义 Executor models、ports、loop graph/service 和 provider adapter。
- 定义有界 ReAct state、model decision、Tool observation、execution result、stop reason 和 loop limits。
- 使用独立的 compiled Executor `StateGraph` 表达循环；当前 Runtime compiled graph 仍负责 Intent → Policy → Skill → Executor 的外层编排。
- 把 Skill prompt contributions、Policy 与 Skill 求交后的 `AllowedToolSet`、filtered Tool catalog 和同 run `ToolRuntime` 传给 Executor。
- 每次 model decision 只允许二选一：返回一个 `ToolCall`，或返回一个非空最终回答；不接收并行 ToolCalls。
- 将每次 `ToolResult` 转成模型可消费的结构化 `ToolObservation`，再进入下一次 model decision。
- 支持多个 Domain Tool 的串行调用、失败 observation 回流、最大步数停止、无 Tool 最终回答和逐 WRITE action confirmation。
- 定义 Context provider、Memory provider、confirmation provider、Recovery hook 和 Feedback sink 的窄接口；提供 empty/no-op 实现与 fake consumer tests。
- 增加 Executor 语义事件、契约测试、outer graph integration tests、跨 Domain E2E 和统一离线回归。

### 3.2 本次不做

- 不实现阶段 7 Planner、PlanRun、PlanStep、replan 或 DAG。
- 不实现真正的 Context assembly、budget/compaction、Memory retrieval/write、Recovery replay 或 ExecutionFeedback 持久化。
- 不实现 LangGraph checkpointer、interrupt、跨进程/跨 run confirmation resume 或 pending execution store。
- 不实现并行 ToolCalls、并行 branch、streaming、background execution、自动重试 policy 或模型自定义 retry budget。
- 不实现 MCP、LangChain `create_agent` / `ToolNode` adapter、Calendar 写入或真实 Travel booking/payment。
- 不修改 Research / Travel 业务能力、repository schema 或冻结 Tool JSON schema。
- 不让 Executor 读取 Domain service、repository、handler、provider response、SQLite row 或 request-local cache 内部结构。
- 不保存或要求模型输出 chain-of-thought / private reasoning；ReAct 在本项目中体现为可观察的 action/observation 控制循环。

## 4. 核心架构与依赖方向

### 4.1 两层 graph

```text
RuntimeService.handle(request)
-> RuntimeOrchestrator / outer compiled graph
   -> Intent
   -> Policy
   -> Skill preparation
   -> resolve AllowedToolSet
   -> ReactExecutor.execute(...)
      -> executor model decision
         -> final answer --------------------------+
         -> one ToolCall                           |
            -> optional synchronous confirmation  |
            -> ToolGateway.execute(...)            |
            -> ToolObservation                     |
            -> next executor model decision -------+
   -> map ExecutorResult to RuntimeResult
-> close run lifecycle
```

outer graph 保持 request lifecycle 与 policy route 的总编排；Executor 使用自己的小型 compiled graph 表达 cycle。这样：

- `GraphState` 不需要膨胀为 observations、model transcript 或 loop counters 的容器；
- `ReactExecutor` 可以在阶段 7 被 Planner 直接复用；
- Executor graph 可以独立做 route、limit 和 failure tests；
- LangGraph 只负责编排，Policy、Gateway、Domain facts 和 confirmation 仍由 LifeOps 自己的组件负责。

Executor graph 不启用 checkpointer。当前 run 的 execution state 和 Domain temporary state 都只在进程内、当前 `RuntimeService.handle(...)` 生命周期内存在。

### 4.2 稳定依赖方向

```text
Runtime / Planner (future)
-> ReactExecutor
-> ExecutorModelClient + provider hooks
-> ToolRuntime.registry model_catalog
-> ToolGateway.execute(...)
-> Guardrails
-> registered Domain Tool handler
-> Domain service / repository / external Port
```

禁止反向依赖：

- Domain 不 import Executor、LangGraph、Planner 或 provider SDK。
- Tool core 不 import Executor 或具体 Domain。
- Executor 不 import Research / Travel models、services 或 repositories。
- Model client 不获得 Registry handler、Policy object、SQLite connection、confirmation secret 或 raw provider adapter。
- Planner 未来只调用 `ReactExecutor` 公共入口，不读取 Executor graph state。

### 4.3 现有模块保持的职责

- `RuntimeService`：唯一外部入口、run lifecycle、每 run execution scope、session logs 和最终 `RuntimeResult`。
- Intent / Policy：判断请求类型和允许的 effect；模型 observation、Planner 或 Executor 不得扩大权限。
- Skill：提供业务候选和 prompt instructions，不授权。
- `resolve_allowed_tools(...)`：将 Skill candidates 与 Policy effects 求交；同一 run 内结果固定，不由模型动态扩大。
- `ToolGateway`：每次 ToolCall 的唯一安全执行入口，负责 pre/post Guardrail、结构化错误和 evidence。
- Domain：业务规则、request-local workflow、长期事实和 external Port。
- `TraceSink`：语义事件写入边界；不进入 Executor state 或模型输入。

## 5. 状态与生命周期

| 状态 | owner | 创建时机 | 生命周期 | 是否持久化 | 消费者 |
| --- | --- | --- | --- | --- | --- |
| `RuntimeRequest` / `RuntimeResult` | Runtime | 外部请求 / run 完成 | 单 run | run summary 只按现有规则 | outer graph / caller |
| `ToolRuntime` execution scope | RuntimeService | 每个 run 开始 | 整个 run，多次 Tool 调用共享 | 否 | Executor / Gateway |
| outer `GraphState` | RuntimeOrchestrator | graph invoke | 单次 outer graph | 当前不 checkpoint | outer nodes |
| `ExecutorState` | ReactExecutor graph | Executor 开始 | 单次 Executor invocation | 否 | Executor nodes/routes |
| `AllowedToolSet` / catalog | outer execution node | Skill/Policy 后 | 单次 Executor invocation，内容固定 | 否 | model client / Gateway |
| Context / Memory contributions | 对应 provider | Executor 开始时读取一次 | 单次 Executor invocation | 否 | model input builder |
| `ToolObservation` 列表 | Executor | 每个 Gateway result 后 | 单次 Executor invocation | 否 | 后续 model decisions / result |
| Domain observation/candidate/draft | Domain service | Tool handler 执行时 | 当前 execution scope | 否 | 同 scope 后续 Domain tools |
| `ConfirmedAction` | confirmation provider | 用户确认一个具体 WRITE action 后 | 当前 call 且到期前 | 否 | Gateway pre-Guardrail |
| `ExecutorResult` | ReactExecutor | final/stop/failure | 返回给 caller | 本阶段不单独持久化 | Runtime / future Planner/hooks |

任何模型 transcript、Tool arguments、Tool output、private reasoning、Context item 或 temporary Domain ID 都不写入 `run_records`、Domain 业务表或稳定 event payload。

## 6. 数据模型

### 6.1 `ExecutionLimits`

初版只定义 `max_steps`，默认 `8`，允许范围 `1..16`。一次 step 表示一次 model decision；final answer 和 ToolCall decision 都消耗一步。达到上限后不得再调用模型或 Tool，结果为 `limit_reached`。

limit 由 composition/config 提供，不能由用户输入、模型输出或 Skill instructions 提升。阶段 7 若需要按 PlanStep 收紧 limit，只能传入更小或显式允许的配置。

### 6.2 model decision

使用明确的 discriminated result，而不是 `ToolCall | None`：

- `ToolActionDecision(call: ToolCall)`：本步请求一个 ToolCall。
- `FinalAnswerDecision(message: str)`：本步给出非空最终回答。

两者必须互斥。空回答、同时返回回答与 ToolCall、多个 ToolCalls、未知 decision type、非对象 arguments 或重复 `call_id` 都属于 `invalid_model_action`。

model decision 不包含 `thought`、`reasoning` 或 chain-of-thought 字段。需要给用户解释时，解释属于最终回答；需要观测控制流时，使用 action type、Tool identity、status 和 stop reason。

### 6.3 `ToolObservation`

`ToolObservation` 是 `ToolResult` 的 Executor-owned、模型可见投影，至少包含：

- `step_index`
- `call_id`
- `tool_name`
- `status`
- schema-validated `output` 或 `None`
- 结构化 `error`（code、safe message、retryable）或 `None`
- `evidence` 的 type/summary/reference

它不包含原始用户输入、Tool arguments、handler exception、Policy reason、Registry internals 或 provider raw response。Tool output 仍必须先通过 Gateway post-Guardrail；Executor 不自行信任 handler 返回。

### 6.4 `ExecutorStatus` 与 `ExecutorStopReason`

`ExecutorStatus`：

- `completed`：模型给出最终回答。
- `stopped`：需要外部动作或达到控制边界，没有声称任务完成。
- `failed`：model/contract/runtime failure，无法安全继续。

初版冻结 stop reason：

- `final_answer`
- `confirmation_required`
- `limit_reached`
- `safety_denied`
- `model_failed`
- `invalid_model_action`
- `input_provider_failed`
- `executor_internal_failed`

普通 `ToolResult.failed` 不自动成为 stop reason。它先作为 observation 回流，模型可以在剩余 step 内换 Tool、修正参数或给出诚实的失败说明。`ToolResult.denied` 表示安全边界拒绝，立即以 `safety_denied` 停止；`requires_confirmation` 立即以 `confirmation_required` 停止。

### 6.5 `ExecutorResult`

作为阶段 7 Planner 的稳定消费入口，至少包含：

- `run_id`
- `status`
- `stop_reason`
- `final_message` 或 `None`
- `step_count`
- ordered `observations`
- `last_tool_result` 或 `None`
- `error_code` 或 `None`

`ExecutorResult` 不包含 outer `GraphState`、Policy/Intent summary、private model transcript、Domain object 或 exception text。`RuntimeResult` 继续是外部结果；outer node 负责把 Executor status/stop reason 映射到现有 Runtime status/message/tool_result。

### 6.6 `ExecutorState`

Executor graph 的 internal `TypedDict` 只保存：

- immutable request/input contributions；
- fixed allowed catalog；
- ordered observations；
- current decision；
- step count；
- final `ExecutorResult`；
- internal executor path / error code。

`ToolRuntime`、Gateway、model client、providers、hooks、TraceSink 和 SQLite connection 通过 executor runtime context / service dependency 提供，不写入 state。

## 7. 公共接口与 Ports

### 7.1 `ReactExecutor`

目标入口：

```python
ReactExecutor.execute(
    request,
    prompt_contributions,
    allowed_tools,
    execution_scope,
    trace=None,
) -> ExecutorResult
```

Executor 接收已经解析完成的 `AllowedToolSet`，不重新读取 Policy 或 Skill selection。它通过 `execution_scope.registry.model_catalog(...)` 得到 filtered catalog，并只通过 `execution_scope.gateway.execute(...)` 执行。

### 7.2 `ExecutorModelClient`

```python
ExecutorModelClient.decide(model_input) -> ToolActionDecision | FinalAnswerDecision
```

`model_input` 只包含当前用户请求、Skill prompt contributions、Context/Memory provider contributions、filtered catalog、ordered observations 和 step index。OpenAI-compatible adapter 每一步从 typed state 重建输入，不把 provider response object 或 `previous_response_id` 作为 LifeOps state 事实。

当前 `ToolCallSelectionClient` 在迁移期间保留；Executor model adapter、outer graph 和 tests 全部切换后再删除或收口旧 Direct Executor client。不能同时长期保留两套生产执行入口。

### 7.3 Context / Memory provider

定义两个独立只读 Protocol：

```python
ExecutorContextProvider.load(request) -> tuple[ExecutorContextContribution, ...]
ExecutorMemoryProvider.load(request) -> tuple[ExecutorMemoryContribution, ...]
```

本阶段 production 使用 empty provider，测试使用 fake provider。它们不能修改 request、Policy、AllowedToolSet、Domain facts 或 execution scope。Stage 9 可以在不修改 Executor loop 的前提下提供真实实现；具体 retrieval、budget 和 compaction 仍由 Stage 9 设计。

### 7.4 confirmation provider

```python
ActionConfirmationProvider.confirm(
    run_id,
    call,
    tool_definition,
) -> ConfirmedAction | None
```

- 只有 Registry 中 effect 为 WRITE 的 action 会请求 confirmation。
- provider 是唯一能表示“用户已确认”的交互边界；模型、Skill、Planner、request text 和 observation 都不能生成可信 confirmation。
- provider 返回的 `ConfirmedAction` 仍必须由 Gateway 校验 run/call/tool/arguments digest/expiry。
- 返回 `None` 时，Executor 以无 confirmation 调用 Gateway，得到规范的 `requires_confirmation` ToolResult 并停止；handler 不执行。
- 本阶段支持同 run 的同步 confirmation provider，因此 execution scope 与 temporary IDs 仍存活。默认 provider 不自动批准。
- 跨 run、异步 UI、进程重启后的 pending action 恢复留给后续 Interaction Safety / persistence 计划，不使用 metadata 或全局 dict 临时绕过。

### 7.5 Recovery hook / Feedback sink

```python
ExecutorRecoveryHook.on_stop(result) -> None
ExecutorFeedbackSink.record(step_or_result) -> None
```

本阶段使用 no-op production 实现和 recording fake。Recovery hook 只能观察终止结果，不能自动 replay、改变 stop reason 或再次执行 Tool。Feedback sink 不等同于 `TraceSink`：前者是未来结构化反馈消费者，后者是当前稳定语义事件边界。

hook/sink 自身失败不得改写已经产生的 Tool evidence 或业务事实；只记录安全诊断事件。

## 8. Loop 语义

1. outer graph 在 Policy allow、Skill preparation 成功后解析一次 `AllowedToolSet`。
2. Runtime 为本 run 创建一次 `ToolRuntime`；Executor 全循环复用它。
3. Executor 在开始时各调用一次 Context / Memory provider；empty 结果是合法结果。
4. Executor model client 根据当前 typed input 返回 final answer 或一个 ToolCall。
5. final answer 立即产生 `completed/final_answer`；即使 catalog 为空，模型仍可诚实回答或说明无法完成。
6. ToolCall 必须使用新的非空 `call_id`，并只能指向 filtered catalog；Gateway 仍做最终 membership/schema/safety 检查。
7. WRITE Tool 在 Gateway 前请求 synchronous confirmation。获得确认则把 exact `ConfirmedAction` 传给 Gateway；未确认则由 Gateway 返回 `requires_confirmation`。
8. Gateway result 转成 `ToolObservation` 并追加到 ordered observations；Feedback sink 接收 step record。
9. `succeeded` / `failed` observation 回到下一次 model decision；Executor 不基于 error.retryable 自动重试。
10. `denied` 立即停止为 `safety_denied`；`requires_confirmation` 立即停止为 `confirmation_required`。
11. 达到 `max_steps` 后立即停止为 `limit_reached`，不再发起模型或 Tool 调用。
12. Executor result 返回 outer node；Runtime 完成 run record 和最终事件闭合。

模型可以根据 retryable error 决定下一 action，但每次决定都消耗 step，不能扩大 allowed catalog，不能复用旧 confirmation，也不能把失败文本改写成成功事实。

## 9. Runtime / Orchestration 接入

- outer graph 的 `execute_tool` node 改为语义明确的 Executor node；旧单 Tool helper 在新路径全绿后删除，避免两套入口。
- Intent、Policy、requires-confirmation、deny 和 Skill preparation routes 保持不变。Policy-level clarification/confirmation 仍在 Executor 之前停止。
- outer `GraphState` 只保存最终 `RuntimeResult`，不复制 Executor observations、limits 或 transcript；详细控制结果通过 `ExecutorResult` 在 node-local 映射。
- `RuntimeOrchestrator` 构造时注入 `ReactExecutor`，Runtime invoke 时继续通过 request-local context 传入 execution scope 与 TraceSink。
- `RuntimeService` 不实现 loop，不创建 Domain-specific Executor，也不延长 SQLite WRITE transaction。
- Stage 7 Planner 未来调用相同 `ReactExecutor.execute(...)`，但 Planner 如何生成 step、限制 catalog 或 replan 由 Planner 计划定义。

## 10. Observability

新增稳定语义事件候选：

- `executor.action.selected`：step index、decision type；Tool action 时包含 call/tool identity。
- `executor.observation.recorded`：step index、call/tool identity、status、error code、retryable、evidence count。
- `executor.stopped`：status、stop reason、step count、last call/tool identity（若存在）。

Gateway 已拥有 `tool.call.*` 与 `tool.guardrail.decided`，Executor 不重复记录 arguments、output 或 Guardrail 明细。event payload 禁止包含：

- user input、完整 prompt、Context/Memory content；
- chain-of-thought、provider raw response、Tool arguments/output；
- exception text、secret、confirmation digest；
- 完整 ExecutorState / GraphState。

`application.log` 只记录本地诊断，不镜像每个正常 step。当前 request-local `LlmInteractionSink` 已把 Skill selection 与每步 Executor model decision 的 provider、model、request、response、status 和安全 error code 按独立 `seq` 写入 `llm.jsonl`；provider exception text 不落盘，日志写入失败只进入本地诊断且不改写主执行结果。未来统一 LLM Gateway 可以复用该 sink，但不是 Stage 6 完成前提。

## 11. 失败模式

| 场景 | 期望结果 | 禁止行为 |
| --- | --- | --- |
| model config/provider failure | `failed/model_failed`，安全 error code | 暴露 provider exception 或自动无限 retry |
| model 同时返回 final 与 ToolCall、多个 calls、非法 JSON | `failed/invalid_model_action` | 猜测或修补成可执行 WRITE |
| call ID 重复 | `failed/invalid_model_action` | 用重复 identity 覆盖旧 observation |
| Tool 不在 filtered catalog | Gateway deny，Executor `stopped/safety_denied` | Executor 绕过 Gateway 或扩大 catalog |
| WRITE 无 confirmation | `stopped/confirmation_required`，零 handler 调用 | 从模型文本或 request 自动确认 |
| confirmation 跨 run/过期/参数变化 | Gateway deny/requires confirmation | 修改 digest、复用旧确认 |
| Tool handler exception / schema invalid | safe failed observation | exception text 进入模型、event 或 RuntimeResult |
| ToolResult failed | observation 回流，剩余 step 可恢复 | Executor 自动声称成功或自动 replay WRITE |
| Domain temporary ID 不在当前 scope | failed observation，数据库零误写 | 跨 run 查询私有 cache |
| 达到 step limit | `stopped/limit_reached` | 再调用模型/Tool 或依赖 LangGraph recursion exception 作为正常控制流 |
| Context/Memory provider 失败 | `failed/input_provider_failed` | 静默注入部分不可信内容 |
| Recovery/Feedback hook 失败 | 保留主结果，记录安全诊断 | 改写 evidence、stop reason 或重新执行 Tool |
| final answer 与 evidence 冲突 | evidence 仍是副作用事实源 | 以 assistant 文本覆盖 ToolResult |

## 12. 测试策略

### 12.1 Model / pure function

- limits 范围、decision 互斥、非空 final answer、call ID uniqueness。
- ToolResult → ToolObservation 投影和敏感字段负向断言。
- status / stop reason → RuntimeStatus 映射。
- Executor routes：final、tool、continue、confirmation、deny、limit、error。

### 12.2 Executor contract tests

- `ReactExecutor` 只依赖 `AllowedToolSet`、ToolRuntime/Gateway 和窄 provider ports。
- Executor package 不 import Research / Travel、repository、storage 或 provider-specific Domain modules。
- `ExecutorResult` 字段和 stop reason 冻结。
- model client 每步只看到 filtered catalog 和 ordered safe observations。
- private reasoning、raw arguments/output、exception 不进入 state/events/result。

### 12.3 Loop unit tests

- immediate final answer，零 ToolCalls。
- Tool success → observation → final answer。
- failed Tool → observation → alternate Tool / final answer。
- exact max step 停止，无 off-by-one Tool 调用。
- duplicate call ID、unknown Tool、invalid decision fail-closed。
- empty catalog 仍可 final answer。

### 12.4 confirmation tests

- WRITE 每个 action 单独请求 confirmation。
- absent/reject provider 不触达 handler。
- fake approve provider 生成 exact `ConfirmedAction` 后 WRITE 成功且 evidence 存在。
- 第二个 WRITE 不能复用第一个 action 的 confirmation。
- 参数变化、call ID 变化、跨 run 和过期全部拒绝。

### 12.5 Provider hook fake consumers

- Context / Memory empty 与 fake contribution 均不改变授权。
- Recovery hook 只收到 final stop result，不 replay。
- Feedback sink 按顺序收到 steps/result，不替代 TraceSink。
- provider/hook exception 的隔离语义。

### 12.6 Runtime / graph integration

- outer graph allow route 调用 ReactExecutor；deny/requires-confirmation route 不调用。
- Runtime 每 run 只创建一个 execution scope；同 run 多 Tool 共享，跨 run 隔离。
- LLM/external read 不持有 SQLite WRITE transaction；每个 Domain WRITE 保持短 transaction。
- outer GraphState 继续满足 Stage 5 frozen fields，不加入 Executor internals。
- run record、events 和 session logs 在 success/stop/failure 时闭合。

### 12.7 跨 Domain compiled E2E

- Research fetch → parse → rank → build draft 的多 Tool loop。
- Travel external search → comparison → itinerary draft 的多 Tool loop。
- 同一 run Research READ → Travel READ 的跨 Domain sequence。
- confirmed Research/Travel WRITE 返回真实 evidence；未确认或失败路径数据库零误写。
- catalog 外 Tool、伪造 temporary ID、过期 quote、幂等 retry 和 partial failure。

所有强制测试使用 fake model、fixture adapters、临时 SQLite/session logs，不访问真实网络、真实用户数据库或真实日志目录。真实 LLM/provider E2E 单独运行并区分 provider failure 与 LifeOps contract failure。

## 13. 文档更新

- `plans/modules/EXECUTOR_PLAN.md`：记录设计、步骤状态、验证证据和最终边界。
- `docs/ARCHITECTURE.md`：Executor 实现后同步两层 graph、state owner、loop、confirmation 与 provider hooks。
- `docs/PROGRESS_LOG.md`：只记录已经完成并验证的实施事实，不在计划确认时提前标记 Stage 6 进行中。
- `plans/RUNTIME_REFACTOR_PLAN.md`：实现开始/完成或 Stage 7 gate 改变时同步阶段状态。
- `docs/RUNTIME_CONCEPTS.md`：沉淀 ReAct action/observation、bounded loop、stop reason、private reasoning 与 evidence 边界。
- `docs/AGENT_LEARNING_LINKS.md`：本计划创建时补充 ReAct 原始论文和阶段 6 对 LangGraph cycle/recursion、tool calling、interrupt 边界的官方学习入口。
- `README.md`：只有当前阶段或阅读路径实际变化时更新。

## 14. 实施步骤

每一步只做一个小范围变更；先写目标 contract，再修改对应实现，不通过放宽断言隐藏边界问题。

1. **[已完成] 确认计划与冻结目标。** 用户已确认两层 graph、`max_steps=8`、不保存 reasoning、synchronous confirmation provider、Context/Memory 与 Recovery/Feedback empty hooks 和本阶段排除项；确认前未修改生产代码。后续路线图已把这些消费者调整到 Stage 9/10。
2. **[已完成] 建立 Executor models 与 contract tests。** 新增 status、stop reason、limits、decision、observation、result 和最小 internal state；冻结字段、不变量、dependency direction 和敏感字段禁区。
3. **[已完成] 建立 ports 与 empty/no-op/fake adapters。** 定义 model、Context、Memory、confirmation、Recovery 和 Feedback 接口；先证明它们不能授权、写业务事实或 replay。
4. **[已完成] 实现纯 Executor graph 与 routes。** 建立独立 compiled cycle、step counting、final/tool/continue/stop/error route；使用 fake model 和 fake Gateway 完成 bounded-loop 单测。
5. **[已完成] 接入真实 ToolRuntime / Gateway。** 固定 catalog、执行 ToolCall、生成 ToolObservation、处理 success/failure/denied/confirmation，并证明同 scope 多 Tool 与跨 scope 隔离。
6. **[已完成] 实现 synchronous WRITE confirmation。** 只为 WRITE 请求 provider，传递 exact `ConfirmedAction` 给 Gateway；覆盖 approve/reject/absent/expired/changed/reused confirmation。
7. **[已完成] 实现 OpenAI-compatible Executor model adapter。** 从 typed state 重建每步输入，解析 final answer 或单 ToolCall；保留 filtered catalog、关闭 parallel calls，安全处理 provider/JSON/contract failure。
8. **[已完成] 替换 outer Direct Executor 接缝。** outer graph node 调用 `ReactExecutor` 并映射 `ExecutorResult -> RuntimeResult`；删除已无调用方的单 Tool生产入口，保持 Runtime/GraphState frozen contract。
9. **[已完成] 补齐语义 observability 与 hooks。** 增加 executor action/observation/stop events，验证不重复 Gateway events、不泄露内容；接入 no-op/fake Recovery/Feedback consumers。
10. **[已完成] 运行跨 Domain compiled E2E。** 完成 Research、Travel、跨 Domain、多 WRITE confirmation、failure/limit/zero-write 场景；不依赖真实网络或 provider。
11. **[已完成] 运行分层与统一离线回归。** 依次运行 Executor models/contracts、Tool/Domain integration、Runtime/compiled graph、architecture/migration 和全量 unittest；记录数量、时长和失败分类。
12. **[已完成] 整理最终设计与 Stage 7 gate。** 已同步 ARCHITECTURE、PROGRESS_LOG、RUNTIME_CONCEPTS、总计划和 README；Executor gate 为 `go`，Stage 7 可以单独创建并确认 `PLANNER_PLAN.md`。

## 15. 完成标准

只有同时满足以下条件，阶段 6 才能标记完成：

- fake model 能完成 final-only、单 Tool、多 Tool、失败恢复和 limit stop。
- Research / Travel 多步 workflow 在同一 execution scope 中通过 compiled path。
- 每个 ToolCall 都经过 frozen Gateway；不存在第二执行入口或 Domain-specific loop。
- WRITE 逐 action confirmation、evidence、短 transaction、幂等与数据库零误写测试通过。
- Runtime/outer GraphState、Tool schema、Domain contracts 和 Stage 5 compatibility tests 未被静默改义。
- Context / Memory / Recovery / Feedback fake consumers 证明后续模块无需读取 Executor internals。
- stop reason、events、RuntimeResult 和 run lifecycle 在所有终止路径一致且不泄露敏感内容。
- 强制测试 deterministic/offline，全量 unittest 在当前工作树通过。
- 文档与代码一致，并明确真实 LLM/provider E2E 的运行情况和剩余风险。

若 confirmation 生命周期仍不清晰、loop 依赖 Domain internals、模型可绕过 filtered catalog/Gateway、状态跨 run 泄漏、step limit 不可靠或 Stage 5 frozen tests 需要通过放宽断言才能通过，结论必须为 `no-go`。

## 16. 变更控制

- 本计划已经确认；后续严格按实施步骤逐步施工，不跨步实现。
- 实施时每个行为调整必须对应本计划步骤、一个聚焦测试和一个明确 owner。
- 若 synchronous confirmation 不能满足真实调用方，先单独设计 interaction/persistence 边界；不得临时把 pending state 塞进 `RuntimeRequest.metadata`、GraphState、全局 dict 或 Domain 表。
- 若 LangGraph 子图不能在不扩大 state/依赖的前提下满足 loop，再以测试证据评估 LifeOps-owned Python loop；不能仅为框架形式增加复杂度。
- 新增公共字段、错误码、event 或 Protocol 必须有阶段 7-9 的真实/fake consumer；没有消费者时保持内部实现。
- 不读取或修改 `legacy_v0/`，除非用户明确批准历史对照范围。
