# LangGraph Orchestration 模块计划

## 1. 目标

本模块是 Runtime 重构阶段 4：LangGraph Orchestration 骨架。

前置边界：阶段 4 施工基于 `plans/modules/OBSERVABILITY_LOGGING_PLAN.md` 的文件日志方案。Graph path trace 应写入 `events.jsonl`。

阶段 4 的目标是把当前 `RuntimeService` 中内联的 request lifecycle 编排，收敛成一个明确的 LangGraph `StateGraph` 主流程：

```text
RuntimeRequest
-> graph state
-> intent node
-> policy node
-> policy route
-> stub execution / confirmation / denied finalize
-> RuntimeResult
```

LangGraph 在本阶段只负责 orchestration runtime：组织 nodes、routes、graph state 和 graph path trace。它不负责授权、不负责事实来源、不负责业务写入、不负责 planner / executor / tool 抽象。

本阶段完成后，`RuntimeService.handle(...)` 应仍然是外部入口，但内部调用 orchestration service / graph，而不是继续在 `RuntimeService` 里手写完整编排链路。

## 2. 当前 V0 参考

本阶段不读取 `legacy_v0/`。

原因：

- 当前阶段是在阶段 3 的 `app/runtime`、`app/intent`、`app/policy` 和 `app/observability` 边界上新增主编排骨架，不是迁移旧模块。
- `plans/RUNTIME_REFACTOR_PLAN.md` 已明确 LangGraph 当前状态是“尚未正式接入”，当前升级方向是 `StateGraph` 主编排和自研节点。
- V0 的旧 `Agent` 聚合了太多职责，本阶段不应为了复用旧行为而把 intent、policy、tool execution、context、memory、planner 混回一个大循环。

如果后续进入 Planner / Executor / Tool System 迁移，再按对应模块计划决定是否读取 V0 历史实现。

## 3. 当前范围

### 3.1 初版要做

- 新增 `app/orchestration/` 模块骨架。
- 定义 `GraphState`，承载本轮 request-local graph 状态。
- 用 LangGraph `StateGraph` 编排当前已存在的 `IntentService` 和 `PolicyService`。
- 定义初版 nodes：
  - `classify_intent`
  - `decide_policy`
  - `route_policy`
  - `stub_execute`
  - `requires_confirmation`
  - `deny`
  - `finalize`
- 定义 policy route：
  - `allow` -> `stub_execute` -> `finalize`
  - `requires_confirmation` -> `requires_confirmation` -> `finalize`
  - `deny` -> `deny` -> `finalize`
- 在 trace 中记录有业务语义的关键决策和最终 graph path，例如：
  - `intent.classified` / `intent.failed`
  - `policy.decided` / `policy.failed`
  - `orchestration.route.selected`
  - `runtime.run.completed` / `runtime.run.failed` 中的 `graph_path`
- 保留阶段 3 的 stub execution 语义：policy allow 仍只表示通过授权判断，不执行真实 tool 或业务写入。
- 保持 `RuntimeResult` 的用户可见行为与阶段 3 等价，避免本阶段改变产品语义。
- 添加聚焦测试，验证 graph path、policy route、stub execution 和原有 intent/policy 失败行为。

### 3.1.1 与阶段 2 / 阶段 3 的兼容性

本阶段必须保持以下兼容点：

- 继续复用现有 runtime id / run context，不新增 graph 专用持久化表；最终 graph path 写入 run completed / failed event。
- 继续由 `RuntimeService` 管理 SQLite transaction、run record 写入和 trace callback。
- 继续复用阶段 3 的 `RuntimeRequest`、`RuntimeResult`、`IntentDecision` 和 `PolicyDecision`。
- 继续保持 `IntentService` 只做语义判断，`PolicyService` 只做授权判断。
- 继续保持 policy `allow` 只是“允许进入后续执行阶段”的判断，不代表真实 tool 或 domain write 已发生。
- 继续保持 `runtime.orchestration.stubbed` 作为阶段 4 的执行占位语义，直到 Executor 阶段替换。

不兼容风险主要来自过早把 LangGraph 当成完整 agent framework 使用。因此本阶段不使用 LangChain agent、LangGraph store、LangGraph checkpoint 或 interrupt 来替代已有 runtime 边界。

### 3.2 初版不做

- 不实现 Planner。
- 不实现 Executor。
- 不实现 Tool System。
- 不实现 Context / Memory assembly。
- 不实现 domain write。
- 不引入 LangChain chain、agent 或 tool abstraction。
- 不把 LangGraph checkpoint 接成业务事实源。
- 不把 LangGraph checkpoint 当作授权来源。
- 不实现 human interrupt 的多轮确认状态机。
- 不实现 LangSmith / OpenTelemetry 集成。
- 不把 `RuntimeService` 的外部入口改成 LangGraph API。

### 3.3 后续版本保留

- Context / Memory / Recovery 阶段可把 graph state 扩展为 request-local assembly state。
- Planner / Executor 阶段可把 `stub_execute` 替换为 direct executor 或 planner route。
- Tool System 阶段把 selected Skill candidates 与 `PolicyDecision.allowed_effects` 求交后接入 executor；Skill 只提供业务候选，仍由自研 Policy 决定动作权限。
- Recovery 阶段可对照 LangGraph checkpoint、本项目 event log 和必要业务事实的边界。
- Human-in-the-loop 阶段可研究 LangGraph interrupt，但授权仍必须由 LifeOps Policy / Interaction State 产出。
- Eval / Inspector 阶段可直接使用最终 `graph_path` 和 Intent / Policy / route 语义事件断言 runtime path。
- DAG Scheduler 阶段保持独立，不让阶段 4 的主 graph 提前承担并行 DAG 或任务调度职责。

扩展原则是“可插拔，但不预铺大平台”：每个未来模块只通过明确 node 或 route 接入主 graph，不让 `GraphState` 变成大而全的应用状态容器。

## 4. Runtime 边界

### 4.1 输入

Orchestration 初版输入：

- `RuntimeRequest`
- `IntentService`
- `PolicyService`
- 可选 `append_trace(event_type, payload)` 回调

输入仍由 `RuntimeService.handle(...)` 创建和传入。`RuntimeService` 继续负责 runtime lifecycle、observability writer wiring 和最终 `RuntimeResult` 返回。

### 4.2 输出

Orchestration 初版输出：

- `RuntimeResult`
- graph path summary，例如 `["classify_intent", "decide_policy", "stub_execute", "finalize"]`
- compact trace payload，供 `RuntimeService` 写入 `events.jsonl`

`RuntimeResult` 仍不是业务事实来源。它只是当前 run 的可展示输出。

### 4.3 本模块不负责

- 不判断写入是否授权；授权只来自 `PolicyService.evaluate(...)` 返回的 `PolicyDecision`。
- 不调用业务 tool。
- 不写业务 repository。
- 不读写 Memory。
- 不组装 Context。
- 不创建或持久化 Domain 业务事实或未来 PlanRun / PlanStep；阶段 4 只保留扩展点。
- 不把 graph state、checkpoint、assistant 文本或 planner 输出升级为事实。
- 不吞掉 `IntentService` / `PolicyService` 的职责。

### 4.4 依赖

允许依赖：

- `app.runtime.models`
- `app.intent.service`
- `app.intent.models`
- `app.policy.service`
- `app.policy.models`
- `app.observability` 的 trace event 命名约定

不允许反向依赖：

- `intent` 不依赖 `orchestration`
- `policy` 不依赖 `orchestration`
- `observability` 不依赖 `orchestration`
- `domains` 不依赖 `orchestration`

## 5. 数据模型 / 存储

### 5.1 GraphState 应包含

`GraphState` 是 request-local 编排状态，建议初版使用 `TypedDict` 或小型 dataclass，并保持字段少而显式：

- `request`: 当前 `RuntimeRequest`
- `intent`: `IntentDecision | None`
- `policy`: `PolicyDecision | None`
- `route`: 当前 policy route，例如 `allow`、`requires_confirmation`、`deny`
- `result`: `RuntimeResult | None`
- `error_code`: graph 层错误码，可选
- `error_stage`: graph 层失败阶段，可选
- `graph_path`: 已经过的 node / route 名称列表
- `trace_summary`: 面向 `RuntimeResult.trace_summary` 的紧凑摘要

### 5.2 GraphState 不应包含

- 长期 conversation memory。
- semantic memory。
- Research / Travel 等 Domain 业务事实，以及未来 PlanRun / PlanStep 执行状态。
- tool result 事实。
- 原始 LLM request / response。
- 未压缩的用户隐私数据副本。
- 授权事实的替代来源。
- LangGraph checkpoint 恢复出来的 WRITE 授权。

`GraphState` 可以携带 `PolicyDecision`，但不能重新解释或扩大它。

### 5.3 存储

本阶段不新增 SQLite 表、不新增 repository、不新增 migration。

图执行证据后续写入 `events.jsonl`。LangGraph checkpoint / store 只学习和预留，不接入持久化。

## 6. 对外接口

建议初版暴露：

```text
app/orchestration/state.py
  GraphState
  GraphRoute

app/orchestration/graph.py
  build_runtime_graph(...)
  RuntimeOrchestrator

app/orchestration/routes.py
  route_after_policy(state) -> GraphRoute

app/orchestration/nodes/
  classify_intent(...)
  decide_policy(...)
  stub_execute(...)
  require_confirmation(...)
  deny(...)
  finalize(...)
```

`RuntimeService` 调用方式建议是：

```text
RuntimeService.handle(...)
-> insert run record / append runtime.run.started
-> RuntimeOrchestrator.invoke(request, append_trace=...)
-> finish run record
-> RuntimeResult
```

为了小步实施，第一版也可以先只公开：

```text
RuntimeOrchestrator.handle(request, append_trace=None) -> RuntimeResult
```

内部再逐步拆出 nodes / routes 文件，避免第一刀抽象过多。

## 7. 失败模式

### 7.1 Intent node 失败

行为：

- 返回 `RuntimeStatus.ERROR`
- `error_code = "runtime.intent_failed"`
- 不进入 policy node
- trace 记录 graph path 停在 `classify_intent`

需要保持阶段 3 测试语义：intent failure skips policy。

### 7.2 Policy node 失败

行为：

- 返回 `RuntimeStatus.ERROR`
- `error_code = "runtime.policy_failed"`
- 保留 intent summary
- 不进入 stub execution
- trace 记录 graph path 停在 `decide_policy`

### 7.3 Policy allow 误解为真实执行

风险：

- 用户或后续代码看到 `allow` 后误以为已写入。

约束：

- `allow` route 只能进入 `stub_execute`。
- `RuntimeResult.message` 必须继续说明 execution 尚未实现。
- `RuntimeResult.trace_summary` 保留 `runtime.orchestration.stubbed` 或明确的 graph stub 摘要。

### 7.4 requires_confirmation 被当成 interrupt

风险：

- 直接用 LangGraph interrupt 替代 LifeOps 的 policy / interaction state。

约束：

- 本阶段 `requires_confirmation` 是普通 route，不调用 LangGraph interrupt。
- 多轮确认状态机留给后续 Interaction State / Policy 增强。

### 7.5 checkpoint 被误当成事实源

风险：

- 从 checkpoint 恢复的 graph state 被误认为业务事实或授权。

约束：

- 本阶段不配置 checkpointer。
- 文档明确 checkpoint 只可用于 workflow continuity / debugging / fault tolerance 学习，不是 LifeOps 事实源。

### 7.6 trace 泄露过多

风险：

- graph state payload 直接写入 trace，暴露用户输入、LLM 原文或未来 tool args。

约束：

- trace payload 只写 intent summary、policy summary、route、status、error stage 和最终 graph path。
- 不写完整 graph state。

## 8. 测试和 Eval

### 8.1 聚焦单元测试

新增或更新：

- `tests/test_orchestration_graph.py`
- `tests/test_runtime_service.py`

覆盖：

- `write_request` + `allow` 走 `classify_intent -> decide_policy -> stub_execute -> finalize`。
- `clarification_needed` / `requires_confirmation` 走 confirmation route，不声称写入。
- `unsupported` / `deny` 走 deny route。
- intent node 抛错时 policy 不被调用。
- policy node 抛错时返回 `runtime.policy_failed`。
- graph path summary 稳定且可断言。

### 8.2 Runtime integration 测试

更新现有 runtime 测试，断言：

- `RuntimeService.handle(...)` 仍产出 run/session 关联信息；是否写入 `run_records` 取决于后续是否需要关系查询。
- `events.jsonl` 包含 Intent / Policy / route 语义事件，以及附带 graph path 的 run completed / failed event。
- 阶段 3 的外部返回语义不变：allow 仍是 stub execution。

### 8.3 Eval

本阶段不建立完整 Eval Harness。

但测试用例设计应为后续 eval case 留字段：

- input
- expected intent
- expected policy action
- expected graph path
- expected final status
- expected trace event types

后续 `plans/modules/EVAL_HARNESS_PLAN.md` 可直接复用这些样例。

## 9. 文档更新

本计划创建后，阶段 4 正式施工完成时应更新：

- `docs/PROGRESS_LOG.md`
  - 从“准备进入阶段 4”更新为“阶段 4 初版完成”。
  - 记录 `app/orchestration/`、graph path trace 和仍然 stub execution 的状态。
- `docs/ARCHITECTURE.md`
  - 增加 LangGraph Orchestration 章节。
  - 明确 LangGraph 只做编排，不是 policy / facts / tool executor。
- `docs/RUNTIME_CONCEPTS.md`
  - 增加或扩写 `LangGraph Orchestrator`。
  - 增加 `LangGraph vs LangChain` 在本项目中的分工。
  - 记录官方学习链接和本项目实现解释。
- `docs/ARCHITECTURE.md`
  - 如阶段 4 的实现改变架构边界，应更新当前架构快照。
  - 本仓库不再新增 decisions / ADR 文档；相关边界维护在当前架构与模块计划中。

本阶段不更新 `CHANGELOG.md`，除非用户明确要求。

本阶段学习链接应维护在 `docs/AGENT_LEARNING_LINKS.md`，不散落在模块计划中。阶段 4 施工完成后，应把稳定后的本项目解释同步沉淀到 `docs/RUNTIME_CONCEPTS.md` 的 `LangGraph Orchestrator` / `LangGraph vs LangChain` 章节。

## 10. 实施步骤

### Step 4.0 依赖和安装边界确认

- 状态：已完成（2026-07-10）。
- 检查项目依赖文件中是否已有 LangGraph。
- 若没有，单独做依赖切片：加入最小 LangGraph 依赖并运行 import smoke test。
- 不引入 LangChain agent / chain / tool 抽象。

验证：已加入 `langgraph>=1.2.9`，`langgraph` / `StateGraph` import smoke test 和 `uv lock --check` 均通过。

### Step 4.1 GraphState 和 route 类型

- 状态：已完成（2026-07-10）。
- 创建 `app/orchestration/`。
- 定义最小 `GraphState` / `GraphRoute`。
- 写纯函数测试，确认 graph path append 和 route 值稳定。

验证：`tests.test_orchestration_state` 通过；Intent / Policy / Runtime Service 相邻回归通过，当前仍未接入 nodes、`StateGraph` 或 `RuntimeService`。

### Step 4.2 节点函数先不接 LangGraph

- 状态：已完成（2026-07-10）。
- 把现有 `_handle_core(...)` 的 intent / policy / result 逻辑拆成 node 级纯函数或小函数。
- 先用普通函数测试保持行为等价。

验证：已新增普通 Python 节点函数和 policy route 纯函数；allow / requires confirmation / deny、intent 失败和 policy 失败均有聚焦测试，并已逐字段对照当前 `RuntimeService` 的 `RuntimeResult` 语义。当前节点尚未接入 LangGraph 或 `RuntimeService`。

### Step 4.3 接入 StateGraph

- 状态：已完成（2026-07-10）。
- 用 `StateGraph(GraphState)` 连接 nodes 和 conditional route。
- `build_runtime_graph(...)` 返回 compiled graph。
- `RuntimeOrchestrator.handle(...)` 调用 graph 并产出 `RuntimeResult`。

验证：compiled graph 已覆盖 allow / requires confirmation / deny 三条 policy route，以及 intent / policy 失败的提前结束路径；`RuntimeOrchestrator.invoke(...)` 可返回最终 `GraphState`，`handle(...)` 可返回等价的 `RuntimeResult`。当前尚未由 `RuntimeService` 调用，也尚未增加 `orchestration.*` trace events。

### Step 4.4 RuntimeService 调用 Orchestrator

- 状态：已完成（2026-07-10）。
- `RuntimeService` 继续负责 SQLite transaction 和 trace callback。
- `_handle_core(...)` 改为委托 `RuntimeOrchestrator`。
- 保持 `RuntimeService` 构造参数可注入 `IntentService` / `PolicyService`，方便现有失败测试。

验证：`RuntimeService` 已构建并调用注入相同 Intent / Policy service 的 `RuntimeOrchestrator`；SQLite transaction、run record 和用户可见 `RuntimeResult` 保持兼容。Step 4.5 已用真实执行边界事件取代临时事后 compatibility trace。

### Step 4.5 Graph path trace

- 状态：已完成（2026-07-10）。
- 增加 Intent / Policy / route 语义事件，并在 run 完成或失败时记录 graph path。
- 保持 payload 紧凑，不写完整 graph state。
- 更新 runtime service trace 测试。

实现结论：继续使用 compiled graph 的 `invoke(...)`。LifeOps 应用拥有统一 `TraceSink`；Intent / Policy node 在真实 service 返回后立即写语义事件，Policy route 确定后写 route event，RuntimeService 在 run 完成或失败时附带最终 graph path。TraceSink 通过 request-local `OrchestrationContext` 注入，不进入 `GraphState`。Graph 外关键阶段可直接写同一个 sink，不要求所有可观察阶段都成为 LangGraph node。

验证：测试证明 `intent.classified` / `policy.decided` 紧跟真实 service 调用，失败分别记录 `intent.failed` / `policy.failed`；allow / requires confirmation / deny route 和最终 graph path 可观察；原始用户输入和完整 `GraphState` 不进入 payload；机械化 graph/node started/completed event 已删除。

### Step 4.6 文档同步

- 状态：已完成（2026-07-10）。
- 更新 `docs/PROGRESS_LOG.md` 阶段状态。
- 更新 `docs/ARCHITECTURE.md` 的 orchestration 边界。
- 更新 `docs/RUNTIME_CONCEPTS.md` 的 LangGraph 学习章节；官方链接只维护在 `docs/AGENT_LEARNING_LINKS.md`。
- 必要时更新 `docs/ARCHITECTURE.md` 的当前架构快照。

验证：README、总计划、推进日志、当前架构、概念手册和学习链接已同步；阶段 4 标记为完成，下一阶段指向阶段 5 Skill System / Tool System 与 Domains。

## 11. LangGraph / LangChain 学习边界

### 11.1 本阶段使用 LangGraph

本阶段只使用 LangGraph 的低层编排能力：

- `StateGraph`
- nodes
- edges
- conditional edges / routes
- graph state
- compiled graph invocation

这些概念直接映射到 LifeOps runtime：

```text
node = 一个 runtime 阶段
edge = 阶段顺序
conditional edge = policy / intent route
graph state = request-local runtime state
graph path = inspector / eval 可断言的执行路径
```

### 11.2 本阶段只学习但不实现 persistence / checkpoint / interrupt

学习：

- checkpointer 是 thread-scoped graph state snapshot。
- store 是 application-defined long-term data。
- interrupt 可用于 human-in-the-loop。

不实现：

- 不配置 checkpointer。
- 不使用 LangGraph store 保存 LifeOps 业务事实。
- 不用 interrupt 代替 `requires_confirmation` route。
- 不从 checkpoint 恢复 WRITE 授权。

LifeOps 的长期事实来源仍是 SQLite repository 和成功执行证据。LifeOps 的授权来源仍是 `PolicyService`。

### 11.3 本阶段不引入 LangChain abstraction

LangChain 在后续阶段才正式进入：

- Planner 阶段：models / prompts / structured output 可用于稳定生成 `PlanRun`。
- Executor 阶段：models / tool calling / structured output 可用于结构化执行反馈。
- Tool System 阶段：LangChain tools 可作为对照或 adapter，但 LifeOps 自研 tool safety 和 policy 仍是主边界。

本阶段只记录学习链接和边界，不使用 chain、agent、tool abstraction。

## 12. 阶段 4 的审查问题

施工前和收口时都要回答：

- `RuntimeService` 是否仍然是唯一外部入口？
- `PolicyService` 是否仍然是授权事实源？
- `GraphState` 是否只保存 request-local 编排状态？
- `allow` route 是否仍然没有真实写入？
- trace 是否能解释 graph path，但没有泄露完整用户输入或未来 tool args？
- LangGraph 是否只接管编排，没有吞掉 Intent / Policy / Executor / Tool / Storage 边界？

## 13. 计划复核结论

### 13.1 与之前步骤兼容

结论：兼容。

- 阶段 2 已完成 SQLite / observability 基础设施，但日志边界已改为文件优先。本计划不新增不必要 schema，graph event 后续进入 `events.jsonl`。
- 阶段 3 已完成 Runtime Core / Intent / Policy，本计划保留这些 service 的职责，只把内联流程搬进 graph 编排。
- 现有 `RuntimeService` 仍是外部入口，符合当前 CLI / bootstrap 边界。
- stub execution 继续保留，不会提前改变用户可见行为或写入语义。

### 13.2 对未来扩展性足够

结论：足够，但必须坚持“小 graph state”。

本计划给后续 Context、Memory、Planner、Executor、Tool System、Recovery、Inspector、Eval 都保留了接入点：未来通过新增 node / route 替换 `stub_execute` 或扩展 graph path，而不是重写 `RuntimeService`。

关键约束是 `GraphState` 不能膨胀成长期业务状态容器。长期事实、授权和执行证据仍放在 LifeOps 自己的 repository / policy / trace 边界里。

### 13.3 对学习目标足够

结论：足够覆盖阶段 4 的主要学习目标。

本阶段学习重点是把已有 runtime 概念映射到 LangGraph primitive：

- `Runtime stage` -> node
- `执行顺序` -> edge
- `PolicyAction` -> conditional route
- `request-local state` -> graph state
- `trace / eval path` -> graph path

同时计划明确把 checkpoint、interrupt、LangChain tools、structured output 放在“先理解、后实现”的位置，避免学习路线一下子膨胀成框架大迁移。
