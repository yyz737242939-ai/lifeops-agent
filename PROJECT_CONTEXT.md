# LifeOps Agent 项目上下文

## 文件职责

本文件只描述项目当前事实：定位、架构、状态边界、已经实现的行为和已知限制。

面向 Codex 的长期协作规则见 `AGENTS.md`。学习结论、当前主线与下一步计划见
`LEARNING_PROGRESS.md`。开启新的协作会话时，先阅读 `AGENTS.md`，再阅读本文件和
`LEARNING_PROGRESS.md`。

## 项目定位

LifeOps Agent 是一个本地 Python 生活管理 Agent，也是一个用于学习 Agent Runtime 的长期项目。
它的产品目标是逐步发展成真正可用的个人生活管理助手；它的学习目标是用可阅读、可观察的实现理解：
Function Calling、Skill、Capability、Context、状态、副作用、安全边界和执行可靠性。

当前业务能力不是一次性 demo，而是产品雏形。Todo、Wellbeing、Finance 和 Activity 领域既用于验证
Runtime 机制，也应朝着真实生活管理场景逐步打磨。

当前原则：

1. 优先亲自实现核心机制，避免框架隐藏执行过程。
2. 先用真实失败暴露缺口，再增加最小机制。
3. 业务写入必须来自用户当前输入的明确授权。
4. Event、LLM I/O 和 Application 日志应能解释一次执行。
5. 自动化测试保留为回归安全网；不长期保存一次性大规模验收产物。
6. 学习路线服务于最终产品化：机制设计既要帮助理解，也要让真实用户数据更安全、更可恢复、更可解释。

## 技术与运行

- Python 3.13+
- OpenRouter 与兼容 OpenAI Responses API 的模型
- Pydantic
- 本地 JSON 持久化
- `uv` 项目环境

```powershell
# 运行 Agent
uv run python main.py

# 查看日志
uv run python log_viewer.py

# 运行自动化测试
uv run python -m unittest discover -s tests -v
```

## 代码结构

| 路径 | 当前职责 |
|---|---|
| `main.py` | CLI 入口和多轮用户输入循环 |
| `app/agents/agent.py` | 单次 Chat 的准备、Agent Loop、LLM/Tool 编排和最终回答校验 |
| `app/runtime/run_state.py` | 单次 `Agent.chat()` 的 RunState、ActionRecord、预算与终态 |
| `app/runtime/errors.py` | LLM/Tool 错误分类与结构化错误 |
| `app/runtime/write_policy.py` | 当前用户输入的写授权、批量删除确认和成功声明检测 |
| `app/context/context_engine.py` | LLM 输入组装入口；当前支持 pass-through、滑动窗口、按需恢复，以及主动/被动/手动压缩触发 |
| `app/context/context_budget.py` | Context窗口预算配置，当前使用字符数近似token估算，并区分 soft limit / hard limit |
| `app/context/context_store.py` | 内存版完整历史、Rolling Summary和手动LLM自然语言摘要状态存储 |
| `app/context/context_compactor.py` | 确定性Rolling Summary生成，把被窗口排除的旧Unit压缩成结构化摘要 |
| `app/context/context_index.py` | 基于metadata的旧Context Unit与Ref按需检索；不使用embedding |
| `app/context/context_inspector.py` | 把Context assembly report整理成overview、composition、decisions和diagnostics，便于日志观察和测试定位 |
| `app/context/context_types.py` | ContextAssembly、ContextUnit 和字符数到 token 的近似估算类型 |
| `app/context/context_manager.py` | Tool Observation 的 inline、summary、reference 压缩 |
| `app/context/context_ref_store.py` | 完整 Tool Result 的 Context Ref 存储、metadata/hash/过期校验与读取 |
| `app/memory/profile_loader.py` | 只读加载 `data/memory/profile.md` 用户画像，不创建、不修改Profile |
| `app/memory/memory_types.py` | Semantic Memory 的 `MemoryItem` 数据模型 |
| `app/memory/memory_store.py` | `data/memory/semantic_memories.json` 的保存、查询和软删除 |
| `app/memory/memory_retriever.py` | 按本轮用户输入对 active Semantic Memory 做关键词/type/tag 简单检索 |
| `app/memory/memory_context.py` | 将 Profile 和检索到的 Semantic Memory 格式化成本轮只读上下文片段，并生成日志诊断 |
| `app/runtime/idempotency_store.py` | 写工具成功结果的幂等存储与重放 |
| `app/skills/skill_router.py` | 当前输入的确定性 Skill 路由 |
| `app/skills/skill_state.py` | Skill 继承、替换、清理和 Ref-only 状态 |
| `app/skills/skill_loader.py` | Skill 元数据发现和完整正文按需加载 |
| `app/skills/*/SKILL.md` | Todo、Finance、Wellbeing、Activity 领域规则 |
| `app/prompts/prompt_builder.py` | 根据本轮 Skill 动态构建 Prompt |
| `app/tools/capability_builder.py` | 根据 Skill 和写授权生成本轮工具可见性与权限 |
| `app/tools/registry.py` | 工具定义、副作用、幂等、重试和超时元数据 |
| `app/tools/executor.py` | 工具授权、执行、超时、幂等重放和异常归一化 |
| `app/domains/*` | Todo、日状态、消费预算和活动目录的本地业务数据 |
| `app/observability/*` | 三通道日志及安全序列化 |
| `app/log_viewer/*` | 本地日志查看器，支持普通会话和UAT目录格式 |
| `tests/*` | 核心 Runtime、Context、安全、Skill、日志与工具的回归测试，其中 `tests/test_context_eval_cases.py` 覆盖Context压缩前后关键不变量 |

## 状态与生命周期

这是当前理解项目时最重要的边界：

| 对象 | 生命周期 | 保存内容 |
|---|---|---|
| Logging Session | 一次进程级日志会话 | `session_id` 和三类日志文件 |
| `Agent` | 一个CLI对话实例 | `messages`、Skill元数据、活跃Skill、限制、最近一次RunState |
| `Agent.messages` | 跨多次 `chat()` | 用户消息、LLM输出、Function Call、Tool Observation |
| `TurnContext` | 一次用户输入 | 固定Prompt、Tool Schema、授权工具、加载Skill、安全标记 |
| `RunState` | 恰好一次 `Agent.chat()` | 本次Chat的LLM轮次、API请求、工具执行尝试、Action和终态 |
| `ActionRecord` | 一次模型请求的工具Action | 参数、结果、错误、工具执行尝试、签名和幂等键 |

`Agent.last_run_state` 指向最近一次 `chat()` 创建的RunState；执行过程中它代表当前Run，
执行完成后它代表上一笔已完成Run。它不是整个Session的累计状态。

RunState的主要计数字段已经显式包含作用域和统计对象：

- `chat_llm_round_count`：本次Chat的逻辑LLM轮次。
- `chat_llm_request_count`：本次Chat实际发送的LLM API请求数，包含重试。
- `chat_tool_execution_attempt_count`：本次Chat的工具执行尝试数，包含工具重试。
- `action_records`：本次Chat内的模型请求Action记录。
- `chat_retry_counts_by_operation`：本次Chat按操作归类的重试次数。

序列化的RunState包含 `state_scope: single_agent_chat`。

## 当前执行链路

```text
用户输入
-> Skill Router
-> Skill State Resolver
-> 当前输入写授权分析
-> Prompt Builder
-> Capability Builder 过滤 Tool Schema 和执行权限
-> 创建单次 Chat RunState
-> ContextEngine assemble 生成本轮 LLM input 与预算报告
-> Memory 层读取只读 Profile 并检索相关 active Semantic Memory，注入本轮 LLM input
-> LLM Request
-> LLM回答，或返回Function Call
-> Runtime校验权限、预算、取消、重复与无进展
-> Tool Executor执行，按错误类型决定是否重试
-> 写工具使用幂等键保存成功结果
-> Context Manager压缩Tool Observation
-> ActionRecord记录结果，Observation返回LLM
-> 最终回答校验写入声明
-> 完成，或以结构化StopReason停止
```

## 已实现能力

### 业务工具

- Todo：新增、查看、完成、删除、更新和日计划。
- Wellbeing：记录与查询睡眠、心情、能量和备注。
- Finance：记录、查询、汇总消费，设置和检查分类预算。
- Activity：按时间、地点、预算、心情、能量和目标推荐本地活动。

### Skill与Capability

- Skill元数据始终可用于路由，完整正文只在选中后加载。
- 明确领域信号替换旧Skill；含糊追问可继承；普通闲聊清理。
- Prompt每次Chat重新构建，不把Skill正文追加到历史消息。
- LLM只看到本轮允许的Tool Schema，Executor在执行前再次校验权限。
- 当前输入没有明确授权时，写工具不会暴露给模型。

### 写入安全

- 描述个人状态或请求建议不等于授权保存数据。
- 描述长期偏好或事实不等于授权保存Memory；只有当前输入明确要求“记住/保存/以后默认”等，才暴露 `save_memory`。
- 删除Memory需要当前输入明确表达“忘掉/删除记忆”等授权；删除后该Memory默认不再查询或注入。
- 批量删除需要确认后才能暴露删除能力。
- 最终回答声称“已保存/已修改”时，必须有成功WRITE Action作为依据。
- 部分写入失败时，Runtime会替换模型的虚假全成功声明。

### Agent Loop可靠性

- LLM逻辑轮次、LLM API请求、工具执行尝试和重试分别计数。
- 工具错误统一包含 `type`、`code`、`message` 和 `retryable`。
- SDK隐式重试关闭，LLM/Tool重试由Runtime显式管理。
- 重复非幂等写、相同Observation和A-B-A-B调用循环可以被拦截。
- 强制停止时保留并汇总成功、失败和跳过的Action。
- 工具支持线程超时；取消目前在调用边界协作式生效。

## 当前Context实现

当前已有第一版 ContextEngine 滑动窗口、确定性 Rolling Summary、主动/被动/手动压缩触发和 Tool Observation 压缩。Tool Observation 压缩解决单次工具结果过大，滑动窗口与Rolling Summary解决跨轮历史持续增长，二者不要混淆。

Context Engine 执行计划的前九步已经完成第一轮收口：除了功能机制本身，已新增Context Eval自动化回归，用来验证压缩前后关键行为、事实字段、Ref恢复和安全状态不被破坏。当前Context阶段不继续横向扩展向量检索或复杂LLM评测，已进入并完成最小Memory State v1。

### Prompt与历史消息

- `instructions` 每轮重新生成，通过独立参数发送。
- `Agent.messages` 保存跨Chat历史，包括Function Call和Tool Observation。
- `ContextStore` 当前以内存方式镜像完整历史和Rolling Summary；完整历史仍是事实源，summary只是派生状态。
- 发送给模型的 `input` 已由 `ContextEngine.assemble()` 生成；短对话仍原样透传，超过最近窗口预算时只发送历史summary或占位说明、protected units 和最近完整 units。
- Profile 和 Semantic Memory 在 `ContextEngine.assemble()` 之后作为本轮只读输入插入局部 `input_messages`；它们不写入 `Agent.messages`，不进入 `ContextStore`，不参与 Rolling Summary，也不进入 `ContextIndex`。
- `ContextEngine` 会把历史切分为 user、assistant、tool 或 protected system_note 单元，并在日志中报告原始消息数、组装后消息数、单元数、近似token数、tool schema体积、evicted unit 数、summary插入状态、protected unit 数和被动压缩决策。
- Function Call 与紧随其后的 `function_call_output` 会被识别为同一个 tool unit；无法配对的工具相关消息会保守标记为 `protected=True`。
- `ContextIndex` 会为旧unit提取确定性metadata，包括tool name、ref_id、entity id、domain关键词和action状态。`ContextEngine.assemble()` 只在当前用户请求出现精确字段/后续操作信号时，从窗口外旧unit中召回少量相关内容。
- 按需恢复会把 retrieved unit/ref 写入 assembly report，说明召回原因、匹配字段和ref加载状态；普通总结类请求不会读取完整ref。
- `ContextInspector` 会在 `assembly.report.inspection` 中输出压缩概览、组成计数、关键决策和诊断提示，例如 placeholder summary、精确请求未召回匹配内容、ref rejected 等。
- `tests/test_context_eval_cases.py` 验证压缩不变量：精确Todo后续操作只召回相关旧Unit、Expense金额/日期可恢复、失败WRITE只进入失败摘要、protected确认状态跨窗口/被动压缩保留，以及Ref恢复不会重新插入完整历史。
- Skill正文不会累积进 `messages`。
- `Agent.messages` 仍会随长对话增长；增长的是完整事实源，不再总是无脑全量发送给模型。
- 回合完成或停止时，`ContextEngine.after_turn()` 只在完整历史超过 soft limit 后主动触发确定性 rolling summary，不调用LLM。第一版summary用确定性规则生成：记录来源unit ids、用户目标片段、工具成功/失败、重要实体和受保护项；不会把assistant口头声称的成功当作真实成功。
- `ContextEngine.assemble()` 会在请求前检查 hard limit；如果组装后的输入仍超过预算，会被动缩小 recent window，作为预算保护路径。被动触发不生成新summary，也不调用LLM。
- CLI 支持内部命令 `/compact`。该命令不会作为普通用户消息进入 `Agent.messages`，而是立即执行手动压缩：先更新 deterministic summary，再用一次无工具LLM调用生成 `natural_language_summary`。该自然语言摘要只是软上下文，结构化summary和完整历史仍是事实源。

## 当前Memory实现

当前已有最小 Memory State v1，目标是让 Agent 能使用长期用户画像和用户明确授权保存的长期事实/偏好/目标/约束，同时保持 Memory、Context Summary 和业务数据边界清晰。

### Profile Memory

- Profile 来自 `data/memory/profile.md`，由用户或开发者手动维护。
- `ProfileLoader` 每轮请求前只读加载该Markdown；文件不存在时返回空Profile，不阻断Agent。
- Runtime 不会创建、修改、合并、总结或覆盖 `profile.md`。
- 默认模板使用Markdown注释，避免占位说明被当作真实用户画像注入。
- 加载到的Profile只作为本轮请求的只读system context，不进入对话历史或Context压缩链路。

### Semantic Memory

- Semantic Memory 存储在 `data/memory/semantic_memories.json`，记录 `MemoryItem`：`id`、`type`、`content`、`source`、`created_at`、`updated_at`、`status` 和 `tags`。
- `type` 当前支持 `fact`、`preference`、`goal` 和 `constraint`。
- `save_memory`、`list_memories`、`delete_memory` 已注册为工具；其中 `save_memory` 和 `delete_memory` 是WRITE工具，只有当前用户输入明确授权时才会暴露给模型。
- `list_memories` 是READ工具，用于用户显式查看已保存Memory；默认只返回 active items。
- `delete_memory` 采用软删除，把 `status` 标记为 `deleted`；删除后的Memory默认不再查询，也不会被自动注入上下文。
- assistant 口头声称“记住了”不构成保存事实；只有 `save_memory` 工具成功写入才算真正保存。

### Memory Retrieval 与注入

- 每次 LLM 请求前，Runtime 用本轮原始 `user_input` 调用 `MemoryRetriever.retrieve()`，从 active Semantic Memory 中按关键词、type和tag做简单规则检索。
- 检索结果由 `memory_context.py` 格式化成 `Relevant saved memories` system context，并插入本轮局部 `input_messages`。
- Profile 和 Semantic Memory 注入都发生在 `ContextEngine.assemble()` 之后，因此不会被ContextEngine当作可被压缩、索引或移出窗口的对话历史。
- Memory日志诊断记录 `profile_loaded`、Profile路径和字符数、注入的 Semantic Memory ids、type、命中原因和总字符数，但不把Profile正文复制进诊断report。
- 第一版不做向量检索、embedding、自动聊天扫描、LLM静默提取、Episodic Memory、Procedural Memory，也不把Todo/Expense/Sleep/Daily Log复制进Memory。

### Tool Observation压缩

`compact_tool_output()`在工具成功后，根据字符数、主列表长度和请求数量选择：

1. `none`：小结果完整进入Context。
2. `summary`：中等结果替换成领域结构化摘要。
3. `summary_reference`：中等结果使用摘要进入Context，同时保存完整结果到Ref以便恢复。
4. `reference`：大结果保存完整值，只把摘要、`ref_id`和读取提示放入Context。

当前阈值使用字符数和列表条数，不是精确token数。Todo、Expense、Daily Log和Activity
有领域摘要；Todo/Expense摘要可根据工具参数中的 `limit` 保留更多条关键记录。错误结果与 `read_context_ref` 返回值不再次压缩。

`list_todos` 支持 `limit`、`status` 和 `sort` 参数，优先从工具源头减少Observation体积。

### Context Ref

- Reference和Summary+Reference策略会把完整结果写入本地Ref Store。
- LLM只有在工具结果明确提供真实 `ref_id` 后，才应调用 `read_context_ref`。
- Ref记录包含 `created_at`、`expires_at`、`tool_name`、`summary`、`full_result` 和 `payload_hash`。
- `read_context_ref` 会拒绝非 `ctx_` 前缀、不存在或已过期的Ref。
- 当前Ref还没有session/run归属和更细访问范围策略。
- Summary+Reference策略已经能让被摘要丢掉的完整结果按需展开；纯Summary仍不创建Ref。

### 已确认的Context缺口

- 当前只有工具参数中的 `limit` 会传递给摘要数量；尚未从自然语言用户请求中独立解析 requested_count。
- 压缩策略尚未系统理解哪些字段和后续Action一定需要精确保留。
- Summary与Reference的选择主要由体积决定，而不是信息需求决定。
- ContextIndex目前是确定性metadata检索，不做语义向量检索；只召回窗口外相关unit/ref，不保证理解所有自然语言指代表达。
- Runtime只能检测确定性重复，不能识别“不断微调参数但目标不变”的语义循环。
- 模型可能构造未由Runtime签发的Ref ID；工具会返回Not Found，但调用前尚无来源校验。

## 可观测性

每个Logging Session包含：

- `events.jsonl`：Runtime关键节点和紧凑上下文摘要。
- `llm.jsonl`：完整Request与诊断型Response投影。
- `application.log`：传统程序日志。

LLM Response不重复记录Request中的instructions、tools和参数，只保留输出、状态、错误、
用量和必要标识。日志查看器在Events页面明确显示RunState统计范围及本次Chat计数，并兼容
旧字段和旧日志。

## 当前限制与非目标

- Router仍是简单规则匹配，中英文归一化和广泛表达覆盖暂不优先。
- Memory Retrieval目前是关键词、type和tag的确定性规则检索，不使用embedding，不保证理解所有自然语言指代。
- Semantic Memory目前支持新增、查看和软删除；尚无更新/合并、冲突检测、过期时间、重要性权重和高级检索。
- 工具按顺序执行，没有依赖图、安全并行和并发写控制。
- RunState只在内存中，不支持崩溃恢复。
- 幂等存储不是事务型exactly-once。
- 同步SDK或Python函数不能被强制中断。
- 尚无全局wall-clock、token或cost预算。
- 尚无Interaction State、Task State、MCP和Multi-Agent。

## 本地数据

以下目录是本地运行数据，不属于一次性测试源文件：

```text
data/
data/memory/profile.md
data/memory/semantic_memories.json
logs/
```

它们可能包含用户数据和历史日志，除非用户明确要求，不应删除。
