# Plan-and-Execute Planner 模块计划

文档状态：已完成；步骤 1-16 均已实施并验证，Stage 7 gate 为 `go`。后续 Context / Memory、Recovery / Persistence、MCP、并行 DAG 或异步 human-in-the-loop 仍按各自阶段单独实施。

## 1. 目标

本模块在已经完成的 `ReactExecutor` 之上建立通用 Plan-and-Execute 控制层：简单请求继续直接进入 ReAct；复杂、多步骤或存在显式依赖的请求先生成完整计划并展示给用户，用户确认后再由 Controller 逐个把当前 `PlanStep` 的目标交给同一个通用 `ReactExecutor`。

本阶段的成功标准不是“让 Planner 也会选 Tool”，而是建立以下稳定分工：

```text
Intent / Policy / Skill / AllowedToolSet
        ↓
PlanningRouter
    ├─ direct     → ReactExecutor
    ├─ need_user  → clarification
    └─ plan       → Planner → preview → PlanCommand
                                      ↓ confirmed
                              PlanController
                                      ↓ one step goal
                              ReactExecutor
                                      ↓ structured result
                              deterministic next step
                                      ↓
                              bounded replan / PlanFinalizer
```

具体目标：

- 自动区分 Direct ReAct、Plan-and-Execute 和需要澄清的请求；
- 生成完整、可验证、有显式依赖但不绑定 Tool 名称的计划；
- 坚持 preview-first：计划必须先展示并确认，确认计划不等于授权 WRITE；
- 最小持久化 `PlanRun` / revision / `PlanStep` 生命周期，使计划预览可以跨请求、跨进程读取和确认；
- 每次只向 ReAct 提供一个 Step 的目标、预期结果和所依赖的安全结果；
- 正常成功路径由 Controller 确定性推进，不在每一步后重新调用 Planner；
- 只有结构化目标未完成或明确可重新规划的失败才允许一次 bounded replan；
- 所有 Step 完成后由只读 `PlanFinalizer` 生成整份计划的最终回答；
- 为阶段 8-11 保留窄接口，但不提前实现 Context / Memory、异步恢复、MCP、Eval Harness 或 DAG Scheduler。

## 2. V0 参考

只有在实施对应机制时才局部读取 `legacy_v0/`。可参考的历史经验是：

- Main Orchestrator 负责路由，Planner 只规划，Executor 执行当前步骤；
- 计划先预览再确认；
- Planner 输出不能携带 `tool_name`、Tool arguments 或 `write_authorized`；
- 简单单步请求不能因为出现“计划”相关词语而被误路由；
- 真实模型可能返回 fenced JSON、说明文字或缺少字段，adapter 必须 fail-closed；
- 计划状态应先独立建模，再接入主编排，不能先把新分支硬塞进聚合入口。

不继续沿用：

- V0 `Agent.chat()` 的聚合式职责；
- V0 Domain、Task、Recovery 或旧 planning 文件结构；
- 只存在于 Agent 实例内、无法跨请求确认的隐藏内存状态；
- 关键词驱动的宽泛 planning route；
- Planner 直接选择 Tool、构造 arguments 或暗示写入授权。

## 3. 当前范围

### 3.1 本阶段实现

- 新增 `app/planner/`，包含 models、errors、ports、adapters、repository、service/controller、routes 和 graph；
- `PlanningRouter` 返回 `direct`、`plan` 或 `need_user`；
- `Planner` 生成初始 plan revision，或在信息不足时返回结构化澄清；
- `PlanRun` / `PlanStep` 最小 SQLite 持久化；
- `ConfirmPlan`、`CancelPlan`、`ModifyPlan` 三类结构化 `PlanCommand`；
- preview-first 与 revision 校验；
- 一个 PlanRun 共享一个 request-local `ToolRuntime` / execution scope；
- 每个 PlanStep 使用独立的 Executor state，并复用现有 `ReactExecutor`；
- dependency-ready 的稳定串行调度；
- `goal_not_achieved` Executor 结构化终止结果；
- 最多一次自动 replan，revision 重新确认后才能继续；
- 独立只读 `PlanFinalizer` 与确定性 fallback；
- Planner 相关语义 events 和 provider interaction 日志；
- Research 主业务 E2E 与一个不扩展 Travel 的最小跨 Domain 离线验证。

### 3.2 本阶段不做

- 不让 Planner 输出 Tool 名、ToolCall、arguments、provider schema 或 WRITE authorization；
- 不为 Research / Travel 建立独立 Planner 或 Executor；
- 不实现并行 Step、条件分支、动态 worker、DAG Scheduler 或并行 ToolCalls；
- 不实现 LangGraph checkpointer、interrupt resume、background execution 或跨请求 Executor resume；
- 不持久化完整 Executor observations、Tool output、prompt、模型 transcript、Domain candidate/draft 或 `GraphState`；
- 不在进程重启后自动 replay、自动恢复或自动补偿正在运行的 Step；
- 不实现正式 Context / Memory assembly；Stage 9 的 provider 继续使用 empty/fake；
- 不实现阶段 10 Recovery / ExecutionFeedback 持久化；
- 不接真实 API、MCP、Calendar 或外部 provider；这些在 Planner gate 关闭后单独计划；
- 不修改或扩展 Travel Domain 业务能力；
- 不实现 Inspector UI、正式 Eval Harness、streaming 或多用户调度。

## 4. Runtime 边界

### 4.1 事实源与授权源

- `PolicyDecision` 仍是允许 effect 的唯一授权事实源；
- `AllowedToolSet` 仍由 selected Skill candidates、Policy allowed effects 和 Registry 求交得到；
- Planner 读取 Tool catalog 只为判断计划是否可执行，不能扩大 `AllowedToolSet`；
- `PlanRun` / `PlanStep` 是 Runtime 执行策略，不是 Research / Travel 业务事实；
- 计划确认只允许开始执行当前 revision，不授权任何 WRITE；
- WRITE 仍必须经过当前 `ToolCall` 对应的同步 `ActionConfirmationProvider`、Gateway、Guardrails 和 `ExecutionEvidence`；
- Planner 文本、PlanFinalizer 文本、checkpoint、event 或 SQLite plan row 都不能证明业务副作用成功。

### 4.2 PlanningRouter

PlanningRouter 位于 Policy allow、Skill preparation 和 `AllowedToolSet` 解析之后。输入至少包含：

- 原始用户目标；
- `IntentDecision` 的安全摘要；
- selected Skill prompt contributions；
- 最终 filtered Tool catalog；
- `PlanningLimits`。

输出是互斥结构：

```python
DirectRoute(reason_code)
PlanRoute(reason_code)
NeedUserRoute(question)
```

边界：

- `IntentType.PLAN_REQUEST` 是强 planning 信号，但不能靠单个关键词误触发；
- 明显单目标请求应保持 Direct ReAct；
- 多目标、存在先后依赖或需要根据中间结果推进的请求进入 Planner；
- 信息不足时返回 `need_user`；
- Router 不生成 Step、不执行 Tool、不读取 repository、不授权 WRITE；
- production adapter 使用真实结构化模型输出；测试使用 deterministic fake；
- Router failure fail-closed，不静默降级成自动执行。

### 4.3 Planner

Planner 输入：

- 原始 `PlanRun.goal`；
- selected Skill contributions；
- filtered Tool catalog；
- 可信 `DomainPlanningSnapshot` envelopes；
- 当前 limits；
- replan 时的已完成 Step 安全摘要、失败 Step 结构化结果和用户已确认约束。

Planner 输出不包含 Tool 选择。模型可读取 catalog 描述以确认能力覆盖，但 schema 明确拒绝以下字段：

- `tool_name` / `candidate_tool_names`；
- `arguments`；
- `write_authorized` / `confirmed`；
- provider / MCP schema；
- private reasoning / chain-of-thought。

初始计划必须完整生成后再预览。每个 Step 至少包含：

```python
step_id
position
objective
expected_outcome
dependency_step_ids
```

### 4.4 可信 planning scope

- Planner 只接受 UI/session context、结构化调用方或成功前置 Step 提供的可信 scope reference；
- Research scope 是 Topic ID，Travel scope 是 Trip ID；
- scope 已知时只通过 `DomainPlanningReadModel.get_planning_snapshot(scope_id)` 读取；
- Planner 不直接查询 Domain repository；
- 没有 scope 时计划查询或创建 scope 的 Step；
- 名称匹配多个 scope 时返回澄清，不静默选择；
- 模型不得从自然语言编造稳定 ID；
- Stage 9 Context / Memory 未来可以提供候选 context，但不能绕过相同 read-model contract。

### 4.5 PlanController 与 ReAct

- 一次已确认的 PlanRun 创建一个 `PlanExecutionContext`；
- 一个 `PlanExecutionContext` 持有一个共享 `ToolRuntime` / execution scope；
- 每个 Step 调用一次新的 bounded `ReactExecutor`，不复用前一 Step 的 Executor state 或 decision counter；
- ReAct 输入只包含原始 plan goal、当前 Step objective、expected outcome、当前 Step 明确依赖的安全结果、prompt contributions 和当前 `AllowedToolSet`；
- 不向 ReAct 暴露后续 Step，防止其越界执行整份计划；
- dependency handoff 可以包含 post-Guardrail `ToolObservation` 中的 request-local ID；
- 完整 dependency handoff 只存在于 `PlanExecutionContext`，不写 SQLite；
- 正常完成后由 Controller 按 dependency-ready + position 确定性选择下一 Step；
- Planner 不在每个成功 Step 后重新运行。

### 4.6 Step 目标结果

当前 `ExecutorResult.FINAL_ANSWER` 只表示模型生成了最终消息，不能区分“目标完成”和“诚实说明未完成”。Stage 7 增加：

```python
ExecutorStopReason.GOAL_NOT_ACHIEVED
```

约束：

- `FINAL_ANSWER + COMPLETED` 表示当前 Step 目标已完成；
- `GOAL_NOT_ACHIEVED + STOPPED` 表示工具/模型已经尝试，但结果不足以达到目标；
- 不增加每 Step 一次的额外 LLM judge；
- WRITE Step 只有对应 evidence 时才能被标记完成；
- Controller 不解析 `final_message` 文本来猜测成功；
- model failure、invalid action、safety deny 与 confirmation stop 保持现有结构化语义。

### 4.7 Replan

- 普通 Tool failure 先留在当前 ReAct loop 内处理；
- `goal_not_achieved` 或仍有总预算的单 Step limit 可以触发 replan；
- safety deny、总预算耗尽、confirmation 未获得、provider/model/internal failure 不静默 replan；
- 每个 PlanRun 最多自动 replan 一次；
- replan 保留已完成 Step 的结果与 evidence，只替换未完成部分；
- replan 生成新的 revision，旧 revision 保留用于审计；
- 新 revision 必须重新 preview 并由用户确认；
- revision 确认仍不授权 WRITE；
- revision 再次失败后停止，由用户决定是否创建新的 PlanRun。

### 4.8 PlanFinalizer

所有 Step 完成后调用只读 PlanFinalizer：

- 输入原始 goal、当前 revision、各 Step 的 safe result summary、结构化失败信息和 evidence references；
- 不读取完整 Tool output、prompt 或模型 transcript；
- 不调用 Tool、不改计划、不授权 WRITE；
- 没有 evidence 时不能声称业务写入成功；
- provider interaction 记录到当前 session `llm.jsonl`；
- Finalizer failure 不把已经完成的 PlanRun 改成失败，返回确定性的 Step 摘要 fallback。

### 4.9 LangGraph 边界

outer graph 保留 request lifecycle、Intent、Policy、Skill 和 execution-mode route。Planner 执行使用独立的小型 compiled graph 或等价显式 Controller graph：

```text
load_confirmed_plan
→ select_ready_step
→ execute_current_step
→ record_step_result
→ complete / select_next / create_replan / stop
→ finalize_plan
```

要求：

- Planner graph state 只保存当前控制所需的小型 request-local 字段；
- `PlanRun` / `PlanStep` 生命周期事实从 repository 读取和写入，不复制完整对象到 outer `GraphState`；
- `TraceSink`、LLM log、repository、ToolRuntime 和 Executor 通过 context/constructor 注入；
- 不启用 checkpointer；
- 如果 LangGraph 子图需要膨胀 state 或复制持久化事实，优先保持 LifeOps-owned Controller 并用测试证明路由，而不是为了框架形式扩大边界。

## 5. 数据模型 / 存储

### 5.1 `PlanningLimits`

默认值：

```python
max_plan_steps = 6
max_replans = 1
max_executor_steps_per_plan_step = 6
max_total_executor_steps = 24
```

规则：

- limits 由 composition/config 提供；
- 用户输入、Skill、Planner、replan 都不能提高限制；
- revision 不重置总 Executor decision budget；
- Controller 为每个 Step 传入 `min(per_step_limit, remaining_total_budget)`；
- 达到整个 PlanRun 总预算后立即停止，不再 replan；
- 测试可注入更小限制。

### 5.2 `PlanRun`

建议字段：

```python
plan_id
session_id
goal
status
current_revision
replan_count
executor_steps_used
created_at
updated_at
confirmed_at
completed_at
last_error_code
```

最小状态：

```text
awaiting_confirmation
running
awaiting_replan_confirmation
completed
stopped
failed
cancelled
```

### 5.3 `PlanStep`

建议字段：

```python
plan_id
revision
step_id
position
objective
expected_outcome
dependency_step_ids
status
stop_reason
safe_result_summary
error_code
evidence_refs
executor_steps_used
started_at
completed_at
```

最小状态：

```text
pending
running
completed
goal_not_achieved
stopped
failed
superseded
cancelled
```

数据不变量：

- `(plan_id, revision, step_id)` 唯一；
- position 在一个 revision 内唯一且稳定；
- dependency 只能引用同 revision 的 Step；
- 依赖必须存在、不能自引用、不能成环；
- 当前 revision 只能有一个 running Step；
- Step 完成前所有依赖都必须 completed；
- completed Step 必须有 safe summary；WRITE success 必须有 evidence reference；
- 旧 revision 不可被原地改写；
- Planner 输出不是 Domain fact，不能创建 Research / Travel 记录。

### 5.4 SQLite

当前 canonical schema 是 V1；Stage 7 的真实 schema 变化从 V2 追加，不重写 V1。

最小表：

- `plan_runs`；
- `plan_steps`，包含 revision 字段并保留旧 revision rows。

不新增通用 blob/transcript 表。不把完整 plan model JSON 作为唯一事实源；关键字段保持可查询。依赖和 evidence reference 可以使用小型 canonical JSON 列，但必须有严格 schema 和稳定排序。

repository 负责：

- 创建初始 awaiting-confirmation plan；
- 按 session + plan ID 读取当前 revision；
- revision-aware confirm / cancel / modify transition；
- claim 一个 ready Step 为 running；
- 原子记录 Step 结果与累计 budget；
- 创建 replan revision；
- 完成、停止或失败 PlanRun；
- 重复 command 的幂等读取；
- 拒绝旧 revision、非法状态、跨 session command 和重复执行 claim。

进程重启后：

- awaiting-confirmation plan 可以继续确认、修改或取消；
- completed/stopped/failed/cancelled plan 可以读取；
- running plan 不自动恢复或 replay；再次操作时返回明确的 `plan_execution_interrupted` / stopped 结果，并允许用户取消或创建新计划；
- 不恢复 request-local ToolRuntime、Executor observations 或 Domain temporary IDs。

### 5.5 `PlanExecutionContext`

仅 request-local：

```python
plan_id
revision
tool_runtime
allowed_tools
prompt_contributions
dependency_results_by_step
total_executor_steps_used
```

不进入 SQLite、outer `GraphState`、event payload 或 LLM log。

## 6. 对外接口

### 6.1 Ports

建议保持窄 Protocol：

```python
class PlanningRouteClient(Protocol):
    def decide(self, input: PlanningRouteInput) -> PlanningRouteDecision: ...

class PlannerModelClient(Protocol):
    def create_plan(self, input: PlannerInput) -> PlanDraftResult: ...
    def replan(self, input: ReplanInput) -> PlanDraftResult: ...

class PlanFinalizerClient(Protocol):
    def finalize(self, input: PlanFinalizerInput) -> str: ...

class PlanningSnapshotProvider(Protocol):
    def load(self, scope_refs: tuple[PlanningScopeRef, ...]) -> tuple[PlanningSnapshotEnvelope, ...]: ...

class PlanRepository(Protocol):
    ...
```

production 可以由一个 OpenAI-compatible adapter 实现三个模型 client，但公共 Protocol 不合并，避免 Router、Planner、Finalizer 权限和输入边界混淆。

### 6.2 Service / Controller

```python
PlanningService.route(...)
PlanningService.create_preview(...)
PlanningService.modify_preview(...)
PlanController.confirm_and_execute(...)
PlanController.cancel(...)
PlanController.get_plan(...)
```

`ReactExecutor.execute(...)` 需要增加一个真实 Planner consumer 使用的窄 Step input，或新增兼容入口；不能把 Planner 字段塞进 `RuntimeRequest.user_input` 或 metadata。该入口至少表达：

- plan / step identity；
- original plan goal；
- current objective / expected outcome；
- dependency results；
- per-step execution limit。

现有 Direct ReAct 入口和行为必须保持兼容。

### 6.3 `PlanCommand`

```python
ConfirmPlan(plan_id, revision)
CancelPlan(plan_id, revision)
ModifyPlan(plan_id, revision, feedback)
```

规则：

- command 必须绑定 session、plan ID 和当前 revision；
- CLI/UI 可把上下文中的“确认/取消/修改”转换为结构化 command；
- Runtime 内部不靠自由文本猜测要操作哪个 plan；
- `ConfirmPlan` 成功后立即开始执行；
- 重复 confirm 不启动第二次执行；
- `ModifyPlan` 创建新 revision，旧确认失效；
- 用户主动修改不消耗自动 replan 次数，但每次仍受 plan-step limit 并需重新确认；
- Stage 7 不支持运行中的异步 cancel。

## 7. 失败模式

### 7.1 路由与模型

- Router 把简单请求错误送入 Planner；
- Router 把依赖明确的复杂请求错误送入 Direct ReAct；
- Router / Planner / Finalizer provider timeout、rate limit 或 invalid response；
- Planner 输出超过 Step limit；
- Planner 输出空 objective / expected outcome、重复 ID、未知依赖或 cycle；
- Planner 输出 Tool 名、arguments、authorization 或 private reasoning 字段；
- replan 修改已完成 Step 或丢失已成功 evidence；
- Finalizer 无 evidence 却声称 WRITE 成功。

### 7.2 生命周期与存储

- 旧 revision 被确认；
- 跨 session 操作 plan；
- 重复确认启动两次 Controller；
- 非法状态转换；
- 多个 Step 同时 claim 为 running；
- revision 生成后旧 pending Step 仍被执行；
- SQLite transaction 失败导致 Step status 与 budget 不一致；
- 进程重启后错误地恢复 request-local ID；
- 把 PlanRun 当作 Domain fact 或 Task。

### 7.3 执行

- ReAct 执行了后续 Step 的目标；
- dependency output 未注入，导致 request-local ID 丢失；
- 未声明依赖的 Step 读取其他 Step output；
- 新 Step 创建了新的 ToolRuntime，导致 draft/candidate ID 失效；
- `goal_not_achieved` 被当作 completed；
- safety deny 或总预算耗尽仍触发 replan；
- replan revision 未确认就继续；
- WRITE 缺少当前 action confirmation 或 evidence；
- synchronous confirmation 未获得后仍继续后续 Step；
- Planner/Controller exception 泄漏 provider 或数据库内部文本。

### 7.4 错误收敛

公共错误使用稳定 code，例如：

```text
planning_route_failed
planning_clarification_required
plan_generation_failed
plan_contract_invalid
plan_not_found
plan_revision_stale
plan_command_not_allowed
plan_dependency_invalid
plan_budget_exhausted
plan_step_goal_not_achieved
plan_replan_exhausted
plan_execution_interrupted
plan_finalization_failed
```

Runtime result、event 和正常日志不包含 provider exception、SQL、prompt、完整 Tool arguments/output 或用户敏感正文。

## 8. 测试和 Eval

### 8.1 模型与纯状态

- PlanRun / PlanStep / PlanningLimits 构造与非法值；
- 状态转换、revision、旧 revision 拒绝；
- dependency existence、自引用、cycle 和稳定 ready ordering；
- Step、replan、总 Executor budget；
- Planner forbidden fields；
- `goal_not_achieved` 与 Executor status / stop reason 映射；
- Finalizer fallback。

### 8.2 Repository

- schema V2 fresh migration 与 V1 → V2；
- plan/step round trip；
- awaiting confirmation 跨连接读取；
- confirm / cancel / modify；
- duplicate command idempotency；
- stale revision、cross-session、illegal transition；
- atomic step result + budget update；
- replan revision 保留 completed result/evidence；
- interrupted running plan 不自动恢复。

### 8.3 Router / Planner / Finalizer adapters

- deterministic fake 的 direct / plan / need_user；
- 明显单步请求 direct guard；
- 多目标/依赖请求 plan；
- invalid JSON、fenced JSON、unknown fields、duplicate IDs、oversized plan；
- model/provider failure fail-closed；
- `llm.jsonl` 分别记录 route、create-plan、replan、finalize interaction；
- 不记录 private reasoning；
- Finalizer 无 evidence 不声称 WRITE success。

### 8.4 Controller / Executor integration

- 每次只传当前 Step；
- 成功后确定性选择下一个 ready Step；
- 多 ready Step 按 position 串行；
- 同 PlanRun 共享 ToolRuntime，每 Step 独立 Executor state；
- dependency safe observations 传递 request-local IDs；
- 未声明依赖不可见；
- `goal_not_achieved` 触发一次 replan preview；
- revision 未确认不执行；
- 第二次失败停止；
- per-step 和 total budget；
- synchronous WRITE confirmation、拒绝时停止、成功 evidence；
- safety deny/model failure/internal failure 不错误 replan；
- Finalizer success 与 deterministic fallback。

### 8.5 Outer graph / Runtime

- Direct ReAct 现有路径行为不变；
- plan route 返回 preview，不执行 Tool；
- need_user 不创建 PlanRun；
- structured PlanCommand 进入 confirm/cancel/modify 路径；
- outer `GraphState` 不保存 PlanRun、ToolRuntime 或完整 Step observations；
- Runtime lifecycle record 正确闭合；
- semantic events 顺序和 payload 安全；
- file-backed log handler 正常释放。

### 8.6 Stage 7 E2E

主业务场景使用 Research deterministic fixture：

```text
复杂研究目标
→ PlanningRouter.plan
→ 完整 plan preview
→ ConfirmPlan
→ fetch / parse / rank / draft Steps
→ 同步确认所需 Source / Brief WRITE
→ PlanFinalizer
→ Domain facts 与 evidence 一致
```

至少覆盖：

- Research READ-only happy path；
- Research request-local document/item/draft ID 跨 Step handoff；
- Research WRITE confirmation 与无确认零写；
- `goal_not_achieved` → replan → reconfirm → complete；
- replan exhausted；
- direct simple Research request 不进入 Planner；
- 一个不扩展 Travel 的 Research READ → Travel READ 最小跨 Domain 离线计划；
- budget exhausted、safety deny、stale revision；
- restart 后 plan 可读取但 running Step 不自动恢复。

真实 LLM/provider 验证至少包含：

- 一个 direct route；
- 一个 plan route 与合法 plan generation；
- 一个 need_user；
- 一个完整 Research happy path。

真实调用单独报告，不作为 deterministic/offline merge gate；外部 provider 不可用不能掩盖本地 contract failure。

### 8.7 分层验证

1. Planner models / lifecycle / dependency；
2. repository / migration；
3. adapters / schema contract；
4. Controller / Executor integration；
5. outer graph / Runtime；
6. Research 主 E2E + 最小 cross-domain；
7. architecture / import / public-contract tests；
8. 受影响范围稳定后运行统一离线回归。

## 9. 文档更新

计划确认时：

- 创建本文；
- 在 `docs/AGENT_LEARNING_LINKS.md` 增加 Stage 7 当前学习链接；
- 在 `docs/RUNTIME_CONCEPTS.md` 增加明确标注“计划中、尚未实现”的 Planner 学习章节；
- 不修改 `docs/ARCHITECTURE.md`，因为 Planner 尚未成为当前实现事实；
- 不修改 `docs/PROGRESS_LOG.md` 的完成事实，只在实施步骤真正完成后逐步记录。

用户确认的学习沉淀范围只包含：

- Plan-and-Execute 与 ReAct 的职责差异；
- `PlanningRouter → Planner → Controller → ReactExecutor → PlanFinalizer`；
- `PlanRun` / revision / `PlanStep` 生命周期；
- LangGraph 串行依赖编排；
- bounded replan；
- 为什么 Stage 7 不做 checkpoint、异步恢复、并行和 DAG。

以下内容虽然属于实现和测试规则，但不新增为本阶段学习章节：

- SQLite 状态转换、幂等确认和 optimistic version check；
- structured output 与 schema validation；
- preview-first、计划确认与 WRITE confirmation 的区别；
- Planner / Executor events、LLM logs 和 evidence。

模块完成后：

- 更新 `docs/PROGRESS_LOG.md`，只记录已经完成和验证的步骤；
- 更新 `docs/ARCHITECTURE.md`，把 Planner 写成当前事实；
- 更新 `docs/RUNTIME_CONCEPTS.md`，删除“尚未实现”标记并改成代码真实入口；
- 根据实际实现同步 `README.md` 与 `plans/RUNTIME_REFACTOR_PLAN.md` 的 Stage 7 gate；
- 不更新 `CHANGELOG.md`，除非用户明确要求。

## 10. 实施步骤

### 步骤 1 冻结基线与契约矩阵（2026-07-14）

施工起点：

- Git 分支：`russell/refactor-v2-begin`；基线提交：`eb89907`。
- 工作树在步骤 1 开始前不是 clean：`README.md`、`docs/AGENT_LEARNING_LINKS.md`、`docs/PROGRESS_LOG.md`、`docs/RUNTIME_CONCEPTS.md`、`plans/RUNTIME_REFACTOR_PLAN.md` 已修改，本文为未跟踪文件；这些均作为已有 Stage 7 计划/文档工作保留。
- Python：`3.13.14`；uv：`0.11.21`。
- canonical SQLite schema 为 V1，唯一 migration 是 `initial_canonical_schema`；步骤 4 只能追加 V2，不能重写 V1。
- Stage 6 冻结的 Tool catalog 共 `22` 个：Research `9` 个，Travel `13` 个。名称、effect、risk、Skill binding 与 input/output schema hash 继续由 `tests/test_stage5_contract_tool_surface.py` 冻结；Planner 只能读取过滤后的 catalog 描述，不能选择 Tool 或扩大授权。
- 公共回归基线分为 Executor、Runtime/Orchestration、Domain/Tool 三组；步骤 1 的验证命令和结果记录在本节末尾，后续步骤优先运行新 Planner 聚焦测试，再运行受影响的公共组。

现有公共测试入口：

| 边界 | 冻结测试 |
| --- | --- |
| Executor models / ports / graph / Runtime mapping | `tests.test_executor_contracts`、`tests.test_executor_models`、`tests.test_executor_ports`、`tests.test_executor_graph`、`tests.test_executor_runtime_integration` |
| Runtime / Orchestration public surface | `tests.test_stage5_contract_runtime`、`tests.test_orchestration_state`、`tests.test_orchestration_nodes`、`tests.test_orchestration_graph`、`tests.test_runtime_service` |
| Domain / Tool public surface | `tests.test_stage5_contract_domain`、`tests.test_stage5_contract_tool_surface`、`tests.test_tool_models`、`tests.test_tool_registry`、`tests.test_tool_gateway` |

Stage 7 公共契约矩阵：

| 公共契约 / 字段 | Owner | 当前或计划内真实 consumer | 首个验证步骤 / 测试 |
| --- | --- | --- | --- |
| `PlanningLimits(max_plan_steps, max_replans, max_executor_steps_per_plan_step, max_total_executor_steps)` | composition / planning models | Planner validator、Controller | 步骤 2-3 / `test_planning_models`、`test_planning_lifecycle` |
| `PlanningRouteDecision(route, clarification)`，route 仅 `direct/plan/need_user` | PlanningRouter adapter | outer graph（步骤 12）；步骤 5 fake/adapter consumer | 步骤 2、5 / `test_planning_models`、`test_planning_router` |
| `PlanRun(plan_id, session_id, goal, status, current_revision, replan_count, executor_steps_used, timestamps, last_error_code)` | PlanRepository | PlanCommand service、Controller、preview/result mapper | 步骤 2-4 / model、lifecycle、repository tests |
| `PlanStep(plan_id, revision, step_id, position, objective, expected_outcome, dependency_step_ids, status, result/error/evidence/budget/timestamps)` | PlanRepository | scheduler、Controller、Finalizer | 步骤 2-4 / model、scheduler、repository tests |
| `PlanCommand(command_id, plan_id, session_id, revision, action, replacement_goal)` | planning service contract | PlanCommand service（步骤 7）与 repository transition | 步骤 2、4 / model、repository tests |
| `PlannerInput` / `PlanDraftResult` / `ReplanInput` | Planner port | Planner adapter（步骤 6）与 preview service | 步骤 2、6 / model、adapter tests |
| dependency existence、自引用、cycle、position、stable ready ordering | planning lifecycle / scheduler | Planner validator、Controller、repository claim | 步骤 2-4 / model、scheduler、repository tests |
| revision-aware confirm/cancel/modify、atomic Step result + budget、interrupted semantics | PlanRepository | PlanCommand service、Controller | 步骤 4 / `test_plan_repository` |
| `ExecutorStopReason.GOAL_NOT_ACHIEVED` | Executor result contract | Controller replan eligibility（步骤 9-10） | 步骤 2 / Executor model、route、Runtime mapping regression |
| `PlanningRouterClient.route(PlanningRouterInput, llm_log=...)` | PlanningRouter port | outer route node（步骤 12）；步骤 5 adapter/fake tests | 步骤 5 / `test_planning_router` |
| request-local route provider interaction | PlanningRouter adapter + `LlmInteractionSink` | session `llm.jsonl` | 步骤 5 / router log tests |

步骤 1 不修改生产行为、SQLite schema 或测试契约。验证范围只证明当前冻结面可复现；后续步骤不得用 Planner 施工反向改写 Stage 5/6 已冻结边界。

步骤 1 验证：上述三组 `85/85` 公共测试通过，failure/error/skip 均为 `0`；Tool catalog contract 仍为 `22` 个，schema 仍为 V1。步骤 1 完成，下一步只实施步骤 2。

### 步骤 2 Planner 纯 models / errors / limits（2026-07-14）

- 新增 `app/planning/models.py`、`errors.py` 与公开 package surface，包含 composition-owned `PlanningLimits`、三种互斥 route decision、PlanRun / PlanStep / revision / status、PlanCommand 以及 initial/replan typed input。
- `PlanDraft` 在构造边界拒绝重复 Step ID、重复 position、未知 dependency 和自引用；cycle 与 ready ordering 留给步骤 3 的纯 scheduler。
- Executor 兼容扩展 `ExecutorStopReason.GOAL_NOT_ACHIEVED`，映射为 `STOPPED`；现有 Direct ReAct graph 不产生该结果，Runtime 当前安全映射为 `ERROR`，后续由 Planner Controller 消费。
- 未接入 graph、repository、SQLite 或 provider。

步骤 2 验证：Planner model 与受影响 Executor contract / route / Runtime mapping 共 `22/22` 通过，`compileall` 通过。步骤 2 完成，下一步只实施步骤 3。

### 步骤 3 纯 Plan 生命周期与 dependency scheduler（2026-07-14）

- 新增纯 `app/planning/lifecycle.py`，集中维护 Run / Step 合法状态转换，不依赖 LangGraph、模型、Tool 或 SQLite。
- `validate_plan_draft` 验证 Step 上限、从 1 开始的连续 position 和 dependency cycle；`ready_steps` 只返回 dependency-completed 的 pending Step，并按 position 稳定排序，已有 running Step 时不再 claim 新 Step。
- Executor decision budget 同时累计到 PlanRun 与 PlanStep；每 Step limit 取 per-step 与剩余总预算较小值，revision 不重置累计总预算。
- bounded replan eligibility 只接受当前 revision 的 `goal_not_achieved` Step，且必须仍有 replan 次数和总预算。

步骤 3 验证：Planner models / lifecycle 聚焦测试 `9/9` 通过，`compileall` 通过。步骤 3 完成，下一步只实施步骤 4。

### 步骤 4 schema V2 与 PlanRepository（2026-07-14）

- canonical migration 只追加 V2 `plan_and_execute`，新增可查询的 `plan_runs` / `plan_steps`；V1 内容保持不变。dependency/evidence 使用稳定的小型 JSON array，关键 lifecycle 字段保持独立列。
- 新增 `SqlitePlanRepository`：创建/读取 preview、session + revision-aware confirm/cancel/modify、重复 command 幂等读取、稳定 claim ready Step、原子记录 Step result + PlanRun budget、创建 replan revision和 terminal transition。
- repository 拒绝 cross-session、stale revision、非法状态和重复 running claim；旧 revision rows 保留，pending rows 在新 revision 创建时变为 superseded，completed result/evidence 不改写。
- `recover_interrupted=True` 只把已持久化的 running Run/Step 收敛为 `plan_execution_interrupted` / stopped，不 replay request-local ToolRuntime 或 Executor state。
- 未接入 Runtime graph、provider 或真实用户数据库。

步骤 4 验证：fresh V2、V1 → V2、migration 幂等、repository 与原有 SQLite/UoW 回归共 `23/23` 通过。步骤 4 完成，下一步只实施步骤 5。

### 步骤 5 PlanningRouter port 与 adapter（2026-07-14）

- 新增窄 `PlanningRouteClient` Protocol、deterministic fake 与 OpenAI-compatible production adapter；公共结果只可能是 `DirectRoute`、`PlanRoute` 或 `NeedUserRoute`。
- production adapter 使用 strict JSON schema；parser 拒绝 fenced JSON、未知字段、互斥字段组合和未知 route，不生成 Step、不选择 Tool、不构造 arguments、不授权 WRITE。
- provider/config failure 使用稳定 `planning_route_failed`，invalid response 使用 `plan_contract_invalid`，不把 provider exception 文本写入公共错误。
- route provider request/response 通过现有 request-local `LlmInteractionSink` 进入 session `llm.jsonl`，沿用同一 run/turn identity 与递增 `seq`。
- 本步骤只建立可独立消费的 Router adapter；未接 outer graph、repository、Planner model 或 Tool execution。

步骤 5 验证：Router、observability 与既有 Executor model adapter 聚焦回归 `15/15` 通过，`compileall` 通过。前五步完成；下一施工入口是步骤 6，不在本轮提前实施。

前五步整体复验：统一离线回归 `320/320` 通过，failure/error/skip 均为 `0`；覆盖既有 Direct ReAct、Runtime、Skill、Tool、Research、Travel 与新增 Planning/Schema V2。Stage 7 仍处于实施中，尚未达到步骤 16 gate；当前只确认步骤 6 可以继续。

### 步骤 6 Planner port、adapter 与 plan validation（2026-07-14）

- 新增窄 `PlannerModelClient` 与 `PlanningSnapshotProvider` Protocol，initial plan / replan 使用不同 typed input；deterministic fake 分别记录两类调用。
- 新增可信 `PlanningScopeRef` / `PlanningSnapshotEnvelope`；Planner 只接收调用方通过 read-model boundary 提供的 envelope，不直接读取 Domain repository，也不从自然语言生成稳定 scope ID。
- OpenAI-compatible adapter 使用 strict plan schema，输出只可能是完整 `PlanDraft` 或 `PlannerNeedUser`；本地 parser 再验证 Step 字段、唯一 ID/position、dependency existence/self/cycle 和 composition-owned step limit。
- 递归拒绝 Tool 名、candidate Tool、arguments、WRITE authorization、provider/MCP schema 和 private reasoning 字段；provider failure fail-closed 为稳定 `plan_generation_failed`。
- create-plan / replan interaction 通过 request-local `LlmInteractionSink` 记录；未执行 Tool、未写 PlanRepository、未接 graph。

步骤 6 验证：Planner adapter 与既有 Planning models/lifecycle/router 聚焦测试 `18/18` 通过，`compileall` 通过。步骤 6 完成，下一步只实施步骤 7。

### 步骤 7 plan preview 与结构化 PlanCommand service（2026-07-14）

- 新增 `PlanPreview` 与 preview-first `PlanningService`：Planner 完整结果验证通过后才创建 awaiting-confirmation PlanRun；结构化 clarification 不创建 durable row。
- `get_preview` 通过 session + plan ID 读取当前 revision；confirm/cancel/modify 只接受 action 匹配、session-bound、revision-bound `PlanCommand`，repository 继续拥有状态转换与 duplicate command 幂等。
- modify 保留原始 PlanRun goal，把用户 feedback 作为 typed confirmed constraint 交给 Planner，生成新 revision 并使旧 pending Step superseded；Planner 再次需要澄清时不修改旧 revision。
- service 拒绝调用方提高或替换 composition-owned limits。
- confirm 后 PlanRun 进入 running，但所有 Step 仍为 pending；本步骤没有 Executor dependency，不执行 Tool。

步骤 7 验证：PlanningService、PlanRepository、Planner adapter 与 Planning models 聚焦测试 `22/22` 通过，`compileall` 通过。步骤 7 完成，下一步只实施步骤 8。

### 步骤 8 Planner-to-Executor 窄 Step 入口（2026-07-14）

- 新增 `PlanStepExecutionInput`：只表达 plan/revision/step identity、原始 plan goal、当前 objective、expected outcome、显式 dependency safe results 和 per-step max；没有 future Steps、Policy、authorization、ToolRuntime 或 graph state。
- `ReactExecutor.execute_step(...)` 是独立兼容入口；现有 `execute(...)` 签名与 Direct ReAct 行为保持不变。Step limit 取 Executor composition limit 与 Planner per-step limit 较小值，Planner 不能提高 Executor 上限。
- Plan Step input 通过 invocation-local `ExecutorGraphContext` 进入每次新构建的 `ExecutorModelInput`，不进入 outer GraphState，也不塞进 `RuntimeRequest.user_input` / metadata。
- dependency result 只包含显式 Step ID、安全摘要和 post-Guardrail `ToolObservation`，为步骤 9 的声明依赖 handoff 提供窄契约。
- 新增 Planner-step-only `GoalNotAchievedDecision`；production adapter 只在 Step 模式提供内部 `report_goal_not_achieved` control function，fake/graph 映射为 `STOPPED + GOAL_NOT_ACHIEVED + plan_step_goal_not_achieved`。Direct 模式返回该 control result 会 fail-closed 为 invalid action。
- 本步骤没有实现 PlanController、共享 ToolRuntime 生命周期或 next-step 调度。

步骤 8 验证：Step entry、Executor models/contracts/ports/graph、production model adapter 与 Runtime mapping 聚焦回归 `41/41` 通过。步骤 8 完成；下一施工入口是步骤 9，不在本轮提前实施。

步骤 6-8 整体复验：Planning 模块级测试 `30/30` 通过；统一离线回归 `337/337` 通过，failure/error/skip 均为 `0`。Stage 7 仍处于实施中，尚未实现 PlanController、bounded replan orchestration 或 Finalizer；当前只确认步骤 9 可以继续。

### 步骤 9 PlanExecutionContext 与串行 PlanController（2026-07-14）

- 新增 LifeOps-owned 显式 `PlanController` 循环，不启用 checkpointer，也不把持久化 PlanRun / PlanStep 复制进 outer GraphState。
- 一次成功 confirm 创建一个 request-local `PlanExecutionContext`，持有同一 ToolRuntime、AllowedToolSet、prompt contributions、声明依赖结果和累计 Executor budget；这些值不进入 SQLite/event/LLM log。
- Controller 按 repository 的 dependency-ready + position 每次 claim 一个 Step；每次调用一次 `execute_step()`，因此 Executor graph state / decision counter 都重新创建，但 execution scope 保持同一对象。
- 只有当前 Step 声明的 dependency result 可见；post-Guardrail observations 可在同一 context 中传递 request-local ID，未声明依赖不可见。
- `FINAL_ANSWER + COMPLETED` 确定性映射为 completed，不解析 final message；goal/safety/confirmation/model/internal 等结构化结果不会错误推进后续 Step。使用 WRITE Tool 的完成结果必须含 evidence reference。
- PlanRun / PlanStep budget 原子累计；总预算耗尽时不 claim 新 Step。重复 confirm 只读取已有结果，不启动第二个 Controller。
- 本步骤使用 fake Step Executor 验证 Controller，不实现 replan 或 Finalizer。

步骤 9 验证：PlanController、PlanningService/Repository 与 Step Executor 受影响回归 `20/20` 通过，`compileall` 通过。步骤 9 完成，下一步只实施步骤 10。

### 步骤 10 一次 bounded replan（2026-07-14）

- 只有 `goal_not_achieved` 或单 Step `limit_reached` 且 Plan 总预算仍有余量时可触发 replan；safety、confirmation、model、internal 和总预算耗尽均直接终止。
- Controller 最多调用一次 Planner replan；新 revision 保留旧 revision 的 completed safe summaries / evidence，不重新创建已完成 Step，也不复用旧 Executor state。
- 新 revision 回到 `awaiting_replan_confirmation`，不会在同一次 confirm 中继续执行；用户必须对新 revision 再次结构化确认。
- 第二次目标未达成或单步限额停止不再重规划，稳定映射为 `plan_replan_exhausted`；总预算耗尽映射为 `plan_budget_exhausted`。
- 本步骤不实现 Recovery replay、异步暂停或 Finalizer。

步骤 10 验证：PlanController replan、生命周期与 Repository 聚焦回归 `18/18` 通过，`compileall` 通过。步骤 10 完成，下一步只实施步骤 11。

### 步骤 11 只读 PlanFinalizer（2026-07-14）

- 新增窄 `PlanFinalizerInput` / `PlanFinalizerStepResult`：只包含 goal、revision、按 position 排序的 Step status、安全摘要、结构化 stop/error 和 evidence refs；不包含原始 prompt、arguments、Tool output、transcript 或 request-local observations。
- 新增 deterministic fake 与 OpenAI-compatible production adapter；production request 使用 strict schema，不提供 Tool，interaction 进入现有 request-local `LlmInteractionSink`。
- Finalizer 输出显式声明是否声称 WRITE 成功及所引用 evidence；无 evidence 的 WRITE 成功声明、未知 evidence 或非法 schema 均以 `plan_finalization_failed` fail-closed。
- Controller 在所有 Step 已完成后先将 PlanRun 原子结束为 completed，再调用只读 Finalizer；Finalizer/provider/contract 失败不会反转已完成事实，而是返回只使用安全摘要的 deterministic fallback。
- `PlanControlResult` 新增 request-local final message 与 fallback 标记；不把模型 final message 持久化到 PlanRun / PlanStep，也不接 outer Runtime graph。

步骤 11 验证：Planning 模块聚焦回归 `43/43` 通过，`compileall` 通过；统一离线回归 `350/350` 通过，failure/error/skip 均为 `0`。步骤 11 完成，下一施工入口是步骤 12。

### 步骤 12 outer LangGraph / Runtime / CLI composition（2026-07-14）

- Policy 与 Skill preparation 之后新增 planning route node；未配置 Planning composition 时既有 graph path 完全不变，配置后 direct route 继续进入同一个 `ReactExecutor`。
- plan route 只创建 durable preview 并映射为 `RuntimeResult(REQUIRES_CONFIRMATION)`，不调用 Executor/Tool；need-user 只返回 clarification，不创建 PlanRun。
- outer `GraphState` 只新增 typed planning route decision；PlanRun、PlanStep、ToolRuntime、完整 observations 和 Planner input 均不进入 state。
- 新增 revision-bound `RuntimeService.handle_plan_command(...)` / orchestrator command composition；confirm 调用 Controller，cancel/modify 调用 PlanningService，command 与原 plan goal/session 必须匹配。
- CLI 只把显式 `confirm-plan`、`cancel-plan`、`modify-plan <feedback>` 语法翻译成 `PlanCommand`，计划确认仍不等于 WRITE action confirmation。
- production bootstrap 组合共享 Executor、PlanningRouter、Planner、Repository、Controller、Finalizer 与 composition-owned limits。

步骤 12 验证：Planning Runtime、既有 Orchestration/Runtime/CLI 与 Executor mapping 聚焦回归 `28/28` 通过，`compileall` 通过；随后补充的 CLI structured-command boundary 测试也通过。步骤 12 完成，下一步只实施步骤 13。

### 步骤 13 Planning 语义 observability（2026-07-14）

- outer planning node 记录 `planning.route.selected` 与 `plan.preview.created`；command composition 记录 command action/result 与新 revision，不记录原始 goal、feedback、prompt 或 Step 文本。
- Controller 记录 `plan.step.started` / `plan.step.finished`、`plan.replan.created`、`plan.finalize.started` / `completed` 和 `plan.stopped`；payload 只包含 plan/revision/step identity、position、status、budget/evidence count、fallback 标记与稳定 error code。
- route/create-plan/replan/finalize production adapters 继续共用 request-local `LlmInteractionSink`；新增 file-backed 验证确认四类 interaction 写入同一 `llm.jsonl`，保留同一 run/session/turn identity 与严格递增 seq。
- Planning event payload 测试明确验证不包含原始用户输入、Tool arguments/output、完整 observations、provider exception 或 finalizer message。

步骤 13 验证：Planning observability、Runtime composition、Controller/replan/finalizer 与既有 Orchestration 聚焦回归 `33/33` 通过；`compileall` 通过；统一离线回归 `356/356` 通过，failure/error/skip 均为 `0`。步骤 13 完成，下一施工入口是步骤 14。

### 步骤 14 Research 主 E2E 与最小 cross-domain E2E（2026-07-14）

- 新增 compiled Planning E2E：除模型决策和外部数据源使用 deterministic fake/fixture 外，真实经过 outer graph、durable preview、structured confirm、PlanController、ReactExecutor、Tool Gateway/Guardrails、Research/Travel services/repositories 与 Finalizer。
- Research 主链路按六个 Step 完成 fetch → parse → rank → draft → save source → save brief；显式 dependency observations 在同一 ToolRuntime 中传递真实 document/item-set/draft/observation ID，最终产生两条 WRITE evidence 和一致的 Source/Brief durable facts。
- 无 action confirmation 时在第一个 WRITE handler 前停止，Research Source/Brief 均为零写；outer result 将结构化 `confirmation_required` 映射为 `REQUIRES_CONFIRMATION`，不把它误报为通用 ERROR。
- 覆盖 Research direct route 不创建 PlanRun、Research READ → Travel READ 最小跨域计划、goal-not-achieved → replan preview → reconfirm → complete、第二次失败 `plan_replan_exhausted`、总预算耗尽、安全拒绝、stale revision、Finalizer fallback。
- file-backed restart 场景验证 preview/running durable state 可重新读取，但 running Step 只会由显式 interrupted recovery 标记 stopped，不自动恢复或重放 Tool。
- 本步骤没有访问真实网络、扩展 Travel、增加 checkpoint/Recovery replay 或修改 Domain contract。

步骤 14 验证：新增 compiled Planning E2E `9/9` 通过；Planning/Runtime/Executor/Domain 受影响层 `64/64` 通过；`compileall` 通过；统一离线回归 `365/365` 通过，failure/error/skip 均为 `0`。步骤 14 完成，下一施工入口是步骤 15。

### 步骤 15 分层回归与真实 LLM 验证（2026-07-14）

- Planner models / lifecycle、repository / migration、adapters、Controller / Executor、outer Runtime 与 compiled Planning E2E 聚焦回归共 `70/70` 通过；统一离线回归 `369/369` 通过，failure/error/skip 均为 `0`，没有需要修复的本地 contract、integration、runtime/graph 或 architecture/migration 失败。
- production `PlanningRouter` 已使用真实 OpenRouter model 分别验证：包含精确 `hf_daily_papers` source key 的单步请求返回 `DirectRoute`，显式依赖的多步 Research 请求返回 `PlanRoute`，缺少研究主题/来源的请求返回 `NeedUserRoute`。空 catalog 或缺少必要 source key 的请求安全返回 `NeedUserRoute`，属于输入信息不足，不按路由失败处理。
- Research happy-path 使用真实 Planner、Executor 与 Finalizer model，并使用内存 SQLite、Research deterministic fixture、READ-only Policy 与无 WRITE Tool catalog 隔离用户数据和外部内容波动：生成 `4` Step preview，结构化 confirm 后返回 `status=ok`、`plan_status=completed`。
- 首次沙箱内真实 route 调用统一返回安全错误码 `planning_route_failed`；允许外部网络后 provider 调用成功，分类为验证环境网络隔离，不是本地 contract failure。Research 完成结果返回后，临时验证脚本追加读取 repository 详情时出现 `TypeError`；该错误发生在已确认的 completed RuntimeResult 之后，不属于产品执行链失败。

步骤 15 完成，下一施工入口是步骤 16 文档与 Stage 7 gate 收口；本步骤不提前修改 Architecture、Progress、Runtime Concepts、README 或总路线图。

### 步骤 15 后代码审查与稳定化（2026-07-14）

- 修复 cancel 终态映射：结构化取消现在返回 terminal `plan_result`，CLI 会清除当前 preview；Repository 同一事务内把当前 revision 尚未执行的 Step 标记为 `cancelled`，不再留下伪 pending 状态。
- 将 modify feedback 收敛为 PlanRun 的 durable confirmed constraints，并新增 schema V3 增量迁移；后续自动 replan 会继续携带用户已确认约束，不依赖当前请求的瞬时变量。
- Finalizer 改为汇总截至当前 revision 的全部 completed Step facts/evidence；replan 前已完成的结果不会从最终总结输入中丢失，同时保持每个 revision 的 PlanStep 持久化记录不变。
- PlanningService / PlanController 改为依赖 `PlanRepository` Protocol，不再直接绑定 SQLite adapter；新增 architecture contract，冻结 Planning core 不依赖 Domain/LangGraph、outer GraphState 只保留 route-level planning data。
- `PlanningSnapshotProvider` 已成为 PlanningService 的显式可选 seam：只接受上游传入的 typed trusted scope refs，未配置 provider 时 fail-closed；不从自然语言自行推断 scope，真实 Context/Memory snapshot resolution 仍属于 Stage 9。
- Executor Context、Memory、Feedback、Recovery hooks 新增可选 `PlanStepExecutionInput` identity；Direct ReAct 继续传 `None`，Plan execution 可让后续 provider/observer 精确关联 `plan_id/revision/step_id`。本次只完善接口与传递，不实现 Context/Memory/Recovery 业务。

稳定化验证：新增/受影响层 `82/82` 通过；完整 Planner 聚焦回归 `79/79` 通过；`compileall` 通过；统一离线回归 `379/379` 通过，failure/error/skip 均为 `0`；`git diff --check` 通过。稳定化检查完成后进入步骤 16，且没有提前实现 Context / Memory 或 Recovery / Feedback 功能。

### 步骤 16 文档与 Stage 7 gate 收口（2026-07-14）

- 已将 `docs/ARCHITECTURE.md` 中的 outer orchestration、Planning control layer、PlanRun/Domain fact 和依赖方向更新为当前实现事实。
- 已将 `docs/PROGRESS_LOG.md`、`docs/RUNTIME_CONCEPTS.md`、`README.md` 与 `plans/RUNTIME_REFACTOR_PLAN.md` 从“Planner 尚未实施”同步为 Stage 7 已完成。
- 完成标准逐项成立：三路 route、preview/revision/command、串行 Step controller、request-local dependency handoff、一次 bounded replan、预算、WRITE confirmation/evidence、Finalizer fallback、Research/cross-domain E2E、既有回归与文档事实均有测试或步骤 15 真实模型证据。
- Stage 7 下游 gate 结论为 `go`：现有 `PlanningSnapshotProvider`、Executor Context/Memory provider 与 `PlanStepExecutionInput` identity 已提供窄接入面，可以在不改写 Planner/Executor 控制骨架的前提下单独接入 Stage 8 Research MCP，并在 Stage 9 规划 Context / Memory。
- Stage 8 MCP 必须继续经过现有 Tool/Gateway contract；Stage 9 不得把 Memory 读取变成写入授权，不得把 Context contribution、snapshot、PlanRun 或 checkpoint 当作 Domain fact；Stage 10 Recovery/Feedback、并行 DAG 和异步 resume 继续延后。

步骤 16 完成。Stage 7 Plan-and-Execute Planner 模块关闭；后续 Stage 8 Research MCP 已于 2026-07-15 完成并取得 `go`，当前下一模块施工入口是 Stage 9 Context / Memory 计划设计。

1. **冻结 Stage 7 基线与契约矩阵**：记录当前 branch/commit、工作树、schema V1、Executor/Runtime/Domain 公共测试和现有 Tool catalog；把本文每个公共字段、owner、consumer 和测试映射成表。只做基线，不修改行为。
2. **实现 Planner 纯 models / errors / limits**：新增 route decision、PlanRun、PlanStep、status、revision、PlanCommand、input/output 与依赖验证；增加 `goal_not_achieved` Executor 契约及聚焦测试，不接 graph/repository/provider。
3. **实现纯 Plan 生命周期与 dependency scheduler**：完成合法状态转换、ready-step 选择、cycle/position 校验、预算累计和 replan eligibility 纯函数；不调用模型、Tool 或 SQLite。
4. **新增 schema V2 与 PlanRepository**：实现 `plan_runs` / `plan_steps`、跨连接读取、revision-aware command、原子 Step result/budget、stale/interrupted 语义和 repository tests；不接 Runtime graph。
5. **实现 PlanningRouter port 与 adapter**：先完成 fake 和 schema contract，再接 OpenAI-compatible production adapter、request-local LLM log 与安全错误映射；只返回 direct/plan/need_user。
6. **实现 Planner port、adapter 与 plan validation**：完成 initial plan/replan typed input、forbidden fields、Step/dependency/limit 校验、可信 snapshot envelope 和 fake consumers；不执行 Tool。
7. **实现 plan preview 与结构化 PlanCommand service**：创建 awaiting-confirmation plan、读取 preview、confirm/cancel/modify、旧 revision/cross-session/duplicate command 测试；确认后暂不接真实 Executor。
8. **增加 Planner-to-Executor 窄 Step 入口**：保持 Direct ReAct 兼容，加入 current objective、expected outcome、dependency results 和更小 limit；实现 `goal_not_achieved` production/fake adapter 行为和聚焦回归。
9. **实现 PlanExecutionContext 与串行 PlanController**：同 PlanRun 复用 ToolRuntime、每 Step 新 Executor state、只传声明依赖、安全 handoff、预算和确定性 next-step；先使用 fake Executor。
10. **接入一次 bounded replan**：只对允许的结构化结果生成新 revision，保留 completed facts/evidence，重新 preview/confirm，第二次失败停止；不实现 Recovery replay。
11. **实现 PlanFinalizer**：加入只读 adapter、evidence-aware input、LLM log 与 deterministic fallback；完成 PlanRun terminal result。
12. **接入 outer LangGraph / Runtime / CLI composition**：增加 planning route 与 plan preview/result 映射、结构化 command 入口、同步 action confirmation composition；保持 outer GraphState 最小和 Direct ReAct 行为不变。
13. **补充语义 observability**：增加 route、plan、revision、step、replan、finalize、stop events，验证 payload 不含原始 prompt/arguments/output/exception；验证 route/plan/replan/finalize 的 `llm.jsonl`。
14. **完成 Research 主 E2E 与最小 cross-domain E2E**：覆盖 preview、confirm、request-local handoff、READ/WRITE、replan、budget、finalizer、无确认零写，以及 Research READ → Travel READ；不访问真实网络或扩展 Travel。
15. **分层回归与真实 LLM 验证**：先运行聚焦层和统一离线回归；再单独执行 direct/plan/need_user/Research happy-path 真实模型验证并分类报告外部失败。
16. **文档与 Stage 7 gate 收口**：只在所有完成标准满足后更新 Architecture、Progress、Runtime Concepts、README 和总路线图；给出下游 `go/no-go`，不在本阶段创建 Context/Memory 或外部 integration 实现。

## 11. 完成标准

只有同时满足以下条件，Stage 7 才能标记完成：

- Direct、Plan、NeedUser 三条 route 有 deterministic 与真实模型证据；
- preview-first、revision command 和最小 SQLite lifecycle 可跨请求/进程读取；
- Planner 输出不含 Tool 选择、arguments 或授权；
- 每次只执行一个 Step，正常路径确定性推进；
- 一个 PlanRun 共享 execution scope，每 Step 独立 ReAct state；
- dependency handoff 可以完成 Research request-local ID 链路；
- `goal_not_achieved`、一次 replan、重新确认和 exhausted stop 均有测试；
- 每 PlanStep、每 PlanRun 的预算均不可由模型或用户提高；
- WRITE 继续使用同步逐 action confirmation 与 evidence；
- PlanFinalizer 不调用 Tool，失败有 deterministic fallback；
- Research 主 E2E 和最小 cross-domain E2E 通过；
- Direct ReAct、Tool Gateway、Research、Travel 和 Runtime 既有回归无行为漂移；
- 文档只陈述已实现事实，下游 gate 有明确结论。

## 12. 施工纪律

- 每次只实施一个编号步骤，先读本计划对应片段和相关代码，再做最小 patch；
- 每个行为变化必须有聚焦测试和明确 owner；
- 新增公共字段、Protocol、event 或错误码必须有当前真实 consumer；
- 不读取 `legacy_v0/`，除非当前步骤明确需要验证一项历史机制；
- 不借 Planner 施工重构无关 Intent、Policy、Skill、Tool、Domain 或 Storage 代码；
- 如果同步 confirmation 无法满足真实产品调用方，先停止并在 Stage 10 Recovery / Feedback 单独设计边界，不能把 pending Executor state 塞进全局 dict、`RuntimeRequest` metadata、Domain 表或 outer `GraphState`；
- 如果跨 Step handoff 无法在不持久化 Domain temporary artifacts 的情况下成立，必须以测试证据重新评估 Step 粒度，不得伪造或重建 request-local ID；
- API / MCP integration 必须等待 Stage 7 gate 关闭后创建独立计划。
