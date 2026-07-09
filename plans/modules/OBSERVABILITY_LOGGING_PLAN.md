# Observability Logging 模块计划

## 当前状态

阶段 3.5 Observability 文件日志校正已完成。

已完成：

- `app/observability/file_logs.py` 已实现 `SessionLogWriter`、`EventLogWriter` 和 `LlmLogWriter`。
- `app/observability/logger.py` 已实现幂等的 `application.log` 配置。
- `RuntimeService` 已改为通过 event writer 写入 runtime event，不再依赖 SQLite trace store。
- `config/default.json` 已声明默认日志根目录 `logs/sessions`。
- SQLite 初始 schema 已移除 `trace_events` 和 `llm_interactions`，保留 `run_records` 和 `tool_calls`。
- 聚焦测试已覆盖文件日志写入、application log 幂等、RuntimeService 无 SQLite event log 路径和 storage migration。

仍保留到后续阶段：

- Inspector / Eval 读取 session log directory。
- LLM log 脱敏策略。
- 日志清理、轮转和导出策略。

## 1. 目标

本模块把当前 runtime 的日志边界从“全部塞进 SQLite”校正为三类文件日志：

- `events.jsonl`：结构化 runtime event，用于学习、Inspector、Eval 和复盘 runtime path。
- `llm.jsonl`：原始 LLM request / response，用于回看对话交互具体内容。
- `application.log`：普通程序日志，用于测试、debug 和类似 Java application log 的工程排查。

SQLite 不再默认承载 event log 或 LLM log。SQLite 主要存放业务事实、适合关系查询的数据，以及确实需要 transaction / repository / migration 的状态。

## 2. 当前 V0 参考

V0 曾经形成过三通道观测布局：

```text
logs/sessions/session_<timestamp>/
  metadata.json
  events.jsonl
  llm.jsonl
  application.log
```

本模块只借鉴这个边界，不直接迁移旧 viewer 或旧 runtime 实现。

## 3. 当前范围

初版做：

- 定义 session log directory 策略。
- 写入 `metadata.json`，记录 session id、started_at、runtime version 或必要环境信息。
- 写入 `events.jsonl`，每行一个结构化 event。
- 写入 `llm.jsonl`，每行一个 LLM interaction。
- 接入 Python 标准 `logging`，输出 `application.log`。
- 让 Runtime Core / Orchestration 使用 event writer，而不是 SQLite trace store。
- 保留 SQLite storage 给业务事实和关系型数据。
- 更新 tests，验证三种日志都按预期写入。

初版不做：

- 不实现完整 Inspector UI。
- 不做日志轮转、压缩或远程上传。
- 不把所有 Python logger name 和 handler 策略平台化。
- 不把 LLM log 当成业务事实或写入授权来源。
- 不为了查询方便把 event / LLM log 再写回 SQLite。

后续版本可做：

- Inspector 读取 session log directory。
- Eval runner 读取 `events.jsonl` 断言 runtime path。
- 增加脱敏策略、日志清理策略和导出策略。
- 如果确实需要跨 session 查询，再设计派生索引；派生索引不是日志源头。

## 4. Runtime 边界

输入：

- session id / run id / turn id。
- runtime event。
- LLM request / response。
- normal application logger message。

输出：

- append-only `events.jsonl`。
- append-only `llm.jsonl`。
- append-only `application.log`。
- 可选 `metadata.json`。

依赖：

```text
runtime / orchestration / tools
-> observability
-> common
```

`observability` 不依赖 storage，不依赖业务 domain，不授权写入，不生成业务事实。

## 5. 数据模型 / 存储

推荐目录：

```text
logs/
  sessions/
    session_<timestamp>/
      metadata.json
      events.jsonl
      llm.jsonl
      application.log
```

`events.jsonl` 每行建议字段：

- `id`
- `timestamp`
- `session_id`
- `run_id`
- `turn_id`
- `event_type`
- `level`
- `payload`

`llm.jsonl` 每行建议字段：

- `id`
- `timestamp`
- `session_id`
- `run_id`
- `turn_id`
- `provider`
- `model`
- `request`
- `response`
- `status`
- `error_code`

`application.log` 使用普通文本日志：

```text
timestamp level logger run_id message
```

SQLite 初版不存：

- runtime event log；
- LLM request / response log；
- normal debug log。

SQLite 可继续存：

- Tasks / TaskSteps；
- Wellbeing entries；
- semantic memory；
- tool call 结果，如果后续需要关系查询和事实追溯；
- eval result，如果后续需要结构化查询。

## 6. 对外接口

预期接口：

- `SessionLogWriter`
- `EventLogWriter.append(event)`
- `LlmLogWriter.append(interaction)`
- `configure_application_logging(session_dir, run_id=None)`
- `SessionLogReader`，后续供 Inspector / Eval 使用。

具体命名以施工时实际代码为准。

## 7. 失败模式

- log directory 不可写。
- JSONL 单行序列化失败。
- LLM payload 过大。
- LLM payload 包含不应落盘的 token / credential。
- application logger 重复添加 handler，导致重复日志。
- event payload 复制完整用户输入或 tool 原文，导致泄露或文件膨胀。

初版策略：

- event payload 保持紧凑结构化。
- LLM log 是专门原始通道，但需要预留脱敏入口。
- logging 初始化必须幂等。
- 文件写入失败初版可抛错，让测试暴露问题；后续再设计降级。

## 8. 测试和 Eval

聚焦测试：

- 创建 session log directory。
- append event 后 `events.jsonl` 每行是合法 JSON。
- append LLM interaction 后 `llm.jsonl` 每行是合法 JSON。
- application logger 写入 `application.log`。
- 多条 event 保持 append 顺序。
- logging 初始化幂等，不重复输出。
- RuntimeService 不再依赖 SQLite trace store 才能记录 event。

## 9. 文档更新

- `docs/PROGRESS_LOG.md`：模块完成后记录三通道文件日志已实现、有效测试和旧 SQLite log store 的处理方式。
- `docs/ARCHITECTURE.md`：代码改完后，更新 Observability 当前事实；在代码未改前不要写成已实现。
- `docs/RUNTIME_CONCEPTS.md`：沉淀 Observability、event log、LLM log、application log、SQLite vs file log 的解释。
- `docs/AGENT_LEARNING_LINKS.md`：本模块不需要新增外部链接，除非施工时确实学习了新的官方 logging 文档。

## 10. 实施步骤

1. 定义 session log directory 和 metadata 模型。
2. 实现 event JSONL writer / reader。
3. 实现 LLM JSONL writer / reader。
4. 接入 Python application logging 到 `application.log`。
5. 改造 RuntimeService 的 event 写入路径。
6. 保持 SQLite schema 不承载 event / LLM log。
7. 确认后续新模块依赖 `events.jsonl` / `llm.jsonl` / `application.log`，不依赖日志表。
8. 更新 Runtime Core / LangGraph Orchestration 测试。
9. 更新 `docs/PROGRESS_LOG.md`、`docs/ARCHITECTURE.md` 和 `docs/RUNTIME_CONCEPTS.md`。
