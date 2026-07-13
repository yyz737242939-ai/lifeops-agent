# 阶段 5 稳定化模块计划

## 当前状态

阶段 0-5 已实现，阶段 5 稳定化已于 2026-07-13 完成并给出 Stage 6 `go`。当前路线图下一施工动作是创建并确认阶段 6 ReAct Executor 模块计划。本计划记录进入阶段 6 前对 Runtime、Orchestration、Skill System、Tool System、Research / Personal Knowledge 与 Travel Domain 完成的有限、证据驱动稳定化。

当前代码与步骤 15 列出的公共表面是阶段 5 冻结基线。阶段 6-9 默认只能通过兼容扩展接入，不应反向频繁修改阶段 5 核心设计。

本计划同时保留审计基线、批准的实施顺序和最终冻结报告。历史文档中的测试数量只作为已记录事实；当前冻结证据以步骤 13-15 对当前工作树的重新验证为准。

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

### 步骤 2 文档—代码—测试对照（2026-07-13）

本节建立模块级索引并识别漂移，不替代步骤 3-5 的边界、生命周期和逐字段深审。测试证据表示仓库中存在对应测试，不表示本轮已经重新执行通过。

| 模块 | 计划 / 架构承诺 | 当前代码入口与公共接口 | 当前测试证据 | 步骤 2 结论 |
| --- | --- | --- | --- | --- |
| Runtime | `RUNTIME_CORE_PLAN.md`、`INTENT_POLICY_PLAN.md` 与 `ARCHITECTURE.md`：`RuntimeService` 是单次 run 的唯一入口，负责 transaction、run record、event 和结构化结果 | `app/runtime/service.py`：`RuntimeService.handle(...)`；`app/runtime/models.py`：`RuntimeRequest` / `RuntimeSession` / `RuntimeResult`；`app/runtime/run_store.py` | `test_runtime_service.py`、`test_intent_service.py`、`test_policy_service.py` | 主入口与文档基本对齐；结果字段、metadata、trace 重复性留到步骤 3/5 |
| Orchestration | `LANGGRAPH_ORCHESTRATION_PLAN.md` 与 `ARCHITECTURE.md`：compiled graph 只编排 Intent → Policy → Skill → Direct Executor，不拥有业务事实、安全或持久化 | `app/orchestration/graph.py`：`build_runtime_graph(...)` / `RuntimeOrchestrator` / `OrchestrationContext`；`state.py`：`GraphState`；`nodes/` | `test_orchestration_state.py`、`test_orchestration_nodes.py`、`test_orchestration_graph.py`、`test_orchestration_skills.py`、`test_stage5_e2e.py` | 单 Tool graph 与文档对齐；未来多 Tool execution scope 尚未冻结，见 `B-01` |
| Skill | `SKILL_SYSTEM_PLAN.md`：原生 discovery、全量 metadata selection、lazy body/reference、prompt contribution；Skill 不授权 | `app/skills/loader.py`、`registry.py`、`selector.py`、`service.py`、`references.py`、`prompt_assembler.py`；公共模型在 `models.py` | `test_skill_models.py`、`test_skill_loader.py`、`test_skill_registry.py`、`test_skill_selector.py`、`test_skill_content_loading.py`、`test_skill_prompt_assembler.py`、`test_skill_bootstrap.py`、`test_skill_eval_fixtures.py` | 行为基本对齐；已完成计划仍有 skeleton / planned workflow 历史措辞，见 `D-01` |
| Tool | `TOOL_SYSTEM_PLAN.md`：definition/handler 分离，Skill candidate 与 Policy effect 求交，统一 pre/post Guardrail 和 Gateway，WRITE confirmation/evidence，模型最多选一个 Tool | `app/tools/models.py`、`registry.py`、`authorization.py`、`guardrails.py`、`gateway.py`、`calling.py`、`runtime.py`；核心入口为 `ToolGateway.execute(...)` | `test_tool_models.py`、`test_tool_registry.py`、`test_tool_authorization.py`、`test_tool_guardrails.py`、`test_tool_gateway.py`、`test_tool_calling.py` | 当前 Direct Executor 闭环对齐；公共 schema / 错误码 / event payload 尚缺统一 compatibility 门禁，见 `B-02` |
| Research | `RESEARCH_KNOWLEDGE_DOMAIN_PLAN.md`：可信 source manifest、typed fetch、deterministic parse/rank、request-local workflow、确认后保存、共享 read contracts | `app/domains/research/`；Tool 入口 `build_research_tools(...)`；外部边界 `ResearchSourcePort` / `ResearchContentPort`；只读入口 `ResearchReadService` | `test_research_*` 系列以及 `test_stage5_e2e.py` Research 路径 | 计划能力均能定位到代码与测试；历史“182 项”已不是当前清单规模，见 `D-02` |
| Travel | `TRAVEL_DOMAIN_PLAN.md`：Trip/constraint、五类 typed Port、request-local candidate → comparison → draft、确认后保存 itinerary、KnowledgeReference、共享 read contracts | `app/domains/travel/`；Tool 入口 `build_travel_tools(...)`；五个 Port 在 `ports.py`；fixture adapters 在 `adapters.py`；只读入口 `TravelReadService` | `test_travel_*` 系列以及 `test_stage5_e2e.py` Travel 路径 | 计划能力均能定位到代码与测试；大文件职责和生命周期只作为步骤 4 检查项，不因长度判定漂移 |
| Storage | `STORAGE_SQLITE_PLAN.md`、Domain plans：SQLite 保存长期事实，migration 可升级且幂等，request-local observation/draft 不落库，transaction 由 runtime / UoW 控制 | `app/storage/sqlite.py`、`migrations.py`、`schema.py`、`unit_of_work.py`；Domain repositories | `test_storage_sqlite.py`、`test_storage_migrations.py`、`test_storage_unit_of_work.py`、Research/Travel repository 与 planning tests | schema v8 与 Domain 声明对齐；`tool_calls` 是明确保留但未写入的历史兼容表，见 `N-01` |
| Observability | `OBSERVABILITY_LOGGING_PLAN.md`、`ARCHITECTURE.md`：`events.jsonl` 保存稳定语义事件，`llm.jsonl` 保存 provider 调试交互，`application.log` 用于本地诊断；`TraceSink` 不进入 GraphState | `app/observability/events.py`、`file_logs.py`、`logger.py`；公共窄口 `TraceSink.append(...)` | `test_observability_file_logs.py`，并由 runtime / orchestration / Skill / Tool 测试断言部分事件 | 三类文件基础设施存在；稳定事件名、最小 payload 与跨层去重尚缺集中契约证据，见 `B-03`；生产 LLM 写入仍按计划延后，见 `N-02` |

#### Blocking

- `B-01`：当前 `tool_runtime_factory` 在 `execute_tool` node 内调用，能够保证不同 Direct Executor invocation 隔离，但仓库没有证明“同一个未来 ReAct run 的多次 Tool 调用共享同一 Research / Travel service 临时状态，同时不同 run 隔离”。Research 的 document/item-set/draft 和 Travel 的 observation/candidate/comparison/draft 都依赖该 execution scope。步骤 4 必须确认最终 owner / 创建与清理时机，并用多 Tool fake loop 与跨 run 负向测试证明；在此之前 Stage 6 为 `no-go`。
- `B-02`：Tool 名称、effect/risk/skill binding、input/output schema、错误码、confirmation/evidence 关系目前散落在模块测试中，尚无统一的小型 compatibility contract。现有测试能证明当前行为，但不能阻止后续 Executor 接入时静默改义。步骤 5 确定冻结表面，步骤 6 增加门禁。
- `B-03`：事件由各层测试局部断言，但尚无稳定事件名、允许 payload、敏感字段禁止项及 events/application log 去重的集中清单和契约测试。阶段 9 Recovery 未来会消费 stop/error/evidence，因此步骤 5 必须先形成保留结论，步骤 6/11 再冻结和整理。
- `B-04`：当前工作树的 216 个测试方法只完成静态清点，尚未在稳定化基线上重新运行。它不阻塞步骤 2-5 的只读审计，但在步骤 14 完成前阻塞最终 Stage 6 `go`。

#### Non-blocking

- `N-01`：SQLite `tool_calls` 表仍由初始 migration 创建，但 Gateway 不写入。计划与架构均明确它是历史兼容结构，当前没有跨 run 查询消费者；保持不动，不为整洁提前 migration。
- `N-02`：`LlmLogWriter` / `llm.jsonl` 基础设施已存在，但 Skill selector 和 Tool calling 尚未通过统一 LLM Gateway 写入生产 provider interaction。当前计划已明确延后到统一 LLM Gateway，不阻塞 Stage 6 核心 loop；步骤 5 只需确认 runtime failure event 的最小同步语义。
- `N-03`：总路线图仍把根 `main.py` 列为 V1 入口，而当前仓库尚无该文件。RuntimeService 和 bootstrap 已可测试，CLI 不影响阶段 5 公共契约冻结；保留为后续 V1 产品入口工作，不在本稳定化步骤顺手实现。
- `N-04`：当前没有 LangChain Tool adapter。`TOOL_SYSTEM_PLAN.md` 已记录真实调用方不存在时不实现，代码和测试也不依赖该 adapter；这不是缺失功能。

#### Documentation-only

- `D-01`：`SKILL_SYSTEM_PLAN.md` 的已完成步骤 4 仍把 Research / Travel Skill 描述为 skeleton / planned workflow，但当前 Skill body 已描述可执行 workflow。行为和边界没有冲突，步骤 12 整理成最终设计措辞。
- `D-02`：`RESEARCH_KNOWLEDGE_DOMAIN_PLAN.md` 末尾保留“全量 182 项通过”，`TRAVEL_DOMAIN_PLAN.md` / `PROGRESS_LOG.md` 记录后来的“216 项通过”。两者是不同时间点的历史数字，但已完成计划作为最终设计说明书时会造成当前验证歧义；步骤 12 移除或明确历史时间点，最终数量以步骤 14 实跑为准。
- `D-03`：`TOOL_SYSTEM_PLAN.md` 使用“每次 invocation 重建”描述 Registry / Gateway / Domain service。对当前单 Tool graph 成立，但对未来 ReAct 的 invocation / run / iteration 含义不够精确；待 `B-01` 生命周期结论后在步骤 12 改为明确 execution-scope 术语。

步骤 2 已完成：八个模块均已建立计划承诺、代码入口、公共接口和测试证据索引；当前记录 `4` 个 blocking、`4` 个 non-blocking、`3` 个 documentation-only 项。步骤 2 未修改生产代码或测试，下一步只进入阶段 0-4 横向边界审计。

### 步骤 3 阶段 0-4 横向边界审计（2026-07-13）

#### 已满足且无需修改

- 阶段 0/1 隔离成立：`app/` 与当前测试没有 import `legacy_v0`；旧目录只出现在归档说明中。
- `RuntimeService` 仍是外部请求入口，`RuntimeOrchestrator` 只负责 compiled graph 编排；Intent、Policy、Skill、Tool safety、Domain repository 和日志 writer 均以显式依赖存在，没有由 LangGraph 接管业务事实或授权。
- `GraphState` 是 request-local 值；`OrchestrationContext` 只携带 request-local `TraceSink`，service / registry / SQLite connection 没有写入 state。
- Policy 是 Tool effect 的授权事实源；Skill selection 和 request metadata 不能提升 WRITE 权限，现有负向测试覆盖 metadata 绕过。
- `SqliteUnitOfWork` 对 commit、rollback、嵌套 transaction 拒绝有独立测试；Domain repository 继续使用同一显式 connection，没有隐藏全局数据库。
- events 使用每个 run 独立递增的 `seq`，并携带 run/session/turn identity；事件 payload 不直接记录原始用户输入。

#### Blocking / adjust findings

- `S3-01 Intent / Policy 与当前 Domain 漂移`：`RuleBasedIntentClassifier._WRITE_OBJECTS` 和 `PolicyService._identifies_supported_write_target(...)` 仍只认识 Tasks / Memory / Wellbeing 词汇，不认识 Research Note/Brief/Source、Trip/constraint/itinerary；READ 词汇也未覆盖常见 fetch/search 表达。阶段 5 E2E 使用 fake Intent/Policy，因此没有证明生产 `build_runtime_service()` 能从真实 Research / Travel 请求到达相应 Tool。该问题阻塞生产入口和 Stage 6；步骤 6 先补 contract/E2E，步骤 7 最小调整通用 intent/effect 判定，不能把业务 Tool 名写入 Policy。
- `S3-02 transaction 过宽`：`RuntimeService.handle()` 在进入 compiled graph 前开启 SQLite transaction，transaction 覆盖 Intent/Skill LLM、Tool selection LLM、external read 和整个未来 ReAct loop。阶段 6 会放大锁持有时间和失败回滚范围。应把 run lifecycle record 与 Domain WRITE transaction 的所有权分开；external read / LLM 不应占用写 transaction。该项阻塞 Stage 6 execution scope 设计，步骤 6 用 transaction-boundary tests 固定目标，步骤 7 调整。
- `S3-03 unexpected failure 丢失 durable run record`：`insert_run_record()` 与整次 graph 在同一 transaction；未被 node 归一化的异常会使 `running` row 一并 rollback，只剩文件 failure event。阶段 9 Recovery 无法从 SQLite 区分“未开始”和“异常中止”。需要定义 run record 自身的短 transaction / 最终失败写入策略，并验证异常路径闭合；与 `S3-02` 一并处理。
- `S3-04 RuntimeResult 泄露内部异常文本`：`_safe_error_summary()` 把 `Exception.__str__` 写入 `GraphState.trace_summary` 和对外 `RuntimeResult.trace_summary`。这与 event 只保留 error type/code 的安全边界不一致，可能暴露 provider、路径或内部参数。步骤 5 决定删除或改为稳定 code，步骤 6/7 冻结并修正。
- `S3-05 session log owner 错误`：`RuntimeService._session_log` 只初始化一次；同一 service 后续处理不同 `session_id` 时仍写入第一个 session 目录，并保留 `first_run_id` metadata。事件行 identity 虽是当前请求，但文件归属跨 session 污染。需要按 session 管理 writer 或明确 RuntimeService 只能绑定单 session；当前服务定位是进程级入口，因此采用前者，步骤 6 先补跨 session 隔离测试。
- `S3-06 application logger handler 跨 session 累积`：`configure_application_logging()` 只去重相同 path，不移除/隔离其他 session 的 FileHandler。多个 RuntimeService/session 可能把一条普通日志复制到多个历史 `application.log`，形成重复和跨 session 泄漏。步骤 11 处理，但必须在 Stage 6 `go` 前通过隔离测试。

#### 留到步骤 5 决定的公共表面

- `RuntimeSession.metadata`、`RuntimeRequest.metadata`、`RuntimeResult.intent/policy/tool_result/trace_summary` 的消费者与稳定性。
- `GraphState.graph_path`、`trace_summary`、`error_stage` 与 events / final result 的重复表达。
- `PolicyDecision.allowed_effects` 使用字符串而 Tool core 使用 `ToolEffect` 的双重类型边界。
- `runtime.run.started` 与 `runtime.request.created` 是否都有独立消费者，以及 graph path 是否应进入完成/失败 event。

步骤 3 已完成：确认 `6` 个必须调整或冻结的问题；其中 Intent/Policy Domain 漂移、transaction/run-record 边界、异常文本泄露和 session/log 隔离会阻塞最终 Stage 6 `go`。本步未修改生产代码或测试。

### 步骤 4 阶段 5 深度模块审计（2026-07-13）

#### 真实依赖路径

当前 allow 路径为 `SkillService.prepare()` → `resolve_allowed_tools(selected_skill_ids, policy, registry)` → filtered model catalog → `ToolCallSelectionClient.select(...)` → `ToolGateway.execute(...)` → pre-Guardrail → Domain handler → post-Guardrail。检查确认：

- Skill 只产生候选能力，未直接生成 `AllowedToolSet` 或绕过 Policy。
- Policy 只授权 effect，不枚举具体业务 Tool；最终 Tool 集合是 Skill binding、Policy effect 与 Registry 的交集。
- Gateway 对未注册、未授权、参数错误、handler exception、非法 result、output schema 和 WRITE evidence fail-closed；拒绝与 confirmation 不触达 handler。
- Tool core 不 import 具体 Domain；Research / Travel 只在 Tool adapter 层依赖 `app.tools`，Domain models/service/repository 不依赖 LangGraph 或 Planner/Executor。
- Research / Travel repository 保存长期事实；document/item-set/observation/candidate/comparison/draft 保存在 service instance 内，未写入业务表。
- 三个共享 read Protocol、`KnowledgeReference` 与 typed Ports 都有 fake consumer 或聚焦测试；消费者不直接读取另一 Domain repository。

#### Blocking / adjust findings

- `S4-01 execution scope 未成为显式契约`：`tool_runtime_factory` 在当前单次 `execute_tool` node 内创建 Registry、Gateway 和两个 Domain services。它能做到 Direct Executor 跨 run 隔离，却无法保证未来 ReAct iteration 复用同一 service；若每轮调用 factory，第二个 Tool 将读不到前一轮 document/candidate/draft。需要将“每个 runtime run 创建一次、run 内多 Tool 共享、run 后释放”定义为窄 execution-scope owner，Executor 只拿 Gateway/catalog 能力，不读取 service internals。与 `B-01` 合并，步骤 6 先写 fake loop + 跨 run 测试，步骤 7 调整 composition seam。
- `S4-02 production bootstrap 依赖测试 fixture`：`app/runtime/bootstrap.py` 将 `TRAVEL_FIXTURE_ROOT` 硬编码为 `tests/fixtures/travel`，并直接构造五个 `Fixture*Adapter`；Research 旧 `research.fetch_source` 也由内联 `FixtureResearchSourcePort` 支撑。安装或运行不带 tests 的产品会失败，且 production composition 与测试资产反向耦合。阶段 5 可以保留 fixture-backed provider，但 fixture 必须是明确的 app/eval adapter 配置或测试注入，不能由 production bootstrap 硬依赖测试目录。步骤 6 增加“bootstrap 不 import/读取 tests”架构测试，步骤 7 最小收口 composition。
- `S4-03 confirmation continuation 缺失`：Policy 的 `REQUIRES_CONFIRMATION` route 在 Skill/Tool 前结束；Policy 即使允许 WRITE，compiled `execute_tool` 调用 Gateway 时也从不传 `confirmed_tool_name`，因此所有 WRITE 都只能返回 `confirmation_required`。Domain WRITE 在直接 Gateway tests 中成立，但 production compiled Graph 没有可信的确认后继续入口。不能用 `RuntimeRequest.metadata` 作为授权。步骤 5 冻结最小 confirmation/interaction 边界，步骤 6 先写“未确认不执行、确认绑定具体 action、不能跨 run/改参数复用”的 contract；具体 resume 若属于 Stage 6/Interaction Safety，可通过窄接口接入，但 Stage 6 开工前必须明确 owner。
- `S4-04 Stage 5 E2E 绕过生产 Intent/Policy/bootstrap`：`test_stage5_e2e.py` 使用 `ReadIntentService`、`ExternalReadPolicyService`、固定 Skill selector、固定 ToolCall 和自建 fixture runtime。它很好地证明 graph/Gateway/handler 层，但不能支持“生产入口已打通”的更强声明。需要保留该分层测试，同时增加离线 production-composition contract，覆盖真实 Intent/Policy 与可注入 provider，不调用真实 LLM/网络。
- `S4-05 provider/adaptor 状态表达未统一冻结`：Travel 有统一 success/no-results/partial-failure/failed、retryable、expiry/provenance；Research `ResearchExternalSourceError` / typed content fetch 采用异常与 Domain-specific结果形状。业务输出可以不同，但 Executor 需要只通过 `ToolResult.status/error.retryable/output` 判断下一步，不能识别 provider 内部异常。步骤 5 只冻结 Tool 层共同语义，不强行合并 Domain Port 类型。
- `S4-06 confirmation 粒度仅绑定 Tool 名`：Gateway 的 `confirmed_tool_name` 不绑定 call ID、参数摘要、run、有效期。计划已声明这是后续 Interaction Safety State，但 Stage 6 一旦支持循环和继续执行就会成为真实安全边界。结论为 `adjust contract now, implement with Stage 6 interaction scope`；不得把当前字符串参数宣称为最终冻结接口。

#### Non-blocking / 保留现状

- `research.fetch_source` 是早期 fixture-backed Source observation 纵向切片，而 `research.fetch_briefing_source` 是当前可信 manifest/content workflow。两者目前有不同用途和测试，不在未完成消费者/字段审计前仅因相似而删除；步骤 5 将其列为公共 Tool 表面复核项。
- Research / Travel 的 models、service、repository、tools 文件较长，但当前职责仍可按 Domain model、workflow service、persistence、Tool adapter 解释。没有仅凭长度拆分的依据。
- `KnowledgeReferenceResolver` 不由 bootstrap 全局装配；它只在读取 Trip detail 时作为窄参数使用，resolver unavailable 返回结构化 resolution 而不阻塞主体。该形状符合 adapter-only 边界。
- LangChain adapter、真实 Travel HTTP/MCP adapters 和跨 run Tool history 没有当前消费者，继续 defer。

步骤 4 已完成：Skill → Policy → AllowedToolSet → Gateway → Domain 的安全依赖方向成立，但发现 `6` 个需要冻结或调整的问题；execution scope、production bootstrap fixture 依赖、confirmation continuation 与生产入口证据为 Stage 6 blocking。本步未修改生产代码或测试。

### 步骤 5 字段、日志与公共表面审计（2026-07-13）

#### Runtime / GraphState 字段结论

| 字段 | 写入者 | 当前读取者 | 状态类别 | 结论 |
| --- | --- | --- | --- | --- |
| `RuntimeSession.session_id/started_at` | model factory | 当前没有生产构造或消费者 | session identity 候选 | `adjust`：当前是未使用类型；若 Stage 6 不需要显式 session owner，冻结前删除 `RuntimeSession`，不保留空壳 |
| `RuntimeSession.metadata` | caller | 无 | opaque extension | `remove`：无消费者且授权风险高 |
| `RuntimeRequest.user_input/session_id/turn_id/run_id/created_at` | caller / default factory | Intent、Skill/Tool clients、run record、event envelope | 稳定 run 输入与 identity | `keep` |
| `RuntimeRequest.metadata` | caller | 仅负向 Policy 测试证明它不能授权 | opaque extension | `remove`：当前无合法消费者；未来有明确 typed context 再新增窄字段 |
| `RuntimeResult.run_id/session_id/status/message/error_code` | orchestration | RuntimeService、run record、tests、未来产品入口 | 稳定 run 结果 | `keep` |
| `RuntimeResult.tool_result` | Tool result mapper | E2E/tests、未来 Executor observation / product | 结构化执行结果 | `keep`，但冻结为 `ToolResult` 的序列化语义，不允许 Executor 读取 handler/service |
| `RuntimeResult.intent/policy` | orchestration summary helpers | 当前只有 tests | 调试/解释摘要 | `adjust`：不作为阶段 6 控制输入；优先从公共结果移除并保留语义 events。若产品确需展示，改为独立 typed explanation view，而不是重复授权事实 |
| `RuntimeResult.trace_summary` | orchestration nodes | 当前只有 tests | 重复调试摘要 | `remove`：与 status/error/tool result/events 重复，且当前会泄露异常文本 |
| `GraphState.request/intent/policy/route/skill_selection/prompt_contributions/result` | graph nodes | 后续 graph nodes / RuntimeService | request-local orchestration | `keep`；只在 graph invocation 内使用，不进入 Domain 或长期事实 |
| `GraphState.error_code/error_stage` | failure node | routing / RuntimeService failure event | request-local stop reason | `keep`，作为阶段 9 的最小结构化失败边界；不得保存原始异常文本 |
| `GraphState.graph_path` | `_append_node` | tests、run completed/failed payload | debug path | `adjust`：保持 graph-internal，可用于测试；从稳定 public result 和默认 event payload 移除，Inspector 出现后再通过专用 trace view 暴露 |
| `GraphState.trace_summary` | nodes | RuntimeResult mapper | 重复状态 | `remove` |

#### Tool / Guardrail 公共字段结论

- `ToolDefinition.name/description/input_schema/output_schema/effect/risk/skill_ids`：全部有 Registry、authorization、model catalog、Guardrail 或测试消费者，`keep/freeze`。
- `AllowedToolSet.tool_names`：`keep/freeze` 为 request-local authorization artifact；不写 GraphState、event 大 payload或数据库。
- `ToolCall.call_id/tool_name/arguments`：`keep/freeze`；arguments 只进入 selection、schema validation 和 handler，不进入稳定 event/log。
- `ToolError.code/message/retryable`：`keep/freeze`；Executor 只按 code/retryable/ToolResult status 判断，不解析 provider exception。
- `ToolResult.call_id/tool_name/status/output/evidence/error`：`keep/freeze`；是 ReAct observe → next action 的核心边界。
- `ExecutionEvidence.evidence_type/reference`：`keep/freeze`；当前所有 WRITE 都提供稳定 Domain reference。`summary` 保留为紧凑人类解释，但不作为成功判据。`attributes` 当前生产构造均为空、没有消费者，`remove`，未来需要时增加 typed evidence subtype，避免任意字典变成事实源。
- `GuardrailDecision.action/stage/reason_code/tool_name`：`keep/freeze`；用于执行控制与安全事件。`reason` 保留为内部/用户安全提示但不作为恢复分支。`sanitized_args_summary` 目前只记录参数类型且只有测试读取，不能绑定 confirmation，`remove`。`evidence_requirements` 当前恒等于可由 WRITE effect 推导的 `write_effect` 且没有消费者，`remove`；未来多类 evidence 要求出现时再以 typed policy 增加。
- confirmation：当前 `confirmed_tool_name` 不冻结。目标契约必须绑定 `run_id + call/action identity + canonical argument digest + expiry`，并由 interaction/execution scope 验证；未经确认、跨 run、参数变化或过期都 fail-closed。

#### Domain / Port / read contract 字段结论

- Research / Travel 长期模型的业务 ID、scope ID、version、状态、created/updated timestamps、provenance、Source snapshot reference、Trip constraints、Itinerary items/decision、KnowledgeReference 均有 repository、migration、read model、Tool 或引用完整性消费者，`keep`。
- request-local document/item-set/observation/candidate/comparison/draft 的稳定 ID、父级 ID、provenance、status、expiry 和 version 支撑防伪、顺序、stale 检查与下一步 Tool，`keep`；它们不进入 SQLite。
- Tool output 中的 stable IDs、status、structured error/retryable、provenance/evidence 和下一步所需业务字段，`keep/freeze`。`raw HTML`、provider 原始响应、内部异常和 repository row 不得加入。
- `DomainPlanningReadModel`、`DomainContextProvider`、`DomainMemoryCandidateProvider` 的方法名、参数顺序、scope 语义和稳定排序，`keep/freeze`；Research scope 为 Topic ID，Travel scope 为 Trip ID。
- Research 与 Travel 的业务 candidate/snapshot 类型继续各自拥有，不提取万能基类。Travel 的统一 provider status 与 Research 的 fetch exception 可以在 Port 层不同；共同的 Executor 语义只冻结在 `ToolResult`。
- `research.fetch_source` 与 `research.fetch_briefing_source` 暂不删除：前者仍有独立 Source observation/save 测试，后者承载可信 briefing workflow。步骤 9 整理时若消费者矩阵证明前者已完全被替代，再以 breaking Tool change 流程单独决定。

#### 稳定事件清单与最小 payload

以下事件保留为冻结候选；公共 envelope 统一只含 event id/time、run/session/turn、seq、level，payload 只保留所列语义：

| 事件 | 最小 payload |
| --- | --- |
| `runtime.run.started` | 空 |
| `intent.classified` / `intent.failed` | 成功：intent type、clarification/write flags；失败：error code/type |
| `policy.decided` / `policy.failed` | 成功：action、allowed effects、confirmation flag；失败：error code/type |
| `orchestration.route.selected` | route |
| `skill.selected` / `skill.selection.failed` | selected IDs/count；或 error code/type |
| `skill.loaded` / `skill.load.failed` | skill ID；失败再加 error code/type |
| `skill.reference.loaded` / `skill.reference.load.failed` | skill/reference ID；失败再加 error code/type |
| `tool.catalog.resolved` | Tool names/count；不得含 schema、handler 或参数 |
| `tool.call.requested` | call ID、Tool name |
| `tool.guardrail.decided` | stage、action、reason code、Tool name |
| `tool.call.completed` / `tool.call.failed` | call ID、Tool name、status、evidence count、可选 error code |
| `runtime.run.completed` / `runtime.run.failed` | status；失败再加 error code/stage |

删除候选：

- `runtime.request.created`：run started envelope 已包含 run/session/turn，当前 payload 再复制 session/turn，没有独立消费者。
- completed/failed payload 的 `graph_path`：是可由事件序列推导的 debug 信息，不作为恢复事实。
- 所有 `trace_summary`、原始 exception message、Tool arguments/output、raw provider payload、raw HTML。
- `application.log` 的 routine run started/completed 镜像；保留真正异常诊断和少量本地运行信息，并修复跨 session handler 隔离。

`llm.jsonl` 继续专门保存 provider request/response 调试数据，但必须由统一 LLM logging boundary 写入并执行 secret/redaction；它不是 Policy、Tool success、Domain fact 或 Recovery 的事实源。

#### 最终调整清单与建议

`go`（边界可直接冻结）：

- Skill candidate 与 Policy effect 分离；AllowedToolSet → Guardrail → Gateway 的安全链。
- ToolDefinition / ToolCall / ToolError / ToolResult 核心语义。
- 三个共享 Domain read contracts、KnowledgeReference、typed Port 的 Domain ownership。
- Domain 长期事实与 request-local workflow state 分离。

`adjust`（进入行为修改前先在步骤 6 写失败/契约测试）：

1. 建立每 run 一个 execution scope，run 内共享 Domain temporary state、run 间隔离。
2. 收窄 transaction；run record 独立闭合，Domain WRITE 使用短且明确的 transaction。
3. 让真实 Intent/Policy 覆盖 Research / Travel effect 语义，同时保持 Policy 不枚举 Tool 名。
4. 移除 production bootstrap 对 `tests/fixtures` 的依赖并保留可注入 fixture adapter。
5. 定义可信 confirmation action contract；当前 `confirmed_tool_name` 不作为最终接口。
6. 删除 Runtime/GraphState 的 metadata/trace 重复与异常文本泄露。
7. 修复 session log writer 和 application logger 的跨 session 所有权。
8. 增加 Tool schema/error/event、依赖方向、production composition、multi-call lifecycle 和 cross-run isolation compatibility tests。

`defer`（有明确理由，不阻塞 Stage 6 loop）：

- `tool_calls` 历史兼容表重新设计/写入。
- 统一 LLM Gateway 的完整 `llm.jsonl` provider 记录实现。
- LangChain Tool adapter、真实 Travel HTTP / Calendar MCP adapters。
- 根 `main.py` 产品 CLI、Inspector/Eval/DAG UI。
- 无真实第二消费者的 Domain helper/base class 抽取。

步骤 5 结论：`adjust`，当前 Stage 6 为 **`no-go`**。原因不是 Domain 功能不足，而是 execution scope、transaction、production composition、confirmation、公共结果/事件和 session 日志边界尚未由目标契约测试冻结。下一步必须先向用户确认上述调整清单；获准后从步骤 6 开始只写目标契约与负向测试，不能直接重构生产代码。

### 步骤 6 目标契约测试（2026-07-13）

已新增三个职责独立的离线测试模块：

- `tests/test_stage5_contract_tool_surface.py`：冻结 22 个 Tool 的名称、effect、risk、Skill binding 和 input/output schema digest；定义精简 Evidence / Guardrail 字段与 structured confirmation 目标。
- `tests/test_stage5_contract_architecture.py`：冻结 Domain 不依赖 Runtime/Orchestration/Skill/LangGraph 的方向；要求 production bootstrap 不依赖 tests fixture/assets。
- `tests/test_stage5_contract_runtime.py`：定义 Research/Travel Intent/Policy、每 run execution scope、短 transaction、异常 run record 闭合、RuntimeResult 脱敏/精简、event 去重、session writer 和 application logger 隔离目标。

执行命令：

```powershell
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'
uv run python -m unittest tests.test_stage5_contract_tool_surface tests.test_stage5_contract_architecture tests.test_stage5_contract_runtime -v
```

当前结果：共运行 `14` 个 test methods；`2` 个通过，`12` 个目标测试为红灯并产生 `13` 条 failure records（Intent/Policy 参数化 case 产生两条 failure）。没有 import error、测试代码 error、网络访问或真实数据/日志写入。

立即通过并完成冻结的证据：

- 当前 22 个 Tool contract 与步骤 1 catalog 完全一致。
- Domain 源码没有反向 import Runtime、Orchestration、Skill 或 LangGraph。

预期红灯与批准问题逐项对应：

| 红灯 | 对应审计项 |
| --- | --- |
| structured confirmation 替代 `confirmed_tool_name` | `S4-03` / `S4-06` |
| 移除 Evidence/Guardrail 无消费者字段 | 步骤 5 Tool 字段结论 |
| production bootstrap 不读取 tests fixture | `S4-02` / `S4-04` |
| Research / Travel write intent 与 Policy effect | `S3-01` |
| LLM/external work 不处于 SQLite transaction | `S3-02` |
| unexpected failure 仍有 finished run record | `S3-03` |
| RuntimeResult 不包含内部 exception 文本 | `S3-04` |
| 每个 session 独立 event log 目录 | `S3-05` |
| application log 不跨 session 镜像 | `S3-06` |
| 删除重复 request event / graph path payload | 步骤 5 事件结论 |
| 精简 RuntimeRequest/RuntimeResult/GraphState 字段 | 步骤 5 Runtime 字段结论 |
| RuntimeService 显式拥有每 run execution scope | `B-01` / `S4-01` |

步骤 6 已完成：目标边界已经可执行，当前红灯均为批准的后续实现工作，没有通过放宽断言隐藏问题。下一步步骤 7 只允许收口 Runtime / Tool / Orchestration 接缝；Domain 业务能力不得在该步修改。

### 步骤 7 Runtime / Tool / Orchestration 接缝收口（2026-07-13）

已按步骤 6 的目标契约完成最小接缝调整，未修改 Research / Travel Domain 业务能力：

- Runtime 公共模型移除无消费者的 `RuntimeSession`、`RuntimeRequest.metadata`、`RuntimeResult.intent/policy/trace_summary`；GraphState 不再保存 `trace_summary`，内部 exception 文本不再进入公共结果。
- `RuntimeService` 将 run lifecycle record 与 Domain WRITE transaction 分离：run record 先独立提交，Intent/Skill/LLM/external read 不占用 SQLite 写 transaction；异常路径回滚当前业务 transaction 后闭合失败 run record。
- composition seam 改为每次 runtime invocation 创建一个 `execution_scope`，同一 run 内显式复用，跨 run 隔离；Orchestration node 只消费该 scope，不读取 Domain service internals。
- Tool confirmation 改为 `ConfirmedAction`，绑定 `run_id`、`call_id`、Tool、canonical arguments digest 和 expiry；参数变化、跨 run 或过期确认均拒绝。具体交互恢复入口仍由阶段 6/Interaction Safety 按该窄契约接入。
- 删除 `ExecutionEvidence.attributes`、`GuardrailDecision.sanitized_args_summary/evidence_requirements`，保留有真实授权、审计和恢复语义的字段。
- production bootstrap 不再 import 或读取 `tests/fixtures`；未配置真实 provider 时使用 app 内部 unavailable port，并由既有 Gateway 错误边界安全归一化。
- Intent / Policy 的通用对象与动作判定覆盖当前 Research / Travel read/write 词汇，没有把具体 Tool 名写入 Policy。
- event contract 删除重复的 `runtime.request.created` 和 final event `graph_path`；session event writer 改为按 `session_id` 隔离。

验证结果：

```powershell
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'
uv run python -m unittest tests.test_orchestration_graph tests.test_orchestration_nodes tests.test_orchestration_state tests.test_runtime_service tests.test_policy_service tests.test_tool_models tests.test_tool_guardrails tests.test_tool_gateway tests.test_tool_calling tests.test_research_tools tests.test_travel_tools tests.test_travel_planning tests.test_stage5_e2e tests.test_stage5_contract_tool_surface tests.test_stage5_contract_architecture tests.test_stage5_contract_runtime -v
uv run python -m unittest discover -s tests
```

- 聚焦回归运行 `84` 项：`83` 通过，唯一红灯为 `test_application_logs_do_not_mirror_into_another_session`。
- 全量离线回归运行 `230` 项：`229` 通过，同一项红灯；无其他 failure/error。
- 该红灯对应已批准的 `S3-06`，其 owner 明确为步骤 11 Observability。步骤 7 不提前修改全局 application logger 生命周期，避免越过当前步骤边界。

步骤 7 已完成。步骤 6 的其他目标红灯均已转绿；Stage 6 仍为 **`no-go`**，因为 `S3-06` 尚未关闭，且步骤 8-15 的共享契约、Domain、文档与最终冻结门禁尚未完成。下一步只执行步骤 8，共享 Domain contract 的调整必须以真实跨 Domain 消费者和共同不变量为依据。

### 步骤 8 共享 Domain contract 收口（2026-07-13）

共享 contract 审计结论与调整：

- 三个 Protocol 的方法名、参数顺序和 keyword-only `scope_id` 已由 Research / Travel 两个真实实现及 fake Planner/Context/Memory consumers 共同证明，继续保留在 `app/domains/contracts.py`，不增加 Domain 基类。
- 修正 Research scope 漂移：Context / Memory scoped query 现在使用 Topic ID，只返回与该 Topic 建立显式 link 的 source/note/brief；未知 Topic 失败，不退化为全局查询。Travel 继续使用 Trip ID。
- Context candidate 的真实公共字段为 `candidate_id/item_kind/content/provenance/estimated_chars/created_at`；Memory candidate 跨 Domain 只有 identity、provenance 和 created time 共同稳定，业务内容形状不同，因此不提取共享 candidate model。
- `KnowledgeReferenceResolution` 的 `resolved` 与 `unavailable` payload 改为互斥：resolved 不允许 `error_code`，unavailable 不允许携带陈旧 title/summary/provenance，避免消费者同时看到成功内容和失败状态。
- Travel 多候选 typed Port 继续使用 `success/no_results/partial_failure/failed` 互斥结果和结构化 `retryable` provider failure。Research 单来源 fetch 没有 partial-success 语义，继续使用 Domain-owned typed document/observation 与稳定 AppError code；没有两个相同业务不变量，因此不抽取共享 `ExternalResult`。
- WRITE evidence 继续由 Tool System 的 `ExecutionEvidence` 统一，Domain Port 不生成授权或成功 evidence；partial success 只保留成功 observation/candidate，不触发跨 Domain transaction 或自动重放。
- `plans/DOMAIN_CONTRACT_STANDARD.md` 已同步 structured confirmation、Research/Travel scope 和 typed Port 提取规则，删除旧的“只绑定 Tool 名”描述。

新增 `tests/test_stage5_contract_domain.py`，冻结 Protocol/实现调用形状、候选公共字段和 KnowledgeReference resolution 字段；Research/Travel 既有 read model、Port、fixture adapter 测试继续负责业务语义。

验证命令与结果：

```powershell
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'
uv run python -m unittest tests.test_stage5_contract_domain tests.test_research_read_models tests.test_travel_read_models tests.test_travel_knowledge_references tests.test_travel_ports tests.test_travel_fixture_adapters -v
uv run python -m unittest discover -s tests
```

- 共享契约聚焦回归：`23/23` 通过。
- 全量离线回归：运行 `235` 项，`234` 通过；唯一红灯仍为步骤 11 所有的 `test_application_logs_do_not_mirror_into_another_session`，没有新增 failure/error。

步骤 8 已完成。没有创建无真实第二消费者的公共 utility/base model，也没有改动 Research / Travel 业务能力范围。Stage 6 仍为 **`no-go`**；下一步只执行步骤 9 Research Domain 整理。

### 步骤 9 Research Domain 整理（2026-07-13）

按步骤 4/5 审计结论复核 Research 的 models、Port/adapter、processing、service、repository、read model、Tool adapter、schema 和测试后，结论如下：

- `ExternalObservation`、HTML document、item set 和 brief draft 继续由每 run 的 `ResearchService` 持有；repository 只接收确认后的 Source/Note/Brief、Topic/Link/Revision 等长期事实。没有把 request-local state 移入 SQLite，也没有发现 service/repository 所有权倒置。
- 同一 service 的 fetch → parse → rank → build → save 链路已有聚焦测试；新增跨 execution scope 负向测试，证明另一 `ResearchService` 即使共享同一 SQLite connection，也不能用前一 scope 的 `observation_id` 保存 Source，且失败后数据库零误写。
- Tool adapter 只把稳定 ID、必要业务字段、结构化失败和 WRITE evidence 暴露给 Tool System；raw HTML、repository row 和内部异常文本不进入 Tool output。步骤 6 的 Tool schema digest 继续作为冻结门禁，无需改 schema。
- `ResearchExternalSourceError` / typed content fetch 的 Domain-specific error 在 Tool adapter 归一化为 `ToolError`；单来源 fetch 不具备 partial-success 业务语义，不引入 Travel 风格的多候选结果模型。
- models/service/repository/tools 虽然较长，但职责仍分别对应业务不变量、request-local workflow、持久化和 Tool translation；没有真实职责混放证据，因此不按文件长度拆分。
- `research.fetch_source` 与 `research.fetch_briefing_source` 有重叠，但前者仍是独立 observation → confirmed Source save 的已冻结兼容 Tool，后者还承担 HTML document → parse/rank/brief 链路。当前不能证明前者无消费者，故不执行 breaking 删除。
- 第 8 步已经修正 Topic scoped Context/Memory query；本步没有再修改 Research 生产代码。`RESEARCH_KNOWLEDGE_DOMAIN_PLAN.md` 中旧 scope、旧 confirmation 和历史测试数字属于步骤 12 的文档整理项，本步只记录漂移，不提前混入最终设计说明书整理。

验证命令与结果：

```powershell
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'
uv run python -m unittest discover -s tests -p 'test_research*.py' -v
uv run python -m unittest discover -s tests
```

- Research 聚焦回归：`37/37` 通过。
- 全量离线回归：运行 `236` 项，`235` 通过；唯一红灯仍为步骤 11 所有的 application logger 跨 session 隔离，没有新增 failure/error。

步骤 9 已完成。Research Domain 不需要额外生产重构，现有业务能力和 Tool catalog 均保持不变。Stage 6 仍为 **`no-go`**；下一步只执行步骤 10 Travel Domain 整理。

### 步骤 10 Travel Domain 整理（2026-07-13）

按与 Research 相同的标准复核 Travel models、五类 Port/fixture adapters、service、repository、read model、Tool adapter、schema 和测试，完成以下有限调整：

- 保持 external result → comparison → itinerary draft 为每 run `TravelService` 的 request-local state；新增跨 execution scope 负向测试，证明共享 SQLite connection 的另一 service 不能消费前一 scope 的 observation ID，且不会产生 itinerary 写入。
- 发现并修正真实时间边界缺口：candidate 在 draft 构建时虽检查 expiry，但用户确认保存前 quote 仍可能过期。`save_itinerary()` 现在在创建长期 Itinerary/Item/Decision 前重新验证所有选中 observation 的 expiry，过期时 fail-closed 且数据库零写入。
- `TravelService` 增加窄 `clock` 依赖，默认仍使用 `utc_now_iso`；comparison 与 save 使用同一可注入时间来源，使 expiry 测试 deterministic，不依赖运行机器当前时间。
- 保持幂等语义优先于重新执行：同一 idempotency key + draft 已成功保存后，即使 quote 后来过期，重试仍返回已保存 bundle；不同 draft 复用 key 继续以 `travel_itinerary_idempotency_conflict` 拒绝。repository 增加窄 idempotent-result 读取入口，同时 `save_itinerary_bundle` 保留最终竞态保护。
- candidate provenance、observation identity、comparison assessment、draft version、saved itinerary provenance 和 WRITE evidence 均有防伪、过期、恢复或消费者价值，继续保留；未发现可安全删除字段或需要 schema migration 的长期数据问题。
- `models.py`、`service.py`、`repository.py`、`tools.py` 虽较长，但职责仍分别对应业务不变量、request-local workflow、持久化和 Tool translation；没有因真实职责混放而拆分。
- 五个 typed Ports 的 success/no-results/partial-failure/failed、retryable、expiry/provenance 形状保持不变；真实 HTTP/MCP adapter 仍无当前消费者，不在本步实现。

验证命令与结果：

```powershell
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'
uv run python -m unittest discover -s tests -p 'test_travel*.py' -v
uv run python -m unittest discover -s tests
```

- Travel 聚焦回归：`37/37` 通过。
- 全量离线回归：运行 `239` 项，`238` 通过；唯一红灯仍为步骤 11 所有的 application logger 跨 session 隔离，没有新增 failure/error。

步骤 10 已完成。Travel 业务能力、Tool catalog 和 JSON schema 均保持不变，没有新增 booking、真实 provider 或 MCP 范围。Stage 6 仍为 **`no-go`**；下一步只执行步骤 11 Observability 整理并关闭当前唯一契约红灯。

### 步骤 11 Observability 整理（2026-07-13）

已按三类日志职责完成最小整理并关闭 `S3-06`：

- `application.log` 明确为当前 session 的本地诊断目标。`configure_application_logging()` 现在只保留一个 active FileHandler；切换 session 时移除并关闭旧 handler，相同路径重复配置保持幂等，不再把一条日志镜像到历史 session。
- `RuntimeService` 每次处理已有 session 时都会重新激活该 session 的 application log，避免 session A → B → A 时仍写入 B。当前 runtime 是同步入口；未来若引入真正并发 session，需在并发 runtime 计划中升级为 request-context routing，不能重新累积全局 handlers。
- 删除 application log 中 routine `runtime run started/completed`，这些事实已由 `runtime.run.started/completed` 语义事件表达；application log 继续保留 unexpected exception traceback 和结构化失败诊断，不复制完整事件流。
- `intent.classified` payload 删除 confidence 与 classifier detail；`policy.decided` payload 删除 denied reason。稳定事件只保留控制流所需的 intent type、clarification/write flags、policy action/effects/confirmation、route、Skill/Tool identity、Guardrail decision、结构化 error/evidence count 和 final status。
- 事件契约测试现在精确断言 runtime/intent/policy/final 与 Tool requested/guardrail/completed 的 payload 字段，并禁止 user input、Tool arguments/output、raw HTML、trace summary、classifier detail 和 reason 文本进入稳定 payload。
- `llm.jsonl` 的职责不变：只保存未来统一 LLM logging boundary 产生的 provider 调试交互，不作为授权、业务事实或 Recovery 成功证据；本步没有伪造尚不存在的生产 LLM writer 接线。

验证命令与结果：

```powershell
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'
uv run python -m unittest tests.test_observability_file_logs tests.test_stage5_contract_runtime tests.test_runtime_service tests.test_orchestration_graph tests.test_orchestration_nodes tests.test_orchestration_skills tests.test_tool_gateway -v
uv run python -m unittest discover -s tests
```

- Observability / Runtime / Orchestration / Gateway 聚焦回归：`43/43` 通过。
- 全量离线回归：`240/240` 通过，当前没有 failure/error。
- `S3-06` 与步骤 6 最后一项目标红灯已关闭；测试只使用临时 session 目录，没有写入真实用户日志目录。

步骤 11 已完成。代码与离线测试当前全绿，但 Stage 6 仍暂为 **`no-go`**，因为步骤 12 的最终设计文档对齐和步骤 13-15 的分层验证、统一回归记录及最终冻结决策尚未完成。下一步只执行步骤 12 文档整理。

### 步骤 12 最终设计文档对齐（2026-07-13）

已按文档职责完成当前事实同步：

- `SKILL_SYSTEM_PLAN.md`、`TOOL_SYSTEM_PLAN.md`、`RESEARCH_KNOWLEDGE_DOMAIN_PLAN.md`、`TRAVEL_DOMAIN_PLAN.md` 标记为阶段 5 完成后的最终设计说明；保留最终边界、接口、失败模式和验证理由，不再把 skeleton、旧字符串 confirmation 或历史测试数字表述为当前事实。
- Tool 文档删除不存在的 `ToolExecutionContext`、`sanitized_args_summary`、`evidence_requirements` 和 `confirmed_tool_name` 设计，改为当前 `ConfirmedAction` 与每 run execution scope；`tool_calls` 明确为不写入的历史兼容表。
- Research 文档改为 Planning/Context/Memory 均以 Topic ID 为 scope，Context/Memory 支持全局或 Topic scoped query；Travel 文档补充保存前 expiry 复验、可注入 clock、跨 scope 隔离和幂等重试语义。
- `docs/ARCHITECTURE.md` 已同步精简 RuntimeResult/GraphState、短 transaction、execution scope、structured confirmation、Research scope、Travel expiry/idempotency 和单 active-session application logger；删除旧 summary/字符串确认/全局 Research query 描述。
- `docs/RUNTIME_CONCEPTS.md` 已同步 structured confirmation、精简 RuntimeResult 和 graph path/event 的边界；`docs/PROGRESS_LOG.md` 新增稳定化已完成事实和 `240/240` 验证，历史 `182/216/33` 只保留为明确的当时快照。
- `plans/RUNTIME_REFACTOR_PLAN.md` 与 `README.md` 将阶段状态改为“阶段 5 功能完成、稳定化收尾中”；只有步骤 12-15 完成并给出 `go` 后才创建 Executor 计划，避免提前宣称进入阶段 6。
- 本步未新增外部技术或依赖，不需要修改 `docs/AGENT_LEARNING_LINKS.md`；代码和测试行为未改变。

文档一致性检查使用已知漂移词搜索和 `git diff --check`；当前没有残留的 `confirmed_tool_name`、不存在的 Tool model 字段、Research scope 拒绝或未标注的当前 `182/216/33` 测试声明。步骤 12 已完成，Stage 6 仍暂为 **`no-go`**；下一步只执行步骤 13 分层验证。

### 步骤 13 分层验证（2026-07-13）

使用本地 `UV_CACHE_DIR` 按责任层运行离线测试；为保证消费者边界可独立定位，read model、workflow 和 repository 测试在相邻层有少量有意重叠，以下数量是各层实际执行数，不是去重后的仓库总数：

| 层 | 覆盖 | 结果 |
| --- | --- | --- |
| L1 Model / pure function | common、Skill/Tool models、GraphState pure helper、Research processing、Travel models | `37/37` |
| L2 公共契约 | Registry/authorization/Guardrail/Gateway、Research content Port、Travel typed Ports、KnowledgeReference、observability、Tool/Domain compatibility | `44/44` |
| L3 Domain integration | Research content/knowledge/seed/read/resilience/manifest/tools；Travel fixture/repository/planning/read/tools | `54/54` |
| L4 Runtime integration | Intent、Policy、Skill discovery/selection/load/prompt、orchestration nodes、Tool calling、RuntimeService | `57/57` |
| L5 compiled Graph E2E | Stage 5 Research/Travel compiled graph 与 orchestration graph 路由/失败路径 | `13/13` |
| L6 阶段 6-9 fake consumers | Research/Travel fake Planner/Context/Memory、同 scope 多 Tool workflow、跨 scope 隔离与幂等 | `22/22` |
| L7 compatibility / architecture | dependency direction、public signatures/fields、Tool schema digest、Runtime/transaction/event/session contracts | `17/17` |
| L8 migration compatibility | storage migration/SQLite/UoW、Research schema upgrade/reference、Travel repository/rollback/idempotency | `28/28` |

所有八层均通过，共执行 `272` 次 test methods（含上述跨层重复），没有网络/API key、真实数据库或真实日志目录依赖，也没有通过放宽断言处理失败。本步没有修改代码、测试或公共契约。

步骤 13 已完成。Stage 6 仍暂为 **`no-go`**；下一步只执行步骤 14 统一离线回归，记录去重后的仓库总数、时长与失败分类。

### 步骤 14 统一离线回归（2026-07-13）

执行仓库统一命令：

```powershell
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'
uv run python -m unittest discover -s tests -v
```

结果：去重后的仓库测试共 `240` 项，`240/240` 通过，用时 `1.187s`，exit code `0`，failure/error/skip 均为 `0`。

离线与数据边界证据：

- provider/HTTP/LLM 路径均使用 fake client、patched response、fixture adapter 或显式 unavailable port；测试不需要 API key 或真实网络。
- SQLite 使用 `:memory:` 或测试临时路径；session/application log 测试使用 `TemporaryDirectory`。
- 回归后执行 `git status --short -- data logs data/lifeops.sqlite3` 无输出，证明没有修改或新增真实用户数据库/日志路径中的 Git 可见文件。
- `git diff --check` 通过；仅输出工作树既有的 LF→CRLF 提示，不是测试失败或内容错误。

步骤 14 已完成。所有自动化门禁当前全绿，但 Stage 6 仍暂为 **`no-go`**，直到步骤 15 完成冻结基线、剩余风险核对和正式 `go / no-go` 决策。

### 步骤 15 冻结基线与 Stage 6 决策（2026-07-13）

#### 放行条件核对

| 放行条件 | 结论与证据 |
| --- | --- |
| blocking findings 全部关闭 | `B-01` 由每 run execution scope 与同 run 多 Tool / 跨 run 隔离测试关闭；`B-02` 由 Tool surface compatibility tests 关闭；`B-03` 由稳定事件 payload、敏感字段负向断言和 application log 隔离测试关闭；`B-04` 由步骤 14 的 `240/240` 统一回归关闭。步骤 3-5 发现的 `S3-*` / `S4-*` 调整项也已在步骤 7-11 完成并转绿。 |
| 阶段 6-9 消费者兼容 | 步骤 13 的 L6 fake consumers 为 ReAct、Planner、Context、Memory 与 Recovery 边界执行 `22/22`；消费者只读取稳定 Tool result、Domain read contract、evidence/error/event，不读取 Domain service、repository 或 request-local 内部对象。 |
| 公共契约与依赖方向冻结 | L2 公共契约 `44/44`、L7 compatibility / architecture `17/17`；四个 `test_stage5_contract_*` 文件集中冻结公共字段、签名、Tool schema digest、事件 payload、transaction 与 dependency direction。 |
| 生命周期、字段和日志审计完成 | 每 run execution scope、短 transaction、request-local state、structured confirmation、KnowledgeReference、Travel expiry/idempotency 和单 active-session logger 均已有聚焦测试；无消费者或重复字段已按步骤 5-11 的批准清单处理。 |
| 文档与当前实现一致 | 步骤 12 已同步最终模块设计、`ARCHITECTURE.md`、总计划、进度日志和 README；历史测试数字只作为当时快照。 |
| 当前工作树离线验证全绿 | 步骤 13 八层共执行 `272` 次（含跨层重复）且全部通过；步骤 14 去重后 `240/240`，`1.187s`，failure/error/skip 均为 `0`；没有真实网络、真实用户数据库或真实日志目录写入。 |

#### 最终冻结表面

- Runtime：`RuntimeService.handle(...)`、`RuntimeRequest` / `RuntimeResult`、run lifecycle record、每 run execution scope，以及 compiled Graph 的窄 orchestration context。
- Skill：selection、lazy body/reference loading、prompt contribution 与候选 Tool 边界；Skill 不承担授权。
- Tool：`ToolDefinition`、`AllowedToolSet`、`ToolCall`、`ToolResult`、`ToolError`、`ExecutionEvidence`、`ConfirmedAction`，以及 Registry / authorization / Guardrail / `ToolGateway.execute(...)`；Tool 名称、effect、risk、skill binding、JSON schema、错误码和 confirmation/evidence 关系受 compatibility tests 保护。
- Domain：三个共享 read Protocol、Research Topic scope、Travel Trip scope、typed Port 的状态/retryable/expiry/provenance 语义，以及 `KnowledgeReference` 的 resolved/unavailable 只读引用边界。
- Observability：`TraceSink.append(...)`、稳定语义事件名称、最小允许 payload、run/session/turn identity 和敏感信息禁止项。

Domain service 的其他方法、repository、adapter、helper、fixture 和文件组织仍是内部实现，不因本次冻结变成公共 API。

#### 后续允许的扩展方式与兼容性规则

- 阶段 6-9 优先新增 Executor/Planner/Context/Memory/Recovery 自有类型、窄 adapter 或有真实消费者的可选字段；通过上述稳定接口组合，不反向读取内部实现。
- 已冻结字段不得静默改义。删除、重命名、必填化、错误码/effect/risk/scope 改义均是破坏性变更，必须有缺陷证据、迁移策略、计划更新、用户确认和对应 compatibility test 更新。
- Tool schema snapshot 只在公共契约被明确批准改变时更新；不能为了让测试通过而覆盖期望值。
- request-local Thought、observation、candidate、comparison 和 draft 不进入 Domain 业务表；模型文本不作为副作用成功事实。

#### 剩余非阻塞债务与未运行项

- `N-01`：SQLite `tool_calls` 历史兼容表继续保留且不写入；由未来真实迁移/查询需求决定是否处理，当前 Storage owner 无动作。
- `N-02`：生产 provider interaction 尚未统一写入 `llm.jsonl`；由后续统一 LLM Gateway / Executor composition 承接，不阻塞 ReAct 核心 loop。
- `N-03`：根 `main.py` V1 交互入口尚未实现；由后续产品入口阶段承接，不属于 Stage 5 契约。
- `N-04`：LangChain Tool adapter 继续按需实现；没有真实调用方时不增加适配层。
- 未运行真实 LLM、真实 Research HTTP provider 和其他真实外部服务 E2E。这些验证依赖网络、凭据和 provider 状态，按 9.3 属于可选集成验证，不是本次离线冻结门禁。

#### 最终决定

Stage 6 正式结论为 **`go`**。阶段 5 功能与稳定化均已完成，当前公共契约成为后续阶段的冻结基线。下一施工动作可以创建并确认 `plans/modules/EXECUTOR_PLAN.md`；本步骤不提前设计或实现 ReAct Executor。

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
