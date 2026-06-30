# LifeOps Agent 学习进度与计划

## 文件职责

本文件只保留学习结论、当前问题和下一阶段计划。项目结构、实现细节与当前行为统一放在
`PROJECT_CONTEXT.md`，不在这里重复维护。

LifeOps Agent 的最终方向是真实可用的生活管理产品；本文件只记录当前学习主线和推进顺序，
不承载长期产品愿景本身。

## 当前阶段

第一阶段的Runtime基础已经结束。当前主线是：

> Context压缩、长期消息窗口、压缩后的认知连续性，以及高风险事实的精确保留/按需恢复。

暂不横向增加业务工具，也不立即进入长期Memory、MCP或Multi-Agent。

## 第一阶段已经建立的认识

### Agent Loop与状态边界

- 一次用户输入可以触发多轮LLM请求和多次工具执行。
- LLM逻辑轮次与实际API请求数不同；请求重试只增加后者。
- RunState属于一次 `Agent.chat()`，Session、对话历史、RunState和长期Task State是不同层次。
- Function Call是模型请求的Action；工具重试是同一Action的多次执行尝试。

### Skill、Prompt与Capability

- Skill提供领域规则，Tool提供真实能力，Capability决定本轮模型能看到和执行什么。
- Skill正文应按需加载，避免无关Prompt和Schema占用Context。
- 对话延续不能只靠历史文本，还需要明确的Runtime状态边界。

### 可靠性与副作用

- Runtime Retry处理临时基础设施错误；把工具业务错误重新交给LLM属于模型纠正流程。
- 幂等重放、重复Action和新的模型Action不是同一个问题。
- 模型输出不可信，权限、写入授权、Ref来源和成功声明必须由Runtime校验。
- 确定性签名能阻止完全重复，但不能替代语义级进展判断。

### 可观测性

- Event用于理解执行决策，LLM I/O用于查看模型边界，Application日志用于程序诊断。
- 日志字段必须表达统计作用域和统计对象，不能只写含糊的 `attempt` 或 `count`。
- 原始SDK Response会回显Request配置；诊断日志应投影必要字段，而不是无差别保存整个对象。

## 当前Context知识地图

后续学习时先区分五类容易混在一起的内容：

| 类型 | 作用 | 当前状态 |
|---|---|---|
| System Instructions | 本轮行为规则 | 每轮动态重建 |
| Recent Conversation | 最近用户、助手和工具交互 | 完整历史保存在 `messages`/ContextStore；发给模型的是滑动窗口后的工作上下文 |
| Tool Observation | 工具返回的数据 | 已有none/summary/summary_reference/reference压缩 |
| Conversation Summary | 被移出窗口的历史语义 | 已有第一版确定性Rolling Summary；尚未实现LLM摘要和失效重建 |
| Long-term Memory | 跨会话长期事实与偏好 | 尚未实现 |

当前最重要的认识：

> Tool Result压缩解决“一次Observation太大”；长期Context管理解决“历史消息不断累积”。
> 两者相关，但不是同一个机制。

## 下一阶段：Context压缩与长期窗口

具体 Context 学习方案和施工清单统一维护在 `CONTEXT_ENGINE_IMPLEMENTATION_PLAN.md`。
本文件只保留总方向：

- Context 当前主线已经从“压缩后可逆恢复原文”修正为“压缩后保持认知连续性”。
- 普通对话摘要允许有损，重点是让 LLM 知道窗口外的用户目标、偏好、已做决定、开放问题和当前任务。
- 工具结果、ID、金额、日期、确认范围等高风险事实不能只靠自然语言摘要，应通过结构化字段、Ref、Index 或按需恢复路径精确保留。
- 已完成 Context 执行计划的前五步；下一步从第六步开始，重点学习按需恢复、Context Index 和旧内容检索。

## Context之后的路线

Context阶段完成后，再按以下顺序推进：

1. 最小Memory State：用户明确授权保存的长期事实和偏好。
2. Interaction/Safety State：跨轮确认、取消、范围修改和过期。
3. Skill References与受控只读脚本。
4. Task State：跨Chat的长期目标、步骤和恢复。
5. 高级Memory Retrieval。
6. MCP。
7. 复杂规划与Multi-Agent。

继续暂缓：正式Routing Eval、向量数据库、自动记忆提取、任意Shell、复杂Planner和
大规模LLM-as-judge评测。
