# Skill Routing Test Plan

## 目标

验证 Skill 元数据发现、确定性路由、正文按需加载、动态 Prompt、Context Ref 编排
以及现有 Agent 行为没有发生回归。

测试时重点区分四层问题：

```text
用户表达 -> Router 选 Skill -> Prompt 加载说明 -> Agent 选择并调用 Tool
```

## 1. 自动化测试

运行：

```powershell
uv run python -m unittest discover -s tests -v
uv run python -m compileall -q app tests
```

预期：所有测试通过，编译检查无输出。

当前覆盖：

- Loader 只接受 `name` 和 `description` frontmatter。
- Skill 名称必须与目录一致，正文可以在路由后单独加载。
- Todo、Wellbeing、Finance、Activity 单领域路由。
- 四领域组合路由。
- “预算报告任务”不会因为歧义错误触发 Finance。
- 普通对话使用 Core fallback。
- Prompt 只加载被选中的 Skill 正文。
- Core fallback 仍包含通用 `read_context_ref` 规则。
- Finance Skill 包含精确消费明细的 Ref 读取规则。

## 2. Loader 结构测试

逐个检查：

```text
app/skills/todo/SKILL.md
app/skills/wellbeing/SKILL.md
app/skills/finance/SKILL.md
app/skills/activity/SKILL.md
```

确认：

- frontmatter 只有 `name` 和 `description`。
- 名称与目录完全一致。
- description 能独立表达触发范围。
- 正文简短，只包含非显然的工具编排和 Ref 规则。
- Skill 内没有直接执行脚本的机制。

## 3. 单领域路由测试

依次运行 CLI，并在每次请求后查看 Trace 中的 `skill_routing`：

| 输入 | 期望 Skill | 期望主要工具 |
| --- | --- | --- |
| 提醒我明天完成 Agent 笔记 | todo | add_todo |
| 列出我的待办任务 | todo | list_todos |
| 我昨晚睡了 5 小时，今天能量低，记一下 | wellbeing | record_daily_state |
| 查看我最近一周的状态 | wellbeing | list_daily_logs |
| 今天午饭花了 35 元，记到餐饮 | finance | record_expense |
| 检查本周餐饮预算 | finance | check_budget |
| 推荐一个 20 分钟、不花钱的恢复活动 | activity | recommend_activities |

每个案例确认：

- `directly_selected` 只包含当前输入直接匹配的领域，`loaded_skills` 包含本轮最终领域。
- `reasons` 能解释命中的意图。
- `fallback_used` 为 `false`。
- Raw 日志中的 instructions 不包含其他 Skill 的 `Loaded skill:` 标记。
- 工具调用和最终答案符合原有业务行为。

## 4. 跨领域路由测试

输入：

```text
我昨晚只睡了 5 小时，今天能量低。这周餐饮预算紧，还有重要任务。
帮我安排一个现实一点的今天计划，并推荐一个不花钱的恢复活动。
```

期望：

- 选中 `wellbeing`、`finance`、`todo`、`activity`。
- 每个 Skill 都有独立的匹配原因。
- Prompt 中出现四个 `Loaded skill:` 标记。
- 可能的工具链为：记录或查询状态、检查预算、`plan_day`、推荐活动。
- 最终计划考虑低能量、预算限制、任务优先级和恢复活动。
- 未从工具获得的金额不得被虚构。

注意：LLM 可能在一次响应中并行发出互不依赖的工具调用，因此验证语义依赖，
不要机械要求所有调用严格串行。

## 5. Fallback 和歧义测试

| 输入 | 期望 |
| --- | --- |
| 你好，介绍一下自己 | 不加载领域 Skill，`fallback_used=true` |
| 提醒我完成预算报告任务 | 只选 Todo，不选 Finance |
| 我最近状态怎么样 | 选 Wellbeing |
| 帮我规划一下 | 当前可能 fallback；记录为 Router 召回案例 |
| 把刚才的明细展开 | 可以 fallback，但 Core Ref 规则仍应生效 |

对未覆盖表达，不要立即堆关键词。先把真实失败样本加入评测集，再判断应增加规则、
改写 description，还是需要使用历史上下文。

## 6. Context Ref 测试

准备至少 30 条消费或足够长的 Todo 列表，使工具结果触发 reference compaction。

第一轮：

```text
列出我最近所有消费，先总结。
```

确认：

- 路由选择 Finance。
- Raw 日志保存完整工具结果。
- Trace 的压缩策略为 `reference`，包含非空 `ref_id`。
- 模型收到摘要而不是全部记录。
- 如果摘要足够，Agent 不调用 `read_context_ref`。

第二轮：

```text
把刚才那批消费逐笔展开，包含日期和描述。
```

确认：

- 即使本轮 Router fallback，Core Prompt 仍包含 Ref 规则。
- Agent 使用上一轮 `ref_id` 调用 `read_context_ref`。
- 完整结果不被再次压缩。
- 最终回答中的日期、金额和描述与 Raw 记录一致。

Todo Ref 还需验证：在摘要缺少目标 ID 时，更新、完成或删除之前必须先展开 Ref，
不得猜测 ID。

## 7. Prompt Budget 测试

对同一版本分别测试普通对话、单领域和四领域输入，记录 Trace 中的
`prompt_chars`，并查看 Raw instructions。

确认：

- 普通对话只包含 Core、Ref 和 Skill 元数据目录。
- 单领域只多加载一个正文。
- 四领域加载全部正文。
- 同一输入多次运行，路由和 Prompt 字符数保持一致。

当前使用字符数作为近似指标。以后接入模型 tokenizer 后，再记录精确输入 token 数。

## 8. 回归测试

重新执行 `docs/agent_learning_test_plan.md` 中所有已有场景，确认：

- Todo、Wellbeing、Finance、Activity 的写入和读取没有回归。
- 工具结果压缩阈值和 Ref 文件格式没有变化。
- Trace 和 Raw 日志仍能完整解释 Agent 行为。
- Agent 达到最大循环次数时的原有停止行为没有变化。

## 9. 失败诊断顺序

出现错误回答时，按以下顺序检查：

1. `skill_routing` 是否选中正确 Skill。
2. Raw instructions 是否真正加载了对应正文。
3. 模型是否选择了正确 Tool 和参数。
4. Tool Raw result 是否正确。
5. 压缩后的 Observation 是否丢失了必要信息。
6. 最终回答是否忠于 Observation。

这个顺序可以避免把 Router、Prompt、Tool 和 Context 压缩问题混在一起。

## 10. 完成标准

- 自动化测试和编译检查全部通过。
- 所有单领域案例正确路由且不加载无关 Skill。
- 典型四领域案例完整召回四个 Skill。
- 歧义案例不误选 Finance。
- Ref 摘要足够时不展开，需要精确明细时可以按需读取。
- 现有业务和 Context 压缩测试无回归。
- 每次失败都能通过 Trace 定位到具体层级。
