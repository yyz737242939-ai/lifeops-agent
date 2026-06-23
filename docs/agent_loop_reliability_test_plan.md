# Agent Loop 执行可靠性手动测试计划

## 学习目标

观察 Agent 如何区分并处理重复、无进展、业务错误、临时错误、超时、重试、幂等重放、
部分成功和取消。

## 重点观察位置

- Trace：`llm_attempt`、`llm_retry_scheduled`、`tool_retry_scheduled`、`tool_skipped`、
  `run_stopped`。
- Raw：模型原始 Function Call 和完整 Tool Result。
- RunState：调用签名、Observation 签名、重试次数、Action 状态和 StopReason。
- `data/idempotency.json`：写工具成功结果的幂等记录。不要在未经允许时删除已有数据。

## 场景一：重复非幂等写

使用 Fake LLM 连续两轮返回参数相同的 `add_todo` 或 `record_expense`，但使用不同
`call_id`。

预期：

- 第一次正常执行。
- 第二次在写入前标记为 `skipped`。
- StopReason 为 `repeated_call`。
- Store 只新增一条业务数据。

## 场景二：相同 Observation 无进展

连续两次读取同一个不存在的 Context Ref。

预期：

- 两次调用都返回相同结构化 Not Found。
- 第二次结果后 StopReason 为 `no_progress`。
- Trace 能配对看到相同调用签名和 Observation 签名。

## 场景三：A-B-A-B 循环

使用 Fake LLM 返回两个参数固定的只读工具，并形成 A、B、A、B 调用序列。

预期：第四个调用在执行前被识别为循环，剩余调用全部获得对应的 skipped Output。

## 场景四：Tool Runtime Retry

让一个可重试只读工具第一次抛出 `OSError`，第二次成功。

预期：

- Tool Error 分类为 `transient_error`。
- `tool_retry_scheduled` 记录原因和次数。
- 同一个 ActionRecord 的 `attempt_count` 为 2。
- 累计工具预算统计两次实际尝试。

## 场景五：非幂等写错误不自动重试

让 `record_expense` 返回临时错误或超时。

预期：Runtime 不自动重试；错误 Observation 返回模型，由模型解释或选择其他动作。

## 场景六：LLM Retry 与部分成功

1. 第一次 LLM 请求超时，第二次成功：逻辑 LLM Round 为 1，LLM Attempt 为 2。
2. 一个工具成功后，下一轮 LLM 发生不可重试错误：RunStatus 为 `partial`，停止回答列出
   已完成工具。

## 场景七：幂等结果重放

对同一个写工具和相同 `idempotency_key` 调用两次 `call_tool`。

预期：

- 业务函数只执行一次。
- 第二次返回第一次结果。
- `idempotency.replayed` 为 `true`。

## 场景八：协作式取消

在 LLM 返回 Function Call 后、工具执行前调用 `agent.cancel_current_run()`。

预期：

- 工具没有执行。
- 每个 Function Call 仍有对应 Output。
- StopReason 为 `cancelled`。

注意：当前取消不会强杀已经进入同步 SDK 或 Python 函数的调用。

## 自动化回归

```powershell
uv run python -m unittest discover -s tests -v
```
