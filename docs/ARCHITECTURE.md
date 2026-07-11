# Runtime 架构

本文档记录当前架构快照和当前架构边界。它故意比模块实施计划更高层。

本文档不是递增历史。随着 runtime 推进，过时的架构描述应被替换为当前事实；项目演进过程记录在 `docs/PROGRESS_LOG.md`。

## 核心边界

当前 runtime 将职责拆分为显式层次：

```text
runtime
intent
policy
orchestration
context
memory
planning
execution
tools
domains
integrations
recovery
observability
inspector
evals
dag
storage
common
```

## 新代码根目录

当前代码放在：

```text
app/
```

Legacy 代码保留在：

```text
legacy_v0/app/
```

当前 runtime 不应隐式依赖 legacy 的 `legacy_v0/app/agents/agent.py`。

## 依赖方向

允许的高层依赖方向：

```text
main
-> runtime
-> orchestration
-> intent / policy
-> context / planning / execution / inspector
-> tools / domains / memory / recovery / integrations
-> storage / observability / common
```

默认禁止：

- domain 模块依赖 orchestration；
- policy 执行工具；
- planner 授权写入；
- inspector 修改 runtime 或业务状态；
- evals 使用真实用户数据；
- storage 依赖 domain service。

## Runtime Core

Runtime Core 是当前单轮 request lifecycle 的入口层，当前实现位于：

- `main.py`
- `app/runtime/models.py`
- `app/runtime/service.py`
- `app/runtime/bootstrap.py`
- `app/runtime/run_store.py`

`RuntimeRequest` 是当前 turn/run 的结构化输入，包含 `session_id`、`turn_id`、`run_id` 和 `user_input`。它不是长期 conversation memory。

`RuntimeResult` 是本轮可展示结果，包含 status、message、intent 摘要、policy 摘要和 trace summary。它不是业务事实来源。

当前 `RuntimeService.handle(...)` 的链路是：

```text
RuntimeRequest
-> RuntimeOrchestrator
-> StateGraph
-> classify_intent
-> decide_policy
-> policy conditional route
-> stub_execute / requires_confirmation / deny
-> finalize
-> RuntimeResult
```

传入 SQLite connection 时，Runtime Core 可以写入 `run_records`。传入 event log 或配置 `log_root` 时，Runtime Core 会把 runtime event 写入 `events.jsonl`。未传入 connection 时，它仍可通过文件 event log 记录运行路径，也可以保持 request-local 纯内存运行，便于聚焦测试。

当前 tool execution 仍是 stub。`runtime.orchestration.stubbed` 表示阶段 4 graph 已完成编排，但没有执行真实工具或业务写入。

## LangGraph Orchestration

LangGraph Orchestration 当前实现位于：

- `app/orchestration/state.py`
- `app/orchestration/routes.py`
- `app/orchestration/nodes/`
- `app/orchestration/graph.py`

`RuntimeService` 仍是唯一外部入口，负责 SQLite transaction、run record、request event writer 和最终 `RuntimeResult`。`RuntimeOrchestrator` 只负责把现有 Intent / Policy / stub result lifecycle 映射到 compiled `StateGraph`。

当前 graph 路径是：

```text
START
-> classify_intent
-> decide_policy
-> allow -----------------> stub_execute -----------\
-> requires_confirmation -> requires_confirmation --+-> finalize -> END
-> deny ------------------> deny -------------------/
```

Intent 或 Policy 失败时，graph 在对应节点后直接进入 `END`，不执行后续 Policy 或结果节点。

`GraphState` 只保存当前 request 的编排数据：request、intent、policy、route、result、error、graph path 和紧凑 trace summary。它不保存长期 Memory、Task 事实、工具执行事实或授权替代来源。

`OrchestrationContext` 是 request-local 运行依赖，目前只携带应用拥有的 `TraceSink`。它通过 LangGraph `context_schema` / `Runtime` 提供给节点，不进入 `GraphState` 或 checkpoint。Intent / Policy node 在真实 service 返回后分别写 `intent.classified` / `policy.decided`，失败时写对应 failed event；Policy 分支确定后写 `orchestration.route.selected`。机械化的 graph/node started/completed 不进入稳定事件契约。

LangGraph 不负责 Policy 决策、业务事实、工具安全、真实执行或持久化；这些边界仍由 LifeOps 自研 runtime 拥有。

## Intent / Policy

Intent Layer 当前实现位于：

- `app/intent/models.py`
- `app/intent/classifiers.py`
- `app/intent/service.py`

Intent 判断用户可能想做什么，例如 `chat`、`read`、`write_request`、`plan_request`、`clarification_needed`。`IntentService` 会调用规则 classifier 和 LLM classifier 接口。当前 `LlmIntentClassifier` 是空实现，只返回 `not_available`，不调用真实模型。

Policy / Permission Layer 当前实现位于：

- `app/policy/models.py`
- `app/policy/service.py`

Policy 判断系统现在被允许做什么。它只基于当前 `RuntimeRequest` 和 `IntentDecision` 产出 `PolicyDecision`，不能从 Planner、assistant 文本、LLM classifier、Recovery Context 或 LangGraph checkpoint 获得写入授权。

当前允许的写入 scope 只是候选授权模型：

```text
task.write_candidate
memory.write_candidate
wellbeing.write_candidate
```

这些 scope 不代表对应 domain 已经实现，也不代表真实工具已经执行。

## 基础设施层

`common`、`storage` 和 `observability` 是当前 runtime 的基础设施层：

- `common` 提供配置读取、ID、时间、错误和 JSON 序列化，不依赖业务模块。
- `storage` 提供 SQLite 连接、schema migration 和 transaction boundary，不依赖 domain service。
- `observability` 提供 event / LLM / normal 程序日志的写入和读取，不负责业务状态变更。

真实数据库默认路径由 `config/default.json` 的 `database.path` 声明。当前默认值是：

```text
data/lifeops.sqlite3
```

测试必须使用 `:memory:` 或临时文件数据库，不复用真实用户数据库。

真实日志默认根目录由 `config/default.json` 的 `logs.root` 声明。当前默认值是：

```text
logs/sessions
```

## 事实来源

Runtime 的事实来源是：

- 基于 SQLite 的业务 repository；
- 成功的 WRITE tool result；
- 用户明确授权的 TaskStep。

不是事实来源：

- assistant final answer 文本；
- Planner 输出；
- LangGraph checkpoint state；
- Recovery Context；
- conversation summary。
- 原始 LLM request-response log。

## Observability

当前 observability 分成三类日志：

- `events.jsonl`：结构化 runtime event，只保存少量必要字段和紧凑 payload，用于解释 runtime 路径和失败层级。
- `llm.jsonl`：原始 LLM / agent request-response 记录，用于人工排查最原始对话，不作为业务事实或写入授权来源。
- `application.log`：普通程序日志，用于测试和 debug。

三类日志默认写入 `logs/sessions/session_<timestamp>_<session_id>/`。SQLite 不再默认承载 runtime event log 或 LLM log。

`TraceSink` 是应用拥有的 request-local event 接口。Graph 内 node 通过 `OrchestrationContext` 使用同一个 sink；Graph 外未来的 Executor、Tool Safety、repository 或 integration 关键阶段也可以直接写同一个 sink，不需要为了可观察性变成 LangGraph node。Event 在真实逻辑边界实时追加，不根据最终 state 事后补写。

## Runtime 不变量

- 用户数据安全优先。业务写入必须来自用户当前输入中的明确授权。
- Intent 只提供语义信号，不授权写入。
- Policy 是当前写入授权事实源；Executor 未来只能执行 Policy 允许的操作。
- 不能只凭 assistant 文本判断成功。Runtime 状态和成功的 WRITE action 才是“已保存”或“已更新”的事实来源。
- Skill、Tool、Capability、Context、Runtime State、业务数据和长期 Memory 必须保持分离。
- Conversation Summary 不是 Long-term Memory。Context compaction 结果不能自动升级为长期记忆。
- LangGraph checkpoint state、Planner 输出和 Recovery Context 不是业务事实来源，也不是写入授权来源。
- `TraceSink` 是运行依赖，不进入 `GraphState`；event payload 不写完整 GraphState 或原始用户输入。
- 修改 Runtime 行为、Context 处理、Memory、写入安全或工具执行时，需要聚焦的回归测试。

## Task vs Plan

Task 是长期业务状态。

PlanRun 是临时 runtime 执行策略。

PlanRun 只有经过明确 WRITE 授权后，才能变成 TaskStep。

## 架构维护规则

- 当前架构事实写在本文档。
- 历史推进和完成状态写在 `docs/PROGRESS_LOG.md`。
- 学习解释写在 `docs/RUNTIME_CONCEPTS.md`。
- 外部学习链接写在 `docs/AGENT_LEARNING_LINKS.md`。
