# Interaction / Safety State 实现计划

本文档用于下一阶段继续施工。目标是在已有 Tool、Capability、Write Safety、Context、Memory 和 MCP 边界之上，新增一层跨轮的交互安全状态：

```text
用户请求
-> 当前输入写授权分析
-> Interaction / Safety State 检查 pending confirmation
-> Capability Builder 决定本轮可见工具
-> Agent Loop / Tool Executor 执行真实 Action
-> Interaction / Safety State 更新或清理
```

本阶段学习重点不是让模型“更礼貌地问一句确认”，而是让 Runtime 持有可观察、可过期、可取消、可修改的安全事实。模型文本只能提出或解释确认，真正能否执行危险写入必须由 Runtime 状态和当前用户输入共同决定。

## 0. 当前事实与施工边界

当前仓库已有：

- `app/runtime/write_policy.py`：当前用户输入的写授权、批量删除确认和成功声明检测。
- `app/runtime/run_state.py`：单次 `Agent.chat()` 的 RunState、ActionRecord、预算和终态。
- `app/tools/capability_builder.py`：根据 Skill 和授权决定本轮模型可见 Tool Schema。
- `app/tools/executor.py`：工具授权、执行、重试、超时、幂等和错误归一化。
- `app/agents/agent.py`：Skill、Prompt、Capability、Context、Memory、LLM 和 Tool 编排。
- `app/context/*`：对话工作上下文、Rolling Summary、Context Ref 和 Context Index。
- `app/memory/*`：只读 Profile Memory 与用户授权 Semantic Memory。
- `app/mcp/*`：MCP v1 Agent 侧 Adapter 和只读 Mock Package Tracking 接入。

本阶段建议新增：

```text
app/runtime/interaction_state.py
app/runtime/interaction_policy.py

tests/test_interaction_state.py
tests/test_agent_interaction_safety.py
```

具体文件名可在实现时按现有代码风格微调，但职责边界保持不变。

本阶段明确不做：

- 不做长期 Task State。
- 不做复杂 Planner 或 Multi-Agent。
- 不做后台自动任务、定时任务或调度系统。
- 不接真实外部账号、OAuth 或真实高风险 API。
- 不把 pending confirmation 写入 Memory。
- 不把 pending confirmation 压缩进 Conversation Summary。
- 不实现复杂自然语言理解型安全策略；第一版优先使用确定性规则。
- 不把所有 WRITE 工具都改成两阶段确认；只处理高风险或批量写入。

## 1. 核心目标

完成后，Agent 应该能处理以下多轮场景：

```text
用户：把所有已完成 todo 都删掉。
助手：这会删除 12 条已完成 todo，请确认。
用户：确认。
-> Runtime 执行删除。
```

```text
用户：删除所有记忆。
助手：这是高风险操作，请确认要删除全部 active memory。
用户：算了。
-> Runtime 清理 pending 状态，不执行删除。
```

```text
用户：把所有已完成 todo 都删掉。
助手：这会删除 12 条已完成 todo，请确认。
用户：不是全部，只删今天完成的。
-> Runtime 作废旧 pending，创建新范围或要求重新确认。
```

```text
用户：把所有已完成 todo 都删掉。
助手：这会删除 12 条已完成 todo，请确认。
用户：今天天气怎么样？
用户：确认。
-> 如果 pending 已过期，Runtime 不执行旧删除。
```

核心学习点：

- 当前输入写授权只属于当前 turn。
- pending confirmation 是跨轮临时 Runtime State，不是长期 Memory。
- `RunState` 记录一次 Chat 执行，Interaction State 记录跨轮待确认意图。
- Capability 负责本轮模型能看到什么工具，Interaction State 负责危险操作是否需要先确认。
- 高风险操作必须能取消、修改范围和过期。
- assistant 声称“已确认/已删除”仍不可信，真实执行必须看成功 WRITE Action。

## 2. 状态模型

### PendingConfirmation

第一版建议模型：

```text
id: str
operation: str
tool_name: str | None
risk_level: low | medium | high
scope_summary: str
arguments: dict
created_at: str
created_turn_index: int
expires_after_turns: int
status: pending | confirmed | cancelled | expired | superseded
requires_current_confirmation: bool
source_user_input: str
```

字段说明：

- `operation` 描述用户意图，例如 `delete_completed_todos`、`delete_memory`、`clear_budget`。
- `tool_name` 只在范围和工具已确定时填写；不确定时可为空。
- `risk_level` 决定是否需要二次确认和过期策略。
- `scope_summary` 是给用户看的确认范围摘要。
- `arguments` 保存候选工具参数或范围条件，但不能绕过后续授权校验。
- `created_turn_index` 和 `expires_after_turns` 用于过期。
- `status` 用于解释 pending 生命周期。
- `source_user_input` 用于可观测性和调试，不作为长期记忆。

### InteractionState

第一版建议 `Agent` 持有一个轻量 `InteractionState`：

```text
pending_confirmation: PendingConfirmation | None
turn_index: int
```

规则：

- 同一时间第一版只允许一个 active pending confirmation。
- 新的高风险请求可以 supersede 旧 pending。
- 用户取消后 pending 立即清理或标记 cancelled。
- 用户确认后 pending 只能在本轮消费一次。
- 过期 pending 不能再恢复执行。

## 3. 策略判断

### 需要确认的操作

第一版优先覆盖：

- 批量删除 Todo。
- 删除全部或多条 Memory。
- 删除单条 Memory 但用户表达含糊。
- 覆盖或清空预算。
- 未来 MCP WRITE 或外部副作用工具的预留风险分类。

暂不强制确认：

- 新增单条 Todo。
- 完成单条 Todo。
- 新增单条消费记录。
- 记录每日状态。
- 保存一条明确授权的 Semantic Memory。

原因：

- 当前已有写授权规则保护普通写入。
- 本阶段重点学习危险操作的跨轮安全状态，不要把所有写入都变成复杂流程。

### 确认 / 取消 / 修改

第一版可用确定性规则识别：

```text
确认：确认、是的、对、继续、执行、可以、yes、confirm
取消：取消、算了、不要了、别删、停止、撤销、no、cancel
修改：不是、改成、只、仅、范围、别、除了
```

规则：

- 没有 active pending 时，单独“确认”不能授权任何危险操作。
- 有 active pending 时，确认只消费该 pending 的候选操作。
- 取消会清理 pending，不执行工具。
- 修改范围时，不执行旧 pending；Runtime 应创建新 pending 或要求用户重新确认。
- 模糊确认不能扩大原始范围。

## 4. Runtime 接入点

建议接入顺序：

```text
Agent.chat(user_input)
-> interaction_state.advance_turn()
-> interaction_policy.classify_reply_to_pending(user_input, pending)
-> 如果取消：清理 pending，回复已取消
-> 如果过期确认：清理 pending，回复需要重新说明操作
-> 如果确认：生成本轮临时授权或候选工具调用条件
-> 如果修改：作废旧 pending，重新分析新范围
-> 否则继续现有 _prepare_turn()
```

危险操作的创建路径：

```text
用户提出高风险写入
-> write_policy / interaction_policy 判断需要 confirmation
-> 不暴露最终危险工具，或不允许立即执行
-> assistant 请求用户确认
-> InteractionState 保存 PendingConfirmation
```

确认后的执行路径：

```text
用户确认 pending
-> Runtime 检查 pending 未过期、未取消、未消费
-> 本轮暴露或允许对应 WRITE tool
-> Tool Executor 正常执行
-> 成功或失败都清理 pending
```

关键边界：

- pending confirmation 不进入 `Agent.messages` 作为事实源。
- pending confirmation 不进入 Memory。
- pending confirmation 不进入 Rolling Summary。
- pending confirmation 可以写入事件日志。
- 最终是否执行仍以 Tool Executor 和成功 WRITE Action 为准。

## 5. Capability / Write Policy 关系

现有 `authorized_write_tools(user_input)` 只判断当前输入有没有写授权。本阶段不要把它膨胀成所有交互状态的容器。

建议新增 `interaction_policy.py`，负责：

- 判断某个授权写入是否还需要二次确认。
- 判断用户当前输入是不是在回应 pending。
- 判断 pending 是否过期。
- 生成本轮允许执行的 pending operation。

`capability_builder.py` 仍负责：

- 根据当前 Skill 和授权结果暴露 Tool Schema。
- 不关心 pending 的生命周期细节。

`write_policy.py` 仍负责：

- 当前输入是否明确授权写入。
- assistant 成功声明是否有 WRITE Action 支撑。
- 已有批量删除确认逻辑可逐步迁移到 Interaction / Safety State。

## 6. 可观测性

事件日志建议增加或复用事件字段：

```text
interaction_pending_created
interaction_pending_confirmed
interaction_pending_cancelled
interaction_pending_expired
interaction_pending_superseded
interaction_pending_consumed
```

每条事件建议包含：

```text
pending_id
operation
tool_name
risk_level
scope_summary
status
created_turn_index
current_turn_index
expires_after_turns
reason
```

注意：

- 可以记录范围摘要和 id。
- 不要无差别复制大量用户隐私正文。
- 不要把 Memory/Profile 正文写进 pending 诊断。

## 7. 测试计划

建议新增或更新测试：

```text
tests/test_interaction_state.py
tests/test_agent_interaction_safety.py
tests/test_write_policy.py
tests/test_capability_builder.py
```

测试覆盖：

- 创建 pending confirmation。
- pending confirmation 能确认并消费一次。
- 取消 pending 后不执行工具。
- 过期 pending 不能确认执行。
- 新高风险请求会 supersede 旧 pending。
- 用户修改范围时旧 pending 不执行。
- 没有 pending 时，“确认”不能授权危险写入。
- 普通单条写入仍按现有写授权执行，不被强制二次确认。
- 批量删除 Todo 需要确认。
- 删除多条 Memory 需要确认。
- pending 不进入 Memory。
- pending 不进入 Context Summary。
- assistant 声称已执行但没有成功 WRITE Action 时仍会被纠正。

第一版不默认运行全量测试。优先运行新增 interaction 测试、write policy 测试、capability 测试和相关 Agent Loop 聚焦测试。

## 8. 分阶段实施

### Step 1: 计划与边界

目标：

- 新增本计划文档。
- 明确 Interaction / Safety State 和 `RunState`、Memory、Context、Capability 的边界。

验收：

- 计划说明当前阶段只做跨轮临时安全状态。
- 明确不进入 Task State、Planner、Multi-Agent。
- 明确 pending confirmation 不是 Memory，也不是 Conversation Summary。

### Step 2: 状态模型

目标：

- 新增 `PendingConfirmation` 和 `InteractionState`。
- 支持创建、确认、取消、过期、supersede 和 consume。

验收：

- 单元测试覆盖 pending 生命周期。
- 同一 pending 不能被重复消费。
- 过期状态不可执行。

### Step 3: Policy 判断

目标：

- 新增或整理 `interaction_policy.py`。
- 识别确认、取消、修改和无 pending 的孤立确认。
- 定义第一版高风险操作规则。

验收：

- 确定性规则能覆盖核心中文表达。
- 修改范围不会执行旧 pending。
- 没有 pending 时确认不会产生授权。

### Step 4: Agent Runtime 接入

目标：

- 在 `Agent.chat()` 或 `_prepare_turn()` 前后接入 Interaction State。
- 高风险写入先创建 pending。
- 用户确认后才进入真实工具执行路径。

验收：

- 批量删除 Todo 先要求确认。
- 用户确认后执行真实 WRITE tool。
- 用户取消后不执行。
- 确认过期后要求重新说明操作。

### Step 5: Capability / Write Safety 收口

目标：

- 保持 Capability Builder 和 Executor 的二次校验。
- 将已有批量删除确认逻辑逐步收敛到 Interaction / Safety State。
- 确认普通写入不被意外阻断。

验收：

- 当前输入无授权时 WRITE tool 不可见。
- pending 确认只授权对应范围的操作。
- assistant 虚假成功声明仍会被 final answer guard 修正。

### Step 6: Observability 与文档同步

目标：

- 为 pending 生命周期增加事件日志。
- 代码完成后更新 `PROJECT_CONTEXT.md`。
- 阶段状态变化后更新 `LEARNING_PROGRESS.md`。
- `CHANGELOG.md` 只有在用户明确要求阶段记录时再更新。

验收：

- 日志能解释 pending 为什么创建、取消、过期或执行。
- 文档记录 Interaction / Safety State 的稳定事实和学习结论。

## 9. 后续扩展

本阶段稳定后再考虑：

- 多个 pending confirmation 队列。
- 更细的风险等级和工具级 policy 表。
- 将外部账号、OAuth 和 MCP WRITE tool 纳入确认策略。
- 把长期目标、暂停、恢复、blocked 状态升级为 Task State。
- 为后台任务和定时任务增加人类确认窗口。
- 更强的 Policy / Permission Layer。
- Planner 在执行高风险步骤前主动生成确认节点。

## 10. 学习检查问题

每一步完成后，都要能回答：

```text
这个状态属于 RunState、Interaction State、Task State、Memory 还是 Context？
当前输入授权为什么不能跨轮自动延续？
pending confirmation 为什么不能进入 Memory？
assistant 说“用户已确认”为什么不等于 Runtime 确认？
取消、修改范围和过期分别如何改变 pending 生命周期？
Capability Builder 和 Interaction Policy 的责任边界在哪里？
真实执行事实为什么仍然要看成功 WRITE Action？
如果未来接入 MCP WRITE tool，需要新增哪些安全检查？
```
