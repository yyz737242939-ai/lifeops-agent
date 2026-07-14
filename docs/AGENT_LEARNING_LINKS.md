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
- Travel typed Port + fixture adapter；真实 Calendar MCP 仍留在阶段 10。

## 选择标准

- 优先官方文档、正式 specification 和成熟开源项目的核心文档。
- 每个链接都必须能解释当前阶段已实现、正在实现或明确准备学习的 runtime 边界。
- 不提前收录 MCP、Eval Harness、DAG Scheduler、长期 Memory 或完整多轮 human-in-the-loop 的实现资料。
- 如果一个主题只是后续扩展点，而不是当前阶段的学习重点，先放在“暂不收录”。

## 阶段 3：Runtime Core / Intent / Policy

### Runtime Core / Run Lifecycle

- [OpenAI Agents SDK - Intro](https://openai.github.io/openai-agents-python/)  
  学习重点：用少量 primitive 描述 agent runtime、agent loop、guardrails 和 tracing。对照本项目为什么先自建轻量 `RuntimeService`，把外部框架作为后续映射对象，而不是让框架吞掉 runtime 边界。

- [OpenAI Agents SDK - Running agents](https://openai.github.io/openai-agents-python/running_agents/)  
  学习重点：一次 run 的 lifecycle、输入输出、run config、state / conversation management 和错误恢复边界。对照本项目的 `RuntimeRequest -> IntentService -> PolicyService -> RuntimeResult`。

- [OpenAI Agents SDK - Results](https://openai.github.io/openai-agents-python/results/)  
  学习重点：run result、final output、intermediate items 与执行状态的边界。对照本项目为什么 `RuntimeResult` 只是本轮展示结果，不是业务事实来源，也不是写入授权来源。

### SQLite schema / migration baseline

- [SQLite - CREATE TABLE](https://www.sqlite.org/lang_createtable.html)
  学习重点：表级 / 列级约束、主键、唯一约束、CHECK 与外键声明。对照 LifeOps canonical V1 如何一次建立当前最终表结构。

- [SQLite - Foreign Key Support](https://www.sqlite.org/foreignkeys.html)
  学习重点：外键启用方式与 `ON DELETE` 行为。对照 `connect_sqlite()` 的 `PRAGMA foreign_keys = ON` 以及 Domain 表的 CASCADE / RESTRICT 边界。

- [SQLite - CREATE INDEX](https://www.sqlite.org/lang_createindex.html)
  学习重点：普通、唯一和 partial index。对照 itinerary idempotency key 的非空唯一索引。

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

- [Python typing.Protocol](https://docs.python.org/3/library/typing.html#typing.Protocol)
  学习重点：用 structural subtyping 定义小而稳定的 external Port。Travel 的 Calendar、Weather、Transport、Lodging、Place adapters 应能用 fixture 和未来真实实现共享 contract，而不让 Domain 依赖具体 provider。

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

## 暂不收录

以下主题已经在总路线图或后续模块中规划，但不属于当前阶段学习链接范围。等对应模块施工时，再按模块 plan 补充权威链接：

- MCP / Calendar external integration。
- Eval Harness。
- DAG Scheduler。
- Inspector / Debugger 的正式 UI 或 CLI。
- 多轮 human-in-the-loop / pending confirmation state。
- 长期 Memory、RAG、conversation summary。
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
