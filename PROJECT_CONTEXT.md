# LifeOps Agent 项目说明

## 如何使用

本文件只记录项目定位、代码结构、模块职责和当前技术状态。

学习进度与未来计划见：

```text
D:\lifeops-agent\LEARNING_PROGRESS.md
```

开启新的 AI 编程会话时，可以直接说：

```text
请先阅读 D:\lifeops-agent\PROJECT_CONTEXT.md 和
D:\lifeops-agent\LEARNING_PROGRESS.md，了解项目背景、当前状态和学习计划。
```

## 项目定位

LifeOps Agent 是位于 `D:\lifeops-agent` 的 AI Agent 开发学习项目。

目标不仅是完成功能，更重要的是通过清晰、可观察、可阅读的代码理解 Agent
Runtime、工具调用、Context、Skill 和可靠性设计。

开发原则：

1. 优先通过亲自实现理解原理。
2. 抽象保持简单，避免框架隐藏核心流程。
3. 只在产生真实需求后引入复杂度。
4. 通过 Trace 和 Raw 日志解释、复盘 Agent 行为。
5. 当前重视快速迭代，只保留少量关键自动化测试。

## 协作偏好

- 讨论架构或学习方向时，除非用户明确要求实现，否则不要修改代码。
- 实现功能时解释其中体现的 Agent 知识点。
- 给建议前先阅读当前代码。
- 为学习型功能提供能暴露内部行为的手动测试计划。
- 引入新知识点时提供官方文档或可靠的一手资料。

## 技术与运行

- Python 3.13+
- OpenRouter 与兼容 OpenAI Responses API 的模型
- Pydantic 数据模型
- 本地 JSON 持久化
- `uv` 项目环境

```powershell
# 运行 Agent
uv run python main.py

# 查看 Trace/Raw 日志
uv run python log_viewer.py

# 运行测试
uv run python -m unittest discover -s tests -v
```

## 模块职责

| 路径 | 职责 |
|---|---|
| `main.py` | CLI 入口，创建 Agent 并处理用户输入输出 |
| `app/agents/agent.py` | Agent Loop、跨轮状态、LLM 与工具编排、日志记录 |
| `app/prompts/system_prompt.py` | 始终加载的核心行为与 Context Ref 规则 |
| `app/prompts/prompt_builder.py` | 根据最终 `loaded_skills` 动态组合 System Prompt |
| `app/skills/skill_loader.py` | 发现 Skill 元数据并按需加载完整正文 |
| `app/skills/skill_router.py` | 根据当前输入执行确定性直接路由 |
| `app/skills/skill_state.py` | 处理 Skill 继承、切换、清理和 Ref-only 状态 |
| `app/skills/*/SKILL.md` | 四个业务领域的知识和工具编排规则 |
| `app/tools/tool.py` | 工具注册、Schema、工具实现、执行与权限检查 |
| `app/tools/tool_schema.py` | 完整工具 Schema 的静态导出 |
| `app/tools/capability_builder.py` | 将 Skill 映射为本轮 Tool Schema 和授权集合 |
| `app/runtime/run_state.py` | 单次请求的 RunState、ActionRecord、调用预算和终止状态 |
| `app/runtime/context_manager.py` | 工具结果的摘要压缩和引用压缩 |
| `app/runtime/context_ref_store.py` | 完整结果的 Ref 存储与读取 |
| `app/runtime/conversation_logger.py` | 生成结构化 Trace 和原始 LLM 日志 |
| `app/memory/todo_store.py` | Todo 模型与 JSON 持久化 |
| `app/memory/daily_log_store.py` | Wellbeing 状态与 JSON 持久化 |
| `app/memory/expense_store.py` | 消费、预算与 JSON 持久化 |
| `app/memory/activity_catalog.py` | 本地活动目录与推荐逻辑 |
| `log_viewer.py`、`app/log_viewer/*` | 本地 Trace/Raw 日志查看 UI |

手动学习测试位于：

```text
docs/agent_learning_test_plan.md
docs/skill_routing_test_plan.md
docs/capability_scoping_test_plan.md
docs/multi_turn_skill_state_test_plan.md
docs/agent_loop_execution_skeleton_test_plan.md
```

## 当前 Agent 运行链路

```text
用户输入
-> Skill Router 直接路由
-> Skill State Resolver 继承、切换或清理
-> Prompt Builder 加载最终 Skill 正文
-> Capability Builder 生成 Tool Schema 和授权集合
-> Runtime 创建 RunState 并检查 LLM/Tool 调用预算
-> LLM 返回回答或 Function Call
-> Runtime 校验权限并执行工具
-> Context Manager 压缩 Observation
-> RunState 记录 Action 和状态变化
-> Observation 返回 LLM，直到完成或以明确原因停止
```

## 已实现的业务领域

### Todo 与计划

- 新增、查看、完成、删除和更新 Todo。
- 支持优先级和截止日期。
- 根据未完成 Todo 生成日计划。

### Wellbeing

- 记录睡眠、心情、能量和备注。
- 查询指定日期或最近一段时间的状态。

### Finance

- 记录、查询和汇总消费。
- 设置并检查每日、每周或每月分类预算。

### Activity Recommendation

- 从本地目录推荐活动。
- 按能量、心情、时间、预算、地点和目标筛选。

## 当前关键行为

### Prompt 与 Skill

- 核心 Prompt、Ref 规则和 Skill 元数据始终可见。
- 完整 Skill 正文只在最终选中后加载。
- Prompt 每轮重新构建，不在对话 Context 中累积 Skill 正文。

### 多轮 Skill 状态

- 明确领域信号替换旧状态。
- “继续”“第一个”等含糊追问可以继承活跃 Skill。
- 普通闲聊清理旧状态。
- Ref-only 请求只使用公共工具，但保留活跃话题。

### Context 管理

- 中等长度列表使用结构化摘要。
- 很长且可能需要精确细节的结果使用引用压缩。
- `read_context_ref` 的完整结果不会再次被压缩。

### 能力边界

- Skill 显式映射到允许工具集合。
- LLM 只看到本轮允许的 Tool Schema。
- Runtime 在执行前再次校验工具权限。
- Trace 记录可见工具、权限来源和 Schema 大小。

### Agent Loop 执行骨架

- 每次 `chat()` 创建独立的 `RunState` 和 `run_id`。
- 分别限制 LLM 轮数、单轮工具数和请求累计工具数。
- `ActionRecord` 记录工具成功、失败或因预算跳过。
- Run 使用 `completed`、`partial`、`failed` 和 `stopped` 等明确状态。
- 达到预算时记录结构化 `StopReason`，并保留已经成功的工具结果。
- Trace/Raw 中的 LLM 和工具事件通过 `run_id` 关联到单次请求。

### 日志

- Trace：Agent 整体运行过程的结构化摘要。
- Raw：完整 LLM 输入输出、Tool Schema 和工具结果。
- 本地 UI 支持会话选择、筛选、搜索和 JSON 展开。

## 当前技术限制

- Router 词表仍然较小，需要根据真实 Trace 继续迭代。
- 跨领域请求后的含糊追问会继承整组 Skill。
- Prompt 和 Tool Schema 大小使用字符数，不是精确 token 数。
- Agent Loop 已有分层调用预算，但尚未实现重复调用和无进展检测。
- 尚未系统实现幂等写入、错误分类、重试和完整的部分成功恢复。
- 尚未实现 `/reset` 等 CLI 调试命令。

## 典型跨领域场景

```text
我昨晚只睡了 5 小时，今天能量低。这周餐饮预算比较紧，还有重要任务。
帮我安排一个现实一点的今天计划，并推荐一个不花钱的恢复活动。
```

可能触发：

```text
record_daily_state
-> check_budget 或 summarize_spending
-> plan_day
-> recommend_activities
-> 最终回答
```

## 本地运行数据

以下内容是被 Git 忽略的本地运行产物：

```text
data/*.json
logs/
```

它们可能包含手动测试数据，不要视为已提交源代码，也不要在未经允许时删除。
