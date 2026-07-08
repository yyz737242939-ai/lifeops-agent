# 面试 Demo 指南

本文档将成为当前 runtime 的面试和 demo 指南。

## 目的

用本文档准备一段简短、可解释的 Runtime 架构 demo。

本指南最终应覆盖：

- 5 分钟架构解释；
- 10 分钟 CLI demo；
- 20 分钟更深入的 runtime walkthrough；
- 常见面试问题；
- 当前 runtime 如何映射到 LangGraph、LangChain、MCP、DAG、eval 和 inspector 概念。

## 计划 Demo 主题

- Intent 避免关键词误路由。
- Policy 阻止未授权写入。
- Task 和 Plan 相互分离。
- LangGraph 负责编排，但不拥有业务事实。
- Executor 返回结构化反馈。
- Inspector 解释一次 run。
- Eval 证明 runtime 行为。
- DAG Scheduler 独立且可 trace。

## 状态

目前只是骨架。等第一个可运行的当前 runtime demo 出现后再补全。
