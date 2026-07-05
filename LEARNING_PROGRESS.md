# LifeOps Agent 学习进度与计划

## 文件职责

本文件记录学习路线、阶段结论和下一步计划。项目当前事实、代码结构和已实现行为统一记录在
`PROJECT_CONTEXT.md`；阶段性交付记录统一记录在 `CHANGELOG.md`。

## 当前阶段

已完成第一轮核心 Runtime 学习闭环：

```text
Agent Loop -> Business Tools -> Skill -> Capability -> Write Safety
-> RunState / Tool Reliability -> Observability -> Context Engine -> Memory v1
-> MCP -> Interaction / Safety State -> Task State v1
```

当前下一阶段调整为：

> Persistence / Recovery。

暂不进入 Multi-Agent、复杂 Planner、向量数据库、自动 Memory 提取或真实外部账号/OAuth。

## 已学习模块

### 1. Agent Loop

- 学会了 Responses API 多轮 Function Calling 的基本循环。
- 一次用户输入可能触发多轮 LLM 请求和多次工具执行。
- Function Call 是模型请求的 Action；Tool Observation 会返回模型继续推理。
- LLM 文本不是 Runtime 事实，真实副作用必须看工具执行结果。

### 2. Business Tools

- 已建立 Todo、Wellbeing、Finance、Activity 四个本地业务领域。
- 业务数据使用 Pydantic + 本地 JSON 持久化。
- 业务工具既提供产品能力，也用于验证写入安全、工具可靠性和 Context 管理。
- Todo / Expense / Daily Log 是业务数据，不是 Memory。

### 3. Skill Routing

- Skill 提供领域规则，不等于 Tool。
- Skill Router 根据当前输入选择领域。
- Skill State 支持继承、替换、清理和 Ref-only 状态。
- 明确领域信号替换旧 Skill；含糊追问可继承旧 Skill；普通闲聊清理活跃 Skill。

### 4. Prompt 与 Skill 加载

- Prompt 每轮重新构建。
- Skill 元数据始终可用于路由，Skill 正文只在选中后加载。
- Skill 正文不追加进 `Agent.messages`，也不进入 Rolling Summary。
- Prompt 是本轮运行配置，不是对话历史。

### 5. Capability

- Capability 决定本轮模型能看到哪些 Tool Schema。
- Skill 决定领域工具范围，当前用户输入授权决定 WRITE 工具是否可见。
- Executor 执行前会再次校验 `allowed_tool_names`。
- Capability 默认不暴露 WRITE 工具；通用 WRITE 工具也必须当前输入授权。

### 6. Write Safety

- 描述事实不等于授权写入。
- 请求建议不等于授权保存状态。
- 批量删除需要明确确认。
- assistant 声称“已保存/已修改”不可信，必须有成功 WRITE Action。
- Memory 写入也遵守同一原则：只有工具成功写入才算真正保存。

### 7. RunState 与 ActionRecord

- `RunState` 属于一次 `Agent.chat()`，不是 Session 或长期 Task State。
- `ActionRecord` 记录一次模型请求的工具 Action。
- 已区分 LLM 逻辑轮次、实际 API 请求数、工具执行尝试数和重试次数。
- StopReason、预算、部分成功和取消都属于单次 Chat Runtime 状态。

### 8. Tool Reliability

- Tool Executor 负责授权、执行、超时、重试、幂等和错误归一化。
- 工具错误统一为 `type`、`code`、`message`、`retryable`。
- SDK 隐式重试关闭，LLM / Tool 重试由 Runtime 显式管理。
- 非幂等写不能随意重试；幂等重放和重复 Action 是不同问题。
- Runtime 可检测重复调用、相同 Observation 和 A-B-A-B 循环。

### 9. Observability

- Event 日志解释 Runtime 决策。
- LLM I/O 日志观察模型边界。
- Application 日志用于程序诊断。
- 日志字段必须表达作用域，例如单次 Chat、单次 LLM 请求、单次工具执行尝试。
- LLM Response 日志应做诊断投影，不无差别保存 SDK 对象。

### 10. Context Engine

- 学会区分“完整历史”和“本轮工作上下文”：完整历史是事实源，本轮发送给模型的是经过装配的输入。
- Context 管理的核心不是尽量保留原文，而是在预算内维持认知连续性。
- Tool Observation 压缩和长期对话窗口管理是两个问题：前者处理单次工具结果过大，后者处理多轮历史增长。
- Summary 是派生上下文，不是事实源；工具成功、ID、金额、日期、确认范围等高风险事实需要结构化记录、Ref、Index 或 Runtime 状态支撑。
- 压缩有不同生命周期：回合后的主动压缩、请求前的被动预算保护、用户触发的手动 `/compact` 不能混为一谈。
- Context 召回当前是确定性 metadata 检索，不是 embedding 语义搜索。
- Context 行为必须可观察、可测试，尤其要验证压缩前后关键行为不变。
- Conversation Summary 不等于 Long-term Memory，不能自动升级为用户长期记忆。

### 11. Memory v1

- 学会区分 Profile Memory、Semantic Memory、Conversation Summary 和业务数据。
- Profile Memory 是用户手动维护的只读长期画像，Runtime 只读取，不自动修改。
- Semantic Memory 只保存用户明确授权的长期事实、偏好、目标和约束。
- 用户陈述偏好不等于授权保存；只有明确“记住/保存/以后默认”等表达才允许写入 Memory。
- assistant 口头说“记住了”不算保存；只有成功的 Memory WRITE Tool Action 才是真实保存。
- 删除 Memory 后，后续默认查询和上下文注入都不应再使用它。
- 自动使用 Memory 是 Runtime 每轮请求前的长期状态装配，不依赖模型主动调用读取工具。
- Memory 不属于对话历史，不应进入 `Agent.messages`、Rolling Summary 或 ContextIndex。
- 业务数据不能自动复制进 Memory；Rolling Summary 也不能自动升级为 Memory。

### 12. Skill References 与受控只读脚本

- 学会让 Skill 从纯 Prompt 规则升级为可声明只读资料、受控来源和确定性 helper 的领域包。
- Skill Reference 只能读取当前 Skill 自有目录下 manifest 声明过的 Markdown 文件。
- Reference Loader 必须拒绝路径穿越、未声明 reference 和越界文件读取。
- Reference / Source / Helper 输出只属于当前工具观察，不写入 `Agent.messages`、Memory 或 Rolling Summary。
- Hugging Face News Source 通过 `source_id` 白名单读取，不允许模型传任意 URL。
- `run_news_helper` 只允许调用 news Skill manifest 声明过的只读 helper，参数和错误都要结构化。
- Capability 和 Executor 仍然负责可见性和二次校验；未选中 news Skill 时不能调用 news reference / source / helper。
- Hugging Face News Briefing 已完成 reference -> source -> helper -> 中文简报第一版闭环。

### 13. MCP v1

- 学会把 MCP Server 视为外部能力提供者，而不是内部业务 domain。
- 第一版使用 Mock Package Tracking MCP，避免和 Todo、Finance、Daily Log、Activity 等现有 domain 发生语义重叠。
- MCP Server 通过真实 stdio JSON-RPC 协议暴露 `track_package`、`list_package_updates` 和 `estimate_delivery_window`，背后数据源先使用本地 mock JSON。
- MCP Adapter 属于 Agent Runtime 接入层，负责启动 server、调用 `tools/list` / `tools/call`，并归一化协议错误、server 不可用、超时和非法响应。
- Tool Bridge 把 MCP tool 转成 Agent 可见的 ToolDefinition：`track_package_via_mcp`、`list_package_updates_via_mcp`、`estimate_delivery_window_via_mcp`。
- Package Tracking MCP 第一版不新增 domain、不新增 Skill，三个工具作为全局 READ tools 进入 common capability。
- 全局 READ tool 仍必须经过 Capability Builder 和 Executor；全局可见不等于绕过 Runtime。
- MCP tool result 默认只是本轮 Tool Observation，不自动进入 Memory、业务数据或长期历史。
- MCP v1 已完成 Mock Server、Agent Adapter、全局 READ Tool Bridge 和自然语言 Agent 闭环。

### 14. Interaction / Safety State

- 学会把 pending confirmation 建模为跨轮临时 Runtime State，而不是 RunState、Memory 或 Context Summary。
- 高风险写入不能只靠当前输入的一句“确认”直接暴露工具；必须先有 Runtime 持有的 active pending。
- 用户确认 active pending 后，只在本轮临时授权对应 WRITE tool，不能顺手扩大到其它写工具。
- 取消、修改范围、过期和 supersede 都是 pending 生命周期的一部分，必须可观察、可测试。
- Capability Builder 仍只负责根据 Skill 和授权结果暴露工具，不关心 pending 生命周期。
- pending confirmation 生命周期已写入 compact event 日志，但不记录原始用户输入正文。

### 15. Task State v1

- 学会把长期任务现场建模为独立状态源，而不是依赖模型记忆、对话历史、Memory 或 Rolling Summary。
- `TaskItem` 负责跨 Chat 的目标、步骤、当前步骤、blocker、note 和任务状态生命周期；`RunState` 仍只负责一次 `Agent.chat()`。
- `TaskStore` 使用本地 versioned JSON 持久化，是 Task State v1 和 Persistence v0 的事实源；文件不存在时应安全返回空任务列表。
- Task WRITE tools 必须来自用户当前输入的明确授权；普通“我想做 X”只是本轮上下文，不自动创建任务。
- 恢复或查看任务是 READ 行为，不等于授权更新 Task State，也不等于授权执行任务里的危险操作。
- Task Context 在 `ContextEngine.assemble()` 之后作为 request-local system context 注入本轮 LLM 输入，但不进入 `Agent.messages`、Memory、Rolling Summary 或 ContextIndex。
- Agent 可以通过自然语言创建任务、添加步骤、记录 blocker 和恢复查看任务，但最终回答必须基于真实 Task Tool Observation。
- Task State 是 Planner 和 Recovery 的地基，但 v1 不自动生成计划、不自动推进步骤、不自动执行工具。

## 当前输入层心智模型

```text
System Instructions
+ Loaded Skill Prompt
+ Read-only Profile Memory
+ Relevant Semantic Memory
+ Current Task Context
+ Conversation Working Context
+ Tool Schemas
```

对应责任：

| 层 | 负责人 | 作用 |
|---|---|---|
| System Instructions | Prompt Builder | 本轮通用行为规则 |
| Skill Prompt | Skill Loader / Prompt Builder | 本轮领域规则 |
| Profile Memory | ProfileLoader | 只读长期画像 |
| Semantic Memory | MemoryStore / MemoryRetriever | 用户授权长期状态 |
| Current Task Context | TaskContextBuilder | 本轮只读任务现场 |
| Conversation Context | ContextEngine | 对话历史工作窗口 |
| Tool Schemas | Capability Builder | 本轮可见工具能力 |

## 下一阶段：Persistence / Recovery

目标：

> 在已有 Tool、Capability、Context、Memory、MCP、Interaction/Safety State 和 Task State 边界之上，学习崩溃恢复、运行中状态持久化和可恢复执行边界。

为什么现在做：Task State 已经能保存长期任务现场，下一步可以学习 Runtime 中断、失败、重启后如何判断“做到哪里、什么可以继续、什么必须重新确认”。这会把 Task State、ActionRecord、幂等记录、Write Safety 和 Context 恢复边界串起来。

后续需要单独制定 Persistence / Recovery 实施计划；不要把 Recovery 提前混进 Task State v1 的收尾补丁。

## 后续路线

1. Persistence / Recovery：崩溃恢复、运行中状态持久化和可恢复执行边界。
2. Policy / Permission Layer：把授权、风险等级和可执行能力进一步拆清楚。
3. 高级 Memory Retrieval：关键词归一化、更新/合并、冲突检测、重要性、过期时间，之后再考虑 embedding。
4. Planner / Multi-Agent：等状态、上下文、Memory、工具和安全边界稳定后再推进。

继续暂缓：向量数据库、自动记忆提取、任意 Shell、复杂 Planner、Multi-Agent、大规模 LLM-as-judge。

阶段路线：

```text
Skill References（已完成）
-> MCP（已完成）
-> Interaction / Safety State（已完成 v1）
-> Task State（已完成 v1）
-> Persistence / Recovery（当前阶段）
-> Policy / Permission Layer
-> Plan and Execute
-> LangGraph / LangChain 对照整合
-> Advanced Memory
-> Multi-Agent
```

## 当前学习原则

每增加一类能力，都要先判断它属于 `Prompt / Skill / Tool / Capability / Context / Memory / Runtime State / Business Data / Logs`。边界清楚，Agent 才能安全、可观察、可恢复地成长。


## 学习以及面试准备
初级 Agent Engineer：
Agent Loop
-> Tool
-> Capability
-> Write Safety
-> Skill
-> Skill References
-> Context Engine
-> Memory v1

中级 Agent Engineer：
MCP
-> Safety State
-> Task State
-> Recovery
-> Planner
-> LangGraph / LangChain 对照

强中级 / 准高级：
Human-in-the-loop
-> Scheduling / Background Agent
-> Eval Harness
-> Inspector / Debugger
-> MCP Security

高级 Agent / Agent Platform Engineer：
Cost / Token / Latency Budget
-> Async / Concurrency Runtime
-> Advanced Memory
-> RAG / Knowledge System
-> Multi-Agent
-> Plugin System
-> Product Layer
