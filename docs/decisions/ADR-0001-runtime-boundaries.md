# ADR-0001：Runtime 边界

## 状态

已接受，用于当前 runtime 规划。

## 背景

V0 runtime 是在学习 Agent Runtime 概念的过程中逐步长出来的。旧 `Agent` 路径耦合了多个职责，包括 routing、planning、tool execution、task state、recovery 和 observability。

## 决策

Runtime 使用显式分层：

- intent first；
- tool exposure 或 execution 之前先经过 policy；
- 使用 LangGraph 做 orchestration；
- 自有 runtime 模块负责 policy、context、tools、execution、recovery、trace 和 facts source；
- `app/` 作为新的代码根目录；
- `docs/` 和 `plans/` 作为新的文档和计划根目录。

## 结果

- 当前 runtime 模块不能隐式依赖 legacy 的 `legacy_v0/app/agents/agent.py`。
- 每个模块实现前都需要专门的模块计划。
- Legacy 实现是参考，不是默认设计来源。
