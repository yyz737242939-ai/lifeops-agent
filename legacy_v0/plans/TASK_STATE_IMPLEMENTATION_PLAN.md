# Task State v1 + Persistence v0 实现计划

本文档用于 Interaction / Safety State 之后继续施工。目标是让 LifeOps Agent 能记录一个跨 Chat 的长期任务，包括目标、步骤、状态、blocked 原因和恢复入口，并用最小本地持久化保存这些任务状态。

```text
用户长期目标
-> Task State 创建或选择任务
-> 记录步骤、当前进度、状态和 blocked 原因
-> 本地 JSON 持久化
-> 后续 Chat 可恢复任务现场
-> Planner / Recovery 后续基于 Task State 工作
```

本阶段不做复杂 Planner，也不做完整崩溃恢复系统。核心是先把“任务现场”从模型记忆和对话历史里拿出来，变成 Runtime 可读写、可观察、可测试的状态源。

## 0. 当前事实与施工边界

当前仓库已有：

- `app/runtime/run_state.py`：单次 `Agent.chat()` 的 RunState、ActionRecord、预算和终态。
- `app/runtime/write_policy.py`：当前输入写授权、批量删除确认和成功声明检测。
- `app/tools/capability_builder.py`：根据 Skill 和授权决定本轮模型可见 Tool Schema。
- `app/tools/executor.py`：工具授权、执行、重试、超时、幂等和错误归一化。
- `app/context/*`：对话工作上下文、Rolling Summary、Context Ref 和 Context Index。
- `app/memory/*`：只读 Profile Memory 与授权 Semantic Memory。
- `app/agents/agent.py`：Agent Loop、Context、Memory、Tool 和最终回答校验。

本阶段建议新增：

```text
app/tasks/
  __init__.py
  task_types.py
  task_store.py
  task_context.py

data/tasks/
  tasks.json

tests/
  test_task_store.py
  test_agent_task_state.py
```

具体文件名可在实现时按现有代码风格微调，但职责边界保持不变。

本阶段明确不做：

- 不做自动 Planner。
- 不做 Multi-Agent。
- 不做后台任务、定时任务或异步调度。
- 不做完整 Recovery。
- 不让 Task State 自动执行工具。
- 不把 Task State 混入 Memory。
- 不把 Task State 当作 Conversation Summary。
- 不从聊天历史中静默提取长期任务。
- 不把所有 Todo 自动升级成 Task State。

## 1. 核心目标

完成后，Agent 应该能管理这类长期任务：

```text
用户：创建一个任务：完成 Interaction / Safety State 第一版。
Agent：已创建任务，包含目标和初始步骤。
```

```text
用户：把当前任务的第一步标记完成，下一步是写 interaction_state.py。
Agent：已更新任务进度。
```

```text
用户：这个任务现在卡住了，原因是批量删除确认和旧 write_policy 有重叠。
Agent：已把任务标记为 blocked，并记录原因。
```

```text
用户：继续上次那个 Safety State 任务。
Agent：读取 Task State，告诉用户当前步骤和 blocked 状态，但不自动执行危险写入。
```

核心学习点：

- `RunState` 是一次 Chat 执行状态，Task State 是跨 Chat 的长期任务状态。
- Memory 保存用户长期事实和偏好，Task State 保存一个工作目标的进度。
- Context Engine 管理本轮工作上下文，Task State 是独立状态源。
- Task State 可以被注入本轮上下文，但不能依赖模型历史记忆。
- 持久化是 Task State v1 的一部分，否则跨 Chat 恢复没有事实源。
- 恢复任务不等于自动继续执行工具；危险步骤仍要经过 Safety State 和当前授权。

## 2. 数据模型

### TaskItem

第一版建议模型：

```text
id: str
title: str
goal: str
status: active | paused | blocked | completed | cancelled
steps: list[TaskStep]
current_step_id: str | None
progress_notes: list[TaskNote]
blockers: list[TaskBlocker]
created_at: str
updated_at: str
completed_at: str | None
source: user_authorized
tags: list[str]
```

字段说明：

- `title` 是短标题，用于列表和恢复选择。
- `goal` 是用户授权创建的长期目标。
- `status` 表示任务整体状态。
- `steps` 记录可执行或可检查的阶段。
- `current_step_id` 指向当前正在推进的步骤。
- `progress_notes` 记录关键进展，不保存完整聊天记录。
- `blockers` 记录 blocked 原因和状态。
- `source=user_authorized` 表示任务来自用户明确创建或更新。
- `tags` 用于简单筛选，例如 `runtime`、`learning`、`lifeops`。

### TaskStep

第一版建议模型：

```text
id: str
title: str
status: pending | in_progress | done | skipped | blocked
summary: str
created_at: str
updated_at: str
completed_at: str | None
```

规则：

- 一个任务可以没有步骤，但建议创建任务时至少允许用户提供或后续补充步骤。
- 同一时间第一版只维护一个 `current_step_id`。
- step 完成不等于整个 task 完成。
- blocked step 可以让 task 进入 blocked，也可以只记录局部 blocked；第一版优先让 task 进入 blocked，降低复杂度。

### TaskBlocker

第一版建议模型：

```text
id: str
reason: str
status: open | resolved
created_at: str
resolved_at: str | None
related_step_id: str | None
```

### TaskNote

第一版建议模型：

```text
id: str
content: str
created_at: str
related_step_id: str | None
```

## 3. Store 与持久化

第一版使用本地 JSON：

```text
data/tasks/tasks.json
```

建议文件结构：

```text
{
  "version": 1,
  "tasks": [
    ...
  ]
}
```

`TaskStore` 负责：

- 创建任务。
- 读取单个任务。
- 列出 active / paused / blocked 任务。
- 更新任务状态。
- 添加、更新、完成、跳过步骤。
- 设置当前步骤。
- 添加 progress note。
- 添加和解决 blocker。
- 取消或完成任务。

持久化规则：

- 写入必须是 JSON-safe。
- 文件不存在时返回空 store，不阻断 Agent。
- 写入前保证 `data/tasks/` 存在。
- 第一版不做数据库、不做事务、不做并发锁。
- 第一版可采用临时文件替换写入，降低半写入风险。

## 4. Tool 设计

建议新增 Task 工具：

```text
create_task
list_tasks
get_task
update_task_status
add_task_step
update_task_step
set_current_task_step
add_task_note
add_task_blocker
resolve_task_blocker
```

Tool effect 建议：

- `list_tasks`、`get_task` 是 READ。
- 其他都是 WRITE。

授权规则：

- 创建、修改、完成、取消任务都需要当前用户输入明确授权。
- 用户只是表达“我想做某事”不自动创建 Task。
- 用户说“帮我记成一个任务/创建任务/把这个任务标记完成”才授权写入 Task State。
- 恢复查看任务可以是 READ，不需要写授权。
- 恢复任务后若要继续执行危险操作，仍必须经过 Safety State 和当前授权。

第一版也可以先不暴露全部工具给模型，而是分两步施工：

1. 先完成 `TaskStore` 和直接单元测试。
2. 再接入最小 Agent 工具闭环：create/list/get/update status/add step/add note/add blocker。

## 5. Task Context 注入

`task_context.py` 负责把当前相关任务格式化成本轮只读上下文片段，例如：

```text
Current task:
- id: task_xxx
- title: Interaction / Safety State v1
- status: active
- current step: 状态模型
- blockers: none
```

注入规则：

- 用户明确说“继续上次任务/查看当前任务/这个任务下一步”时，读取相关 Task。
- 只注入摘要，不注入完整历史聊天。
- Task Context 不进入 `Agent.messages`。
- Task Context 不进入 Rolling Summary。
- Task Context 不写入 Memory。
- Task Context 可以在事件日志中记录 task id、status、step id 和字符数。

第一版检索策略：

- 如果用户给出 task id，精确读取。
- 如果用户说“当前任务/上次任务”，优先读取最近 updated 的 active / blocked / paused 任务。
- 如果用户给出关键词，按 title、goal、tag 简单匹配。
- 如果匹配多个任务，Agent 应要求用户选择，不自动猜测执行。

## 6. 与 Safety State 的关系

Task State 负责“任务做到哪里”，Safety State 负责“危险操作现在能不能执行”。

规则：

- Task State 可以记录“下一步需要删除旧数据”。
- 但记录下一步不等于授权删除。
- 恢复任务时，旧授权不能自动恢复。
- blocked 任务恢复后，如果下一步是危险写入，必须重新确认。
- pending confirmation 不应保存进 Task State；Task State 只可保存高层说明，例如“等待用户确认删除范围”。

一句话边界：

> Task State 保存长期工作现场；Safety State 保存短期危险操作确认。

## 7. 与 Planner / Recovery 的关系

本阶段为 Planner 和 Recovery 铺地基，但不实现它们。

Planner 以后会使用 Task State：

- 生成步骤。
- 选择下一步。
- 执行后更新 step 状态。
- 失败后调整计划。

Recovery 以后会使用 Task State：

- 程序重启后发现未完成任务。
- 判断任务停在 active、paused 还是 blocked。
- 根据 action records 和幂等信息决定能否继续。

本阶段只保证：

- 任务状态能可靠保存和读取。
- 用户能显式创建、查看、更新、暂停、恢复、取消和完成任务。
- Agent 能把相关 Task 摘要用于本轮回答。
- Task State 不自动驱动工具执行。

## 8. 可观测性

事件日志建议增加：

```text
task_created
task_updated
task_status_changed
task_step_added
task_step_updated
task_current_step_changed
task_note_added
task_blocker_added
task_blocker_resolved
task_context_injected
```

每条事件建议包含：

```text
task_id
task_status
step_id
step_status
blocker_id
operation
effect
status
reason
```

注意：

- 日志记录 id、状态和摘要即可。
- 不要把完整用户聊天历史写入 Task State 或事件日志。
- 失败写入必须有结构化错误，不能让模型声称任务已保存。

## 9. 测试计划

建议新增或更新测试：

```text
tests/test_task_store.py
tests/test_agent_task_state.py
tests/test_capability_builder.py
tests/test_write_policy.py
```

测试覆盖：

- 文件不存在时 `TaskStore` 返回空列表。
- 可以创建任务并持久化到 JSON。
- 可以重新实例化 store 后读取已有任务。
- 可以添加步骤、设置当前步骤和完成步骤。
- 可以暂停、恢复、取消、完成任务。
- 可以添加 blocker，并把任务标记为 blocked。
- 可以解决 blocker。
- 普通陈述长期目标不会自动创建任务。
- 明确“创建任务/保存为任务”才暴露 Task WRITE tools。
- `list_tasks` / `get_task` 是 READ。
- Task Context 注入不进入 `Agent.messages`。
- Task Context 不进入 Memory。
- 恢复任务不会自动执行危险工具。
- assistant 声称任务已更新但没有成功 WRITE Action 时会被最终回答校验修正。

第一版不默认运行全量测试。优先运行新增 Task 测试、write policy 测试、capability 测试和相关 Agent Loop 聚焦测试。

## 10. 分阶段实施

### Step 1: 计划与边界

目标：

- 新增本计划文档。
- 明确 Task State v1 和 Persistence v0 合并施工。
- 明确它和 RunState、Memory、Context、Safety State、Planner、Recovery 的边界。

验收：

- 计划说明 Task State 是长期工作现场，不是模型历史。
- 计划说明持久化是 v1 的一部分。
- 计划不把 Planner / Recovery 提前混进本阶段。

### Step 2: Task 数据模型

目标：

- 新增 `TaskItem`、`TaskStep`、`TaskBlocker`、`TaskNote`。
- 定义状态枚举和 JSON-safe 序列化。

验收：

- 模型能表达 active、paused、blocked、completed、cancelled。
- step 和 blocker 生命周期清晰。
- 单元测试覆盖基本创建和状态变更。

### Step 3: TaskStore + Persistence v0

目标：

- 实现本地 JSON store。
- 支持创建、读取、列表、更新状态、步骤、note 和 blocker。
- 支持重启后重新读取。

验收：

- 文件不存在时不报错。
- 写入后可重新加载。
- JSON 格式稳定，包含 `version`。
- 失败不会产生模型层面的虚假成功事实。

### Step 4: Task Tools 与授权

目标：

- 注册最小 Task tools。
- READ tools 可用于查看任务。
- WRITE tools 需要当前输入明确授权。

验收：

- 用户明确创建任务时，模型能看到 `create_task`。
- 用户只是表达目标时，不暴露 Task WRITE tools。
- `list_tasks` / `get_task` 不需要写授权。
- Executor 仍做二次校验。

### Step 5: Task Context 注入

目标：

- 实现 `task_context.py`。
- 用户请求继续或查看任务时，注入相关 Task 摘要。
- 多个候选任务时要求用户选择。

验收：

- “继续上次任务”能读取最近 active / blocked / paused 任务。
- 注入内容只包含必要摘要。
- Task Context 不进入 `Agent.messages`、Memory 或 Rolling Summary。

### Step 6: Agent 闭环

目标：

- 用户可通过自然语言创建任务、添加步骤、更新状态、记录 blocker、恢复查看任务。
- Agent 基于真实 Tool Observation 回复。

验收：

- 创建任务后能列出。
- 更新步骤后能再次读取到新状态。
- blocked 状态和原因可恢复。
- 恢复任务不会自动执行危险写入。

### Step 7: 文档同步

目标：

- 代码完成后更新 `PROJECT_CONTEXT.md`。
- 若学习阶段状态变化，再更新 `LEARNING_PROGRESS.md`。
- `CHANGELOG.md` 只有在用户明确要求阶段记录时再更新。

验收：

- 项目上下文记录 Task State v1 的稳定事实。
- 学习进度记录 Task State 和 Persistence v0 的核心学习结论。

## 11. 后续扩展

本阶段稳定后再考虑：

- Planner / Plan-and-Execute 基于 Task State 自动生成和推进步骤。
- Recovery v1 读取 Task State、ActionRecord 和幂等记录判断中断后能否继续。
- 多任务选择 UI。
- 任务优先级、截止时间、负责人和依赖关系。
- 任务模板。
- 后台任务和提醒。
- 与 Todo domain 的显式关联，但不自动互相复制。
- 更强的持久化格式、迁移和并发保护。

## 12. 学习检查问题

每一步完成后，都要能回答：

```text
这个状态属于 RunState、Task State、Memory、Context 还是 Safety State？
为什么 Task State 需要本地持久化？
为什么恢复任务不等于自动执行下一步？
Task State 和 Todo domain 的区别是什么？
Task State 和 Planner 的区别是什么？
Task State 和 Recovery 的关系是什么？
任务 blocked 时，Runtime 应该保存什么，不应该臆测什么？
用户长期目标什么时候应该进入 Memory，什么时候应该成为 Task？
```
