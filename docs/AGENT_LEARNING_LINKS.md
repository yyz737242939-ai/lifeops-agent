# Agent 学习链接索引

本文档只沉淀 LifeOps Agent 当前施工阶段已经需要学习、对照和讲解的权威资料。它不是通用书签列表，也不提前收录后续阶段资料。

阶段 3 的模块计划已经把学习范围限定为：

- Runtime Core：request / result / run lifecycle、stub execution、event log evidence、本地 SQLite persistence。
- Intent：误触发防护、结构化 intent 输出的未来接口形状、规则 classifier 与 LLM classifier 边界。
- Policy：授权事实源、write safety、permission decision、禁止从 planner / assistant 文本 / checkpoint 反向授权。

阶段 4 的模块计划已经把学习范围扩展到：

- LangGraph Orchestration：`StateGraph`、nodes、edges、conditional routes、graph state、graph path trace。
- LangGraph persistence / checkpoint / interrupt：只学习边界，不在阶段 4 实现，不作为 LifeOps 事实源或授权来源。
- LangChain models / tools / structured output：只做后续 Planner / Executor / Tool System 的预备阅读，本阶段不引入 chain、agent 或 tool abstraction。

阶段 5 的模块计划把学习范围扩展到：

- 原生 Skill discovery / routing / progressive reference 与 framework adapter 的边界。
- LifeOps 原生 Tool Gateway、Policy authorization resolution、pre/post Guardrails 和 execution evidence。
- LangChain tool schema / ToolNode / middleware 作为可选 adapter，不替代 Policy、Guardrail 或业务事实来源。
- Hugging Face 白名单外部来源、provenance、临时 observation 与用户确认保存边界。
- Travel typed Port + fixture adapter；Calendar MCP 不属于当前 V1，未来仍只能作为 Calendar Port 的可选 Adapter。

阶段 8 的模块计划把学习范围扩展到：

- MCP stdio client/server 的短生命周期 session、initialize 和可靠关闭。
- MCP `tools/list`、Tool schema 校验、`tools/call` 与 structured result。
- MCP Adapter 把 provider result 转换成 LifeOps-owned `ExternalObservation`，同时保留 Policy / Guardrail / Gateway 边界。
- Hugging Face public paper search 的 no-results、timeout、rate limit、invalid result 和 provenance。

## 选择标准

- 优先官方文档、正式 specification 和成熟开源项目的核心文档。
- 每个链接都必须能解释当前阶段已实现、正在实现或明确准备学习的 runtime 边界。
- 不提前收录尚未进入确认规划的 DAG Scheduler、复杂 RAG/向量服务或完整多轮 human-in-the-loop 实现资料；Trace、Inspector与Eval只收录当前共享标准和Stage 11A/11B计划直接需要的主体概念。MCP只保留Stage 8已确认的stdio Tool调用切片，Memory只保留Stage 9已确认的轻量边界。
- 如果一个主题只是后续扩展点，而不是当前阶段的学习重点，先放在“暂不收录”。

## 阶段 3：Runtime Core / Intent / Policy

### Runtime Core / Run Lifecycle

- [OpenAI Agents SDK - Intro](https://openai.github.io/openai-agents-python/)  
  学习重点：用少量 primitive 描述 agent runtime、agent loop、guardrails 和 tracing。对照本项目为什么先自建轻量 `RuntimeService`，把外部框架作为后续映射对象，而不是让框架吞掉 runtime 边界。

- [OpenAI Agents SDK - Running agents](https://openai.github.io/openai-agents-python/running_agents/)  
  学习重点：一次 run 的 lifecycle、输入输出、run config、state / conversation management 和错误恢复边界。对照本项目的 `RuntimeRequest -> IntentService -> PolicyService -> RuntimeResult`。

- [OpenAI Agents SDK - Results](https://openai.github.io/openai-agents-python/results/)  
  学习重点：run result、final output、intermediate items 与执行状态的边界。对照本项目为什么 `RuntimeResult` 只是本轮展示结果，不是业务事实来源，也不是写入授权来源。


### Structured Output / Intent

- [OpenAI API - Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)  
  学习重点：用 JSON Schema 约束模型输出。阶段 3 的 `LlmIntentClassifier` 仍是空实现，但接口应为未来 structured intent output 留出位置；模型输出只能提供 intent signal，不能直接授权写入。

- [OpenAI API - Function calling](https://developers.openai.com/api/docs/guides/function-calling)
  学习重点：Responses function tool schema、`function_call` 输出与 `call_id`；LifeOps 只发送授权后的 Tool catalog，并在执行前继续经过本地 Guardrail。

### Guardrails / Policy / Permission

- [OpenAI Agents SDK - Guardrails](https://openai.github.io/openai-agents-python/guardrails/)  
  学习重点：input guardrails、output guardrails、tripwires 和 fail-fast safety checks。对照本项目的 `PolicyService`：先判断系统此刻被允许做什么，再进入后续 execution。

- [OpenAI API - Safety best practices](https://developers.openai.com/api/docs/guides/safety-best-practices)  
  学习重点：生产系统中的输入处理、安全检查、输出控制和分层防护。对照阶段 3 的 write safety：不明确的写入默认 `requires_confirmation`，不能由 planner、assistant 文本或 checkpoint 反向授权。

### Trace / Evidence

- [OpenAI Agents SDK - Tracing](https://openai.github.io/openai-agents-python/tracing/)  
  学习重点：trace 和 span 如何解释 agent workflow。对照本项目的 `events.jsonl`：记录 run 经过了哪些 runtime 决策，但 event log 本身不新增授权事实。

## 阶段 4：LangGraph Orchestration

### 必读：LangGraph orchestration / StateGraph / nodes / edges / graph state

阅读顺序：

1. [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)  
   学习重点：理解 LangGraph 的定位。它是低层 orchestration framework / runtime，关注 durable execution、streaming、human-in-the-loop、persistence 等编排能力；同时注意官方说明：可以不使用 LangChain 也使用 LangGraph。

2. [LangGraph runtime](https://docs.langchain.com/oss/python/langgraph/pregel)  
   学习重点：理解 compiled graph 背后的 runtime 模型。重点看 actor / channel / step / execution / update，以及 `StateGraph` 编译后如何成为可 invoke 的 graph runtime。

3. [StateGraph API reference](https://reference.langchain.com/python/langgraph/graphs/#langgraph.graph.state.StateGraph)  
   学习重点：施工时查具体 API。重点看 `StateGraph`、`add_node`、`add_edge`、`add_conditional_edges`、`compile`、`invoke`。

4. [LangGraph Graph API overview](https://docs.langchain.com/oss/python/langgraph/graph-api)
   学习重点：理解 `state_schema` 与 `context_schema` 的区别，以及节点如何通过 `Runtime` 获得 request-local 依赖。对照本项目的 `GraphState` 与 `OrchestrationContext(trace=...)`。

本阶段只需要掌握：

- `StateGraph`
- node function
- edge
- conditional edge / route
- graph state
- compiled graph invocation
- runtime context / `context_schema`

项目对照：

- `Runtime stage` -> node。
- `执行顺序` -> edge。
- `PolicyAction` -> conditional route。
- `request-local state` -> graph state。
- `trace / eval path` -> graph path。

### 必读：LangGraph persistence / checkpoint / interrupt 边界

阅读顺序：

1. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)  
   学习重点：理解 checkpointer 和 store 的区别。checkpointer 是 thread-scoped graph state snapshot，可支持 continuity、interrupt、fault tolerance 和 time travel；store 是 application-defined long-term data。Checkpoint restore 只恢复 graph state，不会自动撤销已经提交到 Domain repository 或外部系统的副作用。

2. [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)  
   学习重点：理解 human-in-the-loop 能力和暂停 / 恢复流程。

本阶段只学习、不实现：

- 不配置 checkpointer。
- 不使用 LangGraph store 保存 LifeOps 业务事实。
- 不用 interrupt 代替 `PolicyAction.REQUIRES_CONFIRMATION`。
- 不从 checkpoint 恢复或推断 WRITE 授权。

项目边界：

- LifeOps 的长期事实来源仍是 SQLite repository 和成功执行证据。
- LifeOps 的授权来源仍是 `PolicyService`。
- LangGraph checkpoint 可以作为后续 Recovery 学习对照，但不是业务事实源。

### 选读：LangChain models / tools / structured output

阅读顺序：

1. [LangChain overview](https://docs.langchain.com/oss/python/langchain/overview)  
   学习重点：理解 LangChain 在模型、工具和 agent loop 抽象上的定位，并和 LangGraph runtime 区分开。

2. [LangChain models](https://docs.langchain.com/oss/python/langchain/models)  
   学习重点：后续 Planner / Executor 阶段可能需要的模型接口和调用边界。

3. [LangChain tools](https://docs.langchain.com/oss/python/langchain/tools)  
   学习重点：后续 Tool System 阶段可作为 adapter 对照，但不能绕过 LifeOps tool safety 和 policy。

4. [LangChain structured output](https://docs.langchain.com/oss/python/langchain/structured-output)  
   学习重点：后续 Planner 生成 `PlanRun`、Executor 返回结构化反馈时可参考的结构化输出能力。

本阶段不引入 LangChain chain、agent 或 tool abstraction。

### 对照解释：LangGraph 和 LangChain 在本项目中的分工

```text
LangGraph
-> orchestration runtime
-> nodes / edges / routes / graph state / graph path trace
-> 阶段 4 正式进入主流程

LangChain
-> model / prompt / tool / structured output integration layer
-> 后续 Planner / Executor / Tool System 阶段进入
-> 本阶段只学习和记录边界

LifeOps 自研 runtime
-> Policy / Context / Memory / Tool safety / Executor / State / Trace / Facts source
-> 不被 LangGraph 或 LangChain 替代
```

面试讲法：本项目不是为了“套上 LangGraph”而重写 runtime，而是先建立自研 runtime 的事实源、授权源和 trace 边界，再把 LangGraph 映射到控制流编排层。这样既能学习主流框架，也能说明自己理解 agent runtime 的底层职责拆分。

## 阶段 5：Skill / Tool / Research / Travel

### Agent Skills / Deep Agents

- [Agent Skills Specification](https://agentskills.io/specification)
  学习重点：`SKILL.md` 的目录结构、必填 `name` / `description`、命名约束和三级 progressive disclosure。LifeOps 阶段 5 采用严格原生子集，只解析启动时需要的 metadata；可选 frontmatter 字段和附属资源在后续步骤按本项目边界扩展。

- [Deep Agents Skills](https://docs.langchain.com/oss/python/deepagents/skills)
  学习重点：Deep Agents 如何读取 `SKILL.md` frontmatter、按描述匹配、延迟读取正文和附属资源，以及 skills 与 Memory 的区别。LifeOps 只参考其 progressive disclosure 和失败模式，不复用 `SkillsMiddleware` 或 Deep Agents harness；现有 Intent、Policy、Tool Gateway 和业务事实来源继续由 LifeOps 拥有。

- [LangChain Skills pattern](https://docs.langchain.com/oss/python/langchain/multi-agent/skills)
  学习重点：LangChain Core 中 Skill 更接近 prompt-driven specialization / progressive disclosure 架构模式；真正的 built-in Skill 支持位于 Deep Agents。对照本项目为什么让 Skill 只负责 instructions，并由 Policy 与 Tool System 独立完成授权。

- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
  学习重点：理解 provider 侧 schema 约束与应用侧结构校验的差别。LifeOps 当前通过 OpenAI-compatible Chat Completions 请求 JSON，并用 Pydantic 解析 `selected_skill_ids` 与 `reason`，再在本地校验未知 ID、重复 ID 和业务边界；OpenAI SDK 不接管 Registry、Skill loading 或 orchestration。

### LangChain Tools 与 LifeOps Tool Adapter

- [LangChain Tools](https://docs.langchain.com/oss/python/langchain/tools)
  学习重点：tool schema、结构化输入输出、`ToolRuntime` 和 `ToolNode`。阶段 5 已评估 `StructuredTool`，当前因为没有真实 LangChain 调用方且不会减少 schema/invocation glue而不实现 adapter；LifeOps `ToolGateway` 仍负责 Policy authorization、Guardrail 和 execution evidence。未来接入时尤其要避免让 framework callable 或 store 绕过 Gateway 保存业务事实或 Memory。

### Guardrails / Human Approval 对照

- [LangChain Guardrails](https://docs.langchain.com/oss/python/langchain/guardrails)
  学习重点：deterministic / model-based guardrails 以及 before/after/tool-call interception。对照 LifeOps 为什么把 pre-execution 授权检查和 post-execution success evidence 检查放进 framework-agnostic Tool Gateway。

- [LangChain Human-in-the-loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)
  学习重点：approve/edit/reject 与暂停执行的框架实现。阶段 5 只对照 confirmation 边界，不引入完整 interrupt/checkpointer resume；LifeOps Policy 仍是授权事实源。

### Hugging Face 外部来源

- [Hugging Face Hub API](https://huggingface.co/docs/hub/en/api)
  学习重点：Hub 官方 API/OpenAPI 入口和 provider contract。阶段 5 首版仍可基于声明的 Papers/Blog 页面 fixture 重写 V0 briefing，但 source identity、fetch metadata、失败和 provenance 必须使用稳定结构，未来 adapter 可以切换到官方 API。

### 阶段 5 明确不提前实现

- LangChain `create_agent` 替换现有 Runtime/LangGraph 主流程。
- Tool 通过 `ToolRuntime.store` 直接写 LifeOps Memory 或 Domain facts。
- Travel 真实预订、付款、Calendar 写入或具体商业 provider 集成。
- semantic retrieval、embedding、向量数据库和完整 RAG。
- 完整 LangGraph interrupt/checkpointer confirmation resume。

## 阶段 6：ReAct Executor

### ReAct 与有界 action / observation loop

- [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)
  学习重点：理解 ReAct 通过 reasoning/action 与 environment observation 交替推进任务的核心机制。LifeOps 采用可测试的 action → ToolResult/Observation → next action 控制循环，但不要求、保存或记录模型 private chain-of-thought；副作用事实仍来自 Gateway evidence。

- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
  学习重点：用 nodes、conditional edges 和 cycle 表达 bounded Executor loop，并明确 state reducer、termination 和 recursion limit 的职责。LifeOps 使用显式 `max_steps` 作为业务控制边界，不把 framework recursion exception 当作正常 stop reason。

- [LangGraph workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
  学习重点：对照官方 tool-calling agent loop 的 model node、tool node 和 conditional routing。LifeOps 保留自己的 `AllowedToolSet`、Tool Gateway、Guardrails、execution scope、stop reason 和 evidence，不用预构建 agent 替换 Runtime 主流程。

### Tool calling 与 confirmation continuation 边界

- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
  学习重点：理解模型产生 function call、应用执行函数、再把 function output 反馈给模型的多步协议。LifeOps provider adapter 只负责 decision 编解码；catalog authorization、参数复验、handler 调用和 evidence 仍由本地 Gateway 负责。

- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
  学习重点：理解暂停、恢复、checkpointer 和 side-effect 重放风险。本阶段只实现同 run synchronous confirmation provider，不提前实现跨进程/跨 run pending execution；未来若引入 interrupt，必须重新证明 execution scope、幂等和已提交副作用边界。

## 阶段 7：Plan-and-Execute Planner

### Plan-and-Execute 与 ReAct 分工

- [Plan-and-Solve Prompting](https://aclanthology.org/2023.acl-long.147/)
  学习重点：理解“先把复杂目标拆成较小子目标，再逐步执行”的基本动机。LifeOps 不保存模型 private reasoning；落地对象是可验证的 `PlanStep` 目标、预期结果和显式依赖。

- [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)
  学习重点：对照 Planner 与 ReAct 的不同时间尺度。Planner 负责跨 Step 的目标分解，`ReactExecutor` 仍负责一个 Step 内的 action → observation 循环和 Tool 选择。

### Planner 控制链与串行依赖编排

- [LangGraph workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
  学习重点：对照 prompt chaining、routing、orchestrator-worker 与 evaluator-optimizer workflow。Stage 7 采用显式 route、完整计划、确定性 next-step 和一次 bounded replan，但不引入 worker 并发或额外 outcome judge。

- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
  学习重点：使用 node、edge、conditional route 和 cycle 表达 `PlanningRouter → Planner → PlanController → ReactExecutor → PlanFinalizer`，同时保持持久化 Plan state 与 request-local graph state 分离。

### 当前明确延后的能力

- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
  学习重点：只用来解释 Stage 7 为什么不配置 checkpointer。Plan state 可被读取不代表 Executor state、Domain temporary artifact 或已经提交的副作用可以自动恢复。

- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
  学习重点：只理解异步暂停/恢复所需的 durable execution 边界。Stage 7 保持同步 action confirmation，不实现跨请求 Executor resume、并行 Step 或 DAG Scheduler。

## 阶段 8：Research External Interfaces / Hugging Face MCP

### MCP stdio client/server 生命周期

- [Model Context Protocol specification - Transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
  学习重点：stdio 与 Streamable HTTP 的进程/连接模型、消息边界和 stdout 约束。LifeOps Stage 8 只实现本地短生命周期 stdio；Server stdout 只承载 MCP 消息，普通日志不污染协议流。

- [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/)
  学习重点：官方 SDK 的 client/server 能力和标准 transport。当前实现使用官方 `mcp` 包，不迁移 V0 手写 JSON-RPC 或硬编码 protocol version。

- [MCP Python SDK - Building servers](https://py.sdk.modelcontextprotocol.io/server/)
  学习重点：用 `FastMCP` 定义 typed Tool 和 stdio Server，并理解 structured result、Server 生命周期和错误边界。LifeOps 本地 Server 只暴露 `search_papers`，不承载 Domain persistence 或授权。

### MCP Tool discovery / call / structured result

- [MCP Python SDK - Writing clients](https://py.sdk.modelcontextprotocol.io/client/)
  学习重点：`ClientSession.initialize()`、`list_tools()`、`call_tool()`、stdio client context 和 structuredContent 解析。LifeOps 每次 `research.search_papers` 都新建一次 session，校验已配置 Tool schema 后只调用一次并可靠关闭。

项目边界：

- `tools/list` 是能力校验，不会把 MCP Server 动态发现的 Tool 加入 `AllowedToolSet`。
- MCP `search_papers` 与模型可见 `research.search_papers` 是两个 contract；后者仍由 LifeOps Registry、Policy、Guardrail 和 Gateway 控制。
- MCP SDK / provider 类型只存在于 integration 层，Adapter 输出必须是 LifeOps-owned `ExternalObservation`。

### Hugging Face public paper provider

- [Hugging Face HfApi Client](https://huggingface.co/docs/huggingface_hub/main/en/package_reference/hf_api)
  学习重点：`list_papers(query, limit, token=False)`、`list_daily_papers(...)` 与 `paper_info(...)` 的 public-read contract。Stage 8 只用论文搜索/必要详情读取，结果经过 bounded validation 后成为 request-local observation；不下载全文或 PDF。

- [Hugging Face Papers CLI](https://huggingface.co/docs/huggingface_hub/main/en/guides/cli#hf-papers)
  学习重点：对照官方提供的 papers list/search/info/read 业务能力。LifeOps 只实现 search metadata 主线，不把 CLI、全文 markdown 或 Hub token 直接暴露给模型。

本阶段明确不学习或实现：远程 Streamable HTTP、SSE、OAuth、MCP authorization、Resources、Prompts、Sampling、Roots、全文/PDF ingestion 和常驻 session pool。

## 阶段 9：Context / Memory

### short-term conversation 与 long-term memory

- [LangChain Memory overview](https://docs.langchain.com/oss/python/concepts/memory)
  学习重点：区分 thread/session 内 short-term memory 与跨 session 的 long-term memory，并理解长对话会带来模型注意力和成本问题。LifeOps 不直接采用框架 store，而是用自己的 JSONL conversation repository、rolling summary 和明确 Memory Tool 保持边界可解释。

- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
  学习重点：理解 thread/checkpoint 与跨 thread store 是不同持久化问题。LifeOps Stage 9 明确不把 conversation 或长期 Memory 放进 outer GraphState/checkpoint，避免把可恢复 graph state 误当事实或授权。

- [JSON Lines](https://jsonlines.org/)
  学习重点：每行一个完整 UTF-8 JSON value，适合 append-only session conversation 与 restart recovery；LifeOps 对 schema、sequence、路径和损坏尾部另做显式校验。

- [Python `os.replace`](https://docs.python.org/3/library/os.html#os.replace)
  学习重点：Stage 9B 先在目标目录写临时文件，再用 replace 提交不可变 Memory version；只有 replace 成功后才允许提交 SQLite index。

- [SQLite Transactions](https://www.sqlite.org/lang_transaction.html)
  学习重点：Memory index 的 active version、supersede、archive 和 evidence metadata 必须在明确 transaction 中原子更新；SQLite 不保存 Memory 全文。

## Stage 9 后整体验收：Live User E2E

### 真实 Agent workflow 的 eval 设计

- [OpenAI Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
  学习重点：生成式模型具有变异性，因此验收应采用 task-specific、贴近真实用户分布且可自动评分的测试；Agent workflow 要分别观察 instruction following、Tool selection、arguments precision 和 functional correctness。LifeOps live E2E 以 route、ToolCall、confirmation、evidence、SQLite、文件和语义日志作为主要 grader，不用“回答看起来不错”替代产品事实。

- [OpenAI Prompt engineering](https://developers.openai.com/api/docs/guides/prompt-engineering)
  学习重点：固定模型版本并持续运行同一 eval suite，避免 model alias 或 prompt 漂移让 live 结果失去可比性。LifeOps 仍以当前 OpenAI-compatible adapter 为边界，不在本轮迁移 provider 或 hosted Evals 平台。

## 阶段 10：Execution Feedback / 解释型 Recovery

### Structured output 与 evidence-grounded claim validation

- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
  学习重点：用 schema 约束模型返回的 success claims、call/step identity 和 evidence references，再由 LifeOps 确定性 validator 对照当前执行事实。Structured output 只改善输出契约，不会把模型声明升级为 Tool 或 Domain 事实。

- [LangChain structured output](https://docs.langchain.com/oss/python/langchain/structured-output)
  学习重点：对照 provider-native 与 tool-calling structured output 的通用实现方式。Stage 10 保持 LifeOps-owned `FinalAnswerDraft` / validator，不引入新的 Agent abstraction，也不让 parsing failure 绕过 deterministic fallback。

### Agent eval 与事实型 grader

- [OpenAI Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
  学习重点：把“是否错误声称成功”“是否区分 completed/failed/not-run”“Recovery 是否零 Tool 调用”写成 task-specific、可自动判定的 grader；真实模型 smoke 与 deterministic compiled E2E 分层报告。

### Checkpoint / replay / side-effect 边界对照

- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
  学习重点：checkpoint、pending writes、replay 和 time travel 属于 durable execution 问题；replay 会重新触发 checkpoint 之后的 LLM/API/interrupt。Stage 10 只读取执行事实并解释，不配置 checkpointer、不 replay，也不撤销已提交副作用。

- [LangGraph Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)
  学习重点：理解恢复型 workflow 为什么要把 side effects 封装为可 checkpoint 的 task，并要求 idempotency。LifeOps Stage 10 暂不承担这个控制流复杂度，而是用 ToolResult/evidence 和 Plan lifecycle 完成可解释、不可执行的恢复闭环。

## Feedback / Recovery / Inspector / Eval 共享 Trace 标准

### OpenTelemetry tracing core

- [OpenTelemetry Traces](https://opentelemetry.io/docs/concepts/signals/traces/)
  学习重点：Trace、Span、parent span、Span Context、Attributes、Span Events、Span Links 与 Span Status。LifeOps 使用这些概念建立本地 Trace Contract，但不在当前阶段实现 OTLP、Collector 或分布式 tracing。

- [OpenTelemetry Signals](https://opentelemetry.io/docs/concepts/signals/)
  学习重点：区分 traces、metrics、logs 与 baggage。LifeOps 当前共享标准聚焦 trace 与现有文件 logs 的关联；生产 metrics/alerts 和跨服务 baggage 延后。

- [OpenTelemetry Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/)
  学习重点：理解 semantic conventions 如何冻结 operation names、attribute keys/types/meaning。LifeOps 为 Runtime/Policy/Planner/Executor/Feedback 定义自己的稳定命名，并对照而不直接依赖仍可能变化的 GenAI experimental keys。

### OpenInference GenAI semantic conventions

- [OpenInference Specification](https://arize-ai.github.io/openinference/spec/)
  学习重点：OpenInference 如何在 OpenTelemetry 上表达 LLM、Agent、Tool、Retriever、Guardrail、Evaluator 与 Prompt spans。LifeOps 复用 span-kind 思想，同时保持 ToolResult/evidence、Policy和隐私边界由自己拥有。

- [OpenInference Semantic Conventions](https://arize-ai.github.io/openinference/spec/semantic_conventions.html)
  学习重点：对照 LLM provider/model、token、Tool calling、input/output 与 evaluation attributes。LifeOps 默认不把 raw prompt、messages、Tool arguments/output 或 private reasoning写入普通 trace/index，只保存安全 metadata和 artifact reference。

## Stage 11A：Inspector / Runtime Debugger

### Trace navigation 与 details view

- [LangSmith View traces](https://docs.langchain.com/langsmith/view-traces)
  学习重点：对照 Messages、Turns 与 Details 三种观察层级，以及从thread/turn概要下钻到具体run、Tool、输入输出、timing、token、error和metadata的调试流程。LifeOps v0只实现本地summary/tree/timeline/details CLI，不复制完整云端产品。

- [Phoenix Tracing](https://arize.com/docs/phoenix/learn/tracing)
  学习重点：理解trace由root和parent/child spans组成，Agent、LLM、Tool、Retriever等不同span kinds如何帮助重建执行过程。LifeOps进一步用ExecutionFeedback和Plan/DAG links提供自己的事实与dependency语义。

- [OpenAI Agents SDK Tracing](https://openai.github.io/openai-agents-python/tracing/)
  学习重点：对照Agent run、LLM generation、function Tool、Guardrail、handoff和custom spans的默认instrumentation，以及敏感数据和custom processor边界。LifeOps不引入Agents SDK，只比较其trace coverage和processor/exporter职责。

## Stage 11B：Eval Harness

### Eval lifecycle、dataset 与 grader

- [OpenAI Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
  学习重点：从目标、dataset、metrics、run和持续评价形成闭环。LifeOps把代表性任务固化为versioned suite，以route、Policy、Tool、evidence、state、grounding和trace的确定性grader作为主gate。

- [OpenAI Evals guide](https://developers.openai.com/api/docs/guides/evals)
  学习重点：理解eval configuration、test data、run和result的基本生命周期。LifeOps实现本地轻量case/suite/runner/report，不迁移到hosted platform。

- [OpenAI Graders](https://developers.openai.com/api/docs/guides/graders)
  学习重点：grader如何把候选输出映射为可比较结果，以及string、score和model grader的适用边界。LifeOps优先使用typed `RuntimeReport`上的deterministic graders，LLM judge只作为未来显式annotation增强。

- [LangSmith Evaluation concepts](https://docs.langchain.com/langsmith/evaluation-concepts)
  学习重点：对照dataset、example、experiment、run和evaluator的职责分离。LifeOps使用`EvalSuite/EvalCase/EvalRun/GradeResult`表达相同主体概念，同时保持facts和trace由自己的shared standard拥有。


## 暂不收录

以下主题已经在总路线图或后续模块中规划，但不属于当前阶段学习链接范围。等对应模块施工时，再按模块 plan 补充权威链接：

- MCP remote Streamable HTTP / OAuth / authorization 与 Calendar integration。
- DAG Scheduler。
- 多轮 human-in-the-loop / pending confirmation state。
- 复杂 RAG、向量数据库、embedding/reranker 服务、后台自动 Memory 提取和多 Agent 共享 Memory。
- Pydantic 或其他 schema validation 框架替换。

## 后续维护规则

模块计划的“文档更新”步骤应检查：

- 是否新增了重要 Agent 概念。
- 是否需要在本文档新增官方链接；新增前先列出候选重点方向和取舍理由，并等待用户确认。
- 是否需要在 `docs/RUNTIME_CONCEPTS.md` 增补本项目自己的解释。
- 是否需要在 `docs/ARCHITECTURE.md` 增补边界或依赖方向。

如果某个模块只是小实现切片，没有新增核心概念，可以明确记录“不需要新增学习链接”。

确认流程：

1. 先提出本模块可能需要沉淀的 2-5 个重点方向。
2. 简要说明每个方向和当前实现的关系。
3. 用户确认范围后，再搜索和写入权威链接。
4. 如果用户删掉某个方向，不把它放进本文档的当前阶段条目。
