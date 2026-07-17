# Context / Memory 模块计划

文档状态：Stage 9A 与 Stage 9B 已于 2026-07-16 分别完成独立 gate 并取得 `go`；本节 28 的接口保持冻结，整个 Stage 9 已完成并关闭。

最后确认日期：2026-07-16

## 1. 模块目标和用户主线

Stage 9 统一设计 Context 与 Memory，是为了让两者共享清晰的输入、预算、provenance、安全和生命周期边界，但施工必须拆成两个独立 gate。

用户主线分成两条：

1. 同一 session 内，LifeOps 能在 Direct、Planning 和 PlanStep 中连续理解用户刚才说过的话；上下文过长时用 rolling summary 加最近原始 turns 控制 prompt 大小；进程重启后仍能从 session 文件恢复连续性。
2. 用户可以自己编辑固定 Profile，也可以明确说“请记住……”并在预览确认后保存长期 Memory；以后可以查看、检索、修改和归档。系统不能从普通对话、summary、Tool observation、Domain candidate 或模型推断静默保存。

V1 优先小、确定、可解释，适合本地产品、单元测试和面试讲解。

## 2. 当前已有接口与实现基础

当前可直接复用的窄接缝：

- RuntimeService 是外部请求入口，拥有 run lifecycle、session 日志和 outer orchestration 调用。
- RuntimeRequest、run_id、turn_id、session_id 已提供请求身份。
- ReactExecutor 已有 ExecutorContextProvider.load(request, plan_step=None) 和 ExecutorMemoryProvider.load(request, plan_step=None)。
- Executor provider contribution 当前只有 content 和 source；provider 在一次 Executor invocation 开始时读取一次。
- PlanStepExecutionInput 已把 plan_id、revision、step_id、objective、expected outcome 和依赖结果传到 Executor provider。
- PlanningService 已有 PlanningSnapshotProvider 窄接口；它只接受 typed trusted scope refs，不从自然语言推断 Domain scope。
- Planner、PlanningRouter 和 Executor 都已拥有 typed model input builder，不需要改写控制循环。
- events.jsonl、llm.jsonl、application.log 已有不同用途和隐私边界。
- Policy decision、selected Skill、Registry 和 effect 求交得到的 AllowedToolSet 是当前实际 Tool 授权结果；Stage 9 不新增第二套授权来源。

当前 Research、Travel 已实现 DomainContextProvider 和 DomainMemoryCandidateProvider，并有 read model、稳定排序、预算和 contract tests。它们继续作为 Domain 共享只读接口存在，但不是本计划 Stage 9A 的 production 输入。

当前 `app/context/` 已提供 conversation JSONL repository、rolling summary、bounded assembly 与 Runtime/Planner/Executor projection；`app/memory/` 已提供 production read-only Profile provider、Memory contracts、durable SQLite V4 metadata index、immutable Memory document store、save/update/archive lifecycle、orphan audit、duplicate/conflict、deterministic verified retrieval、memory Skill、5 个 Tool、Policy/confirmation/Gateway/evidence、production Context provider、privacy events、compiled E2E 与真实 LLM smokes。实现没有改写 Stage 9A 冻结接口。

本次设计前已运行当前共享 Domain read contract、Research/Travel read model、Executor provider/PlanStep 和 PlanningService 的聚焦核对，共 `26/26` 通过。代码接缝与 Stage 7/8 路线总体一致，但文档有两处需要本计划正式收敛：

- 总路线图仍列出两个尚不存在的 CONTEXT_PLAN/MEMORY_PLAN，本轮改为一个统一设计文件、两个实施 gate。
- 早期路线预期 Context 消费 Research/Travel candidates；用户场景现已明确为不绑定 Domain 的 session conversation，因此保留 Domain provider 契约但不接入 Stage 9A。

## 3. V0 历史参考及可复用经验

历史参考只来自：

- legacy_v0/plans/CONTEXT_ENGINE_IMPLEMENTATION_PLAN.md
- legacy_v0/plans/MEMORY_STATE_IMPLEMENTATION_PLAN.md
- legacy_v0/app/context/
- legacy_v0/app/memory/

可复用经验：

- Context 必须有确定预算、稳定顺序、sliding window 和 rolling summary。
- summary 应由旧 summary 加本次被压缩的连续 turns 增量生成，而不是每轮重做整个 session。
- session conversation 适合使用独立 JSONL 文件，不应混入业务 SQLite 或诊断 llm.jsonl。
- Profile 与长期 Memory 应分开注入；Profile 是用户编辑的稳定说明，Memory 是经过明确授权保存的条目。
- summary、observation、日志和 Domain read model 都不能自动升级为长期 Memory。
- 简单 tag / keyword retrieval 足以验证 V1 边界，不必先引入 embedding 或 vector database。

不复用的 V0 设计：

- 不恢复承担过多职责的全局 Agent messages 聚合器。
- 不恢复复杂 Context ref/index/compactor 平台。
- 不使用可原地覆盖的单一 JSON Memory store。
- 不复用旧 capability map 或 authorized_write_tools 作为另一套授权系统。
- 不提供 hard delete Tool。
- 不把 Domain candidate provider 接入 session conversation assembly。

## 4. V1 范围

### Stage 9A：Context Engine

- 按 session_id 保存用户可见 conversation turns。
- 每个 RuntimeRequest 只组装一次 ContextAssembly。
- Direct、PlanningRouter、Planner 和所有 PlanStep 共享同一 assembly。
- 使用 query、总预算、最近 turn 上限和固定子预算。
- 使用 rolling summary、recent original turns 和 current input。
- 保留 contribution provenance、ContextReport、degrade reason 和 assembly_id。
- 通过现有 Planner / Executor 窄输入接缝投影 bounded context。
- Stage 9A 使用 empty/fake ProfileProvider 和 MemoryProvider。
- 提供离线测试、compiled E2E 和 5 个真实 LLM happy paths。

### Stage 9B：Long-term Memory

- 读取用户直接编辑的固定 Profile Markdown。
- 只保存用户明确要求记住的 Explicit Memory。
- Memory 全文写入不可变文件，SQLite 只保存索引和 lifecycle metadata。
- 提供 save、search、list、update、archive Tool。
- 所有 Memory WRITE 都经过 preview、Policy/AllowedToolSet、confirmation、Gateway、Guardrails 和 evidence。
- 通过 Stage 9A 冻结的 provider 接口加入同一个 ContextAssembly。
- 提供离线测试、compiled E2E 和 5 个真实 LLM happy paths。

## 5. 明确不做的内容

- 向量数据库、独立向量服务、embedding 或模型 reranker。
- SQLite FTS5。
- 自动用户画像。
- 模型自行判断并静默保存 Memory。
- 每轮对话自动提取 Memory。
- 从 conversation summary、Tool observation、Context candidate、MCP result、Domain fact 或模型推断自动写 Memory。
- 多 Agent 或多用户共享 Memory。
- 分布式存储和后台异步 Memory pipeline。
- Memory graph 平台。
- Planner 或 Executor 专用的第二套 Memory。
- 把 LangGraph checkpoint、PlanRun 或 conversation summary 当长期 Memory。
- Stage 9A 的 Domain candidate retrieval。
- 复杂动态 budget allocator、学习排序、权重优化或 query rewrite。
- Profile 写入 Tool和 Memory hard delete。
- session 对话文本或 summary 写入 SQLite。
- 后台 session 清理、自动 retention 或自动归档。

## 6. Context 与 Memory 的职责边界

Context 是“当前请求允许模型看到的 bounded 输入集合”。它包含本 session 的 summary、recent turns、current input，以及 Stage 9B 后可选的 Profile 和显式 Memory。它是 request-local assembly，不是事实库，也不授权 Tool。

Conversation history 是用户可见对话的 session-local 原始记录。它用于连续性，不等于长期偏好或业务事实。

Conversation summary 是 history 的 session-local 派生压缩。它可以进入 prompt，但不能覆盖原始 turns、不能成为 evidence、不能自动写 Memory。

Profile 是用户直接编辑的 durable Markdown。Agent 只读。它表达稳定偏好，但在与当前输入或业务事实冲突时不能静默覆盖它们。

Explicit Memory 是用户明确要求记住、确认后由 Memory Tool 写入的 durable 条目。它是长期补充信息，不是 Tool 授权，也不是 Domain repository 的替代品。

Domain facts 仍由 Domain repository 和成功 ToolResult / ExecutionEvidence 证明。Context 和 Memory 只能提供模型输入，不能提升为 Domain fact。

## 7. request-local、session-local、durable 三种生命周期

| 生命周期 | 对象 | 存储 | 边界 |
|---|---|---|---|
| request-local | ContextQuery、ContextAssembly、ContextReport、bounded model projection | 仅当前 RuntimeRequest 的 runtime context/result-local 对象 | 请求结束即释放，不进入 GraphState/checkpoint/PlanRepository |
| session-local | ConversationTurn、ConversationSummary | 每个 session 独立的 turns.jsonl 与 summaries.jsonl | 跨请求和进程重启可读取，不写 SQLite |
| durable | Profile、Explicit Memory document、Memory index/version/status | 固定 Profile Markdown、不可变 Memory 文件、SQLite index | 跨 session 存在，只有用户编辑 Profile 或确认 Memory Tool 才能改变 |

Stage 9A 不实现 session 删除或 retention。原始 turns 保留在 session JSONL 中，summary 只影响 assembly，不删除源记录。

## 8. 整体依赖方向

依赖方向必须保持：

User input / PlanRun goal
→ RuntimeService request context
→ ConversationRepository + ContextAssembler
→ frozen ContextAssembly
→ Planner/Router projection 或 Executor Context/Memory provider adapter
→ model input builder

Stage 9B 的读取方向：

ProfileFileProvider + MemoryRetriever
→ ContextAssembler 的固定 slots
→ 同一个 frozen ContextAssembly

Stage 9B 的写入方向：

explicit user request
→ memory Skill candidate
→ Policy + AllowedToolSet
→ exact ToolCall preview
→ synchronous confirmation
→ ToolGateway + Guardrails
→ MemoryService
→ immutable file + SQLite index
→ ToolResult + ExecutionEvidence

禁止反向依赖：

- context 或 memory core 不依赖 LangGraph。
- conversation repository 不依赖 Planner、Executor、Domain 或 Tool Gateway。
- Memory repository 不依赖 Planner、Executor 或模型 SDK。
- Planner/Executor 不读取 conversation/Memory 文件或 SQLite internals。
- Domain 不依赖 ContextAssembler。

## 9. Stage 9A Context Engine 架构

### 9.1 计划模型

ConversationTurn：

- schema_version
- session_id
- turn_id
- sequence
- role: user 或 assistant
- kind: natural_input、plan_command、clarification、plan_preview、command_result、final_answer
- content
- run_id
- created_at

只保存用户真正看到的内容：

- 用户自然语言输入。
- confirm-plan、modify-plan、cancel-plan 的安全结构化表示。
- assistant 展示给用户的 clarification、plan preview、confirm/cancel result、Direct final 和 Plan final。

不保存：

- Tool observation。
- PlanStep 中间结果。
- Skill selector、PlanningRouter、Planner、Executor、Finalizer 或 Summarizer 的内部 response。
- private reasoning。
- provider 原始对象。

ConversationSummary：

- schema_version
- session_id
- summary_id
- version
- covered_start_sequence
- covered_end_sequence
- content
- estimated_tokens
- previous_summary_id
- source_turn_ids 或等价的连续范围 provenance
- provider/model identity
- created_at

ContextBudget：

- max_total_tokens
- max_recent_turns
- max_summary_tokens
- max_profile_tokens
- max_memory_items
- max_memory_tokens
- max_current_input_tokens

ContextQuery：

- text
- origin: current_user_goal 或 confirmed_plan_goal
- session_id
- run_id
- turn_id

ContextContribution：

- kind: conversation_summary、conversation_turn、current_input、profile、memory
- source
- content
- estimated_tokens
- provenance

ContextAssembly：

- assembly_id
- session_id
- run_id
- turn_id
- query
- contributions
- estimated_total_tokens
- report

ContextReport 只保存安全 metadata：

- assembly_id
- selected turn count
- summary version 和 covered range
- profile included
- memory candidate/selected counts
- per-kind estimated token counts
- trimmed counts
- degraded components 和稳定 error code
- created_at

以上是计划契约，不是已实现类型。Stage 9A 步骤 1 会把字段冻结成具体 immutable models。

### 9.2 Repository 和 Port

ConversationRepository 最小能力：

- append_turn(turn)
- load_turns(session_id, before_or_at_sequence, limit)
- append_summary(summary)
- load_latest_valid_summary(session_id)

文件布局：

- data/conversations/{validated_session_id}/turns.jsonl
- data/conversations/{validated_session_id}/summaries.jsonl

每行是一个完整 UTF-8 JSON object，以换行结束。session_id 必须由 Runtime 验证并映射为安全目录名，不能由模型提供任意路径。

ContextSummarizer 最小能力：

- summarize(previous_summary, contiguous_turns, budget)

ContextAssembler 最小能力：

- assemble(query, budget, conversation_repo, summarizer, profile_provider, memory_provider)

Stage 9A 的 ProfileProvider 和 MemoryProvider 返回空结果；测试 fake 可返回固定 contribution，用来冻结 Stage 9B 接口和预算行为。

### 9.3 一次请求只 assembly 一次

RuntimeService 在进入 Planning route 或 Direct Executor 前：

1. 校验 current input 上限。
2. 把当前 user turn 追加到 conversation JSONL。
3. 构造 ContextQuery。
4. 读取当前 turn 之前的 history 与最新有效 summary。
5. 必要时调用一次 ContextSummarizer。
6. 产生一个 frozen ContextAssembly。
7. 把 assembly 放入 request runtime context/result-local 容器。

同一请求后续所有模型调用只读取这个 assembly 的 projection。confirmed plan 请求使用 durable PlanRun.goal 加 confirmed constraints 作为 query；所有 PlanStep 复用同一个 assembly_id，不按 Step 重新检索或重新 summary。

请求完成后，把真正展示给用户的 assistant result 追加到 conversation JSONL。

## 10. Stage 9B Long-term Memory 架构

### 10.1 两种且只有两种长期来源

User Profile：

- 固定路径 data/memory/profile.md。
- 用户通过编辑器或产品设置页直接修改。
- Agent 只读，不提供 Profile WRITE Tool。
- 不进入 Memory SQLite index。
- 文件缺失或格式无效时降级为空。

Explicit Memory：

- 只有当前用户明确说“记住……”或等价明确表达时，memory Skill 才应成为候选。
- 模型提出 memory.save ToolCall；confirmation preview 展示规范化后的完整 content、tags 和 global scope。
- 用户确认前不写文件、不写 SQLite。
- 成功 ToolResult 和 ExecutionEvidence 才证明保存完成。

### 10.2 混合存储

Memory 全文保存在不可变 UTF-8 Markdown 文件：

- data/memory/entries/{system_memory_id}/v{system_version}.md

SQLite 只保存 memory_index，不保存全文。Stage 9B 已在原 schema V3 之后新增 V4 `memory_index` migration。

MemoryIndexRecord 最小字段：

- memory_id
- version
- status: active、superseded、archived
- relative_path
- content_hash
- tags_json
- created_at
- updated_at
- supersedes_memory_id
- supersedes_version
- source_session_id
- source_turn_id
- source_run_id
- source_tool_call_id
- confirmation_ref
- evidence_ref

路径、ID、version 和 hash 由系统生成。用户和模型都不能传入文件路径。

MemoryDocument 文件只保存该 version 的确认后全文。update 创建新 version 文件和新 index row，旧 version 标记 superseded；archive 只改变 index lifecycle，不删除文件。

V1 只服务一个本地用户，Memory scope 固定为 global。Research Topic、Travel Trip、session、PlanRun 都不是 Memory scope；optional tags 只用于查看和关键词检索，不能变成隐藏的授权或隔离层。本阶段不设计多用户 user_id 或跨 Agent sharing。

### 10.3 写入原子性

每次 save/update：

1. 校验 confirmed Tool arguments 和 expected version。
2. 在固定 memory root 下写同文件系统临时文件。
3. fsync/close 后使用 atomic replace 放到系统生成的最终路径。
4. 开启短 SQLite transaction 写 index 和 lifecycle 变化。
5. commit 后返回 ToolResult/Evidence。

若文件落盘后 SQLite 失败，文件是不可检索的 orphan；正常 retrieval 只从 committed index 出发。提供安全、显式的 orphan audit/cleanup helper，但 Stage 9B 不做后台任务。

读取时重新计算 hash。文件缺失、损坏或 hash mismatch 的单条 Memory 被跳过并记录安全错误码，不影响其他合法 Memory。

## 11. Domain candidate provider 接入方式

本轮确认后的决策覆盖总路线图中“Stage 9A 收集 Research/Travel Context candidates”的早期表述：

- Stage 9A Context 是 session conversation context，不绑定 Domain。
- Stage 9A 不调用 DomainContextProvider。
- Stage 9B 不把 DomainMemoryCandidateProvider 的候选自动写入或自动检索为长期 Memory。
- Research/Travel 现有 provider、read model 和 tests 保留，不删除、不改名，供未来明确的新场景或其他消费者使用。
- PlanningSnapshotProvider 继续是独立的 trusted Domain read seam，不并入 conversation Context。
- Domain facts 若需进入某次 Tool 执行，继续通过 Domain Tool/read model/PlanStep dependency，而不是通过 Stage 9 Context 暗中注入。

因此 Stage 9 不存在 Domain scope 生成、跨 Domain ranking 或跨 Domain candidate dedupe。

## 12. Context assembly、预算、排序、去重和 provenance

### 12.1 预算

V1 使用确定性的本地 token 估算，例如基于规范化文本字符数除以固定常数并向上取整。它只用于稳定裁剪和测试，不声称等于 provider tokenizer。

规则：

- current input 必须保留，并有独立 max_current_input_tokens 校验；超限直接返回用户可理解的 input-too-large。
- 整个 assembly 受 max_total_tokens 限制。
- recent turns、summary、Profile、Memory 各有简单固定 cap。
- Stage 9A 的 Profile/Memory cap 先冻结但返回空。
- Stage 9B 的 Profile/Memory 只能使用自己的 cap 和剩余总预算，不能挤掉 current input 或已保留的 recent conversation。
- 不做动态配额竞争、模型计数、远程计数或权重优化。

### 12.2 conversation 顺序和压缩

固定 prompt 渲染顺序：

1. Stage 9B 的 Profile。
2. Stage 9B 的 active Memory，按稳定 retrieval 顺序。
3. 最新有效 summary。
4. summary 覆盖范围之后的 recent original turns，按 sequence 升序。
5. current user input，且只出现一次。

Stage 9A 没有 Profile/Memory 内容，因此实际顺序就是 summary → recent turns → current input。渲染顺序不改变预算保护优先级：current input 和 recent conversation 先保留，Profile/Memory 只能使用各自 cap 与剩余预算。把 current input 放在最后，也让最新明确表达保持最靠近模型作答位置。

如果 history 超预算：

- 优先保留最近 max_recent_turns。
- 对更早、尚未被 summary 覆盖的连续 turns 调用 Summarizer。
- 输入是 previous valid summary 加本次新增的连续 turns。
- 只有完整、合法、预算内的 summary 才 append 到 summaries.jsonl。
- 原始 turns 不删除。

### 12.3 去重

- current input 通过 turn_id 排除在 history projection 之外，防止重复。
- summary 的 covered_start/end_sequence 与 recent turns 不重叠。
- 相同 turn_id 在 assembly 中最多一次。
- Memory 用 memory_id + active version 去重。
- Profile 固定只有一个。

### 12.4 provenance

每个 contribution 都必须能追溯：

- conversation turn → session_id、turn_id、sequence。
- summary → summary_id、version、covered range、source summary/turn range。
- Profile → 固定相对路径和内容 hash。
- Memory → memory_id、version、relative path、hash、确认/evidence refs。

provenance 只能解释来源，不能产生授权。

## 13. Context report 和 GraphState 边界

ContextAssembly 和完整 ContextReport 不进入 outer GraphState、ExecutorState、LangGraph checkpoint、PlanRun、PlanStep 或 Domain repository。

RuntimeService 拥有 request-local assembly，并通过窄 provider/projection 传给消费者：

- PlanningRouter 和 Planner model input 新增可选 bounded context contribution 字段。
- Direct Executor 的 ExecutorContextProvider adapter 返回 conversation contribution。
- ExecutorMemoryProvider adapter 返回 Profile/Memory contribution；Stage 9A 为空。
- confirmed PlanStep 的 provider adapter 从相同 request runtime context 读取同一 assembly_id。

GraphState 如确有诊断需要，最多保存已有 route/result，不新增 Context payload 或 report。events 只记录 ContextReport 的安全计数和 error code。

## 14. conversation history、summary 与长期 Memory 的关系

- history 是原始用户可见 session 对话。
- summary 是 history 的有损压缩，只服务当前 session 连续性。
- Profile 是用户自己维护的稳定信息。
- Explicit Memory 是用户明确要求长期保存并确认的条目。
- summary 不能自动生成、更新或删除 Profile/Memory。
- session 结束、summary 更新或进程重启不会自动改变 durable Memory。
- Memory archive 不修改过去 conversation。
- Memory retrieval 不把历史 assistant 推断伪装成用户事实。

冲突时不做静默合并：

- current user input 决定当前意图，但不会自动改写 Profile/Memory。
- 成功 ToolResult 和 Domain repository 是业务事实。
- Profile 是用户编辑的稳定说明。
- active Memory 是用户确认的长期补充。
- conversation summary 只提供连续性，优先级最低。
- 模型 prompt 必须要求标明冲突来源并向用户澄清，而不是选择一个旧来源覆盖当前输入。

## 15. Memory 数据模型、Repository、Port、Service 和 Tool

### 15.1 Port

ProfileProvider：

- load_profile() → optional bounded ProfileContribution

MemoryRetriever：

- search(query, max_items, max_tokens) → active MemoryContribution tuple

MemoryRepository：

- find_active_duplicate(content_hash)
- list_active_index()
- get_version(memory_id, version)
- insert_active(record)
- supersede_and_insert(expected_version, new_record)
- archive(expected_version)
- list_versions(memory_id)
- list_archived()

MemoryDocumentStore：

- write_immutable(memory_id, version, content)
- read_verified(relative_path, expected_hash)
- audit_orphans()

MemoryService：

- search/list
- save_confirmed
- update_confirmed
- archive_confirmed

### 15.2 Tool surface

- memory.save：WRITE。args 为 content、optional tags；scope 固定 global，不接受 path。
- memory.search：READ。args 为 query、bounded limit。
- memory.list：READ。列出 active 条目的安全摘要和 ID。
- memory.update：WRITE。args 为 memory_id、expected_version、new content、optional tags。
- memory.archive：WRITE。args 为 memory_id、expected_version。

Profile 不提供 Tool。

Memory Tools 绑定最小 memory Skill 作为业务候选。Skill selection 只决定候选，不能授权；最终仍必须进入当前 Policy/AllowedToolSet、confirmation、Gateway 和 Guardrail 链。

## 16. Memory 写入授权、confirmation 与 evidence

Memory WRITE 必须同时满足：

1. 当前用户输入明确要求保存、修改或归档 Memory。
2. memory Skill 使对应 Tool 成为候选。
3. Policy 允许对应 effect，解析后的 AllowedToolSet 包含精确 Tool。
4. 模型产生的 ToolCall 参数通过 schema。
5. confirmation provider 向用户显示 exact normalized content/scope/tags 或 update/archive target。
6. ConfirmedAction 绑定 run、call、tool、canonical argument digest 和 expiry。
7. ToolGateway pre-Guardrail 校验确认和 explicit request boundary。
8. handler 成功写文件和 index。
9. post-Guardrail、ToolResult 和 ExecutionEvidence 证明真实结果。

确认前必须零文件写、零 SQLite 写。拒绝、过期、参数变化、call ID 变化、run 变化或 expected_version 不匹配都 fail-closed。

Planner output、Context、Memory retrieval、MCP result、conversation summary、assistant 文本和模型推断都不是授权来源。

## 17. Memory 查询、去重、更新、冲突和归档

### 17.1 V1 retrieval

1. SQLite 读取 status=active 的 bounded index rows。
2. 逐条读取系统相对路径并验证 hash。
3. 在进程内做确定性的规范化 keyword matching。
4. 固定排序 tuple：tag exact match、完整 query/substring match、term overlap、updated_at、memory_id。
5. 受 max_memory_items、max_memory_tokens 和总 Context budget 裁剪。

中文 query 使用规范化 substring/短语匹配，英文同时使用空白/标点 term overlap。V1 不使用 FTS5、embedding 或 reranker。

### 17.2 duplicate

相同规范化 content hash 的 active Memory 是幂等命中：

- memory.save 不创建新文件或 index row。
- 返回 existing memory_id/version 的成功结果。
- evidence 标明 idempotent_existing。

### 17.3 conflict

如果新内容与现有 active Memory 表达冲突但 hash 不同：

- save preview 必须展示检测到的候选冲突。
- memory.save 不能留下两个已知冲突的 active truth。
- 用户应改走 memory.update，指定目标 ID 和 expected_version。
- 简单 V1 冲突检测只依赖明确 target、相同 tags/关键词候选和用户确认，不实现模型后台全库事实推理。

### 17.4 update

- optimistic expected_version 防止 stale update。
- 新内容写入新的不可变文件/version。
- SQLite 单 transaction 把旧 version 标记 superseded，并插入新 active version。
- provenance、确认和 evidence refs 都保留。
- retrieval 只返回新 active version。

### 17.5 archive

- archive 需要 WRITE confirmation 和 expected_version。
- 只把 active version 标记 archived，不删除文件。
- normal retrieval 排除 archived。
- memory.list 的 management mode 可显式查看 archived/history。

V1 没有 expires_at；Memory 一直 active，直到用户明确 update 或 archive。

## 18. 与 Skill、Policy、Planner、Executor、Tool Gateway 的边界

- Skill：memory Skill 只提供语义说明和候选 Tools；不读写 Memory，不授权。
- Policy：维持现有授权事实源。Context/Memory 不能扩大 allowed effects 或 AllowedToolSet。
- Planner：可读取 bounded assembly 来理解目标，但输出仍只有 Step objective/outcome/dependencies；不能保存 Memory 或把 Memory 变成 Tool 权限。
- PlanningSnapshotProvider：继续处理可信 Domain planning snapshot；与 conversation Context 分开。
- Executor：只消费 frozen projection；一次 invocation 不触发重新 assembly。PlanStep 只额外获得自己的 objective/dependency results。
- ToolGateway：所有 Memory Tool 的唯一执行入口；WRITE 使用现有 exact confirmation/evidence chain。
- Guardrails：验证 Tool schema、path 不可控、确认 digest、expected version 和返回结构；不能扩大 Policy。
- Domain：Research/Travel facts、read model 和 candidate provider 不被 Memory 替代。

## 19. failure modes 和安全规则

Stage 9A：

- current user turn append 失败：fail fast，不调用任何 LLM 或 Tool。
- history read 失败：降级为 current input only。
- summary provider 失败或返回非法/超预算内容：保留 previous valid summary + recent turns；没有 previous summary 时 recent turns only。
- 不保存 partial/invalid summary。
- assistant turn append 失败：不能回滚已经完成的 Tool；返回真实执行结果，同时记录 conversation_persist_failed。
- current input 超上限：在 provider 调用前拒绝。
- JSONL 尾部单条损坏：按明确 repository policy fail/skip 并报告稳定 code；不得把异常正文放入 prompt。
- session/path traversal：在文件 IO 前拒绝。

Stage 9B：

- Profile missing/invalid：skip Profile。
- Memory index unavailable：empty Memory，Context 继续。
- 单个 Memory 文件 missing/corrupt/hash mismatch：跳过该条，其他条继续。
- memory.save file failure：SQLite 零写。
- index transaction failure after file replace：不返回成功；orphan 不可检索。
- duplicate：幂等返回已有记录。
- stale expected_version：零写并返回 conflict。
- confirmation deny/expired/mismatch：零写。
- archived/superseded record：普通 retrieval 不返回。
- 任意 user/model path：拒绝。

所有 degrade 都不能扩大授权、伪造事实或把旧 Memory 覆盖 current input。

## 20. observability 与日志隐私边界

实际 bounded Context 会进入真实模型 prompt，所以 llm.jsonl 继续记录实际 provider request，其中可能包含 conversation、Profile 和 Memory 内容。它沿用本地敏感诊断日志的现有语义，不另建影子 prompt。

events.jsonl 只允许：

- assembly_id
- selected/trimmed turn counts
- summary version/covered range
- estimated token counts
- Profile/Memory included counts
- degrade component
- stable error code

events 不允许 conversation、summary、Profile、Memory 全文。

application.log 只记录安全诊断、component 和 error code，不记录全文、provider payload 或 exception text。

Memory Tool events 只记录 tool/call identity、memory_id/version/status、idempotent flag 和 evidence count；confirmation preview 的敏感全文只存在用户交互和实际 llm request 边界，不复制到普通 event。

ContextReport 本身不包含 content。完整 contribution content 只存在 request-local assembly、conversation/memory 文件和实际 llm.jsonl。

## 21. offline 单元测试和 integration tests

### Stage 9A unit

- ConversationTurn/Summary schema、sequence、role/kind 和 path validation。
- JSONL append/load、UTF-8、restart、corrupt tail 和 concurrent append policy。
- deterministic token estimate。
- current input 必留和 over-limit fail-fast。
- recent window、summary covered range、turn_id 去重、稳定顺序。
- incremental summary input 和 previous summary reuse。
- invalid/oversized/failed summary 不落盘。
- ContextReport 无 content。
- empty/fake Profile/Memory provider 预算契约。

### Stage 9A integration

- RuntimeService 在 LLM/Tool 前 append user turn。
- Direct/Router/Planner 接收相同 assembly_id。
- confirmed multi-step Plan 的每个 Executor provider 投影相同 assembly。
- assistant visible output append；内部 model/Tool/Step response 不 append。
- history/provider/write failure 的降级与 fail-fast。
- events 无内容，llm log 含实际 bounded prompt。
- Research/Travel Domain providers 调用次数为零。

### Stage 9B unit

- Profile read-only、missing、invalid、budget trim。
- V4 memory_index migration、constraints 和 indexes。
- generated path、immutable version、SHA-256 verification、path traversal。
- file-first/index-second failure matrix 和 orphan audit。
- keyword/tag/substring stable retrieval。
- duplicate idempotency。
- update expected_version、superseded lifecycle。
- conflict preview。
- archive 和 history management。
- missing/corrupt/hash mismatch 单条跳过。
- Profile/Memory 总预算不挤掉 current/recent context。

### Stage 9B integration

- memory Skill candidate + Policy/AllowedToolSet filtering。
- save/update/archive confirmation 前零写，deny/mismatch/expired 零写。
- Gateway-only handler invocation。
- ToolResult/Evidence 与 index/file 一致。
- restart 后 index → file → hash → Context assembly。
- current input/Domain fact 与旧 Memory 冲突时不静默覆盖。

所有 offline tests 使用 temporary directories、temporary SQLite 或 :memory:，不读写真实用户 data、真实日志目录或网络。

## 22. compiled E2E 场景

Stage 9A compiled E2E：

1. 两轮 Direct conversation，第二轮引用第一轮内容。
2. 长 session 触发 summary，保留 recent turns 和 current input。
3. RuntimeService restart 后从同一 session JSONL 恢复。
4. Planning preview 使用 conversation context，但不把它写入 PlanRun facts。
5. confirmed multi-step Plan 复用 assembly_id，Summarizer 只调用一次。
6. history read failure 降级 current-only。
7. current user turn append failure 在所有 LLM/Tool 前停止。
8. assistant append failure不伪造 Tool rollback。

Stage 9B compiled E2E：

1. Profile 进入 Context，但无 Profile Tool 和写入。
2. explicit save preview → confirm → immutable file/index/evidence。
3. duplicate save 幂等。
4. restart 后 retrieval。
5. conflict → confirmed update → superseded/active lifecycle。
6. confirmed archive → normal retrieval 排除、management list 可见。
7. corrupt one file 只跳过单条。
8. non-explicit conversation/summary/tool observation 均不能触发 save。

## 23. Stage 9A 真实 LLM smoke

真实 LLM gate 使用 5 个独立、小而可诊断的 happy paths：

1. Recent-turn Direct：第一轮提供一个偏好，第二轮指代它；模型只使用 recent original turns。
2. Compacted Direct：构造超预算 session，真实 Summarizer 生成一次合法 summary，Direct 回答同时使用 summary 和 recent turns。
3. Restart continuity：关闭并重建 RuntimeService 后，用同一 session_id 从 conversation JSONL 恢复并正确回答。
4. Planner preview：复杂目标依赖 earlier conversation，PlanningRouter/Planner 使用同一 bounded assembly 生成合理 preview。
5. Shared PlanStep assembly：确认多 Step plan，所有 Step 看到相同 assembly_id，不重复 summary、不按 Step 改写 Context。

每个 case 使用临时 data/log/SQLite 目录，不使用真实 Domain provider 或用户数据。报告必须区分 provider unavailable、provider contract failure、local assembly failure 和 product behavior failure。

## 24. Stage 9B 真实 LLM smoke

真实 LLM gate 同样使用 5 个独立 happy paths：

1. Profile read：模型正确使用用户编辑的 Profile；没有 Profile mutation 或 Memory write。
2. Explicit save preview：确认前文件/index 零写；确认后存在 immutable file、committed index 和 evidence。
3. Restart retrieval：重启后通过 index → file → hash 取回 Memory，模型在不覆盖 current input 的前提下使用它。
4. Conflict update：模型展示冲突并走 update confirmation；产生新 version 文件，旧 version superseded，只有新 active version进入 Context。
5. Archive lifecycle：确认 archive 后重启，普通 retrieval 不再返回，management list 仍能查看 archived/history。

每个 case 单独记录 ToolCall 数、confirmation 次数、文件/index 变化、evidence、assembly memory count 和最终行为。provider/external failure 与本地安全/契约 failure 分开报告。

## 25. 文档更新

设计确认后、本次只同步计划状态：

- README.md：Stage 9 计划已确认，下一入口 Stage 9A，尚未实现。
- docs/PROGRESS_LOG.md：记录设计确认事实，不记录未实施能力。
- docs/ARCHITECTURE.md：只增加 planned boundary 注记，不把候选架构写成当前实现。
- docs/RUNTIME_CONCEPTS.md：增加“Stage 9 已确认、未实现”的生命周期和边界解释。
- docs/AGENT_LEARNING_LINKS.md：增加 conversation/long-term memory、JSONL、atomic file replace 和 SQLite transaction 官方资料。
- plans/RUNTIME_REFACTOR_PLAN.md：统一为一个计划文件，明确 Stage 9A/9B gate 和 Domain provider 不接入决定。
- plans/modules/README.md：用 CONTEXT_MEMORY_PLAN.md 替换两个旧候选文件名。

Stage 9A go 时再把已实施事实同步到 architecture/progress；Stage 9B go 时再关闭整个 Stage 9。

## 26. Stage 9A 实施步骤、完成标准和 go/no-go gate

每一步只完成一个清晰改动。

1. 冻结 Stage 9A contracts 和 error codes。新增 immutable models/Protocols，不接 runtime。运行 context model/contract tests。
2. 实现 deterministic token estimator 和 ContextBudget validation。运行 budget unit tests。
3. 实现 ConversationTurn/Summary JSONL repository。运行 repository append/load/UTF-8/path tests。
4. 完成 restart、corrupt tail 和 sequence policy。运行 repository recovery tests。
5. 实现 ContextSummarizer Port、production LLM adapter 与 fake。运行 summarizer adapter contract tests，不接 RuntimeService。
6. 实现 incremental rolling summary service。运行 summary range/reuse/failure tests。
7. 实现 ContextAssembler 和 content-free ContextReport，接 empty/fake Profile/Memory providers。运行 assembly ordering/dedupe/budget tests。
8. 在 RuntimeService 建立一次请求一个 assembly 的 runtime-context seam，并实现 user turn pre-append fail-fast。运行 runtime context lifecycle tests。
9. 给 PlanningRouter/Planner typed input 增加兼容的 bounded context projection。运行 planning adapter/focused regression。
10. 用 adapter 接入 ExecutorContextProvider/ExecutorMemoryProvider，并让 PlanStep 复用 assembly_id。运行 executor provider/plan-step focused tests。
11. 实现 assistant visible turn append，排除内部 responses。运行 conversation visibility integration tests。
12. 增加 Context semantic events 和 llm/application privacy assertions。运行 observability focused tests。
13. 完成 Stage 9A offline unit/integration suites。运行 context、runtime、planner、executor 分层回归。
14. 完成 Stage 9A compiled E2E。运行本节 22 的 Stage 9A cases。
15. 运行 5 个真实 LLM smokes，分别记录结果和失败分类。
16. 运行统一离线 regression、compileall、git diff --check，审计无 Domain provider 调用、无 SQLite conversation 数据、无控制骨架重写。
17. 同步已实施文档并作 Stage 9A go/no-go 决策；只有 go 才冻结本节 28 的接口。

Stage 9A 完成标准：

- session conversation 可跨请求和进程重启。
- Direct、Planning 和 PlanStep 使用一次 frozen assembly。
- summary/recent/current 顺序、预算和 provenance 可确定测试。
- conversation/summary 不写 SQLite。
- Context payload 不进入 GraphState/events/application.log。
- fake/empty Profile/Memory contract 已冻结。
- Domain candidate providers 未接入。
- focused、compiled E2E、统一离线 regression 和 5 个真实 LLM happy paths 均有可解释证据。

Stage 9A no-go 条件：

- 任一模型调用重新独立 assembly 或 PlanStep 重复 summarization。
- current turn 落盘失败后仍调用 LLM/Tool。
- conversation text 进入 SQLite、events 或普通 application.log。
- summary 自动成为 Memory/事实/授权。
- 需要重写 Planner/Executor control loop 才能接入。
- 真实 LLM happy path 仍有未分类的本地 contract/product failure。

## 27. Stage 9B 实施步骤、完成标准和 go/no-go gate

1. 审计 Stage 9A frozen interfaces 和 regression baseline；不修改 assembly core contract。运行 Stage 9A focused suite。
2. 实现 read-only ProfileProvider 和固定路径校验。运行 profile unit tests。
3. 定义 MemoryDocument、MemoryIndexRecord、status/version/error contracts。运行 model tests。
4. 增加 SQLite V4 memory_index migration 和 repository adapter。运行 migration/repository tests。
5. 实现 immutable MemoryDocumentStore、hash verification 和 safe path generation。运行 file-store tests。
6. 实现 file-first/index-second save transaction 与 orphan audit。运行 failure-matrix tests。
7. 实现 deterministic active Memory retrieval。运行 tag/substring/term/budget tests。
8. 实现 duplicate idempotency 和 conflict candidate detection。运行 duplicate/conflict tests。
9. 实现 optimistic update/version/supersede。运行 update/stale-version tests。
10. 实现 archive/history management。运行 archive/restart tests。
11. 定义 memory Skill 和 5 个 Tool schemas/handlers，所有 handler 只调用 MemoryService。运行 registry/schema/architecture tests。
12. 接入 Policy/AllowedToolSet、confirmation、Gateway、Guardrails 和 evidence。运行 zero-write-before-confirm/deny/mismatch/expiry tests。
13. 用 Stage 9A frozen Profile/Memory provider slot 接入 assembly。运行 context budget/precedence/restart integration tests。
14. 增加 Memory events 和隐私 assertions。运行 observability focused tests。
15. 完成 Stage 9B compiled E2E。运行本节 22 的 Stage 9B cases。
16. 运行 5 个真实 LLM smokes，分别记录文件/index/evidence/assembly 行为。
17. 运行 Stage 9A+9B focused regression、统一离线 regression、compileall、git diff --check，审计无自动写入、无 path exposure、无旧接口改写。
18. 同步已实施文档并作 Stage 9B go/no-go 与 Stage 9 最终结论。

实施结果（2026-07-16）：步骤 1-18 全部完成。Stage 9A focused `63` 项、Stage 9B focused `81` 项、受影响 Executor `33` 项均零失败；统一离线回归 `561` 项零失败，`14` 项显式 live/platform gates 跳过；5 条真实 LLM Memory paths、`compileall`、`git diff --check` 和 architecture/privacy/authorization 审计通过。真实 provider 在 update 成功后可能追加一次 stale update，optimistic version 与 non-retryable guard 会拒绝额外版本并收敛 Tool catalog。未命中本节 no-go 条件，Stage 9B 结论为 `go`；因 Stage 9A 已为 `go`，整个 Stage 9 最终结论为完成。

Stage 9B 完成标准：

- Profile 只读且不进入 Memory index。
- Explicit Memory 只有 preview-confirmed Tool WRITE 才能产生。
- 全文只在 immutable files；SQLite 只有 index/lifecycle metadata。
- duplicate、update、conflict、archive、restart、corrupt file 行为可确定测试。
- retrieval 只返回 verified active versions，并遵守 Stage 9A budget。
- conversation/summary/Domain/model inference 都不能自动保存。
- focused、compiled E2E、统一离线 regression 和 5 个真实 LLM happy paths 均有证据。

Stage 9B no-go 条件：

- 确认前有任意文件/index 写入。
- Memory 写入绕过 Gateway、Policy/AllowedToolSet 或 evidence。
- Profile 可被 Agent Tool 修改。
- SQLite 保存 Memory 全文。
- 缺失/损坏文件导致错误 Memory 被模型使用。
- Stage 9B 为接入而推翻 Stage 9A assembly、预算、GraphState 或 Planner/Executor 边界。

## 28. Stage 9A 冻结后交给 Stage 9B 的接口清单

Stage 9A go 后冻结：

- ContextQuery 字段和 query origin 规则。
- ContextBudget 字段、估算器语义和裁剪优先级。
- ContextContribution kind/source/content/token/provenance 形状。
- ContextAssembly 和 assembly_id 复用语义。
- ContextReport 的 content-free 字段和 event projection。
- ProfileProvider.load_profile 的输入/输出。
- MemoryProvider/MemoryRetriever 的 query、limit、budget 和 contribution 输出。
- ConversationRepository 与 ContextSummarizer Port。
- RuntimeService 一次 assembly 的 ownership。
- PlanningRouter/Planner bounded context input seam。
- ExecutorContextProvider/ExecutorMemoryProvider adapter 语义。
- summary/recent/current/Profile/Memory 固定顺序。
- provider degrade error codes。
- llm/events/application log privacy contract。

Stage 9B 可以实现 Profile/Memory provider 和 durable store，但不能：

- 改变 current input 必留。
- 让 Memory 挤掉 recent conversation。
- 让 PlanStep 重新 query。
- 把 ContextReport 放进 GraphState。
- 把 Domain candidate provider接入 Stage 9A conversation core。
- 改写 Planner/Executor control skeleton。

若 Stage 9B 发现冻结接口确实无法安全实现，必须停止并重新开设计 gate；不能在施工中静默修改。

## 29. 整个 Stage 9 的最终完成标准

Stage 9 只有在 Stage 9A go 和 Stage 9B go 都成立时完成：

- session conversation context、rolling summary 和 restart continuity 已实现。
- Context 在 Direct、Planning 和 PlanStep 间共享一次 bounded assembly。
- Profile 和 Explicit Memory 两种 durable source 已实现。
- Memory hybrid storage、版本、冲突、archive 和 hash verification 已实现。
- Memory WRITE 只有显式请求、preview、confirmation、Gateway 和 evidence 路径。
- Context、Memory、Domain facts、Planner output、MCP result、summary、模型文本和 Tool authorization 的边界都有测试。
- Stage 9A 与 Stage 9B 各 5 个真实 LLM happy paths 有独立证据。
- 全部聚焦测试、compiled E2E、统一离线 regression、compileall 和 diff check 通过。
- README、PROGRESS_LOG、ARCHITECTURE、RUNTIME_CONCEPTS、AGENT_LEARNING_LINKS、总路线图和模块索引与真实实现状态一致。

在 Stage 9B go 之前，仓库只能表述 Stage 9 plan confirmed、Stage 9A implemented/go 或 Stage 9B in progress；不能提前宣称整个 Context/Memory 已完成。
