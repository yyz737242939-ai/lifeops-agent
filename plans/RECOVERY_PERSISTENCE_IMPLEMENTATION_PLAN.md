# Recovery / Persistence v0 实现计划

本文档用于 Task State v1 之后继续施工。目标是给 LifeOps Agent 增加最小的 Runtime 恢复地基：记录一次 `Agent.chat()` 的关键状态、工具 Action 的执行结果和中断提示，让后续 Plan and Execute 不再是黑箱连续执行。

```text
用户请求
-> RunState 开始
-> 工具 Action 执行并写入 ActionRecord
-> RunRecordStore 持久化本轮关键状态
-> Agent 停止、失败或重启
-> Recovery Context 提示上次停在哪里
-> 用户决定查看、继续或重新开始
```

本阶段不做完整 workflow engine，也不做自动 replay。核心是先让 Runtime 拥有可恢复、可观察、可测试的运行事实。

## 0. 当前事实与施工边界

当前仓库已有：

- `app/runtime/run_state.py`：单次 `Agent.chat()` 的内存态 `RunState`、`ActionRecord`、预算和终态。
- `app/runtime/idempotency_store.py`：成功 WRITE 结果的本地 idempotency 缓存。
- `app/tools/executor.py`：工具授权、执行、超时、重试入口和 WRITE idempotency replay。
- `app/agents/agent.py`：Agent Loop、RunState 生命周期、工具 Action 记录和最终回答校验。
- `app/tasks/*`：Task State v1、TaskStore 和 Task Context，可表达长期任务现场。
- `app/runtime/write_policy.py` 与 `app/interaction/*`：当前输入授权与高风险写入确认。
- `app/observability/*`：事件日志、LLM 日志和运行过程观测。

本阶段建议新增：

```text
app/recovery/
  __init__.py
  recovery_types.py
  run_record_store.py
  recovery_context.py

data/recovery/
  runs.json

tests/
  test_run_record_store.py
  test_recovery_context.py
  test_agent_recovery.py
```

具体文件名可在实现时按现有代码风格微调，但职责边界保持不变。

本阶段明确不做：

- 不做自动继续执行工具。
- 不做崩溃后自动 replay。
- 不做事务系统、补偿系统或多进程锁。
- 不做复杂 workflow / DAG / job queue。
- 不替代现有 `RunState`；`RunState` 仍是单次 Chat 的内存执行状态。
- 不把 Recovery Context 写进 Memory、Task State、`Agent.messages` 或 Rolling Summary。
- 不把所有失败都判定为可恢复。
- 不提前实现 Planner 或 Plan and Execute。

## 1. 核心目标

完成后，Agent 应该能处理这类恢复场景：

```text
第一次运行：
用户：帮我创建一个任务，并加两个步骤。
Agent：成功创建任务，添加第一个步骤，第二个步骤失败。
Runtime：把 run、成功 action、失败 action 持久化。
```

```text
重启后：
用户：继续刚才的任务。
Agent：先提示上次 run 的恢复信息：最后成功动作是什么，失败动作是什么，哪些需要重新确认。
```

```text
用户：继续执行。
Agent：不自动 replay 旧工具调用；只基于当前用户输入重新判断授权和下一步。
```

核心学习点：

- `RunState` 是当前进程内的一次执行状态，`RunRecord` 是可跨进程读取的运行记录。
- `ActionRecord` 记录工具调用事实，不等于长期任务进度；Task State 才记录任务做到哪里。
- 成功 WRITE 的 idempotency 缓存用于防重复写，不等于完整 Recovery。
- Recovery 的第一版只提示和保护，不自动继续执行。
- 恢复上下文可以注入本轮请求，但不能自动扩大权限。
- 高风险或不确定 Action 在恢复后必须重新走当前输入授权和 Safety State。

## 2. 状态归属边界

### RunState

`RunState` 仍然只属于一次 `Agent.chat()`：

```text
run_id
status
llm round count
tool attempt count
in-memory action_records
stop_reason
budgets
```

它负责当前执行过程的控制和统计，不负责跨 Chat 恢复事实。

### RunRecord

`RunRecord` 是持久化后的运行摘要：

```text
run_id
status
started_at
ended_at
stop_reason
task_id optional
user_input_summary
last_successful_action
last_failed_action
action_count
created_at
updated_at
```

它负责重启后告诉 Runtime：“上一次做到哪里了”。

### PersistentActionRecord

持久化 Action 只保存恢复需要的字段：

```text
action_id
run_id
call_id
tool_name
arguments_hash
arguments_preview
status
effect
idempotency_key
result_summary
error_summary
created_at
updated_at
```

不要把完整大 Observation 或敏感原始输入塞进 Recovery store。完整工具结果仍按现有日志、Context Ref 或业务 store 的边界处理。

### Task State

Task State 记录长期工作现场：

```text
task_id
goal
steps
current_step_id
blockers
notes
status
```

Recovery 可以引用 `task_id`，但不把 RunRecord 直接写成 Task note，除非用户明确要求记录。

### Memory

Memory 只保存用户授权的长期事实、偏好和约束。Recovery 记录不自动进入 Memory。

### Context

Recovery Context 是本轮 request-local 输入层。它可以告诉模型上次运行摘要，但不进入 `Agent.messages`、Rolling Summary 或 ContextIndex。

## 3. 数据模型草案

### RecoveryStatus

```python
RecoveryRunStatus = Literal[
    "running",
    "completed",
    "partial",
    "failed",
    "stopped",
    "interrupted",
]

RecoveryActionStatus = Literal[
    "completed",
    "failed",
    "skipped",
]
```

说明：

- `running` 表示进程写入了开始记录，但还没写终态。
- `completed` 表示本轮正常结束。
- `partial` 表示已有成功 Action，但因预算、取消或 LLM 错误停止。
- `failed` 表示没有可确认成功的 Action 或遇到不可恢复错误。
- `stopped` 表示 Runtime 有意停止，例如预算耗尽或循环保护。
- `interrupted` 表示下一次启动时发现旧记录仍是 `running`，推断上次进程非正常退出。

### RunRecord

建议字段：

```python
@dataclass
class RunRecord:
    run_id: str
    status: RecoveryRunStatus
    started_at: str
    ended_at: str | None
    stop_reason: str | None
    task_id: str | None
    user_input_summary: str
    last_successful_action: PersistentActionRecord | None
    last_failed_action: PersistentActionRecord | None
    action_count: int
    created_at: str
    updated_at: str
```

### PersistentActionRecord

建议字段：

```python
@dataclass
class PersistentActionRecord:
    action_id: str
    run_id: str
    call_id: str
    tool_name: str
    arguments_hash: str
    arguments_preview: dict[str, Any]
    status: RecoveryActionStatus
    effect: Literal["read", "write"]
    idempotency_key: str | None
    result_summary: str | None
    error_summary: str | None
    created_at: str
    updated_at: str
```

### Store 文件格式

```json
{
  "version": 1,
  "runs": [
    {
      "run_id": "run_xxx",
      "status": "partial",
      "started_at": "...",
      "ended_at": "...",
      "stop_reason": "llm_request_failed",
      "task_id": "task_xxx",
      "user_input_summary": "继续 Task State 任务",
      "last_successful_action": {},
      "last_failed_action": {},
      "action_count": 2,
      "actions": []
    }
  ]
}
```

第一版可以把 `actions` 嵌在 run 里，避免先做复杂索引。后续如果记录量变大，再拆成 JSONL 或按 run 分文件。

## 4. RunRecordStore

新增 `RunRecordStore`，职责类似 `TaskStore`，但服务 Runtime Recovery：

```text
start_run(run_state, user_input_summary, task_id=None)
record_action(run_id, action_record, tool_effect)
finish_run(run_state)
mark_stale_running_as_interrupted()
get_latest_recoverable_run()
list_recent_runs(limit=10)
```

要求：

- 文件不存在时返回空记录。
- JSON 包含 `version`。
- 写入使用现有 `read_json_file` / `write_json_file` 工具。
- `running` 记录在下一次 Agent 启动或下一轮 chat 前可被标记为 `interrupted`。
- 只保存必要摘要，不保存完整用户长文本或大 Observation。

## 5. Agent 接入点

接入点保持很小：

1. `Agent.chat()` 创建 `RunState` 后调用 `RunRecordStore.start_run()`。
2. 每次 `run_state.add_action()` 后同步 `RunRecordStore.record_action()`。
3. run 进入 completed / partial / failed / stopped 时调用 `RunRecordStore.finish_run()`。
4. 新一轮用户输入前调用 `mark_stale_running_as_interrupted()`。
5. 如果用户输入有恢复意图，例如“继续刚才/恢复上次/上次失败在哪”，则注入 Recovery Context。

不要在 `_execute_tool` 内部直接写 Recovery store。第一版由 Agent Loop 持有 run 语义，Executor 仍只负责执行一个工具。

## 6. Recovery Context

新增 `recovery_context.py`：

```text
RecoveryContextBuilder
RecoveryContextResult
RECOVERY_CONTEXT_TITLE = "Recent recovery context (read-only)"
```

触发条件：

- 用户说“继续刚才”
- 用户说“恢复上次”
- 用户问“上次失败在哪”
- 用户问“刚才做到哪了”
- 当前 Task Context 找到任务，且存在相关 interrupted / partial / failed run

注入内容：

```text
Recent recovery context (read-only)
- run_id
- status
- stop_reason
- related task_id if any
- last successful action
- last failed action
- recovery rules:
  - Do not replay tools automatically.
  - Re-check current user authorization before any WRITE.
  - Ask the user when the next action is ambiguous or risky.
```

多个候选 run 时，注入候选列表并要求用户选择，不自动猜。

## 7. Idempotency 边界

现有 `idempotency_store.py` 已经能缓存成功 WRITE 结果。Recovery v0 不重写它，只补清楚边界：

- idempotency 防止同一个 WRITE 结果被重复执行。
- RunRecord 告诉用户上次执行到哪里。
- Recovery Context 提醒模型不要自动 replay。
- 当前输入授权仍由 `write_policy.py`、Interaction State 和 Executor 二次校验负责。

可以在后续小步中考虑把 `idempotency_key` 从 `run_id:call_id` 升级为更稳定的 action signature，但本阶段不强求。

## 8. 安全规则

Recovery v0 必须遵守：

- interrupted / partial run 不等于当前授权。
- 恢复任务不等于继续执行工具。
- 成功 READ 可以作为参考，但不应被当成业务写入事实。
- 成功 WRITE 的事实来源仍是业务 store 或工具返回的 `ok=true`。
- 高风险 WRITE 恢复后必须重新确认。
- 如果上次 Action 状态不确定，默认不自动重试。
- 如果模型声称“已恢复执行”，必须有本轮成功 Tool Observation 支撑。

## 9. 与 Plan and Execute 的关系

本阶段是 Plan and Execute v0 的地基，但不实现 Planner：

```text
Planner 后续会生成步骤
-> Executor 执行一个步骤
-> ActionRecord / RunRecord 落盘
-> 失败或中断后 Recovery Context 解释状态
-> 用户授权后 Planner 再决定下一步
```

Recovery v0 完成后，Plan and Execute 可以先做很小：

- 生成 2-5 个短步骤。
- 一次只执行一个步骤。
- 每步执行前检查 Capability 和 Policy。
- 每步执行后写 ActionRecord / RunRecord。
- 中断后让 Recovery 提示，而不是让 Planner 自己猜。

## 10. 分阶段实施

### Step 1: 计划与边界

目标：

- 新增本计划文档。
- 明确 Recovery / Persistence v0 的最小范围。
- 明确它和 RunState、ActionRecord、Task State、Memory、Context、Idempotency、Planner 的边界。

验收：

- 计划说明 Recovery v0 只提示和保护，不自动 replay。
- 计划说明 RunRecord 是跨进程运行记录，RunState 仍是单次 Chat 内存状态。
- 计划说明本阶段完成后才进入 Plan and Execute v0。

### Step 2: Recovery 数据模型

目标：

- 新增 `RunRecord`、`PersistentActionRecord` 和状态类型。
- 提供 JSON-safe 序列化和反序列化。

验收：

- 模型能表达 running、completed、partial、failed、stopped、interrupted。
- action 能表达 completed、failed、skipped。
- 单元测试覆盖基本创建、序列化和非法状态。

### Step 3: RunRecordStore + Persistence v0

目标：

- 实现本地 JSON store。
- 支持 start、record action、finish、list recent、latest recoverable。
- 支持把 stale running run 标记为 interrupted。

验收：

- 文件不存在时不报错。
- 写入后可重新实例化读取。
- JSON 格式稳定，包含 `version`。
- interrupted 推断只发生在旧 `running` 记录上。

### Step 4: Agent Run 持久化接入

目标：

- 在 `Agent.chat()` run 生命周期里接入 RunRecordStore。
- 每个 ActionRecord 产生后同步持久化摘要。
- Run 终态时更新持久化状态。

验收：

- 正常完成 run 记录为 completed。
- 有成功 action 后预算/错误停止记录为 partial。
- 无成功 action 的错误记录为 failed 或 stopped。
- 已有事件日志行为不被破坏。

### Step 5: Recovery Context 注入

目标：

- 实现 `RecoveryContextBuilder`。
- 用户有恢复意图时读取最近 recoverable run。
- 把恢复摘要作为 read-only request-local system context 注入。

验收：

- “继续刚才”能看到上次 partial / interrupted / failed run。
- 注入内容不进入 `Agent.messages`、Memory 或 Rolling Summary。
- 多候选 run 时要求用户选择。
- 恢复上下文不暴露额外 WRITE tools。

### Step 6: Recovery 行为闭环

目标：

- Agent 能自然语言回答“上次做到哪了/失败在哪/最后成功动作是什么”。
- Agent 不自动 replay 旧工具调用。
- 当前用户明确授权后，才按普通 Tool 流程继续执行。

验收：

- 重启后能提示上次 run 的 stop_reason 和最后 action。
- 恢复请求不会自动执行 WRITE。
- 如果模型尝试未授权 WRITE，Executor 仍拒绝。
- 最终回答不能把“恢复上下文”说成“已执行”。

### Step 7: 文档同步

目标：

- 代码完成后更新 `PROJECT_CONTEXT.md`。
- 若学习阶段状态变化，再更新 `LEARNING_PROGRESS.md`。
- `CHANGELOG.md` 只有在用户明确要求阶段记录时再更新。

验收：

- 项目上下文记录 Recovery / Persistence v0 的稳定事实。
- 学习进度记录 Recovery、RunRecord、ActionRecord、Idempotency 和 Task State 的边界。

## 11. 后续扩展

本阶段稳定后再考虑：

- Plan and Execute v0。
- 更稳定的 action signature idempotency key。
- Recovery Inspector 或 CLI 查看最近 run。
- 按 run 分文件或 JSONL 存储。
- 更细的风险等级和 Permission Layer。
- 可恢复 LLM request 状态。
- 多任务、多 Agent 或后台任务的恢复队列。
- 真正的 replay / compensate / rollback 机制。

## 12. 学习检查问题

每一步完成后，都要能回答：

```text
这个状态属于 RunState、RunRecord、ActionRecord、Task State、Memory 还是 Context？
为什么 RunState 不应该直接承担跨 Chat 恢复？
为什么 Recovery v0 不自动 replay 工具？
idempotency 和 Recovery 的区别是什么？
成功 WRITE 的事实来源是什么？
为什么 interrupted run 不等于当前用户授权？
Recovery Context 为什么不进入 Agent.messages？
Task State 的 blocked 和 RunRecord 的 failed 有什么区别？
Plan and Execute 为什么应该在 Recovery v0 之后做？
```
