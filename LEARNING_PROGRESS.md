# LifeOps Agent 学习进度与计划

## 文件职责

本文件只保留学习结论、当前问题和下一阶段计划。项目结构、实现细节与当前行为统一放在
`PROJECT_CONTEXT.md`，不在这里重复维护。

LifeOps Agent 的最终方向是真实可用的生活管理产品；本文件只记录当前学习主线和推进顺序，
不承载长期产品愿景本身。

## 当前阶段

第一阶段的Runtime基础已经结束。当前主线是：

> Context压缩、长期消息窗口，以及压缩后关键信息可恢复性。

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
| Tool Observation | 工具返回的数据 | 已有none/summary/reference压缩 |
| Conversation Summary | 被移出窗口的历史语义 | 已有第一版确定性Rolling Summary；尚未实现LLM摘要和失效重建 |
| Long-term Memory | 跨会话长期事实与偏好 | 尚未实现 |

当前最重要的认识：

> Tool Result压缩解决“一次Observation太大”；长期Context管理解决“历史消息不断累积”。
> 两者相关，但不是同一个机制。

## 下一阶段：Context压缩与长期窗口

### 学习目标

1. 理解Responses API输入项如何组成真实Context。
2. 理解字符数、token数、Context Window、输出预算和成本之间的关系。
3. 区分无损裁剪、结构化摘要、有损摘要、引用存储和按需读取。
4. 确定Function Call与Tool Observation必须成组保留的原因。
5. 学会定义“摘要必须保留的信息”，而不只是追求更短。
6. 理解摘要的生成、更新、替换、失效和恢复路径。
7. 用轻量Eval证明压缩前后关键行为一致。

### 第一部分：建立Context基线

先测量，再设计压缩策略：

- 记录每轮发送的消息数、消息类型、JSON字符数和真实input tokens。
- 区分instructions、tool schemas、最近对话、历史对话和tool outputs的占比。
- 观察Prompt Caching是否存在，以及缓存命中对成本和延迟的影响。
- 用短对话、10轮对话、大Tool Result三种场景建立基线。

产出：一份小型Context预算报告，以及能回答“token主要花在哪里”的Event数据。

### 第二部分：定义压缩不变量

压缩前先给信息分类：

- 身份字段：Todo ID、Expense ID、Context Ref ID。
- 决策字段：状态、优先级、日期、金额、排序依据。
- 交互字段：待确认操作、用户选择、失败与取消状态。
- 可恢复字段：完整结果存放位置、来源、有效期。
- 展示字段：解释文字、重复描述和可重新生成内容。

核心不变量：

```text
Context可以丢失展示细节，但不能丢失完成当前请求或后续Action所需的信息。
```

### 第三部分：改进Tool Observation压缩

当前体积阈值策略需要升级为“体积 + 用户需求 + 可恢复性”策略：

1. 查询工具支持明确排序、分页和 `limit`，优先只取用户真正需要的记录。
2. 摘要数量不能固定为5；必须考虑“用户要求几项”。
3. 任何被截断且可能继续使用的结果，都应有Runtime签发的恢复路径。
4. Summary与Reference的选择要考虑后续Action是否需要精确字段。
5. `read_context_ref` 只能接受当前Runtime真实产生且仍有效的Ref。
6. Ref增加来源、Session/Run归属、创建时间、过期和清理策略。

已确认的回归场景：

```text
已有12条待办，用户要求“告诉我最值得先做的6项”。
```

当前摘要只保留5条，因此不能可靠回答第6项。后续应加入一个小型、确定性的测试，验证：

- 返回数量满足用户请求，或明确说明数据不足。
- 第6项的标题、ID、优先级和日期来自真实数据。
- 模型不能编造被摘要丢弃的记录。

### 第四部分：实现长期消息窗口

目标不是简单截断最旧消息，而是维护以下结构：

```text
稳定核心规则
+ 历史对话摘要
+ 最近完整消息窗口
+ 当前未完成交互状态
+ 当前请求相关的精确Tool Result或Ref
```

需要重点研究：

- 最近窗口按token而不是固定轮数控制。
- User消息、Function Call和对应Observation不能被拆散。
- 写入确认、失败结果和未完成选择不能被普通摘要吞掉。
- 历史摘要更新后应替换旧摘要，而不是每轮继续叠加。
- 数据发生修改后，旧摘要中的派生结论如何失效。
- 摘要生成失败时如何安全退回完整窗口或确定性裁剪。

当前已完成第一版确定性滑动窗口和Rolling Summary：按近似token预算保留最近完整Context Unit，并总是保留 protected unit；被挤出窗口的旧内容会在回合结束后滚动压缩成结构化summary，下一次assemble时优先放入历史summary message。summary是派生状态，不是事实源。

### 第五部分：Context Eval

后续不再运行70例大规模UAT。每个Context机制只保留少量高信息量用例：

1. 请求条数超过摘要默认上限。
2. 摘要后继续完成指定Todo，ID必须正确。
3. 摘要后追问某笔消费，金额和日期必须正确。
4. 长对话后总结实际写入，只能包含成功WRITE Action。
5. 压缩跨越批量删除确认时，确认范围不能丢失。
6. Ref过期或非法时不能编造完整结果。
7. 压缩前后工具选择、参数和最终事实保持一致。

测试优先使用固定数据和确定性断言；只有验证模型行为时才运行少量真实LLM场景。

## Context阶段完成标准

- `Agent.messages` 不再随对话无界增长。
- 每轮Context有可解释的token预算和组成。
- Function Call与Observation配对关系不会被破坏。
- 摘要后的事实、ID、金额、日期和待确认状态可验证。
- 被截断的信息具有真实、受控、可过期的恢复路径。
- 压缩前后关键工具选择和写入安全行为保持一致。
- 长对话的input tokens相对当前全量历史有可测量下降。

## 推荐执行顺序

```text
1. Context组成与token基线（已完成第一版：ContextEngine pass-through + assembly report）
2. Context不变量和字段分类（已完成第一版：ContextUnit + function_call/observation 配对）
3. 最近消息窗口（已完成第一版：滑动窗口 + 占位摘要 + protected unit 保留）
4. 历史摘要（已完成第一版：确定性Rolling Summary + summary message）
5. 修复“固定5条摘要”问题
6. Ref来源校验与生命周期
7. 摘要更新、失效和恢复
8. 小型Context行为回归
```

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
