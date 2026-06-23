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
- Agent Loop v0.1 核心可靠性。

下一阶段进入长期 Context 生命周期与最小 Memory State。

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
12. RunState 与执行状态机：单次请求使用独立状态、预算、ActionRecord 和终止原因。
13. 错误恢复：Runtime Retry 处理临时基础设施错误，LLM Correction 处理参数和业务反馈。
14. 进展检测：稳定调用签名、Observation 签名和短周期检测用于阻止确定性死循环。
15. 幂等与副作用：同一 Action 的重放与模型生成的新 Action 是不同问题；非幂等写不能
    因结果不确定而盲目重试。
16. 协作式取消：Runtime 可以在调用边界停止，但同步函数内部需要进程隔离才能强制终止。

## 已完成阶段一：多轮 Skill 状态管理

已经实现：

- Agent 保存上一轮活跃 Skill。
- 区分 `directly_selected`、`inherited_skills` 和 `loaded_skills`。
- 明确领域信号优先使用新的直接路由结果。
- “第一个”“刚才那个”“继续”等含糊追问可以继承上一轮 Skill。
- 明确切换领域时替换旧状态，普通闲聊清理状态。
- 新 Agent 从空状态开始。
- Ref-only 请求本轮只使用公共工具，同时保留活跃话题。
- Event 记录状态解析原因和前后活跃 Skill。

学习目标：

- 对话历史与 Agent Runtime 状态的区别。
- 单轮 Router 与多轮状态解析层的边界。
- 话题延续、切换和 Skill 生命周期。
- 继承策略的风险与安全 fallback。

对应手动测试统一见：

```text
docs/manual_test_plan.md
```

## 已完成阶段二：动态 Tool Schema 与 Skill 权限

已经实现：

- 每个 Skill 都有显式的允许工具集合。
- `read_context_ref` 和 `get_current_time` 等公共工具始终可用。
- Capability Builder 根据最终 Skill 返回本轮 Tool Schema。
- 未选中领域的工具默认不暴露给模型。
- 无 Skill 时使用只保留公共工具的安全 fallback。
- `call_tool` 执行前再次检查本轮授权。
- Event 记录可见工具、Schema 大小和能力来源。
- 本地 UI 可以配对查看 Event、LLM I/O 和 Application 三类日志。

学习目标：

- Capability Scoping 和最小权限原则。
- Skill 与 Tool 的能力映射。
- Tool Schema 的 Context 开销。
- 模型可见性和 Runtime 权限之间的区别。

对应手动测试统一见：

```text
docs/manual_test_plan.md
```

## 后续学习路线总览

后续不再优先横向增加业务工具，而是使用真实复杂场景纵向深化现有 Runtime：

```text
Agent Loop 与 RunState（v0.1 核心完成）
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
-> 使用 Event 验证
-> 固化为轻量 Eval
-> 进入下一个缺口
```

## 已完成阶段三：Agent Loop v0.1 核心可靠性

已完成：

- 单请求 `RunState`、ActionRecord、明确终态和结构化 StopReason。
- LLM 轮数、单轮工具数、累计工具数和重试次数的独立预算。
- 稳定调用签名、重复非幂等写拦截、相同 Observation 无进展检测和 A-B-A-B 循环检测。
- 参数、业务、Not Found、权限、临时、超时和内部错误的结构化分类。
- Runtime Retry 与 LLM 参数纠正的边界；SDK 隐式重试改为 Runtime 显式重试。
- Tool Metadata：`effect`、`idempotent`、`retryable` 和 `timeout_seconds`。
- 写工具成功结果的幂等键存储与重放。
- LLM 与工具超时、协作式取消检查点。
- 强制停止时保留并汇总成功、失败和跳过的 Action。
- Event 记录 `run_id`、调用尝试、重试、错误、幂等键和停止原因。

自动化与统一手动测试：

```text
tests/test_run_state.py
tests/test_agent_loop_skeleton.py
tests/test_agent_loop_reliability.py
tests/test_tool_reliability.py
docs/manual_test_plan.md
```

### Agent Loop 是否已经完全做好

结论：**v0.1 单 Agent、顺序工具执行的核心 Loop 已经完成；广义的生产级 Agent Loop
尚未完全完成。** 以下能力保留为以后出现真实需求后再深化：

1. 工具依赖图、安全并行、并发写入控制和并行取消。
2. RunState 持久化、进程崩溃恢复和跨进程继续执行。
3. 事务型幂等、Outbox/Inbox 或补偿操作，覆盖“副作用成功但结果落盘前崩溃”的窗口。
4. 能强制中断底层同步调用的进程隔离；当前取消仅在调用边界生效。
5. 全局 wall-clock deadline、token/cost budget、流式输出和 backpressure。
6. 超越确定性调用签名的语义级进展判断与计划偏航检测。

这些不是进入长期 Context 和 Memory 阶段的阻塞项。

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

### 三通道日志系统

已经完成第一版可观测性分层：

- Event 使用 JSONL 追加写入，记录 Runtime 的关键结构化节点。
- LLM I/O 只记录完整 request/response，不混入工具执行结果。
- Application 使用 Python `logging` 记录程序进程和错误诊断信息。
- 所有对外日志方法使用 `log_` 前缀，并按 run、routing、LLM、tool 分类。
- Viewer 支持三类日志，同时兼容历史 Trace/Raw 文件。

### 公共 Utils 整理

- Memory Store 共享 JSON 文件校验、Pydantic 列表加载与保存。
- JSON 文件使用同目录临时文件加原子替换，降低写入中断造成半文件的风险。
- Context Ref 与幂等存储共享相同的 JSON object 读写规则。
- 工具、Agent 与日志系统共享 JSON 安全序列化和 object 解析。
- 时间字符串集中到轻量 time utils；业务 Store 仍保留各自的领域 CRUD。

### Agent Loop 可读性整理

- `chat()` 只保留创建 Run、准备本轮边界和运行 Loop 三个顶层步骤。
- 使用 `TurnContext` 明确一轮内固定的 Prompt、Tool Schema、授权工具和 Skill。
- LLM 失败分类与重试决策从请求循环中独立出来。
- 工具执行拆分为前置检查、非法参数记录、重复检测、显式重试、Action 记录和后置检查。
- 关键方法补充职责型 docstring；签名检测和幂等键补充设计原因注释。

### Context Manager 可读性与策略测试

- 将 JSON 解析、领域摘要、策略选择、Ref 持久化、payload 和 metadata 构造分离。
- Summary/Reference 阈值集中声明，策略判定本身不执行文件 I/O。
- 保持错误结果和 `read_context_ref` 完整输出不压缩的不变量。
- 新增 inline、summary、reference、错误绕过和 Context 摘要的独立测试。

### Tool Runtime 与业务目录分离

- Registry 只保存 Tool Schema、函数引用、副作用和可靠性元数据。
- Executor 独立处理授权、线程超时、幂等重放、异常归一化和结果序列化。
- `tool.py` 保留业务工具定义与稳定导入门面，避免 Runtime 机制和业务实现交叉。
- Activity 推荐拆分为硬约束过滤、偏好评分和稳定排序。
- Skill State 将四种状态决策拆成命名明确的构造函数。
- Viewer Server 将新旧会话发现与日志加载路径分开。
- 删除不再被引用的旧 `conversation_logger.py` 兼容层。

## 阶段四：长期 Context 生命周期

Agent Loop v0.1 核心可靠性完成后，将长期 Context 提前到最小 Memory 之前研究，解决
`self.messages` 随对话无限增长的问题。

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

受控脚本现在已经具备所需的基础 Runtime 条件。第一个脚本应只读、确定性、无网络、使用
固定参数并返回结构化 JSON。暂不提供任意 Shell 或自由文件读写能力。

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
当前：长期消息窗口、摘要与 Context 关键信息保留
之后：显式 Memory CRUD、来源、冲突和删除
之后：Interaction / Safety State
之后：Skill References 与受控只读脚本

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

> Agent Loop v0.1 核心已经完成。下一步用同样的“真实压力、Trace、轻量 Eval”方式
> 深化长期 Context 和最小 Memory State。
