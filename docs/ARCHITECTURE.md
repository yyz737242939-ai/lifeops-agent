# Runtime 架构

本文档记录当前架构边界。它故意比模块实施计划更高层。

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
-> intent / policy / context / planning / execution / inspector
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

## 基础设施层

`common`、`storage` 和 `observability` 是当前 runtime 的基础设施层：

- `common` 提供配置读取、ID、时间、错误和 JSON 序列化，不依赖业务模块。
- `storage` 提供 SQLite 连接、schema migration 和 transaction boundary，不依赖 domain service。
- `observability` 提供 runtime evidence 的写入和读取，不负责业务状态变更。

真实数据库默认路径由 `config/default.json` 的 `database.path` 声明。当前默认值是：

```text
data/lifeops.sqlite3
```

测试必须使用 `:memory:` 或临时文件数据库，不复用真实用户数据库。

## 事实来源

Runtime 的事实来源是：

- 基于 SQLite 的业务和 runtime evidence repository；
- 成功的 WRITE tool result；
- 用户明确授权的 TaskStep；
- 用作执行证据的 RunRecord 和 LogTraceEvent。

不是事实来源：

- assistant final answer 文本；
- Planner 输出；
- LangGraph checkpoint state；
- Recovery Context；
- conversation summary。
- 原始 LLM request-response log。

## Observability

当前 observability 分成两类日志：

- `LogTraceEvent` / `LogTraceStore`：结构化 runtime trace，只保存少量必要字段和紧凑 payload，用于解释 runtime 路径和失败层级。
- `LogLlmInteraction` / `LogLlmInteractionStore`：原始 LLM / agent request-response 记录，用于人工排查最原始对话，不作为业务事实或写入授权来源。

两类日志分别写入 `trace_events` 和 `llm_interactions`，不混表。

## Runtime 不变量

- 用户数据安全优先。业务写入必须来自用户当前输入中的明确授权。
- 不能只凭 assistant 文本判断成功。Runtime 状态和成功的 WRITE action 才是“已保存”或“已更新”的事实来源。
- Skill、Tool、Capability、Context、Runtime State、业务数据和长期 Memory 必须保持分离。
- Conversation Summary 不是 Long-term Memory。Context compaction 结果不能自动升级为长期记忆。
- LangGraph checkpoint state、Planner 输出和 Recovery Context 不是业务事实来源，也不是写入授权来源。
- 修改 Runtime 行为、Context 处理、Memory、写入安全或工具执行时，需要聚焦的回归测试。

## Task vs Plan

Task 是长期业务状态。

PlanRun 是临时 runtime 执行策略。

PlanRun 只有经过明确 WRITE 授权后，才能变成 TaskStep。

## 架构决策

详细架构决策存放在：

```text
docs/decisions/
```
