# LifeOps Agent 学习进度与计划

## 如何使用

本文件只记录已经学习的概念、已完成的学习阶段和未来计划。

项目架构与各模块职责见：

```text
D:\lifeops-agent\PROJECT_CONTEXT.md
```

## 当前学习阶段

项目已经从“增加业务工具”进入“理解 Agent Runtime 的状态、能力边界和可靠性”。

当前已完成：

- 多轮 Skill 状态管理。
- 动态 Tool Schema 与 Skill 权限。
- Agent Loop 执行骨架：RunState、ActionRecord、分层调用预算和 StopReason。

当前正在继续深化 Agent Loop 与执行可靠性。

Routing Eval 的 Precision/Recall 与行为回归已经讨论过，但决定暂时不做正式 Eval。
每个新功能仍保留少量关键自动化测试和能够暴露内部行为的手动测试。

## 已学习的核心概念

1. Function Calling Agent Loop：模型输出工具调用，Agent 执行工具并把 Observation
   返回模型，直到得到最终回答或达到循环上限。
2. Tool Registry 与 Schema：工具实现、参数 Schema、结构化结果和错误处理之间的关系。
3. Context Management：完整结果、结构化摘要、引用压缩和按需读取之间的取舍。
4. Prompt 与对话记录分离：`instructions` 每次重新生成，`self.messages` 保存跨轮消息、
   Function Call 和工具结果。
5. Skill 渐进式披露：所有 Skill 只暴露简短元数据，选中后才加载完整正文。
6. 确定性 Skill Routing：使用规则、分数和匹配原因选择一个或多个领域 Skill。
7. 动态 Prompt Builder：根据最终 `loaded_skills` 构建最新 System Prompt，避免 Skill
   正文在对话 Context 中重复累积。
8. Skill 与 Tool 的边界：Skill 提供领域知识和编排规则，Tool 提供实际执行能力。
9. Context Ref 与 Skill 的关系：Ref 是通用 Runtime 能力，Skill 只补充领域展开条件。
10. Capability Scoping：Skill 映射为本轮可见工具，Schema 过滤减少干扰和 Context
    开销，Runtime 授权检查守住实际执行边界。
11. 多轮 Skill 状态：直接路由与 Runtime 状态分离，明确领域替换旧状态，含糊追问
    继承状态，闲聊清理状态，Ref 请求使用最小能力但保留话题。

## 已完成阶段一：多轮 Skill 状态管理

已经实现：

- Agent 保存上一轮活跃 Skill。
- 区分 `directly_selected`、`inherited_skills` 和 `loaded_skills`。
- 明确领域信号优先使用新的直接路由结果。
- “第一个”“刚才那个”“继续”等含糊追问可以继承上一轮 Skill。
- 明确切换领域时替换旧状态，普通闲聊清理状态。
- 新 Agent 从空状态开始。
- Ref-only 请求本轮只使用公共工具，同时保留活跃话题。
- Trace 记录状态解析原因和前后活跃 Skill。

学习目标：

- 对话历史与 Agent Runtime 状态的区别。
- 单轮 Router 与多轮状态解析层的边界。
- 话题延续、切换和 Skill 生命周期。
- 继承策略的风险与安全 fallback。

手动测试：

```text
docs/multi_turn_skill_state_test_plan.md
```

## 已完成阶段二：动态 Tool Schema 与 Skill 权限

已经实现：

- 每个 Skill 都有显式的允许工具集合。
- `read_context_ref` 和 `get_current_time` 等公共工具始终可用。
- Capability Builder 根据最终 Skill 返回本轮 Tool Schema。
- 未选中领域的工具默认不暴露给模型。
- 无 Skill 时使用只保留公共工具的安全 fallback。
- `call_tool` 执行前再次检查本轮授权。
- Trace 记录可见工具、Schema 大小和能力来源。
- 本地 UI 可以配对查看 Trace 和 Raw 日志。

学习目标：

- Capability Scoping 和最小权限原则。
- Skill 与 Tool 的能力映射。
- Tool Schema 的 Context 开销。
- 模型可见性和 Runtime 权限之间的区别。

手动测试：

```text
docs/capability_scoping_test_plan.md
```

## 后续学习路线总览

后续不再优先横向增加业务工具，而是使用真实复杂场景纵向深化现有 Runtime：

```text
Agent Loop 与 RunState
-> 轻量 Eval 与可观测性（同步进行）
-> 长期 Context 生命周期
-> 最小 Memory State
-> Interaction / Safety State
-> Skill References 与受控脚本
-> Task State
-> 高级 Memory Retrieval
-> MCP
-> 复杂规划与 Multi-Agent
```

采用螺旋式学习方式：

```text
简单实现
-> 制造压力和失败
-> 发现一个真实缺口
-> 增加最小机制
-> 使用 Trace 验证
-> 固化为轻量 Eval
-> 进入下一个缺口
```

## 阶段三：Agent Loop 与 RunState

这是当前最高优先级。现有 Agent 已具备 Function Calling / ReAct 基础骨架，但执行控制
仍需要继续补充重复检测、错误恢复、幂等性和部分成功。

已完成执行骨架：

- 每次请求创建独立的 `RunState` 和 `run_id`。
- 定义 `RunStatus`、`StopReason` 和 `ActionStatus`。
- 使用 `ActionRecord` 保存工具名称、参数、结果和状态。
- 分别限制 LLM 轮数、单轮工具数和请求累计工具数。
- 达到工具预算或 LLM 预算时进入明确终态。
- 因预算停止时保留已经成功的 Action，并生成可解释的停止回答。
- Trace 和 Raw 事件使用 `run_id` 关联单次请求。

手动测试：

```text
docs/agent_loop_execution_skeleton_test_plan.md
```

接下来计划研究和实现：

1. 扩展结构化终止原因，例如重复调用、无进展、不可恢复错误、
   部分成功和等待用户。
2. 使用规范化的工具名与参数生成调用签名，检测重复调用、相同错误重试和循环调用。
3. 区分参数错误、业务错误、临时错误、权限错误和内部错误，分别决定纠正、重试、跳过
   或停止。
4. 为写工具研究幂等性，避免重试产生重复 Todo、状态、预算或消费记录。
5. 工具部分失败时保留成功结果，并在停止时返回已完成、未完成和可恢复信息。
6. 在可靠性基础稳定后，再研究工具调用的并行性和依赖顺序。

这一阶段会按真实需求逐步深化 Tool Registry。候选元数据包括：

```text
effect: read | write
idempotent: true | false
retryable: true | false
risk: low | high
parallel_safe: true | false
timeout_seconds
```

只有 Agent Loop 真正使用某个字段时才增加它，避免提前设计复杂框架。

完成标准：

- Agent 不再只依赖固定循环上限。
- Trace 可以解释每次继续、重试和停止的原因。
- 写工具重试不会产生重复业务数据。
- 单个工具失败不会丢失其他已经成功的结果。
- 达到限制时能返回明确停止原因和可恢复的部分结果。

## 贯穿阶段：轻量 Eval 与可观测性

Eval 不作为等待所有功能完成后的独立工程，而是随每项 Runtime 机制同步增加。

优先使用确定性行为断言：

- 是否选择了正确 Skill 和工具。
- 工具参数是否正确。
- 写工具是否只执行一次。
- 是否出现未授权工具。
- 是否正确检测重复调用和停止。
- 是否保留部分成功结果。
- Context 压缩是否保留后续 Action 所需的 ID、日期、金额和 Ref。

Trace 逐步增加：

- `run_id` 和 RunState 摘要。
- LLM 轮数、累计工具数和工具耗时。
- 错误分类、重试次数与重试原因。
- 状态变化和最终停止原因。

正式 Routing Eval、Precision/Recall 和大规模 LLM-as-judge 评测继续暂缓。

## 阶段四：长期 Context 生命周期

完成 RunState、调用预算、重复检测、基本停止原因和幂等写入后，将长期 Context 提前到
最小 Memory 之前研究，解决 `self.messages` 随对话无限增长的问题。

计划研究和实现：

1. 区分最近消息窗口、历史对话摘要、结构化 Agent State、长期 Memory 和业务数据。
2. 研究 Function Call 与 Observation 的窗口保留策略。
3. 为压缩结果区分必须保留字段和可丢失的展示细节。
4. 确保 Todo ID、Ref ID、日期、金额和待确认状态不会因摘要丢失。
5. 研究摘要的生成、更新、失效和替换时机。
6. 为 Context Ref 增加生命周期、过期和清理策略。
7. 在真实 Prompt Budget 压力出现后，引入精确 tokenizer 统计。

核心不变量：

```text
Context 可以损失展示细节，但不能损失后续 Action 所需的信息。
```

完成标准：

- 长对话不会导致 `self.messages` 无限增长。
- 摘要前后关键 Agent 行为保持一致。
- 压缩不会破坏后续工具调用。
- Agent 能正确判断何时读取完整 Context Ref。

## 阶段五：最小 Memory State

第一版只保存用户明确表达、具有长期价值的信息，不立即引入向量数据库或自动记忆提取。

第一批记忆类型：

- 用户明确要求记住的事实。
- 稳定偏好。
- 稳定作息和工作时间。
- 明确的长期目标。

计划研究和实现：

1. 建立包含类型、内容、来源、创建时间、更新时间和状态的 `MemoryItem`。
2. 提供保存、查看、修改和删除 Memory 的明确工具。
3. 为 Memory 写入实现幂等性和冲突处理。
4. 区分 Memory、对话摘要、Task State 和 Todo 等业务数据。
5. Trace 记录 Memory 的读取、写入和注入来源。
6. 用户能够查看、纠正和删除 Agent 保存的记忆。

暂时不实现：

- 自动从所有对话中提取记忆。
- 向量数据库和语义相似度检索。
- 自动合并、衰减和遗忘算法。
- 模型自主决定所有 Memory 写入。

## 阶段六：Interaction State 与 Safety State

研究 Agent 在缺少信息或需要用户批准时如何暂停并跨轮恢复。

计划研究和实现：

1. 使用结构化 `PendingInteraction` 保存缺失参数、候选对象和待确认操作。
2. 支持确认、取消、修改范围和确认过期。
3. 将工具分为只读、可逆写入和高影响写入。
4. 高影响操作先预览，确认后执行。
5. 真正执行前重新读取并校验外部业务状态。

完成标准：

- 含糊的高影响操作不会直接执行。
- “只处理前三个”等追问能够基于结构化状态处理。
- 用户可以查看、修改和取消待执行操作。

## 阶段七：Skill References 与受控脚本

先选择一个 Skill 进行 References 小型试点，不一次改造所有 Skill。建议使用 Finance：

```text
finance/
├── SKILL.md
├── references/
│   ├── budget_rules.md
│   └── expense_categories.md
└── agents/
    └── openai.yaml
```

学习目标：

- Skill 正文与 Reference 的边界。
- 二级渐进式披露和按需加载。
- Reference 的访问权限、Context 开销和 Trace。

受控脚本必须等 Agent Loop 的超时、错误分类、权限和幂等性基础稳定后再加入。第一个脚本
应只读、确定性、无网络、使用固定参数并返回结构化 JSON。暂不提供任意 Shell 或自由文件
读写能力。

## 阶段八：Task State

研究跨请求、可暂停、可恢复的长期任务状态，包括 Goal、Step、Dependency、Completed、
Failed、Blocked 和 Next Action。

关键边界：

```text
RunState：一次 chat() 请求的执行状态
Task State：一个长期目标跨多次请求的整体进度
```

完成标准：

- 新请求能够恢复同一个长期任务。
- 已完成步骤不会无意义重做。
- 用户可以查看、暂停、继续和取消任务。

## 阶段九：高级 Memory Retrieval

在最小 Memory、Context 生命周期、Task State 和基础 Eval 稳定后，再研究：

- 自动记忆候选提取。
- 语义检索和向量存储。
- 记忆召回、排序和 Context 注入。
- 冲突合并、置信度、衰减和遗忘。
- Memory Precision / Recall 与错误记忆测试。

## 阶段十：MCP

当本地 Tool Runtime 稳定后，将一个 LifeOps 能力暴露为 MCP Server，并让 Agent 作为
Client 调用，用来理解能力发现、Schema、传输、身份、权限和信任边界。

## 最后阶段：复杂规划与 Multi-Agent

最后再研究 Planner / Executor、DAG、依赖调度、Agent 委派、共享状态、冲突处理和结果
合并。

进入条件：

- 单 Agent Loop 已可靠。
- Tool 副作用和审批受控。
- Agent State 生命周期清晰。
- 已有轻量行为 Eval。
- Trace 能解释完整执行路径。

## 当前近期执行顺序

```text
已完成：RunState + ActionRecord + 调用预算 + 基础 StopReason
下一轮：重复调用检测 + 错误分类
之后：幂等写入 + 部分成功
之后：按 Loop 需求深化 Tool Metadata
之后：长期消息窗口、摘要与 Context 关键信息保留
之后：显式 Memory CRUD、来源、冲突和删除

同步进行：Trace 增强 + 少量行为 Eval
```

## 暂缓但保留的方向

- 正式 Routing Eval、Precision/Recall 和大规模行为回归。
- 使用小模型或语义检索进行 Skill Routing。
- 全面 Skill 脚本化和任意 CLI 执行。
- 自动记忆提取、向量数据库和复杂遗忘算法。
- `/tools`、`/skills`、`/context`、`/refs`、`/trace`、`/raw`、`/reset`
  等 CLI 调试命令。
- Planner、复杂工作流和 Multi-Agent。

当前主线原则：

> 使用 Agent Loop 作为主线，用真实失败场景推动 Tool、Context 和 Skill 深化，
> 用 Trace 和 Eval 证明每次深化确实提高了系统质量。
