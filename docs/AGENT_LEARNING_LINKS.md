# Agent 学习链接索引

本文档只沉淀 LifeOps Agent 当前施工阶段已经需要学习、对照和讲解的权威资料。它不是通用书签列表，也不提前收录后续阶段资料。

阶段 3 的模块计划已经把当前学习范围限定为：

- Runtime Core：request / result / run lifecycle、stub execution、trace evidence、本地 SQLite persistence。
- Intent：误触发防护、结构化 intent 输出的未来接口形状、规则 classifier 与 LLM classifier 边界。
- Policy：授权事实源、write safety、permission decision、禁止从 planner / assistant 文本 / checkpoint 反向授权。

## 选择标准

- 优先官方文档、正式 specification 和成熟开源项目的核心文档。
- 每个链接都必须能解释阶段 3 已实现或正在实现的 runtime 边界。
- 不提前收录 Tool System、MCP、LangGraph Orchestration、Eval Harness、DAG Scheduler、长期 Memory 或多轮 human-in-the-loop 资料。
- 如果一个主题只是后续扩展点，而不是阶段 3 的当前学习重点，先放在“暂不收录”。

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
  学习重点：trace 和 span 如何解释 agent workflow。对照本项目的 `trace_events`：记录 run 经过了哪些 runtime 决策，但 trace 本身不新增授权事实。

- [OpenTelemetry - Traces](https://opentelemetry.io/docs/concepts/signals/traces/)  
  学习重点：trace、span、event 和上下文传播的通用观测模型。对照本项目后续如何把 `runtime.run.started`、`intent.classification.completed`、`policy.evaluation.completed` 等事件讲清楚。

### SQLite / Local Persistence

- [Python sqlite3 documentation](https://docs.python.org/3/library/sqlite3.html)  
  学习重点：Python 标准库 SQLite API、transaction、row factory、connection lifecycle。对照阶段 3 的 `run_records` 和 `trace_events`：它们是 runtime evidence，不是业务事实表，也不是 session store。

## 暂不收录

以下主题已经在总路线图或后续模块中规划，但不属于阶段 3 当前学习链接范围。等对应模块施工时，再按模块 plan 补充权威链接：

- LangGraph Orchestration、graph state、checkpoint 和 interrupts。
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
