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

## 选择标准

- 优先官方文档、正式 specification 和成熟开源项目的核心文档。
- 每个链接都必须能解释当前阶段已实现、正在实现或明确准备学习的 runtime 边界。
- 不提前收录 Tool System、MCP、Eval Harness、DAG Scheduler、长期 Memory 或多轮 human-in-the-loop 的实现资料。
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
   学习重点：理解 checkpointer 和 store 的区别。checkpointer 是 thread-scoped graph state snapshot；store 是 application-defined long-term data。

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

## 暂不收录

以下主题已经在总路线图或后续模块中规划，但不属于当前阶段学习链接范围。等对应模块施工时，再按模块 plan 补充权威链接：

- Tool System / Executor tool calling。
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
