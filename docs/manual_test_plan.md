# LifeOps Agent 统一手动测试计划

## 1. 目标与范围

本计划是项目唯一的手动测试入口，覆盖此前所有测试计划中的内容：

- Todo、Wellbeing、Finance、Activity 四个业务领域。
- Skill 元数据发现、确定性路由、正文按需加载和动态 Prompt。
- 动态 Tool Schema、最小能力暴露和 Runtime 二次授权。
- 多轮 Skill 继承、切换、清理和 Context Ref-only 状态。
- Context inline、summary、reference 压缩与渐进式展开。
- Agent Loop、RunState、调用预算、ActionRecord 和停止状态。
- 错误分类、重试、重复/无进展检测、幂等、部分成功、超时和取消。
- Event、LLM I/O、Application 三通道日志及 Viewer。

测试重点不是只看最终回答，而是对照日志理解完整链路：

```text
用户输入
-> routing.resolved
-> capability.built
-> llm.request / llm.response
-> tool.started / tool.completed / tool.failed
-> Context 压缩或 Ref
-> run.completed / run.stopped
```

## 2. 测试准备

启动 Agent 和 Viewer：

```powershell
uv run python main.py
uv run python log_viewer.py
```

运行静态与自动化基线检查：

```powershell
uv run python -m compileall -q app tests
uv run python -m unittest discover -s tests -v
```

不要为了测试清空已有的 `data/*.json`、`logs/` 或 Context Ref。写入类场景应使用容易识别的测试描述，并记录测试前后的数据变化。

每次启动 Agent 会创建：

```text
logs/sessions/session_<timestamp>/
├── metadata.json
├── events.jsonl
├── llm.jsonl
└── application.log
```

其他运行数据：

```text
data/todos.json
data/daily_logs.json
data/expenses.json
data/budgets.json
data/idempotency.json
logs/context_refs/ctx_*.json
```

## 3. 通用观察方法

每个场景至少记录：

- 用户输入与最终回答。
- `session_id`、`run_id`、RunStatus、StopReason。
- 直接选择、继承和最终加载的 Skill。
- 模型可见工具与实际调用工具。
- 每个 Function Call 的 `call_id`、参数、Action 状态和 Observation。
- LLM 轮数、LLM attempt、工具 attempt 与累计工具调用数。
- Context 压缩策略和 `ref_id`。

三类日志的边界：

- Events：Runtime 决策、工具 Action、压缩与状态变化。
- LLM I/O：完整 `llm.request` 和 `llm.response`，不混入 Tool Result。
- Application：传统 INFO/WARNING/ERROR 进程日志。

失败时按以下顺序定位：

1. `routing.resolved` 是否选择正确 Skill。
2. `llm.request.instructions` 是否只加载目标 Skill 正文。
3. `capability.built` 与 `llm.request.tools` 是否一致。
4. 模型选择的工具和参数是否正确。
5. Event 中的 Action result 与业务文件是否一致。
6. Observation 压缩是否保留后续操作所需的 ID、日期和金额。
7. 最终回答是否忠于 Observation。

## 4. 日志系统与 Viewer

### 4.1 无工具普通回答

输入：

```text
你好，简单介绍一下自己。
```

预期：

- Event 包含 `run.started`、`llm.requested`、`llm.responded`、`run.completed`。
- LLM I/O 只包含实际 request/response。
- Application 包含 run started/completed。
- 三个通道使用相同 `session_id`，Event 与 LLM I/O 使用相同 `run_id`。

### 4.2 Viewer 交互

依次切换 `Events`、`LLM I/O`、`Application`，验证：

- 会话按时间倒序排列。
- 三个标签可以独立显示、筛选、搜索和展开 JSON。
- Application 级别日志被解析成事件卡片。
- 浏览器控制台没有错误。
- 历史 `*_trace.json`、`*_raw.json` 如仍存在，可分别通过 Events、LLM I/O 查看。

### 4.3 错误日志边界

使用可控 Fake LLM 制造一次模型错误，验证：

- Event 记录 `llm.failed`，可重试时记录 `llm.retry_scheduled`。
- Application 记录 ERROR。
- LLM I/O 不出现 Tool Result 或伪造的模型 response。

## 5. Skill Loader、Routing 与 Prompt

### 5.1 Skill 结构

检查四个 `app/skills/*/SKILL.md`：

- frontmatter 只有 `name` 和 `description`。
- name 与目录名完全一致。
- description 能独立表达触发范围。
- 正文只包含必要的领域编排和 Ref 规则。
- Skill 不提供任意脚本执行能力。

### 5.2 单领域路由

| 输入 | 期望 Skill | 期望主要工具 |
| --- | --- | --- |
| 提醒我明天完成 Agent 笔记 | todo | add_todo |
| 列出我的待办任务 | todo | list_todos |
| 我昨晚睡了 5 小时，今天能量低，记一下 | wellbeing | record_daily_state |
| 查看我最近一周的状态 | wellbeing | list_daily_logs |
| 今天午饭花了 35 元，记到餐饮 | finance | record_expense |
| 检查本周餐饮预算 | finance | check_budget |
| 推荐一个 20 分钟、不花钱的恢复活动 | activity | recommend_activities |

每次验证：

- `directly_selected` 只包含输入直接匹配的领域。
- `reasons` 能解释匹配依据，`fallback_used=false`。
- Prompt 不包含其他 Skill 的 `Loaded skill:` 标记。
- 可见工具只包含目标领域和公共工具。

### 5.3 跨领域路由

输入：

```text
我昨晚只睡了 5 小时，今天能量低。这周餐饮预算紧，还有重要任务。
帮我安排现实一点的今天计划，并推荐一个免费的恢复活动。
```

预期：

- 选择 wellbeing、finance、todo、activity，且每项有独立原因。
- Prompt 包含四个 Skill 正文，每个工具只出现一次。
- 可能调用状态、预算、`plan_day` 和活动推荐工具。
- 最终计划考虑能量、预算、优先级和恢复活动。
- 未经工具返回的精确金额不得虚构。

### 5.4 Fallback 与歧义

| 输入 | 预期 |
| --- | --- |
| 你好，介绍一下自己 | 不加载领域 Skill，只暴露公共工具 |
| 提醒我完成预算报告任务 | 只选择 Todo，不误选 Finance |
| 我最近状态怎么样 | 选择 Wellbeing |
| 帮我规划一下 | 当前可能 fallback，作为召回观察样本 |
| 把刚才的明细展开 | 使用 Ref-only 规则，不必加载领域 Skill |

不要因为单个失败样本立即堆叠关键词；先记录 Router、Prompt、Tool 和最终回答分别在哪一层偏离。

### 5.5 Prompt Budget

分别运行普通对话、单领域和四领域输入，比较 `prompt_chars` 与完整 instructions：

- 普通对话只包含 Core、Ref 规则和 Skill 元数据目录。
- 单领域只增加一个正文。
- 四领域加载全部正文。
- 同一输入重复运行时，路由结果和字符数保持稳定。

当前字符数只是近似值，不等同于精确 token 数。

## 6. Capability Scoping 与授权

### 6.1 单领域能力

Todo 输入应满足：

- `routing.resolved.loaded_skills` 只有 todo。
- `capability.built.visible_tool_names` 只有 Todo 和公共工具。
- `llm.request.tools` 与 Event 中可见工具完全一致。
- Finance、Wellbeing、Activity 工具不可见。

对 Finance 输入重复同样检查。

### 6.2 跨领域能力并集

输入：

```text
检查本周餐饮预算，并根据未完成任务安排今天。
```

预期 Todo、Finance 和公共工具合并且无重复，不出现其他领域工具。

### 6.3 安全 Fallback

普通闲聊时：

- `fallback_used=true`。
- 只暴露 `get_current_time` 和 `read_context_ref`。
- 不暴露任何写工具。

### 6.4 Runtime 二次授权

使用受控调用在 Todo-only 授权集合下请求 Finance 写工具，验证：

- 返回 `tool_not_allowed`。
- 底层 expense 写函数没有执行。
- Event 记录 `tool.denied`。

## 7. 多轮 Skill State

所有消息必须在同一 Agent 会话中连续发送，除“新会话”场景外。

### 7.1 Todo 追问继承

```text
列出我的待办任务。
完成第一个。
```

第二轮应满足：direct 为空，previous/inherited/loaded 包含 todo，resolution 为 `ambiguous_followup_inherited`，Todo 工具仍可见。

### 7.2 Finance 追问继承

```text
列出最近的消费记录。
把第一笔改成 35 元。
```

第二轮应继承 Finance。当前没有 expense update 工具，业务动作可能无法完成；测试目标是状态和能力继承。

### 7.3 明确切换领域

```text
列出我的待办任务。
检查本周餐饮预算。
```

第二轮 direct 为 finance、inherited 为空、active 只保留 finance；Todo 工具消失。

### 7.4 普通闲聊清理状态

```text
列出我的待办任务。
你好，介绍一下自己。
继续。
```

闲聊轮 `state_cleared=true`，最后一轮为 `followup_without_active_skill`，仅公共工具可见。

### 7.5 Ref-only 最小能力与主题保留

Finance 请求产生 `ref_id` 后输入：

```text
把刚才引用的完整结果展开。
继续。
```

展开轮应为 `context_ref_only`、loaded 为空、只使用公共工具，但 next active 保留 finance；随后“继续”重新继承 finance。

### 7.6 跨领域状态继承

```text
检查本周预算，并根据任务安排今天。
继续刚才那个。
```

第二轮继承 Todo 与 Finance 整组能力且无重复。这是当前明确保留的策略取舍。

### 7.7 新会话为空状态

重启 `main.py` 后直接输入“继续”，验证没有旧 Skill 可继承。

## 8. 业务工具场景

### 8.1 Wellbeing 写入

```text
我昨晚睡了 5 小时，今天能量低，心情一般，记一下。
```

预期调用 `record_daily_state`，`data/daily_logs.json` 出现当天记录，回答忠于写入结果。

### 8.2 Finance 写入与预算

```text
我今天花了 88 买咖啡和午饭，算餐饮。把本周餐饮预算设成 300，再检查剩余金额。
```

预期链路：`record_expense -> set_budget -> check_budget`。Expense 和 Budget 文件各发生一次预期变化，回答金额来自工具。

### 8.3 Activity 推荐

```text
我今天能量低，只有 30 分钟，不想花钱，在家，推荐一个恢复活动。
```

推荐结果必须免费、居家、低能量且不超过 30 分钟。

### 8.4 跨领域现实计划

```text
我昨晚只睡了 5 小时，今天能量低。这周餐饮预算紧，今天还有重要任务。
帮我安排一个现实的今天计划，也加一个恢复活动。
```

预期可能链路：状态记录/查询、预算检查或消费汇总、`plan_day`、活动推荐。计划应降低负荷、体现任务顺序并包含恢复活动。

## 9. Context 压缩与 Ref

### 9.1 Summary 压缩

准备超过 8 条 Todo 后输入“列出我的所有任务”。

验证：

- `tool.completed.context_compaction.strategy=summary`。
- summary 包含 open、high priority、due today、overdue 和 top items。
- 下一轮 `llm.request.input` 中的 Function Call Output 是摘要，而非完整列表。

### 9.2 Reference 压缩

准备至少 30 条 Expense 或足够长的列表后请求完整列表。

验证：

- strategy 为 `reference`，`ref_id` 非空。
- `logs/context_refs/ctx_*.json` 保存完整结果。
- 模型只收到 summary、ref_id 和按需展开提示。
- 摘要足够时 Agent 不应无意义调用 `read_context_ref`。

随后要求逐笔展开，验证 `read_context_ref` 返回完整结果且不会再次压缩；最终日期、金额、描述与 Ref 文件一致。

Todo 场景中，如果摘要缺少目标 ID，更新、完成或删除前必须展开 Ref，不得猜测 ID。

### 9.3 不压缩边界

验证错误结果和 `read_context_ref` 自身的完整返回始终保持 inline，不创建二次 Ref。

## 10. Agent Loop 基础执行

### 10.1 无工具完成

普通闲聊：`llm_rounds=1`、`total_tool_calls=0`、RunStatus/StopReason 均为 completed。

### 10.2 单工具完成

输入“现在几点？”：第一次响应产生 Function Call，相同 call_id 收到 Output，Action completed，下一轮得到最终回答。

### 10.3 跨领域多工具

输入“查看待办和本周餐饮预算，然后推荐免费恢复活动”：每个 Function Call 都有 ActionRecord 与 Output；单个业务失败不应让 Python 进程崩溃。

### 10.4 LLM 轮数预算

通过临时小 `LoopLimits` 或 Fake LLM 验证：达到 `max_llm_rounds` 后停止；StopReason 为 `llm_budget_exhausted`；已有成功 Action 时状态为 partial，停止回答列出保留结果。

### 10.5 单轮与累计工具预算

让同一响应返回超量 Function Call：预算内执行，超出部分 skipped；每个 call_id 仍有 Output；StopReason 为 `tool_budget_exhausted`；计数只包含实际 attempt。

### 10.6 无效 JSON 参数

Fake LLM 返回非法 arguments：Action failed，错误码 `invalid_json_arguments`，对应 call_id 收到结构化 Observation，Loop 不崩溃。

## 11. Agent Loop 可靠性与故障注入

这些场景需要 Fake LLM、临时 ToolDefinition 或调试脚本；不要修改全局默认值或真实业务数据。

### 11.1 重复非幂等写

连续两轮用不同 call_id 请求参数相同的 add_todo/record_expense：第一次执行，第二次 skipped，StopReason `repeated_call`，Store 只增加一条。

### 11.2 相同 Observation 无进展

连续两次读取同一个不存在的 Ref：两次返回相同 Not Found，第二次后 StopReason `no_progress`，Event 可看到相同调用与 Observation 签名。

### 11.3 A-B-A-B 循环

让两个固定只读调用形成 A、B、A、B：第四次执行前停止，剩余调用全部获得 skipped Output。

### 11.4 Tool Runtime Retry

可重试只读工具第一次抛 `OSError`、第二次成功：错误为 transient，记录 `tool.retry_scheduled`，Action attempt_count=2，工具预算统计两次。

### 11.5 非幂等写不自动重试

让 record_expense 超时或返回临时错误：Runtime 不自动重试不确定写；错误 Observation 交给模型解释。

### 11.6 LLM Retry 与部分成功

- 第一次 LLM timeout、第二次成功：逻辑 Round=1，Attempt=2。
- 工具成功后下一轮 LLM 不可重试失败：RunStatus=partial，回答列出成功工具。

### 11.7 幂等重放

使用相同 `idempotency_key` 调用同一个写工具两次：底层函数只执行一次，第二次返回首次结果，`idempotency.replayed=true`。

### 11.8 Tool Timeout

让只读工具执行时间超过 metadata timeout：返回结构化 `tool_timeout`，标记 retryable；线程超时不会以未捕获异常终止 Agent。

### 11.9 协作式取消

LLM 返回 Function Call 后、工具执行前调用 `cancel_current_run()`：工具不执行，每个 call_id 仍有 Output，StopReason `cancelled`。

当前取消只在调用边界生效，不能强杀已经进入同步 SDK 或 Python 函数的执行。

## 12. 完成标准

- 编译与现有自动化测试全部通过。
- 四个业务领域的写入、读取和跨领域组合无回归。
- 单领域、跨领域、fallback 和歧义路由符合预期。
- Prompt 只加载最终 Skill，Tool Schema 与 Runtime 授权一致。
- 多轮继承、切换、清理和 Ref-only 生命周期可由 Event 解释。
- inline、summary、reference 三种 Context 行为正确，关键 ID/日期/金额不丢失。
- 所有 Function Call 都有 ActionRecord 和对应 Output。
- 预算、错误、重试、幂等、重复、无进展、超时和取消均产生明确状态。
- 三类日志职责清晰，Viewer 可以完成筛选、搜索和 JSON 展开。
- 任一失败都能定位到 Routing、Prompt、Capability、Tool、Context 或 Answer 中的具体层级。

## 13. 代码阅读索引

```text
app/agents/agent.py                 Agent Loop 与编排
app/runtime/run_state.py            RunState、预算、Action 和签名
app/runtime/errors.py               错误分类与标准结果
app/runtime/context_manager.py      Context 压缩策略
app/runtime/context_ref_store.py    完整结果 Ref
app/tools/registry.py               Tool Contract 与注册表
app/tools/executor.py               授权、超时、幂等和执行
app/tools/tool.py                   业务工具 Schema 与处理函数
app/skills/skill_loader.py          Skill 元数据与正文加载
app/skills/skill_router.py          单轮确定性路由
app/skills/skill_state.py           多轮 Skill 状态
app/observability/                  三通道日志
app/log_viewer/                     本地日志 Viewer
```
