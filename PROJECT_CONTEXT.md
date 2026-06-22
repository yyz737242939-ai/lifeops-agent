# LifeOps Agent 项目上下文

## 如何使用本文件

本文件用于帮助新的 AI 编程会话快速了解项目背景、当前进度和协作方式。

每次开启新会话时，可以直接说：

```text
请先阅读 D:\lifeops-agent\PROJECT_CONTEXT.md，了解项目背景和当前进度。
这个会话我想重点学习：<本次主题>。
```

## 项目定位

LifeOps Agent 是一个位于以下路径的 AI Agent 开发学习项目：

```text
D:\lifeops-agent
```

项目目标不只是完成功能，更重要的是通过清晰、可观察、可阅读的代码理解 AI
Agent 的重要原理。

开发优先级：

1. 通过亲自实现功能理解 Agent 原理。
2. 抽象应保持足够简单，确保学习者能够看懂。
3. 只有在项目产生真实需求后才引入新的复杂度。
4. 保持良好的可观测性，让 Agent 行为能够通过日志解释和复盘。
5. 当前阶段重视快速迭代，暂时不要求建立完整的自动化测试体系。

## 协作偏好

- 讨论架构或学习方向时，除非用户明确要求实现，否则不要修改代码。
- 用户要求实现时，应完成对应功能，并解释代码体现了哪些 Agent 知识点。
- 给建议前应先阅读当前代码，避免只提供通用的 Agent 开发建议。
- 为学习型功能提供手动测试计划。
- 测试计划应尽量暴露 Agent 的内部行为，包括工具调用、Context 增长、压缩、
  引用和 Prompt 加载情况。
- 引入新知识点时，提供官方文档或可靠的一手学习资料。
- 除非学习目标就是某个框架，否则不要用大型框架隐藏核心实现原理。

## 当前项目结构

```text
main.py                              CLI 入口
app/agents/agent.py                  Agent Loop 和 LLM/工具编排
app/tools/tool.py                    工具注册、Schema、工具实现和 call_tool
app/tools/tool_schema.py             导出的工具 Schema
app/tools/capability_builder.py      Skill 到工具的权限映射和动态 Tool Schema
app/prompts/system_prompt.py         始终加载的核心行为和 Context Ref 规则
app/prompts/prompt_builder.py        根据路由结果动态组合 System Prompt
app/skills/skill_loader.py           Skill 元数据发现和正文按需加载
app/skills/skill_router.py           确定性的规则 Skill Router
app/skills/skill_state.py            多轮 Skill 继承、切换和清理决策
app/skills/*/SKILL.md                四个业务领域的渐进式 Skill 说明
app/runtime/conversation_logger.py   结构化 Trace 和原始 LLM 日志
app/runtime/context_manager.py       工具结果的摘要压缩和引用压缩
app/runtime/context_ref_store.py     Context 完整结果的引用存储
app/log_viewer/server.py             本地 Trace/Raw 日志查看服务
app/log_viewer/static/*              日志查看器的 HTML、CSS 和 JavaScript
app/memory/todo_store.py             Todo 模型和 JSON 持久化
app/memory/daily_log_store.py        Wellbeing 状态和 JSON 持久化
app/memory/expense_store.py          消费、预算和 JSON 持久化
app/memory/activity_catalog.py       本地活动目录和推荐逻辑
docs/agent_learning_test_plan.md     手动学习和 Context 测试计划
docs/skill_routing_test_plan.md      Skill Routing 完整测试计划
docs/capability_scoping_test_plan.md 动态能力边界手动学习测试计划
docs/multi_turn_skill_state_test_plan.md 多轮 Skill 状态手动学习测试计划
log_viewer.py                        本地日志查看器入口
```

项目使用：

- Python 3.13+
- 通过 OpenRouter 调用兼容 OpenAI Responses API 的模型
- Pydantic 数据模型
- 本地 JSON 持久化
- `uv` 项目环境

运行项目：

```powershell
uv run python main.py
```

## 已实现的 Agent 基础能力

- Function Calling Agent Loop
- 支持跨多轮循环调用多个工具
- 最大工具调用循环限制
- 工具注册表和自动生成的工具 Schema
- 结构化 JSON 工具返回值
- 结构化工具错误
- Todo 的新增、查看、完成、删除和更新
- 每次会话生成 Trace 和 Raw 双日志
- 终端只显示必要的用户交互内容
- 基于规则的 Skill Routing
- Skill 元数据始终可见，完整正文仅在选中后加载
- 每轮 Trace 记录 Skill 选择、原因、分数、fallback 和 Prompt 大小
- 根据本轮加载的 Skill 动态生成 Tool Schema
- Tool Schema 可见性与运行时工具授权双层限制
- Trace 记录可见工具、能力来源、Schema 数量和大小
- 本地 Trace/Raw 日志查看 UI
- 多轮 Skill 状态继承、明确切换、闲聊清理和 Ref 最小权限处理
- Trace 区分直接选择、继承、最终加载和前后活跃状态

## 已实现的业务领域

### 计划和 Todo

- Todo 标题、状态、优先级、截止日期和时间字段
- 根据未完成 Todo 生成日计划
- 获取当前时间

### Wellbeing 身心状态

- 记录每日睡眠、心情、能量和备注
- 查询某一天的状态
- 查询最近一段时间的状态记录

### Finance 财务

- 记录和查询消费
- 汇总消费情况
- 设置分类预算
- 检查每日、每周或每月消费是否超出预算

### Activity Recommendation 活动推荐

- 从本地活动目录推荐活动
- 根据能量、心情、可用时间、预算、地点和目标进行筛选
- 设计目标是与 Wellbeing、Finance 和 Todo 计划组合使用

## 已实现的 Context 管理

目前实现了两种 Context 压缩策略。

### 结构化摘要压缩

用于中等长度的列表型结果。当下一步决策只需要统计信息和重要条目时，用结构化
摘要替代完整结果。

示例：

- Todo 总数、逾期数量和重要未完成任务
- 消费总额和分类汇总
- Wellbeing 趋势和最近状态
- 排名前几位的活动推荐

### 引用压缩

用于很长但未来可能需要精确细节的工具结果。

- 完整结果存储在 `logs/context_refs/`。
- 模型收到摘要、`ref_id` 和按需读取提示。
- `read_context_ref` 工具可以按需读取完整结果。
- `read_context_ref` 返回的完整结果不会再次被压缩，避免反复引用。

日志提供三种视角：

- Raw 日志：工具实际返回的完整结果
- Trace 日志：压缩策略、压缩原因和摘要
- Agent Messages：模型下一轮实际看到的 Observation

比较这三种视角，是当前项目学习 Context Management 的主要方式。

## 当前 Prompt 状态

System Prompt 现在分为两层：

- 始终加载：核心行为、Context Ref 通用规则、四个 Skill 的简短元数据。
- 按需加载：Todo、Wellbeing、Finance、Activity 的完整 `SKILL.md` 正文。

Router 在 LLM 请求之前运行，使用可读、确定性的正则规则。无匹配时只使用核心
Prompt；跨领域请求可以同时加载多个 Skill。Capability Builder 根据最终加载的
Skill 生成本轮 Tool Schema；无匹配时只保留公共工具。`call_tool` 在执行前再次检查
本轮权限，避免仅依赖模型可见性形成虚假的权限边界。

通用 Ref 规则要求：摘要足够时不展开；需要精确记录、ID、日期、金额或用户明确
要求展开时，调用 `read_context_ref`。每个 Skill 正文进一步说明本领域何时需要 Ref。

## 已实现的 Skill Routing

- Skill frontmatter 只允许 `name` 和 `description`。
- `discover_skills` 只扫描元数据，`load_skill` 在选中后才读取正文。
- 当前规则覆盖中英文 Todo、Wellbeing、Finance 和 Activity 意图。
- Router 返回选中 Skill、分数、匹配原因和 fallback 状态。
- Prompt Builder 组合 Core、Ref、Skill Catalog 和选中 Skill 正文。
- 默认最多允许四个 Skill，以支持项目的四领域典型场景。
- 自动化测试覆盖单领域、跨领域、无匹配 fallback、歧义词、按需正文加载和 Ref 指南。

当前限制：

- Router 本身仍是无状态的，只根据当前用户输入选择 Skill；独立的 Skill State
  Resolver 使用上一轮活跃 Skill 处理确定性的含糊追问。
- 跨领域请求后的含糊追问会继承整组活跃 Skill，暂未根据最近工具结果进一步缩小。
- 路由词表仍然较小，需要通过真实 Trace 和评测案例迭代。
- Prompt 大小目前以字符数记录，并非模型 tokenizer 的精确 token 数。
- Router 漏选会直接造成领域工具不可见；目前采用只保留公共工具的安全 fallback，
  后续通过多轮 Skill 状态管理改善依赖上文的含糊追问。

## 当前学习进度

已经通过当前实现学习和讨论过以下概念：

1. Function Calling Agent Loop：模型输出工具调用，Agent 执行工具并把 Observation
   送回模型，直到得到最终回答或达到循环上限。
2. Tool Registry 与 Schema：工具实现、参数 Schema、结构化结果和错误处理之间的关系。
3. Context Management：完整工具结果、结构化摘要、引用压缩和按需读取之间的取舍。
4. Prompt 与对话记录的分离：`instructions` 每次请求重新生成，`self.messages` 保存
   跨轮对话、工具调用和工具结果。
5. Skill 渐进式披露：所有 Skill 只暴露简短元数据，Router 选中后才读取完整正文。
6. 确定性 Skill Routing：使用规则、分数和匹配原因选择一个或多个领域 Skill。
7. 动态 Prompt Builder：Agent 每轮先完成直接路由与状态解析，Builder 再根据最终
   `loaded_skills` 构建最新 System Prompt；同一个 Skill 不会在对话 Context 中重复累积。
8. Skill 与 Tool 的边界：Skill 提供领域知识和编排规则，Tool 提供实际执行能力。
9. Context Ref 与 Skill 的关系：Ref 是通用运行时能力，Skill 只补充领域相关的展开条件。
10. Capability Scoping：最终加载的 Skill 映射为本轮可见工具；Schema 过滤减少模型
    干扰和 Context 开销，Runtime 授权校验负责守住实际执行边界。
11. 多轮 Skill 状态：直接路由与运行时状态分离；明确领域替换旧状态，含糊追问
    继承活跃 Skill，普通闲聊清理状态，Ref 请求只加载公共能力但保留话题。

当前学习阶段已经从“增加业务工具”进入“理解 Agent Runtime 的状态、能力边界和
可靠性”。Routing Eval 的 Precision/Recall 与行为回归已经讨论过，但用户决定暂时
跳过正式 Eval，后续需要时再补充；每个新功能仍应保留少量关键自动化测试。

## 接下来的学习计划

按照以下顺序继续。除非用户明确调整方向，否则优先完成当前阶段后再进入下一阶段。

### 已完成：多轮 Skill 状态管理

Router 仍只根据最新一条用户输入直接选择 Skill，Agent 通过独立状态解析层处理依赖
上文的含糊追问，同时避免旧领域永久污染新话题。

已经实现：

- 在 Agent 中保存上一轮活跃 Skill。
- 区分本轮直接选择、从上一轮继承和最终加载的 Skill。
- 本轮有明确领域信号时，以新路由结果为准。
- 本轮是“第一个”“刚才那个”“继续”等追问时，允许继承上一轮 Skill。
- 明确切换领域时替换旧 Skill；普通闲聊清理状态；新 Agent 从空状态开始。
- Trace 记录 `directly_selected`、`inherited_skills` 和 `loaded_skills`。
- Ref-only 请求本轮只使用公共工具，同时保留上一个活跃话题供后续继续。

学习目标：

- 对话历史与 Agent 运行状态的区别
- 有状态 Router
- 话题延续、话题切换和 Skill 生命周期
- 继承策略的风险与 fallback

最低测试案例：Todo 含糊追问可以继承；切换到 Finance 后不继续继承 Todo；普通
闲聊不会让旧 Skill 永久保持活跃。

当前暂未实现 `/reset` CLI 命令；它仍属于后续 CLI 调试命令方向。

### 已完成：动态 Tool Schema 与 Skill 权限

Prompt 和 Tool Schema 现在都按本轮选中的 Skill 动态加载，选中的 Skill 决定本轮
可以使用哪些业务工具。

已经实现：

- 为每个 Skill 建立明确的允许工具集合。
- 始终暴露 `read_context_ref`、`get_current_time` 等公共工具。
- 独立 Capability Builder 返回本轮 Tool Schema。
- 未选中的领域工具默认不暴露给模型。
- Router 漏选导致工具缺失时，使用只保留公共工具的安全、可观察 fallback。
- Trace 记录本轮可见工具、Schema 大小和能力来源。
- `call_tool` 执行前校验本轮授权，越权时返回 `tool_not_allowed`。
- 本地 UI 配对查看 Trace 和 Raw 日志，支持筛选、搜索和 JSON 展开。

学习目标：

- Capability Scoping 和最小权限原则
- Skill 与 Tool 的能力映射
- Tool Schema Context Budget
- 路由错误后的恢复机制

最低测试案例：Todo 请求只看到 Todo 与公共工具；四领域请求合并四组工具且不重复；
Ref 追问即使没有领域 Skill 也能使用 `read_context_ref`。

### 第三阶段：Agent Loop 与执行可靠性

完成 Skill 的状态和能力边界后，开始强化运行时，避免把所有限制简化为固定的
`MAX_TOOL_CALL_LOOPS`。

计划研究和实现：

- 区分 LLM 循环轮数、单轮工具数和整个请求累计工具数。
- 检测没有进展或重复的工具调用。
- 为写工具研究幂等性，避免重试产生重复 Todo、状态或消费记录。
- 处理工具失败后的参数纠正、重试、跳过和部分结果保留。
- 明确并行工具调用与有依赖顺序的工具调用。
- 达到限制时返回可恢复的中间结果和停止原因。
- 随对话增长研究消息摘要、窗口管理和长期状态边界。

学习目标：

- Agent 状态机与终止条件
- 幂等性、重试和错误恢复
- 可恢复执行与部分成功
- 长对话 Context 生命周期

重点使用项目的四领域典型场景，主动制造某一步工具失败，观察 Agent 是否能保留
已有结果、解释失败并继续完成仍可完成的部分。

### 暂缓但保留的方向

- 正式 Routing Eval、Precision/Recall 和大规模行为回归
- 使用小模型或语义检索进行 Skill Routing
- Skill 内受控脚本和 references 资源加载
- 精确 tokenizer Prompt Budget
- `/tools`、`/skills`、`/context`、`/refs`、`/trace`、`/raw`、`/reset`
  等 CLI 调试命令

不要默认自动实现这些功能。除非用户明确要求修改代码，否则应先讨论设计。

## 典型的跨领域场景

一个具有代表性的 Agent 请求是：

```text
我昨晚只睡了 5 小时，今天能量低。这周餐饮预算比较紧，还有重要任务。
帮我安排一个现实一点的今天计划，并推荐一个不花钱的恢复活动。
```

它可能触发：

```text
record_daily_state
-> check_budget 或 summarize_spending
-> plan_day
-> recommend_activities
-> 最终回答
```

这个场景适合学习工具编排、长 Context、Prompt 行为、摘要压缩和引用读取。

## 本地运行数据

以下内容是本地运行产物，已经被 Git 忽略：

```text
data/*.json
logs/
```

这些文件可能包含手动测试或 Smoke Test 数据。不要把它们视为已提交的源代码，
也不要在没有获得用户许可的情况下删除。
