# Agent Loop 执行骨架手动测试计划

## 学习目标

通过 Trace、Raw 和 Agent Messages 观察：

- Skill State 与单次请求 RunState 的生命周期差异。
- LLM 轮数、单轮工具数和累计工具数之间的区别。
- Function Call、ActionRecord 和 Function Call Output 的对应关系。
- 正常完成、部分完成和预算停止时的状态变化。

## 测试前准备

```powershell
uv run python main.py
uv run python log_viewer.py
```

保留 `data/*.json` 和 `logs/` 中已有数据，不要为了测试清空本地运行产物。

## 场景一：无工具正常完成

输入普通闲聊，例如：

```text
你好，简单介绍一下自己。
```

检查：

- 创建了新的 `run_id`。
- `llm_rounds` 为 1。
- `total_tool_calls` 为 0。
- 最终状态为 `completed`，StopReason 为 `completed`。

## 场景二：单工具后正常完成

输入：

```text
现在几点？
```

检查：

- 第一次 LLM 响应产生 Function Call。
- 工具结果通过相同 `call_id` 返回。
- RunState 中存在一个 `completed` ActionRecord。
- 模型再次调用后返回最终回答。
- Trace 中所有相关事件具有相同 `run_id`。

## 场景三：跨领域多工具调用

输入：

```text
查看我的待办和本周餐饮预算，然后推荐一个免费的恢复活动。
```

检查：

- `llm_rounds` 与 `total_tool_calls` 分开累计。
- 每个 Function Call 都有对应 ActionRecord 和 Function Call Output。
- 工具业务失败被记录为 failed Action，但不会导致 Python 异常退出。
- 正常得到最终回答时 Run 仍可进入 `completed`。

## 场景四：LLM 轮数预算

该场景优先通过自动化测试或临时注入较小的 `LoopLimits` 完成，避免修改全局默认值。

检查：

- 达到 `max_llm_rounds` 后不再请求模型。
- StopReason 为 `llm_budget_exhausted`。
- 如果之前有成功 Action，RunStatus 为 `partial`。
- 停止回答说明保留了多少成功工具结果。

## 场景五：单轮工具预算

使用 Fake LLM 在同一响应中返回超过 `max_tool_calls_per_round` 的 Function Call。

检查：

- 预算内调用正常执行。
- 超出预算的调用标记为 `skipped`。
- 每个被跳过的 `call_id` 仍有 Function Call Output。
- StopReason 为 `tool_budget_exhausted`。
- `total_tool_calls` 只统计实际开始处理的调用。

## 场景六：无效 JSON 参数

使用 Fake LLM 返回一个参数不是有效 JSON 的 Function Call。

检查：

- ActionRecord 状态为 `failed`。
- Error 为 `invalid_json_arguments`。
- 对应 `call_id` 收到结构化错误 Observation。
- Agent Loop 不因 JSON 解析异常崩溃。

## 自动化回归

```powershell
uv run python -m unittest discover -s tests -v
```

重点测试文件：

```text
tests/test_run_state.py
tests/test_agent_loop_skeleton.py
```

## 后续可靠性验证

重复/无进展、错误分类、重试、幂等性、部分成功、超时和取消已经进入下一份测试计划：

```text
docs/agent_loop_reliability_test_plan.md
```

工具并行和跨进程恢复仍属于 v0.1 之后的高级能力。
