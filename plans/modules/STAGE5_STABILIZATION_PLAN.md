# 阶段 5 稳定化模块计划

## 当前状态

阶段 0-5 已实现，当前路线图下一施工模块是阶段 6 ReAct Executor。本计划在进入阶段 6 前，对现有 Runtime、Orchestration、Skill System、Tool System、Research / Personal Knowledge 与 Travel Domain 做一次有限、证据驱动的稳定化。

当前代码是冻结候选，不直接视为已经冻结。稳定化允许在阶段 6 前集中修正公共契约、模块边界、字段、日志和测试；完成后，阶段 6-9 默认只能通过兼容扩展接入，不应反向频繁修改阶段 5 核心设计。

本计划只定义审计和后续实施顺序，不在计划编写步骤中修改生产代码、测试或其他现有文档。历史文档中的测试数量只作为已记录事实，不能替代稳定化完成时对当前工作树的重新验证。

### 步骤 1 基线（2026-07-13）

本节只记录稳定化开始时的可复现事实，不代表契约已经冻结，也不构成 Stage 6 放行结论。

#### 工作树与文档声明

- Git 分支：`russell/refactor-v2-begin`；基线提交：`6bbda89`。
- 工作树不是 clean：`29` 个已修改路径、`27` 个未跟踪路径，共 `56` 个变更路径。它们是稳定化开始前已有的阶段 5 工作，不在步骤 1 中清理、回退或重写。
- 当前文档一致声明“阶段 0-5 已完成，下一步是阶段 6 ReAct Executor”；来源为 `README.md`、`docs/PROGRESS_LOG.md`、`docs/ARCHITECTURE.md` 与 `plans/RUNTIME_REFACTOR_PLAN.md`。该声明是待审计输入，不等于本计划已经给出 `go`。
- `docs/PROGRESS_LOG.md` 记录的“全量 unittest 216 项通过”是历史验证事实；当前工作树尚未在本步骤重新运行全量回归，因此状态为**待复验**。

#### Runtime 与迁移版本

- Python：`3.13.14`；项目约束：`requires-python >= 3.13`。
- uv：`0.11.21`。
- 当前 lockfile / 环境关键版本：`langgraph 1.2.9`、`openai 2.41.1`、`pydantic 2.13.4`。
- `app.storage.schema.MIGRATIONS` 当前包含版本 `1-8`，最新 migration 为 `8`。

#### Tool catalog

catalog 由当前 composition root 使用 `:memory:` SQLite 和项目 Skill root 构建，并通过 `ToolRegistry.list_definitions()` 按名称稳定排序读取；共 `22` 个 Tool：

| Tool | effect | risk | Skill |
| --- | --- | --- | --- |
| `research.build_brief_draft` | `read` | `low` | `research` |
| `research.create_note` | `write` | `medium` | `research` |
| `research.fetch_briefing_source` | `external_read` | `low` | `research` |
| `research.fetch_source` | `external_read` | `low` | `research` |
| `research.parse_items` | `read` | `low` | `research` |
| `research.rank_items` | `read` | `low` | `research` |
| `research.save_brief` | `write` | `medium` | `research` |
| `research.save_source` | `write` | `medium` | `research` |
| `research.search_knowledge` | `read` | `low` | `research` |
| `travel.archive_trip` | `write` | `medium` | `travel` |
| `travel.build_itinerary_draft` | `read` | `low` | `travel` |
| `travel.check_calendar_availability` | `external_read` | `low` | `travel` |
| `travel.compare_options` | `read` | `low` | `travel` |
| `travel.create_trip` | `write` | `medium` | `travel` |
| `travel.get_trip` | `read` | `low` | `travel` |
| `travel.get_weather` | `external_read` | `low` | `travel` |
| `travel.list_trips` | `read` | `low` | `travel` |
| `travel.save_itinerary` | `write` | `medium` | `travel` |
| `travel.search_lodging` | `external_read` | `low` | `travel` |
| `travel.search_places` | `external_read` | `low` | `travel` |
| `travel.search_transport` | `external_read` | `low` | `travel` |
| `travel.update_trip_constraints` | `write` | `medium` | `travel` |

#### 测试清单与可复现命令

- 当前 `tests/test_*.py` 共 `46` 个模块；静态盘点共有 `216` 个 `test_*` 方法。该数字只表示当前清单规模，不表示它们已经在本工作树通过。
- Runtime / Orchestration 聚焦：`uv run python -m unittest tests.test_runtime_service tests.test_orchestration_state tests.test_orchestration_nodes tests.test_orchestration_graph tests.test_orchestration_skills -v`。
- Skill / Tool 聚焦：`uv run python -m unittest discover -s tests -p "test_skill*.py" -v` 与 `uv run python -m unittest discover -s tests -p "test_tool*.py" -v`。
- Research 聚焦：`uv run python -m unittest discover -s tests -p "test_research*.py" -v`。
- Travel 聚焦：`uv run python -m unittest discover -s tests -p "test_travel*.py" -v`。
- Storage / observability 聚焦：`uv run python -m unittest tests.test_storage_sqlite tests.test_storage_migrations tests.test_storage_unit_of_work tests.test_observability_file_logs -v`。
- compiled Graph E2E：`uv run python -m unittest tests.test_stage5_e2e -v`。
- 统一离线回归：`uv run python -m unittest discover -s tests -v`。
- 本机复现前设置：`$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'`，避免全局 uv cache 权限影响测试结果。

步骤 1 已完成：以上基线只供步骤 2-5 审计对照；本步骤未修改生产行为、测试或架构边界，也未运行全量测试。

## 1. 目标

- 让阶段 5 成为阶段 6 ReAct Executor、阶段 7 Plan-and-Execute Planner、阶段 8 Context / Memory、阶段 9 Recovery / Feedback 的稳定基础。
- 对齐代码、测试、`docs/ARCHITECTURE.md`、`docs/PROGRESS_LOG.md`、`plans/RUNTIME_REFACTOR_PLAN.md`、共享 Domain 标准和各模块计划。
- 确认模块依赖方向、状态所有权和生命周期清晰，不让后续 Executor / Planner 读取 Domain、Tool、Skill 或 repository 内部实现。
- 审计公共接口、Tool schema、Domain read contracts、Model 字段、错误、evidence、事件和日志字段，删除无消费者、低收益或语义重复的内容。
- 只提取有共同语义、共同不变量和真实跨模块消费者的公共抽象或纯 utilities；允许少量重复，避免错误抽象。
- 把已完成的 `*_PLAN.md` 整理成最终设计说明书，使其能作为后续开发和面试讲解的可信知识底座。
- 建立 deterministic、离线、分层且可统一运行的契约冻结测试，并给出阶段 6 `go / no-go` 结论。

本计划的成功不是“文件更少”或“代码更像某个框架”，而是后续阶段可以在不破坏现有模块的前提下接入。

## 2. 当前 V0 参考

本次不迁移旧模块，也不解释历史行为，默认不读取 `legacy_v0/`。

只有现行模块计划明确声称继承某项 V0 行为，而当前代码与该声明无法对齐时，才按最小范围读取对应 V0 文件。V0 不能成为恢复旧聚合 Agent、超大工具模块、业务逻辑与 runtime glue 混放或多套执行入口的理由。

## 3. 当前范围

### 3.1 本次做

- 对阶段 0-4 做横向边界审计：Runtime 入口、Intent / Policy、LangGraph Orchestration、storage、observability、状态所有权、错误与阶段 6 接入点。
- 对阶段 5 做深度审计：Skill、Tool、Guardrail、Gateway、Research、Travel、共享 Domain contracts、KnowledgeReference、bootstrap、compiled Graph 和测试。
- 建立阶段 6-9 消费者兼容矩阵，逐项证明消费者只依赖稳定公共契约。
- 盘点公共类型、函数、service、Protocol、Tool 名称与 JSON schema，识别重复、泄漏内部实现或语义不稳定的接口。
- 审计 request-local service / state 生命周期，重点验证一个 ReAct run 中多次 Tool 调用是否共享正确的 Research / Travel 临时状态，run 之间是否隔离。
- 审计 Model 字段和 SQLite 映射，区分业务事实、request-local execution state、公共契约字段与调试字段。
- 审计 `events.jsonl`、`llm.jsonl`、`application.log` 的职责和字段收益，保留语义事件，删除机械噪声和重复内容。
- 审计大文件的职责内聚性，当前优先检查 `app/domains/travel/tools.py`、`app/domains/research/tools.py`、两个 Domain 的 `models.py` / service / repository，以及 `app/orchestration/nodes/`；文件长度只触发检查，不自动触发拆分。
- 整理已完成模块计划中的失效中间方案、旧接口和重复流水账，保留最终边界、关键理由、失败模式、验证证据和明确延后项。
- 增加契约冻结、依赖方向、负向边界、模块集成、compiled Graph 和全量回归门禁。

### 3.2 本次不做

- 不实现 ReAct loop、Planner、Context assembly、长期 Memory、Recovery 或 Feedback。
- 不为阶段 10 以后 MCP、Inspector、Eval、DAG 或未知新 Domain 提前冻结具体接口；只检查当前设计没有主动封死这些扩展方向。
- 不大规模重写现有模块，不因文件较长、风格偏好或少量重复而重构。
- 不引入万能 Domain 基类、宽泛 `common.py` / `helpers.py`、Service Locator、插件平台或新的 Agent 框架。
- 不把业务校验、业务模型或 Domain-specific output serializer 提取为伪公共 utility。
- 不默认删除 SQLite 历史列或重建用户数据库；无害兼容列可以保留。
- 不把真实 LLM 或真实网络 E2E 设为强制门禁。
- 不顺手整理与阶段 6-9 接入无关的内部实现。

## 4. Runtime 与模块边界

### 4.1 目标依赖方向

```text
RuntimeService / bootstrap
-> Orchestration / future Executor / future Planner
-> Skill candidate + Policy authorization
-> ToolRegistry / AllowedToolSet / Guardrails / ToolGateway
-> Domain Tool handlers
-> Domain service
-> Domain repository or typed external Port
-> SQLite or fixture / future adapter
```

- Domain 不依赖 LangGraph、Orchestration、Executor、Planner、Context assembler、Memory store、Recovery、Feedback 或具体 provider SDK。
- Tool System 不 import Research / Travel 业务类型；Domain `tools.py` 负责把业务类型转换为 LifeOps Tool contract。
- Skill 只提供能力说明和 Tool 候选，不授权、不执行、不复制 Guardrail。
- Policy 只授权 effect，不枚举业务 Tool；`AllowedToolSet` 是 Skill candidate、Policy effect 和 Registry 的交集。
- bootstrap 是 composition root，可以知道具体实现并负责装配，但运行期控制模块不能通过 bootstrap 泄漏 Domain 内部对象。
- repository 只拥有持久化与查询；service 拥有业务规则和 request-local workflow；Tool handler 只做参数/结果适配，不复制业务规则。
- observability 通过 `TraceSink` 接入，不要求业务模块变成 LangGraph node，也不成为业务事实来源。

### 4.2 阶段 6-9 消费者兼容矩阵

| 消费者 | 允许依赖 | 禁止依赖 | 本次证明方式 |
|---|---|---|---|
| 阶段 6 ReAct Executor | filtered Tool catalog、`ToolCall`、`ToolResult`、`ToolError`、`ExecutionEvidence`、Gateway、Observation、confirmation、loop-local service 生命周期 | Domain repository、Domain 私有 cache、Tool handler internals、模型 Thought 持久化 | fake ReAct 多步 consumer、跨 Domain Tool 序列、WRITE confirmation、run 隔离测试 |
| 阶段 7 Planner | Tool contract、`DomainPlanningReadModel`、typed planning snapshot、Executor 入口 | SQL、repository internals、request-local candidate/draft、直接执行或授权 | Research / Travel 参数化 fake Planner contract tests |
| 阶段 8 Context | `DomainContextProvider`、typed candidate、provenance、budget estimate | repository internals、最终 prompt assembly 写回 Domain | budget、scope、稳定排序、无副作用 contract tests |
| 阶段 8 Memory | `DomainMemoryCandidateProvider`、显式保存事实形成的 candidate | 自动写 Memory、把 Source / observation / itinerary 推断成偏好 | candidate 来源、scope、limit 和无写入 contract tests |
| 阶段 9 Recovery / Feedback | stop reason、结构化错误、Observation、ToolResult、evidence、事实状态和窄 hook | assistant 文本作为成功事实、自动重放 WRITE / external lookup、checkpoint 回滚副作用 | failure matrix、partial success、幂等与不自动重放测试 |

矩阵中的接口只有通过对应 fake consumer 和负向测试后才能标记冻结。当前代码没有的阶段 6-9 类型只能在各阶段模块计划中定义；本次不以猜测增加空洞抽象。

### 4.3 状态与生命周期审计

必须为每类状态记录 owner、创建时机、存活范围、可持久化性、消费者和清理方式：

- `RuntimeRequest` / `RuntimeResult`：单次 runtime run 的稳定输入输出。
- `GraphState`：单次 compiled graph invocation 的最小编排状态。
- Skill selection、prompt contributions、`AllowedToolSet`：request-local runtime state。
- Research document / item set / observation / brief draft：request-local Domain workflow state。
- Travel external observation / candidate / comparison / itinerary draft：request-local Domain workflow state。
- Domain repository models：长期业务事实。
- 未来 ReAct execution state、Context、PlanRun / PlanStep、Memory 和 Recovery context：不得提前塞入现有 Domain fact 或 GraphState。

重点检查 `app/runtime/bootstrap.py` 当前通过 `tool_runtime_factory` 创建 Domain services 和 Registry 的频率，明确“一次 run 一个 service 集合”或其他最终生命周期，并用多 Tool fake loop 与跨 run 隔离测试锁定。若阶段 6 需要不同生命周期，应通过窄 factory / execution-scope contract 调整 composition root，而不是让 Executor 直接构造或访问 Domain service。

### 4.4 公共抽象与 utility 提取规则

候选内容只有同时满足以下条件才提取：

1. 至少两个模块真实使用；
2. 语义、不变量、错误与演进方向相同；
3. 能指出阶段 6-9 的实际消费者或当前共同调用方；
4. 提取后依赖方向更清晰，不引入双向依赖；
5. 有公共契约测试，而不只是减少行数。

业务模型、业务 schema、业务校验、Domain output serializer 和 provider-specific 转换默认留在所属模块。无业务含义、确定性、无副作用且不会造成 Domain 耦合的纯函数才适合作为通用 utility。相似但可能独立演进的逻辑允许保留重复。

## 5. 数据模型 / 存储

### 5.1 字段审计方法

对 Runtime、Intent、Policy、GraphState、Skill、Tool、Guardrail、observability、Research 和 Travel model 的每个字段建立审计表，至少记录：

- 字段所属模型和状态类别；
- 写入者与读取者；
- 是否进入 Tool schema、event、SQLite、JSONL 或最终 RuntimeResult；
- 表达业务事实、执行状态、授权、evidence、provenance 还是调试信息；
- 阶段 6-9 是否存在明确消费者；
- 是否可以从其他稳定字段可靠推导；
- 保留、重命名、移除、降为内部字段或历史兼容列的结论；
- 对应测试和文档位置。

优先审计：

- `RuntimeSession.metadata`、`RuntimeRequest.metadata`、`RuntimeResult.intent/policy/tool_result/trace_summary` 的真实消费者和重复表达；
- `GraphState.graph_path/trace_summary/error_stage` 与 event / final payload 是否重复；
- `ExecutionEvidence.reference/attributes`、`GuardrailDecision.reason/sanitized_args_summary/evidence_requirements` 是否有稳定语义和消费者；
- Research `provenance`、`source_key`、多个时间字段及 planning/context/memory candidate 字段；
- Travel observation/candidate/comparison/draft/itinerary 中重复的 provenance、observation IDs、summary、version 和 optional compatibility 字段；
- Tool output schema 是否暴露了只服务当前 handler 或测试、却不帮助 ReAct observe → next action 的字段。

不能仅凭“当前没有 grep 到读取者”删除长期事实字段；还要检查 migration、repository、fixtures、Tool schema、日志和计划承诺。

### 5.2 删除与 migration 策略

- request-local、无消费者且无契约价值的字段可以直接删除，并同步 schema、serializer 和测试。
- Tool input/output 或公共模型字段属于冻结候选；删除前必须完成消费者矩阵和兼容性判断。
- 无害的 SQLite 旧列可以停止映射和新写入，但暂时保留物理列，并在计划/架构中说明兼容状态。
- 只有字段语义错误、安全风险、持续污染新数据或阻碍不变量时，才实施显式 SQLite migration。
- migration 必须验证旧 schema 升级、数据保留、引用完整性、transaction 和幂等，不允许为代码整洁无理由重建数据库。
- request-local observation、candidate、comparison、draft、GraphState 和未来 ReAct Thought 不得写入 Domain 业务表。

## 6. 对外接口与冻结标准

### 6.1 冻结候选

- `RuntimeRequest` / `RuntimeResult` 的阶段 6 入口和结果语义。
- `SkillService` 的 selection、lazy loading 与 prompt contribution 输出边界。
- `ToolDefinition`、`AllowedToolSet`、`ToolCall`、`ToolResult`、`ToolError`、`ExecutionEvidence`。
- `ToolRegistry` catalog、authorization、pre/post Guardrails 和 `ToolGateway.execute(...)`。
- Tool 名称、effect、risk、input/output JSON schema、错误码、WRITE evidence 与 confirmation 语义。
- `DomainPlanningReadModel.get_planning_snapshot(scope_id)`。
- `DomainContextProvider.query_context_candidates(query, budget_hint, scope_id=None)`。
- `DomainMemoryCandidateProvider.query_memory_candidates(query, limit, scope_id=None)`。
- typed external Port 的 success/no-results/partial-failure/failed、retryable、expiry 和 provenance 语义。
- `KnowledgeReference` / resolver 的跨 Domain 只读引用边界。
- `TraceSink` 与稳定语义事件的名称、最小 payload 和敏感信息边界。

Domain service 公共方法不默认全部冻结。只有被 Tool adapter、read service 或明确外部消费者使用的方法才进入公共表面；repository、helper 和文件组织属于内部实现。

### 6.2 冻结后的变更规则

- 现有调用方默认不需要修改，已有字段不得静默改义。
- 优先新增独立能力、adapter 或可选字段；新增字段必须有明确消费者、默认语义和测试。
- 删除、重命名、必填化、错误码改义、effect/risk 改变和 scope 语义改变都视为破坏性变更。
- 破坏性变更必须有真实缺陷证据、迁移策略、计划更新和用户确认，不能在后续模块施工中顺手完成。
- compatibility tests 是阶段 6-9 的持续门禁；更新契约快照必须伴随设计说明，不能只为让测试通过而覆盖期望值。

## 7. 失败模式

- 文档宣称阶段 5 完成，但代码、Tool catalog、schema、migration 或测试仍是旧方案。
- 为 ReAct 接入把 loop state、Thought、Context 或 Recovery 数据塞进 Domain model / GraphState。
- Executor 直接读取 Domain service cache、repository 或 SQL，导致 Domain 与执行器耦合。
- request-local service 生命周期过短，ReAct 第二次 Tool 调用无法消费第一次 observation/draft；或生命周期过长导致跨 run 污染。
- Research / Travel 对同一共享 Protocol 使用不同 scope、budget、limit、错误或空结果语义。
- Tool output 只适合当前单步测试，缺少稳定 ID、状态、错误或 evidence，ReAct 无法决定下一步。
- 抽取万能 helper/base class，把不同业务不变量错误合并。
- 删除长期字段却未处理历史 migration、fixture 或引用完整性。
- 事件、`trace_summary`、graph path 和 application log 重复记录同一信息，增加存储和认知噪声。
- 日志写入原始用户输入、Tool arguments/output、raw HTML、secret、provider response 或内部异常文本。
- 测试只覆盖 happy path 或具体实现，不覆盖公共契约、负向边界、run 隔离和 partial failure。
- 真实 provider 波动被误判为 runtime 回归，或离线测试意外依赖网络/API key。
- 为整理文档把已完成计划改成历史流水账，仍保留失效方案与现行契约并列。

## 8. Observability 整理

### 8.1 三类日志职责

- `events.jsonl`：稳定、结构化、低体积的 runtime 语义事件，用于解释路径、失败层级、授权、Tool execution 和阶段 9 Recovery 的事实输入。
- `llm.jsonl`：原始 LLM request/response 调试记录；不作为业务事实、授权或成功证据。
- `application.log`：本地诊断和异常排查；不复制完整稳定事件流。

### 8.2 事件与字段保留标准

每个 event / 字段必须至少支持调试、审计、安全、恢复、产品状态或 Eval 中的一项明确用途。优先保留 run、request、intent、policy、route、Skill selection/load、Tool call、Guardrail decision、confirmation 和最终结果等真实边界。

删除候选包括：

- 单纯函数或文件读取 started/completed；
- LangGraph node 机械生命周期；
- 可由 event sequence 或 final result 稳定推导的重复 summary；
- 没有消费者的 reason 文本、重复 ID、默认值或大 payload；
- application log 与 event JSONL 的逐条镜像。

不能删除阶段 9 恢复所需的 stop reason、结构化 error code、Tool identity、evidence reference/count 和副作用成功状态。是否保留 `graph_path`、`trace_summary` 及其字段位置必须通过消费者审计决定，不能仅因重复外观删除。

### 8.3 验证

- 建立稳定事件名和最小 payload contract tests。
- 验证敏感字段、原始 Tool arguments/output、raw HTML 和内部异常不会进入 event payload。
- 验证 application logger 不重复添加 handler，测试不污染真实日志目录。
- 验证同一 run 的 seq、run/session/turn identity 和完成/失败事件闭合。
- 明确哪些 LLM 失败只进入 `llm.jsonl`，哪些需要同步一个紧凑 runtime failure event。

## 9. 测试和 Eval

### 9.1 强制门禁

所有强制门禁必须 deterministic、离线运行，不依赖 API key、真实网络、系统时间波动或模型随机输出。测试使用 `:memory:` 或临时 SQLite，不读写真实 `data/lifeops.sqlite3` 和真实 session logs。

测试分层：

1. Model / pure function：字段不变量、状态转换、schema validation、parse/dedupe/rank、ID/provenance 防伪。
2. 公共契约：Tool models、Gateway、Guardrails、Domain Protocol、typed Port、KnowledgeReference、event payload。
3. Domain integration：migration、repository、transaction、幂等、request-local workflow、长期事实、失败 fixture。
4. Runtime integration：Skill candidate、Policy effect、AllowedToolSet、Tool selection、Gateway、Domain handler、RuntimeResult。
5. compiled Graph E2E：Research / Travel READ，catalog 外 Tool 拒绝，WRITE confirmation/evidence，错误路径和 SQLite 零误写。
6. 阶段 6-9 fake consumers：多步 ReAct、Planner snapshot、Context budget、Memory candidate、Recovery partial success。
7. compatibility / architecture：稳定 Tool schema、错误码、事件名、import 依赖方向、公共接口签名和 run 生命周期。
8. migration compatibility：旧 schema 升级、历史兼容列、引用完整性和数据保留。
9. 全量 unittest 回归。

测试可以通过一个统一命令运行，但不能合并成无法定位责任的大测试文件。聚焦测试仍需能按模块独立运行。

### 9.2 契约冻结测试

- 精确断言 Tool name、effect、risk、skill binding、input/output schema 和 catalog visibility。
- 参数化验证 Research / Travel 对三个共享 Domain Protocol 的签名和共同语义。
- 验证 Tool success/failure、retryable error、WRITE evidence、confirmation 和 partial failure 的稳定关系。
- 验证 Domain 不 import LangGraph、Orchestration、Executor、Planner 或 provider SDK，Tool core 不 import 具体 Domain。
- 验证 request-local observation/candidate/draft 不落库、不跨 run 泄漏，长期事实不能由模型伪造。
- 验证 Tool output 足以支持 fake ReAct observe → next action，并且不要求读取 service internals。
- 验证事件契约只包含允许字段。

若采用快照文件，快照必须可读、范围小且按公共契约分组；禁止用巨大 snapshot 隐藏无关变更。

### 9.3 非强制真实集成验证

真实 LLM skill/tool selection 与真实 Research HTTP adapter 放入独立的手动或可选 E2E。结果必须区分 provider/network/额度/模型质量问题与 LifeOps runtime contract 回归，不作为阶段 6 强制放行条件。

### 9.4 Stage 6 放行条件

只有同时满足以下条件才可 `go`：

- 审计表中的 blocking 问题全部关闭；非 blocking 问题有明确 owner 和延后理由。
- 阶段 6-9 消费者矩阵每一行有 contract 或 fake consumer 证据。
- 公共契约完成最后一次集中调整并由 compatibility tests 冻结。
- 模块依赖方向和 request-local 生命周期验证通过。
- Model / 日志低价值字段审计完成，保留项均有明确语义。
- 已完成模块计划整理为最终设计说明书，架构/进度/总计划与代码一致。
- 所有离线聚焦测试、compiled Graph E2E 和全量 unittest 在当前工作树通过。
- 没有测试写入真实用户数据库或真实日志目录。
- 最终稳定化报告给出明确 `go`，并记录实际命令、通过数量、未运行项和剩余风险。

任一公共契约仍需依赖阶段 6 实现才能判断、关键测试不稳定、文档仍互相冲突或跨 run 状态边界未证明时，结论必须为 `no-go`，不能因路线图进度而放行。

## 10. 文档更新

稳定化实施期间按职责更新：

- `plans/modules/STAGE5_STABILIZATION_PLAN.md`：审计结论、批准的调整项、步骤状态和最终冻结范围。
- 已完成 `plans/modules/*_PLAN.md`：整理为最终设计说明书，删除失效中间方案，保留最终契约、关键取舍、失败模式和验证证据。
- `plans/DOMAIN_CONTRACT_STANDARD.md`：只在共享 Domain 标准确实改变时更新。
- `plans/RUNTIME_REFACTOR_PLAN.md`：更新阶段 5 稳定化状态与阶段 6 gate，不记录逐文件施工细节。
- `docs/ARCHITECTURE.md`：覆盖为当前最终架构快照、依赖方向、状态所有权和稳定接口。
- `docs/PROGRESS_LOG.md`：只记录已经完成、验证和学到的稳定化事实。
- `docs/RUNTIME_CONCEPTS.md`：只沉淀本次出现的可复用 runtime / interface stability / observability 面试知识点。
- `README.md`：只有 Stage 6 gate 或当前阅读路径实际改变时更新。

本计划主要整理仓库已有概念，不需要在计划创建时新增外部学习链接。若后续实施发现必须引入新的 compatibility、schema evolution 或 architecture test 技术，再先确认学习主题，并按仓库规则把官方/权威链接写入 `docs/AGENT_LEARNING_LINKS.md`。

文档对齐规则：

- 代码和可执行测试是行为证据。
- `docs/ARCHITECTURE.md` 是当前架构事实快照。
- 完成后的模块计划是最终设计、边界和理由说明，不保留完整施工流水账。
- `docs/PROGRESS_LOG.md` 只记录历史推进事实。
- 文档冲突不能靠选取有利版本解决，必须回到代码、测试和当前用户确认的范围判定。

## 11. 实施步骤

每一步只做一个小范围变更。步骤 1-5 是审计与冻结设计；步骤 6 以后才能修改行为。发现问题不等于立即重构，必须先分类和获得计划内结论。

1. **建立当前基线。** 记录工作树状态、当前文档完成声明、Python/runtime 版本、迁移版本、Tool catalog、测试清单与可复现测试命令；历史“216 项通过”等数字只标为待复验。
2. **建立文档—代码—测试对照表。** 按 Runtime、Orchestration、Skill、Tool、Research、Travel、storage、observability 列出计划承诺、代码入口、公共接口、测试证据和漂移项；输出 blocking / non-blocking / documentation-only 分类。
3. **完成阶段 0-4 横向边界审计。** 检查 RuntimeService、Intent、Policy、GraphState、composition root、storage transaction、TraceSink 和三类日志；只深挖会影响阶段 6-9 的问题。
4. **完成阶段 5 深度模块审计。** 检查 Skill → Policy → AllowedToolSet → Gateway → Domain 的真实依赖和错误路径；检查 Research / Travel 的 service 生命周期、request-local state、repository 边界、Port/adapter、read models、KnowledgeReference 与 compiled Graph 接入。
5. **完成字段、日志和公共表面审计。** 逐字段记录写入者/读取者/状态类别/消费者/保留结论；形成稳定接口清单、删除候选、历史兼容列、事件清单和日志去重结论。此步结束后向用户提交最终调整清单和 `go / adjust / defer` 建议，再进入代码修改。
6. **先冻结目标契约。** 根据已批准审计结论，先补充或更新公共契约测试、消费者 contract tests 和依赖方向测试，使预期边界可执行；当前实现可以暂时失败，但失败必须对应已批准调整项。
7. **收口 Runtime / Tool / Orchestration 接缝。** 以最小 patch 调整 composition root、execution scope、RuntimeResult/GraphState、Tool models、Gateway/Guardrail 或事件边界；禁止在本步修改 Domain 业务能力。
8. **收口共享 Domain contract。** 统一三个 read Protocol、KnowledgeReference、typed Port 和错误/partial failure/evidence 语义；只有存在两个真实消费者且满足提取规则时才增加公共抽象或 utility。
9. **整理 Research Domain。** 仅处理审计确认的字段、职责混放、Tool adapter、service/repository 边界、request-local state、schema 和测试问题；保持现有业务能力，不顺手扩展功能。
10. **整理 Travel Domain。** 使用与 Research 相同的判定标准处理已批准问题；重点检查大 model/tool 文件的职责是否真实混杂、candidate → comparison → draft → saved itinerary 链路和幂等/evidence，不以文件长度作为拆分理由。
11. **整理 observability。** 删除批准的低收益事件/字段/普通日志，补齐阶段 9 所需的最小 stop/error/evidence 信息，验证三种日志不重复、不泄露敏感内容。
12. **整理已完成计划与架构文档。** 把 Skill、Tool、Research、Travel 等已完成模块计划改为最终设计说明书；同步 ARCHITECTURE、总计划和进度日志，删除失效接口描述和历史测试数字歧义。
13. **运行分层验证。** 依次运行 Model/pure function、契约、Domain、Runtime、compiled Graph、fake consumer、migration 和 architecture tests；失败时只修改对应层，不通过放宽断言隐藏问题。
14. **运行统一离线回归。** 使用仓库统一 unittest 命令和本地 `UV_CACHE_DIR`，确认测试不访问真实网络、真实数据库和真实日志目录；记录实际数量、时长与失败分类。
15. **形成冻结基线和 Stage 6 决策。** 输出最终稳定接口清单、允许的扩展方式、兼容性规则、剩余非阻塞债务和明确 `go / no-go`。只有 `go` 后才创建并确认 `plans/modules/EXECUTOR_PLAN.md`。

## 12. 变更控制

- 每个实施步骤开始前重新读取本计划对应步骤，只做该步骤。
- 每个代码调整必须关联一个审计发现、一个边界目标和至少一个聚焦测试。
- 任何超出本计划范围的新抽象、依赖或行为变更必须先回到计划确认。
- 若审计证明现有结构已满足目标，应记录“无需修改”及证据，不制造重构工作。
- 稳定化完成前不把阶段 6 标记为进行中；完成后不因后续开发便利而静默修改冻结契约。
