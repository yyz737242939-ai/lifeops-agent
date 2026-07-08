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

## 事实来源

Runtime 的事实来源是：

- 基于 SQLite 的业务和 runtime evidence repository；
- 成功的 WRITE tool result；
- 用户明确授权的 TaskStep；
- 用作执行证据的 RunRecord 和 TraceEvent。

不是事实来源：

- assistant final answer 文本；
- Planner 输出；
- LangGraph checkpoint state；
- Recovery Context；
- conversation summary。

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
