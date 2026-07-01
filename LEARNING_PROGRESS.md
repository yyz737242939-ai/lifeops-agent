# LifeOps Agent 学习进度与计划

## 文件职责

本文件记录学习路线、阶段结论和下一步计划。项目当前事实、代码结构和已实现行为统一记录在
`PROJECT_CONTEXT.md`；阶段性交付记录统一记录在 `CHANGELOG.md`。

## 当前阶段

已完成第一轮核心 Runtime 学习闭环：

```text
Agent Loop -> Business Tools -> Skill -> Capability -> Write Safety
-> RunState / Tool Reliability -> Observability -> Context Engine -> Memory v1
```

当前下一阶段调整为：

> Skill References 与受控只读脚本。

暂不进入 MCP、Multi-Agent、复杂 Planner、向量数据库或自动 Memory 提取。

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

## 当前输入层心智模型

```text
System Instructions
+ Loaded Skill Prompt
+ Read-only Profile Memory
+ Relevant Semantic Memory
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
| Conversation Context | ContextEngine | 对话历史工作窗口 |
| Tool Schemas | Capability Builder | 本轮可见工具能力 |

## 下一阶段：Skill References 与受控只读脚本

目标：

> 让 Skill 从纯 Prompt 规则升级为可以安全引用外部只读资料和小型确定性辅助能力的机制。

为什么现在做：继续把所有规则写进 `SKILL.md` 会让 Prompt 变重；Skill 需要表达只读资料、示例库、领域表格和辅助计算；Runtime 也需要观察 reference / script 何时被加载，并防止它们变成任意文件读取或任意 Shell。

建议实施顺序：

1. 设计 Skill Reference 声明结构，只支持 Skill 自有目录下声明过的 Markdown reference。
2. 实现受控 Reference Loader：只读、拒绝路径穿越、拒绝未声明文件、记录路径和字符数。
3. 接入 Prompt / Context 装配：reference 每轮按 Skill 重新加载，不进入 `Agent.messages`、Memory 或 Rolling Summary。
4. 增加 reference 可观测性：记录本轮加载的 reference ids、路径、字符数和是否注入。
5. 设计受控只读脚本：无写入、无网络、不读任意文件、参数 schema 明确、输出可序列化、有超时和结构化错误。
6. 将只读脚本纳入 Capability：只有当前选中 Skill 声明的 read-only helper 才可见，Executor 二次校验。
7. 增加测试：未选中 Skill 不可读、未声明 reference 拒绝、路径穿越拒绝、脚本不可写、超时/异常结构化、不会污染历史和 Memory。

## 后续路线

1. Interaction / Safety State：跨轮确认、取消、范围修改、授权过期和危险操作保护。
2. Task State：跨 Chat 的长期目标、步骤、暂停、恢复和 blocked 状态。
3. 高级 Memory Retrieval：关键词归一化、更新/合并、冲突检测、重要性、过期时间，之后再考虑 embedding。
4. MCP：外部工具协议、权限控制、错误处理和可观测性。
5. Planner / Multi-Agent：等状态、上下文、Memory、工具和安全边界稳定后再推进。

继续暂缓：向量数据库、自动记忆提取、任意 Shell、复杂 Planner、Multi-Agent、大规模 LLM-as-judge。

后续路线更新版
Skill References
-> MCP
-> Interaction / Safety State
-> Task State
-> Persistence / Recovery
-> Policy / Permission Layer
-> Plan and Execute
-> LangGraph / LangChain 对照整合
-> Advanced Memory
-> Multi-Agent

## 当前学习原则

每增加一类能力，都要先判断它属于 `Prompt / Skill / Tool / Capability / Context / Memory / Runtime State / Business Data / Logs`。边界清楚，Agent 才能安全、可观察、可恢复地成长。
