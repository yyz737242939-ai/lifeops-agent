# Storage / SQLite 模块计划

## 当前状态

阶段 2 Storage / SQLite 初版已完成。

当前边界：

- SQLite 主要服务业务事实、适合关系查询的数据、repository 和 migration；不要因为信息“结构化”就默认写入 SQLite。
- Runtime event、LLM interaction 和 normal 程序日志属于 `plans/modules/OBSERVABILITY_LOGGING_PLAN.md`，当前实现写入 `events.jsonl`、`llm.jsonl` 和 `application.log`。

已完成：

- `app/common/` 已包含配置读取、ID、UTC 时间、项目错误类型和 JSON 序列化 helper。
- `app/storage/` 已包含 SQLite connection factory、schema、migration runner、repository helper 和 `SqliteUnitOfWork`。
- `app/observability/` 已包含 event JSONL、LLM JSONL 和 application log 的文件日志 writer。
- `config/default.json` 已声明默认数据库路径 `data/lifeops.sqlite3`。
- SQLite 当前 schema 包含 `schema_migrations`、`run_records` 和 `tool_calls`。
- 测试数据库 helper 已支持 `:memory:` SQLite 和 migration helper，避免触碰真实 `data/lifeops.sqlite3`。
- `.gitignore` 已覆盖本地 SQLite、JSON 用户数据、导出目录和 legacy 运行输出。
- `docs/PROGRESS_LOG.md`、`docs/ARCHITECTURE.md` 和 `docs/RUNTIME_CONCEPTS.md` 已同步阶段 2 边界。

仍保留到后续阶段：

- Tasks、Wellbeing、Memory、Recovery、Inspector 和 Eval 的业务 repository。
- 旧 V0 数据迁移。
- 产品 UI、Inspector CLI 和 Eval runner。
- 复杂 migration 回滚、备份、导出和隐私增强策略。

阶段 2 收口验证：

- 已运行 `uv run python -m compileall app tests`。
- 阶段 2 聚焦测试覆盖 common、storage、observability 和 test database helper。
- 按用户要求，本次不运行全量测试。

## 1. 目标

本模块对应 `plans/RUNTIME_REFACTOR_PLAN.md` 的“阶段 2：存储与基础设施”。

目标是先建立当前 runtime 的基础设施层，让后续业务模块不再各自混写 JSON、日志和 helper 逻辑。阶段 2 结束时，项目应具备：

- `app/common/`：跨模块基础类型、时间、ID、错误和序列化工具。
- `app/storage/`：SQLite 连接、schema、migration、repository 基类和 unit of work。
- `app/observability/`：event、LLM 和 normal 程序日志接口；当前文件日志实现由 Observability Logging 模块维护。
- 可重复创建的 test database 策略。
- 明确的本地数据、fixture、eval 数据和真实用户数据隔离规则。

本模块不是业务 domain 迁移。它只提供后续 Tasks、Wellbeing、Memory、Recovery、Inspector、Eval 可以依赖的底座。

## 2. 当前 V0 参考

阶段 2 默认不读取 `legacy_v0/`。只有在后续施工时需要追溯旧 JSON store、日志格式或旧 runtime evidence 行为，才按 `AGENTS.md` 的 Legacy 读取规则读取相关片段。

当前可依据的参考是：

- `README.md`：当前 runtime 使用 SQLite 存放业务事实和适合关系查询的数据；event / LLM / normal 程序日志默认走文件。
- `docs/PROGRESS_LOG.md`：阶段 2 Storage / SQLite 已完成初版，新代码放入 `app/`。
- `docs/ARCHITECTURE.md`：SQLite repository 与有 ToolResult / ExecutionEvidence 支持的授权 Domain WRITE 是业务事实来源；event / LLM / normal 程序日志和 PlanRun state 是观测或执行材料，不是业务事实或授权来源。
- `docs/RUNTIME_CONCEPTS.md`：已补齐 Observability 和 SQLite Local Persistence 学习章节。
- `plans/RUNTIME_REFACTOR_PLAN.md`：阶段 2 交付、依赖方向和“按用途选择 SQLite / 文件日志 / JSON”的数据策略。

V0 的主要问题预计是：

- JSON 文件、日志和 runtime helper 分散在业务代码附近。
- 事实来源、执行证据和调试日志容易混在一起。
- 测试 fixture、真实用户数据和临时运行输出边界不够清晰。

阶段 2 的升级方式是重写轻量底座，而不是照搬旧存储实现。

## 3. 当前范围

初版做：

- 创建 `app/` 包结构中的 `common`、`storage`、`observability`。
- 创建 `config/default.json`，把默认数据库路径作为配置声明。
- 使用 Python 标准库 `sqlite3`，不引入 Alembic 或 ORM。
- 建立显式 schema version 和按序 migration skeleton。
- 建立 `lifeops.sqlite3` 的连接工厂和 pragma 初始化。
- 建立 repository / unit of work 的最小接口。
- 建立 run record 和后续 tool call 的基础表。
- 为 observability 预留模型边界；日志落盘由 Observability Logging 模块负责。
- 提供 test database 工厂，支持内存数据库和临时文件数据库。
- 提供 seed / reset / fixture 的边界设计，但不写业务 fixture 内容。
- 更新 `.gitignore` 或确认现有规则覆盖本地 SQLite 和用户数据。

初版不做：

- 不实现 Tasks、Wellbeing、Memory、Recovery 的完整业务 repository。
- 不迁移旧数据。
- 不实现产品 UI、Inspector CLI 或 Eval runner。
- 不实现复杂 migration 回滚。
- 不引入 ORM、后台服务、远程数据库或加密存储。
- 不把 LangGraph checkpoint 当作业务事实源。

后续版本可做：

- 为每个 domain 增加具体 repository。
- 为 Inspector 增加查询视图或 formatter。
- 为 Eval 增加 case/result repository。
- 增加导出、备份、数据清理和更严格的隐私策略。

## 4. Runtime 边界

输入：

- SQLite 数据库路径。
- migration 定义。
- repository 查询 / 写入请求。
- 需要关系查询或事务管理的运行记录。
- 测试或 eval 提供的 fixture seed 数据。

输出：

- 初始化后的 SQLite connection。
- schema version 状态。
- repository 读写结果。
- 已持久化的 run record、tool call 等关系数据。
- 可被后续 Inspector / Eval 只读查询的关系数据；event / LLM / normal 日志由文件日志读取。

依赖：

- `app/common` 可被所有模块依赖，但不能依赖业务模块。
- `app/storage` 可依赖 `app/common`，不能依赖 domain service、orchestration、policy 或 planner。
- `app/observability` 可依赖 `app/common`，不依赖 storage 或业务 service。

不负责：

- 不判断用户 intent。
- 不授权写入。
- 不执行工具。
- 不生成 plan。
- 不把 assistant final answer 文本升级为事实。
- 不替业务 domain 决定语义模型。

关键边界：

- `storage` 是持久化机制，不是业务模型层。
- `observability` 记录 runtime event、LLM interaction 和 normal 程序日志，不直接改变业务事实。
- `inspector` 未来只能读日志和业务事实的只读视图，不能通过本模块修改状态。
- `evals` 必须使用测试数据库，不能复用真实 `data/lifeops.sqlite3`。

## 5. 数据模型 / 存储

当前 SQLite schema 只保留适合关系查询的基础表。event / LLM / normal 程序日志由文件日志负责，业务表等后续 domain 模块计划再设计和实现。

当前已实现的基础表：

```text
schema_migrations
- version
- name
- applied_at

run_records
- id
- started_at
- finished_at
- status
- user_input_hash
- summary
- error_code
- created_at

tool_calls
- id
- run_id
- tool_name
- call_type
- status
- input_json
- output_json
- error_code
- created_at

```

后续 domain 模块再设计的业务表方向：

以下名称只是后续模块的候选方向，不属于阶段 2 已实现 schema。当前 `V1_INITIAL_STORAGE_SCHEMA` 仍只有 `run_records` 和 `tool_calls`；Research / Travel 或 Memory / Eval 真正施工时，必须各自新增 schema migration 和 repository 测试，不能因为本计划列出名称就视为已经落库。

```text
research_topics
research_sources
research_notes
research_briefs
trips
travel_constraints
travel_itineraries
travel_decisions
semantic_memories
eval_runs
eval_results
```

阶段 2 先不创建这些业务表。这里的判断标准是：没有清晰 service 语义前，不让 schema 反向绑死业务设计。

Migration 命名说明：

- 这里的 migration 指“数据库 schema 版本演进”，不是迁移旧 V0 数据。
- 当前没有旧数据需要迁入新 runtime，阶段 2 也不做旧数据迁移。
- 需要 migration skeleton 的原因是：以后新增表、字段或索引时，可以用可测试、可重复的方式把本地 SQLite 从 version 1 升到 version 2，而不是靠手工改库。

Migration 策略：

- `app/storage/schema.py` 保存当前 schema 片段或 migration registry。
- `app/storage/migrations.py` 负责按 `schema_migrations` 顺序执行。
- migration 初版只支持前进，不支持自动回滚。
- migration 必须幂等：重复运行不会破坏已存在数据库。
- 任何 schema 变更都需要聚焦测试覆盖。

Repository 策略：

- `app/storage/sqlite.py`：连接工厂、row factory、pragma 初始化。
- `app/storage/repositories.py`：基础 repository helper，例如执行查询、映射 row、事务内共享 connection。
- `app/storage/unit_of_work.py`：事务边界，提供 commit / rollback。
- 具体业务 repository 放在对应模块，例如 `app/domains/research/repository.py` 或 `app/domains/travel/repository.py`，不堆进 `storage/repositories.py`。

Test database 策略：

- 单元测试默认使用 `:memory:` 或临时目录 sqlite 文件。
- 需要多连接行为的测试使用临时文件数据库。
- test DB 每个测试独立创建并运行 migration。
- fixture seed 只写测试数据库。
- eval 使用专门 eval DB 或临时 DB，不读写真实用户数据。

Reset / seed / fixture 策略：

- `reset` 只允许用于测试和开发 fixture，不对真实数据库默认暴露破坏性入口。
- seed 函数应显式接收 connection / unit of work，避免隐式打开真实数据路径。
- fixture 数据放在 `data/fixtures/` 或 `tests/fixtures/` 时，需要与真实用户数据分离。
- JSON 只作为 fixture、config、sample，不作为长期业务事实源。

隐私和 gitignore 策略：

- 真实运行数据库默认：`data/lifeops.sqlite3`。
- 默认数据库路径由 `config/default.json` 的 `database.path` 声明，`storage` 不硬编码产品默认路径。
- 当前 `.gitignore` 已覆盖 `data/*.sqlite`、`data/*.sqlite3`、`data/**/*.sqlite`、`data/**/*.sqlite3`、`data/*.json`、`data/**/*.json` 和 `data/exports/`。
- 可入库：schema、migration、fixture 示例、空目录 README。
- 不入库：真实 SQLite、OAuth token、calendar cache、eval run output、用户导出数据。

## 6. 对外接口

计划暴露的最小接口：

```text
app/common/ids.py
- new_id(prefix: str) -> str

app/common/time.py
- utc_now_iso() -> str

app/common/errors.py
- AppError
- StorageError
- MigrationError

app/common/serialization.py
- to_json(data: object) -> str
- from_json(raw: str) -> object

app/common/config.py
- load_app_config(path: str | Path = DEFAULT_CONFIG_PATH) -> AppConfig
- AppConfig.database_path

app/storage/sqlite.py
- connect_sqlite(path: str | Path | None = None) -> sqlite3.Connection
- initialize_connection(conn: sqlite3.Connection) -> None

app/storage/migrations.py
- migrate(conn: sqlite3.Connection) -> MigrationReport
- get_schema_version(conn: sqlite3.Connection) -> int

app/storage/unit_of_work.py
- SqliteUnitOfWork

app/observability/events.py
- LogRuntimeEvent
- LogTraceEvent
- LogLlmInteraction

app/observability/file_logs.py
- SessionLogWriter
- EventLogWriter
- LlmLogWriter

app/observability/logger.py
- configure_application_logging(...)
```

接口原则：

- 所有写入应返回结构化结果或抛出项目内错误类型。
- 进入 SQLite 的 payload 才用 JSON 字符串入库；文件日志使用 JSONL。
- event log 不保存超大原文；只保存摘要、引用和结构化字段。
- LLM interaction 保存原始 request / response JSON，但进入 `llm.jsonl`，不进入 SQLite。
- ID 和时间由 `common` 生成，便于测试替换。

## 7. 失败模式

预期失败：

- 数据库路径不存在或不可写。
- migration 执行一半失败。
- schema version 比当前代码更新。
- JSON payload 无法序列化。
- repository 违反唯一约束或外键约束。
- 测试误连真实数据库。
- 文件日志写入失败影响主流程。
- LLM request / response 体积过大或包含敏感字段。

处理原则：

- migration 失败必须抛出 `MigrationError`，不能静默继续。
- schema version 过新时拒绝启动，提示当前代码过旧。
- repository 失败抛出 `StorageError` 或更具体错误。
- 文件日志写入失败初版可以抛错，让测试暴露问题；后续再考虑降级策略。
- test database helper 应尽量要求显式路径或显式 `:memory:`，避免默认真实路径。
- event payload 必须控制大小，避免把完整用户输入、token 或大工具输出直接落盘。
- LLM interaction 是专门的原始记录通道，可以保留原始 request-response；后续如接入真实 token / OAuth / 外部凭证，需要先增加脱敏策略。

Event 记录建议：

- `storage.migration.started`
- `storage.migration.applied`
- `storage.migration.failed`
- `storage.transaction.committed`
- `storage.transaction.rolled_back`
- `event.appended`
- `llm.interaction.appended`

这些事件先用于测试和未来 Inspector，不作为业务事实授权来源。

## 8. 测试和 Eval

最小测试：

- migration 在空数据库上可创建 schema。
- migration 重复运行幂等。
- schema version 正确记录。
- `connect_sqlite` 初始化 row factory、foreign keys 和 WAL / journal 策略。
- unit of work 成功时 commit，异常时 rollback。
- event JSONL writer 可 append / read，且按写入顺序保留 seq。
- LLM JSONL writer 可 append / read 原始 request-response。
- JSON payload 序列化失败能被明确捕获。
- test DB helper 不会创建或触碰真实 `data/lifeops.sqlite3`。

暂不做 Eval：

- 阶段 2 主要是基础设施，不需要完整 eval runner。
- 但要为后续 Eval Harness 保留 `eval_runs` / `eval_results` 的 schema 方向和测试数据库策略。

验证命令建议：

```powershell
uv run python -m unittest discover -s tests -v
```

如果阶段 2 初始施工只新增少量测试，可先运行对应测试文件，再在合并前运行最小相关测试集。

## 9. 文档更新

阶段 2 完成后应更新：

- `docs/PROGRESS_LOG.md`：记录 `app/common`、`app/storage`、`app/observability` 已存在，以及有效测试命令。
- `docs/ARCHITECTURE.md`：补充基础设施层、SQLite facts、文件日志和 observability 的当前边界。
- `docs/RUNTIME_CONCEPTS.md`：补充 `Observability` 和 `SQLite Local Persistence` 章节。
- `docs/ARCHITECTURE.md`：如果正式确认 SQLite schema / migration 策略，应更新当前架构快照。

通常不需要更新：

- `README.md`：除非入口或运行方式发生变化。
- `docs/RUNTIME_CONCEPTS.md`：只沉淀已经实现和学到的 SQLite / Observability 解释。
- `CHANGELOG.md`：除非用户明确要求记录里程碑。

## 10. 实施步骤

建议小步施工顺序：

1. [x] 创建 `app/__init__.py`、`app/common/`、`app/storage/`、`app/observability/` 的空包和最小模块文件。
2. [x] 实现 `common` 的 ID、时间、错误和 JSON 序列化 helper，并添加聚焦测试。
3. [x] 创建 `config/default.json` 和 config loader，并实现 SQLite connection factory，包含 row factory、foreign key pragma 和明确的数据库路径策略。
4. [x] 实现 `schema_migrations` 和 migration runner，只创建最小基础 storage 表。
5. [x] 实现 `SqliteUnitOfWork`，覆盖 commit / rollback 测试。
6. [x] 实现 `LogRuntimeEvent` / `LogTraceEvent` / `LogLlmInteraction` 类型。
7. [x] 通过 Observability Logging 模块实现 event / LLM / normal 文件日志。
8. [x] 增加 test database helper，确保测试默认不触碰真实 `data/lifeops.sqlite3`。
9. [x] 检查 `.gitignore` 是否覆盖阶段 2 产生的真实数据路径；如不足，做最小补充。
10. [x] 更新 `docs/PROGRESS_LOG.md`、`docs/ARCHITECTURE.md` 和 `docs/RUNTIME_CONCEPTS.md`。
11. [x] 如 schema / migration 策略已稳定，同步 `docs/ARCHITECTURE.md`。
12. [x] 运行最小相关测试和 compile 检查。

## Grill-me 检查清单

- 为什么现在先做 storage / common / observability，而不是直接做 Task domain？
  - 因为总计划要求先基础设施再业务 domain，避免后续每个 domain 自带一套 JSON、日志和 helper。

- 为什么不用 ORM 或 Alembic？
  - 当前目标是小而可解释的本地 runtime。`sqlite3` 标准库足够覆盖学习、测试和面试讲解，ORM 会过早增加平台复杂度。

- 什么是事实来源，什么不是？
  - SQLite repository 与有 ToolResult / ExecutionEvidence 支持的授权 Domain WRITE 是业务事实来源。event / LLM / normal log 和 PlanRun state 是观测或执行材料，不是业务事实或授权来源。assistant 文本、Planner 输出、Recovery Context、LangGraph checkpoint 和 conversation summary 也不是。

- trace event 会不会变成又一个日志垃圾桶？
  - 初版必须限制 payload 大小和结构，只记录 run_id、seq、event_type、摘要、引用和必要结构字段。

- 原始 LLM 对话放在哪里？
  - 后续放在独立的 `llm.jsonl` 中，和 `events.jsonl` 分开。event log 用来解释 runtime 路径，LLM log 用来人工查看最原始 request-response。

- migration 是不是旧数据迁移？
  - 不是。这里的 migration 是 SQLite schema 版本演进。当前没有旧数据需要迁入，阶段 2 不做 V0 数据迁移。

- test / eval 如何避免污染真实数据？
  - 所有测试通过显式 test DB factory 创建独立数据库；eval 也使用 fixture/test DB，不复用 `data/lifeops.sqlite3`。

- 哪些表现在建，哪些等 domain 计划？
  - 当前只保留 `schema_migrations`、`run_records`、`tool_calls`。业务语义强的表等 Tasks、Wellbeing、Memory、Eval 模块计划确认后再实现。
