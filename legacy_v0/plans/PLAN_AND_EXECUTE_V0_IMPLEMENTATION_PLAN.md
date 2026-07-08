# Plan and Execute v0 实现计划

本文档用于 Recovery / Persistence v0 之后继续施工。目标是在已有 Tool、Capability、Write Safety、Interaction / Safety State、Task State、RunState、ActionRecord、RunRecord 和 Recovery Context 边界之上，新增第一版真实的 Plan and Execute 闭环。

v0 的重点不是最大化自动化，而是把三个角色拆清楚：

```text
User goal
-> Main Orchestrator route
-> Planner Agent 生成结构化 transient plan
-> 向用户展示 plan 并等待确认
-> 用户确认后 Executor Agent 单步执行
-> Main Orchestrator 更新 transient plan 状态
-> done / need_user / blocked / unsafe / replan
```

第一版先采用保守策略：复杂目标先展示计划，用户确认后才执行；`PlanRun` 先保存在当前 `Agent` 实例内，不做持久化 `PlanStore`。

## 1. 当前地基

当前 repo 已完成这些 Plan and Execute 需要依赖的边界：

- `Agent.chat()` 已经是一个 ReAct-style 执行入口，包含 turn 准备、Skill routing、Prompt / Context 组装、Capability 构建、LLM loop、Tool Executor 调用、RunState、ActionRecord、Recovery persistence 和最终回答校验。
- Tool / Capability / Executor 已经形成两层安全边界：模型只看到本轮允许的 Tool Schema，Executor 执行前再次校验 `allowed_tool_names`。
- Write Safety 已经要求业务 WRITE 必须来自当前用户输入的明确授权；模型口头声明不算写入事实。
- Interaction / Safety State 已经处理高风险 pending confirmation，不让危险删除等操作直接执行。
- Task State v1 已经保存长期任务、步骤、blocker、note 和当前步骤，但当前不自动生成计划、不自动推进步骤、不自动执行工具。
- Recovery / Persistence v0 已经保存 `RunRecord` 和 `PersistentActionRecord` 摘要，可解释上次停在哪里，但不自动 replay。

Plan and Execute v0 要站在这些边界上，而不是绕过它们。

## 2. v0 范围

### 做什么

- 新增 Main Orchestrator / Planner Agent / Executor Agent 的明确边界。
- 支持 deterministic route：
  - simple / single-step 请求：直接执行。
  - complex / multi-step goal：先生成计划并展示给用户确认。
  - ambiguous 请求：先澄清。
  - risky 请求：优先进入 Interaction / Safety State。
- Planner Agent 只输出结构化计划，不调用业务工具，不授权 WRITE。
- Executor Agent 每次只执行一个 step，并复用现有 Agent Loop / Tool Executor 能力。
- Main Orchestrator 负责 pending plan 生命周期、确认后单步执行、step 状态推进、blocked / need_user / done / replan 决策。
- 执行 step 时把 `plan_id` / `plan_step_id` 关联到 RunState / RunRecord，便于 Recovery 解释执行停点。
- 成功 step 后默认推进到下一步，但不自动连续执行完整计划；每轮最多执行一个 step。

### 不做什么

- 不做持久化 `PlanStore`。
- 不做 DAG。
- 不做并行 agent。
- 不做后台任务或长期自动调度。
- 不做 rollback / compensate。
- 不让 Planner 调用业务工具。
- 不让 Planner 授权 WRITE。
- 不自动把 plan 写入 Task State。
- 不自动连续执行完整计划。
- 不把 Recovery v0 升级成自动 replay。

## 3. 角色边界

### Main Orchestrator

Main Orchestrator 是 Plan and Execute v0 的控制层。

职责：

- 接收 `Agent.chat()` 的当前用户输入。
- 先处理已有 Interaction / Safety pending confirmation。
- 判断本轮 route：
  - `direct_execute`
  - `plan_preview`
  - `confirm_plan`
  - `modify_plan`
  - `cancel_plan`
  - `clarify`
  - `safety_pending`
- 对 complex goal 调用 Planner Agent。
- 保存 pending / active transient plan 到 `PlanningState`。
- 向用户展示 plan 并等待确认、修改或取消。
- 用户确认后选择当前 step，调用 Executor Agent。
- 根据 Executor 的 RunState / ActionRecord / answer 更新 PlanStep。
- 在 failed / blocked / need_user / 计划与结果不匹配时触发 replan。

Main Orchestrator 不直接执行业务工具。

### Planner Agent

Planner Agent 只负责计划，不负责执行。

职责：

- 输入原始 user goal、只读 Task Context、Recovery Context 摘要、可用能力摘要和安全规则。
- 输出严格结构化 plan。
- 标记 step 的风险、是否可能需要用户确认、预期工具领域。
- 在目标缺少关键对象、范围或约束时返回 `need_user`。

限制：

- 不暴露业务 tools。
- 不调用 Tool Executor。
- 不生成具体 tool call arguments。
- 不授权 WRITE。
- 不声称任何 step 已经完成。

### Executor Agent

Executor Agent 是单步执行层。

v0 先包装现有 Agent Loop / Tool Executor，不立即大改名或大迁移。

职责：

- 接收一个 step 的执行上下文。
- 用 ReAct / function calling 执行这个 step。
- 继续使用 Capability Builder、Write Policy、Interaction / Safety State、Tool Executor、RunState、ActionRecord 和 Recovery persistence。
- 返回自然语言结果和结构化执行摘要给 Main Orchestrator。

Executor Agent 不负责生成完整 plan，也不负责长期调度。

## 4. 数据模型

v0 新增 transient planning 类型。它们先不落盘，只存在于当前 `Agent` 实例生命周期内，类似 Interaction State 的短期 Runtime State。

### PlanningState

```python
class PlanningState:
    pending_plan: PlanRun | None
    active_plan: PlanRun | None
    turn_index: int
```

职责：

- 保存等待用户确认的 plan。
- 保存确认后正在推进的 active plan。
- 支持 pending plan 的确认、修改、取消、过期和 supersede。
- 不进入 Memory、Conversation Summary、ContextIndex 或 Task State。

### PlanRun

建议字段：

```python
class PlanRun:
    plan_id: str
    goal: str
    status: PlanStatus
    steps: list[PlanStep]
    current_step_id: str | None
    source_user_input_summary: str
    created_at: str
    updated_at: str
```

状态建议：

```text
pending_confirmation
active
completed
blocked
cancelled
superseded
```

### PlanStep

建议字段：

```python
class PlanStep:
    step_id: str
    title: str
    intent: str
    status: PlanStepStatus
    requires_user_confirmation: bool
    risk_level: str
    expected_tool_domain: str | None
    last_run_id: str | None
    last_result_summary: str | None
    blocker: str | None
```

状态建议：

```text
pending
in_progress
done
blocked
skipped
failed
```

### 与 RunRecord 的关联

为了让 Recovery 能解释“上次停在计划哪一步”，v0 建议给运行记录增加最小关联字段：

- `RunState.plan_id: str | None`
- `RunState.plan_step_id: str | None`
- `RunRecord.plan_id: str | None`
- `RunRecord.plan_step_id: str | None`

`PersistentActionRecord` v0 暂不需要增加 plan 字段；通过所属 `RunRecord` 关联到 plan step 即可。

### 与 Task State 的关系

PlanRun 不等于 Task State。

- PlanRun 是当前 Runtime 为一次复杂目标生成的 transient execution plan。
- Task State 是用户授权创建的长期任务事实源。
- Planner 输出不自动写入 Task State。
- 自动推进 PlanStep 是 Runtime progress 更新，不是业务 WRITE。
- 自动推进 TaskStep / TaskItem 属于长期任务事实变更，仍需要当前用户输入明确授权或 Safety confirmation。

如果用户明确说“把这个计划保存成长期任务”或“创建任务并按这个计划推进”，后续可以由 Task WRITE tools 写入 Task State，但这不是 v0 默认行为。

## 5. 控制流

### Direct execute

```text
User input
-> Orchestrator route: direct_execute
-> Executor Agent
-> existing Agent Loop / Tool Executor
-> answer
```

适用：

- 单步读取。
- 明确的一次性写入。
- 简单问答。
- 不需要拆计划的工具调用。

行为：

- 不创建 PlanRun。
- 不进入 PlanningState。
- 保留现有 Agent 行为。

### Plan preview

```text
User complex goal
-> Orchestrator route: plan_preview
-> Planner Agent
-> PlanRun(status=pending_confirmation)
-> PlanningState.pending_plan = plan
-> 展示计划，要求用户确认 / 修改 / 取消
```

行为：

- 不执行任何工具。
- 不写 Task State。
- 不写 Recovery action。
- 只保存 transient pending plan。

### Confirm plan

```text
User confirms
-> Orchestrator confirms pending plan
-> PlanRun(status=active)
-> select current pending step
-> Executor Agent executes one step
-> RunState / RunRecord include plan_id + plan_step_id
-> Orchestrator updates PlanStep
-> answer with result + next step
```

行为：

- 每轮最多执行一个 step。
- step 成功后标记 done。
- 如果还有下一步，提示用户继续或确认继续执行。
- 不自动连续执行完整计划。

### Modify plan

```text
User modifies pending/active plan
-> old plan superseded
-> Planner Agent replans with modification
-> new pending plan preview
-> wait for confirmation
```

行为：

- 修改后的 plan 仍需展示给用户确认。
- 旧 plan 不继续执行。

### Cancel plan

```text
User cancels
-> pending/active plan cancelled
-> no step execution
-> answer cancellation
```

行为：

- 不执行任何工具。
- 不写 Task State。

### Replan

触发条件：

- Executor step failed。
- Executor step blocked。
- Executor 需要用户补充信息。
- 用户修改目标或约束。
- 执行结果与当前 plan 明显不匹配。
- Planner 原计划中的下一步变得 unsafe 或不可执行。

不触发条件：

- step 成功完成后默认不 replan。
- 普通 direct execute 不 replan。

Replan 输出仍需要用户确认后才能继续执行。

## 6. Safety 和写入边界

Plan and Execute v0 必须保留现有安全边界：

- Planner 标记 `requires_user_confirmation=true` 不等于用户已经授权。
- Planner 标记 `risk_level=high` 不等于可以执行危险 WRITE。
- Planner 不能让 WRITE tool 出现在本轮 Capability。
- Capability Builder 仍由当前用户输入和 confirmed pending 决定 WRITE tool 可见性。
- Executor 调用 Tool 前仍做 `allowed_tool_names` 二次校验。
- 高风险输入优先进入 Interaction / Safety State。
- Recovery Context 只解释上次停点，不授权 replay。

安全优先级建议：

```text
Interaction / Safety pending
-> high-risk deterministic detection
-> route / plan preview
-> capability building
-> executor second check
-> final answer validation
```

## 7. 建议先做的小重构

当前 `Agent` 类已经承担较多职责：

- turn 准备
- Skill routing
- Prompt / Context 组装
- Profile / Memory / Task / Recovery 注入
- Interaction Safety
- LLM loop
- Tool execution
- ActionRecord / RecoveryRecord 同步
- Recovery persistence
- final answer validation

Plan and Execute 之前建议做小范围重构，但不要先做大拆分。

### 7.1 Request-local context builder

把 `_request_llm()` 中这些逻辑抽成独立边界：

- `ContextEngine.assemble()`
- Profile Context 注入
- Semantic Memory Context 注入
- Task Context 注入
- Recovery Context 注入
- diagnostics report 组装

目标：

- 统一 request-local context providers 的顺序。
- 避免 `_request_llm()` 继续膨胀。
- 后续 Planner / Executor 可以复用相同输入组装思想。

### 7.2 Action recording helper

把这些路径中的重复记录逻辑收口：

- `_record_tool_result`
- `_record_invalid_arguments`
- `_skip_calls`

目标：

- 统一创建 ActionRecord。
- 统一同步 RecoveryRecord。
- 统一 append tool observation。
- 为 `plan_id` / `plan_step_id` 关联提供稳定入口。

### 7.3 Executor boundary

先包装，不大迁移。

建议新增：

```python
class ExecutorAgent:
    def execute_step(self, context: StepExecutionContext) -> StepExecutionResult:
        ...
```

内部可以先复用现有 `Agent` 的 loop 方法，后续再逐步把执行循环从 `Agent` 中迁出。

## 8. 分阶段实施步骤

### Step 1: Planning 类型与状态机

新增：

- `app/planning/plan_types.py`
- `app/planning/planning_state.py`

实现：

- `PlanRun`
- `PlanStep`
- `PlanningState`
- pending plan create / confirm / cancel / supersede / expire
- active plan current step selection
- step status update

测试：

- pending plan 创建。
- pending plan 确认后变 active。
- cancel 后不能执行。
- supersede 后旧 plan 不再 active。
- terminal plan 不可继续变更。
- current step 必须引用现有 step。

### Step 2: Planner Agent

新增：

- `app/planning/planner_agent.py`
- `app/planning/planner_prompt.py`

实现：

- Planner instructions。
- Planner JSON schema。
- Planner output parser。
- invalid output fallback。

Planner 输出类型建议：

```text
plan
need_user
unsafe_or_needs_confirmation
cannot_plan
```

测试：

- 多步目标生成合法 plan。
- 空 steps 被拒绝。
- 非 JSON 输出被拒绝并转为 need_user / cannot_plan。
- Planner 不输出 tool call arguments。
- 风险步骤只能标记风险，不能授权 WRITE。

### Step 3: Thin refactor

实现：

- request-local context builder。
- action recording helper。
- ExecutorAgent thin wrapper。

要求：

- 现有 `Agent.chat()` 外部行为不变。
- 现有 direct execute 测试继续通过。
- 不在这一步引入 Plan route。

测试：

- 现有 `test_agent_loop_*`。
- 现有 `test_agent_recovery_*`。
- 现有 `test_agent_task_*`。
- 现有 `test_write_policy.py`。

### Step 4: Main Orchestrator route

新增：

- `app/planning/orchestrator.py`
- route 类型和 deterministic route policy。

实现：

- simple request -> direct execute。
- complex request -> plan preview。
- pending plan confirm / modify / cancel。
- ambiguous request -> clarify。
- risky request -> safety pending。

测试：

- simple request 不创建 plan。
- complex request 只展示 plan，不执行工具。
- pending plan 确认后进入 active。
- cancel plan 不执行。
- modify plan supersede 旧 plan。

### Step 5: 单步执行接入

实现：

- Orchestrator 从 active plan 选择 current step。
- 构造 `StepExecutionContext`。
- 调用 ExecutorAgent。
- RunState / RunRecord 写入 `plan_id` / `plan_step_id`。
- 成功后 PlanStep 标记 done。
- 失败后 PlanStep 标记 failed / blocked。

测试：

- 用户确认 plan 后才执行第一步。
- 每轮最多执行一个 step。
- step 成功后更新当前 step。
- step 失败后不继续执行下一步。
- Executor 仍不能绕过 Capability 和 Write Safety。

### Step 6: Replan 和 Recovery 说明

实现：

- failed / blocked / need_user 时触发 replan。
- replan 输出重新进入 pending confirmation。
- Recovery Context 可以说明上次 run 关联的 `plan_step_id`。
- 未持久化的 transient plan 不自动恢复。

测试：

- failed step 触发 replan preview。
- replan 后等待用户确认。
- interrupted / failed RunRecord 能显示 plan step id。
- 不存在 active transient plan 时，不根据 Recovery 自动 replay。

### Step 7: Prompt 和文档

更新：

- System Prompt 增加 Plan and Execute 行为规则。
- `PROJECT_CONTEXT.md` 记录稳定项目事实。
- `LEARNING_PROGRESS.md` 记录学习结论和下一步。

暂不更新：

- `CHANGELOG.md`，除非用户要求关闭阶段里程碑。

## 9. 最小验收测试

必须覆盖：

- direct execute：简单请求不生成 plan。
- plan preview：复杂目标只生成计划，不执行工具。
- confirm plan：用户确认后执行第一步。
- cancel plan：取消后不执行。
- modify plan：修改后旧 plan superseded，新 plan 重新确认。
- single-step execution：每轮最多执行一个 step。
- failed step replan：失败后不继续执行下一步。
- Safety pending：危险写入优先进入 Interaction / Safety State。
- Write boundary：Planner 不能授权 WRITE。
- Recovery association：step 执行的 RunRecord 包含 plan id 和 step id。

建议回归范围：

```powershell
uv run python -m unittest tests.test_agent_interaction_safety -v
uv run python -m unittest tests.test_agent_recovery_persistence tests.test_agent_recovery_context tests.test_recovery_context tests.test_recovery_store -v
uv run python -m unittest tests.test_agent_task_state tests.test_agent_task_context tests.test_task_state tests.test_task_context -v
uv run python -m unittest tests.test_write_policy -v
```

如果 `Agent.chat()` 委派或 `_request_llm()` 重构改动较大，再运行：

```powershell
uv run python -m unittest discover -s tests -v
```

## 10. 学习重点

本阶段完成后，应能回答：

- Planner、Executor、Orchestrator 的边界分别是什么？
- Planner 为什么不能调用业务工具？
- Planner 为什么不能授权 WRITE？
- PlanRun、Task State、RunState、RunRecord 的生命周期有什么区别？
- 为什么 v0 先做 plan preview 而不是自动执行？
- 为什么 v0 先做 transient plan，而不是持久化 PlanStore？
- Replan 为什么不需要每步都触发？
- 单步执行为什么更利于 Recovery 和安全验证？
- 自动更新 PlanStep 和自动更新 TaskStep 的授权边界有什么不同？

## 11. 后续可能升级

v0 稳定后，再考虑：

- 持久化 `PlanStore`。
- PlanRun 与 Task State 的显式保存 / 导入 / 导出。
- Recovery v1 基于 persisted plan 恢复当前 step。
- 多 step 连续执行，但需要用户明确授权执行范围。
- 更强的 route policy 或 LLM route。
- Plan Inspector / UI 页面。
- DAG / parallel execution。
- Long-running tasks / background scheduler。
- rollback / compensate。
- 与 LangGraph / OpenAI Agents SDK / OpenHands 等框架做结构对照。
