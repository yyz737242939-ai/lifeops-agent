# Skill System 真实 LLM E2E 测试报告（2026-07-11）

## 结论

当前内置的 `research`、`travel` 两个 Skill 均完成真实 LLM happy-path 验证。两条通过用例都经过生产 bootstrap、Skill discovery、真实模型选择、selected body lazy loading、prompt contribution 构建和完整 Runtime graph，并以 `status=ok` 结束。

当前 Executor 仍是 `stub_execute`，所以本轮验证不包含真实论文抓取、旅行数据查询或最终答案生成。

## 测试环境

- 入口：`uv run python main.py`
- Provider：`.env` 中配置的 OpenAI-compatible endpoint
- Model：`deepseek/deepseek-v4-flash`
- Skill root：`app/skills`
- 内置 Skill：`research`、`travel`
- 验收条件：Policy allow；模型只选择预期 Skill；出现对应 `skill.loaded`；graph 经过 `prepare_skills -> stub_execute -> finalize`；最终状态为 `ok`

## CASE-01 Research happy path

输入：

```text
请研究并总结近期 Hugging Face Papers 的主要趋势，只需要给出研究分析。
```

结果：通过。

- Run ID：`run_fc33f48bad94426094454f8c54d80230`
- Intent：`chat`
- Policy：`allow`
- Selected Skill：`research`
- Loaded Skill：`research`
- Graph path：`classify_intent -> decide_policy -> prepare_skills -> stub_execute -> finalize`
- Runtime status：`ok`
- 从 `runtime.run.started` 到 `runtime.run.completed` 约 4.40 秒
- Evidence：[events.jsonl](../logs/sessions/session_2026-07-11T110907.991433Z0000_session_60ef3f4cd0f64fc09bcb1cf510496b96/events.jsonl)

## CASE-02 Travel happy path

输入：

```text
Plan a three-day Tokyo trip itinerary with daily areas and transportation suggestions.
```

结果：通过。

- Run ID：`run_99f982f32f7d42b5bc7d385d357b0a54`
- Intent：`chat`
- Policy：`allow`
- Selected Skill：`travel`
- Loaded Skill：`travel`
- Graph path：`classify_intent -> decide_policy -> prepare_skills -> stub_execute -> finalize`
- Runtime status：`ok`
- 从 `runtime.run.started` 到 `runtime.run.completed` 约 4.76 秒
- Evidence：[events.jsonl](../logs/sessions/session_2026-07-11T111000.418734Z0000_session_c567b10f39464deab1f16828f122acd5/events.jsonl)

## 额外观察

Travel 首次使用中文输入时，模型返回了空选择：

```text
请帮我规划东京三天旅行计划，包含每天的区域安排和交通建议。
```

该 run 仍以 `status=ok` 完成，因为零 Skill 是合法结构结果，但它不符合 Travel happy path 的业务预期。对应 Run ID 为 `run_c5e76acf496343bfabde3bf5a15d9abf`，evidence 位于 [events.jsonl](../logs/sessions/session_2026-07-11T110924.792458Z0000_session_5389882acd624818b0fa99d739ac865e/events.jsonl)。改用与英文 metadata 更一致的输入后正确选择了 `travel`。

这说明当前链路工作正常，但 `deepseek/deepseek-v4-flash` 在“中文请求 + 英文 Skill metadata”上的 selection recall 不稳定。后续 Eval 应保留中文 Travel 样例，并考虑在 selector instructions 中明确要求跨语言匹配，或者为 Skill description 增加简短中文语义，而不是把空选择视为系统错误。

## 最终判断

- Research happy path：通过
- Travel happy path：通过
- 全部当前 Skill 的真实 LLM happy path：通过
- 中文 Travel selection 稳定性：需要后续 Eval 持续观察
- Tool/source/external data E2E：不在当前实现范围内
