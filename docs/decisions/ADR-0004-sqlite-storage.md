# ADR-0004：SQLite 存储与 Runtime Evidence

## 状态

已接受，用于当前 runtime 的存储与基础设施阶段。

## 背景

当前 runtime 需要一个本地、轻量、可测试、可解释的持久层，用来保存业务事实和 runtime evidence。

V0 中 JSON 文件、日志和辅助 helper 容易分散在业务代码附近。当前 runtime 需要先建立基础设施层，避免后续 Tasks、Wellbeing、Memory、Recovery、Inspector 和 Eval 各自实现一套存储和日志逻辑。

## 决策

当前 runtime 使用 SQLite 作为本地 facts / evidence store。

- 使用 Python 标准库 `sqlite3`，暂不引入 ORM、Alembic 或远程数据库。
- 默认数据库路径由 `config/default.json` 的 `database.path` 声明，当前为 `data/lifeops.sqlite3`。
- 使用 schema migration 管理数据库表结构版本。这里的 migration 指 schema 版本演进，不迁移旧 V0 数据。
- 启动流程应先 `connect_sqlite()`，再 `migrate(conn)`，之后 repository / store 才读写表。
- `SqliteUnitOfWork` 负责一组写入的 commit / rollback 边界。
- 测试默认使用 `:memory:` 或临时文件数据库，不复用真实用户数据库。
- 本地 SQLite、JSON 用户数据和 exports 不入库，由 `.gitignore` 保护。

当前 v1 schema 只包含基础 evidence 和 log 表：

- `schema_migrations`
- `run_records`
- `trace_events`
- `tool_calls`
- `llm_interactions`

业务语义强的表，例如 Tasks、Wellbeing、Memory 和 Eval 结果表，等对应模块计划确认后再实现。

Observability 分成两类日志：

- `LogTraceEvent` / `LogTraceStore`：结构化 runtime trace，只保存少量必要字段和紧凑 payload。
- `LogLlmInteraction` / `LogLlmInteractionStore`：原始 LLM / agent request-response 记录，用于人工排查。

两类日志分表保存。原始 LLM request-response log 是调试材料，不是业务事实来源，也不是写入授权来源。

## 结果

- 后续 domain repository 应依赖 storage 层和 migration 后的 SQLite schema，不再各自落长期 JSON 事实源。
- 后续 runtime / observability 写入应通过明确的 store 或 repository，并由 `SqliteUnitOfWork` 管理事务边界。
- Inspector / Eval 可以基于 `run_records`、`trace_events`、`tool_calls` 和 `llm_interactions` 查询 runtime evidence。
- 如果数据库 schema version 比当前代码更新，当前代码应拒绝继续使用该数据库。
- 如果未来需要迁移旧 V0 数据，应另行设计 data migration，不混入本 ADR 的 schema migration 机制。
