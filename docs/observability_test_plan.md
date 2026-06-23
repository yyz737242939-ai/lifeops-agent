# 三通道日志系统手动测试计划

## 学习目标

观察 Agent 的模型边界、Runtime 事件和程序调试信息如何分离，并使用 `session_id` 与
`run_id` 重新关联一次完整执行。

## 运行

```powershell
uv run python main.py
uv run python log_viewer.py
```

每次启动 Agent 会创建：

```text
logs/sessions/session_<timestamp>/
├── metadata.json
├── events.jsonl
├── llm.jsonl
└── application.log
```

## 场景一：普通回答

输入一个不需要工具的问题。

预期：

- Event 包含 `run.started`、`llm.requested`、`llm.responded` 和 `run.completed`。
- LLM I/O 只有 `llm.request` 和 `llm.response`，包含完整 messages、instructions 和 tools。
- Application 包含 run started/completed 信息。

## 场景二：工具调用

输入“列出我的待办任务”。

预期：

- Event 包含 `routing.resolved`、`capability.built`、`tool.started` 和 `tool.completed`。
- 工具参数、结果、压缩信息只出现在 Event，不产生 `tool.result` 类型的 LLM I/O 记录。
- 两个文件中的 `run_id` 相同。

## 场景三：模型错误与重试

使用 Fake LLM 制造一次可重试错误。

预期：

- Event 包含 `llm.failed` 和 `llm.retry_scheduled`。
- Application 包含 ERROR 行，便于调试程序执行。
- LLM I/O 仍只包含真正发出的 request 和收到的 response。

## 场景四：Viewer

打开 Viewer，依次切换 `Events`、`LLM I/O` 和 `Application`。

预期：

- 三种日志可独立筛选和搜索。
- Application 日志按级别显示为事件卡片。
- 旧 `logs/conversations/*_trace.json` 与 `*_raw.json` 仍可通过 Events/LLM I/O 查看。

## 自动化回归

```powershell
uv run python -m unittest discover -s tests -v
```
