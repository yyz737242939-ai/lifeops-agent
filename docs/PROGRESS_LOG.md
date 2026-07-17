# 推进日志

本文档是 LifeOps Agent 的递增推进记录。

## 目的

通过本文档追溯项目已经完成、已经验证、已经学到的演进过程：

- 哪些模块已经存在；
- 哪些模块已经规划但尚未实现；
- 当前阶段哪些命令和测试是有效的；
- 哪些已知限制是有意保留的。

本文档只记录已经发生的事实和已经沉淀的学习点。不记录尚未学习的概念，不替代当前架构快照；当前 runtime 边界以 `docs/ARCHITECTURE.md` 为准。

## 当前阶段

项目已完成 Runtime 重构的阶段 2：Storage / SQLite 基础设施。

项目已完成阶段 3：Runtime Core / Intent / Policy 初版。

项目已完成阶段 3.5：Observability 文件日志校正。

项目已完成阶段 4：LangGraph Orchestration 骨架。

阶段 5 功能实现与稳定化、Stage 6 ReAct Executor、Stage 7 Plan-and-Execute Planner、Stage 8 Research External Interfaces / Hugging Face MCP 与整个 Stage 9 Context / Memory 均已完成。Stage 9A、Stage 9B 分别取得独立 `go`，Stage 9 已于 2026-07-16 关闭。

- 共享 Trace 标准步骤 1-8 已完成 foundation 与渐进 instrumentation：新增 immutable Trace/Span/Event/Link/Artifact/Annotation v1 models、request-local `TraceContext`、兼容 `RequestTelemetry`、`traces.jsonl` / `annotations.jsonl` append-only writers，并覆盖 Runtime/Intent/Policy/Skill/Planner/Executor/LLM/Tool/Guardrail spans。现有 `events.jsonl` 与 `TraceSink.append()` 保持兼容，TraceContext不进入GraphState或授权/业务模型；Feedback/Recovery只完成existing hook telemetry与projection seam，不代表Stage 10产品逻辑已实现。Trace/Runtime/Planning/Executor/Tool/architecture 聚焦回归 `90/90`、统一离线回归 `594/594` 通过（`20` 项显式 live/platform gates 跳过），compileall与diff检查通过。
- 共享Trace标准步骤9-13已完成：新增独立derived SQLite index与freshness/file fallback、统一TraceStore/TraceReader/immutable TraceGraph、独立`app/runtime_reporting` typed Ports/models/builder、deterministic sample rule/grader，以及serial diamond shared fixture。Diamond明确parent-child containment与`depends_on` dependency不同，保留B evidence、C failed、D blocked且D零Tool attempt；不实现scheduler。新增及架构focused tests `44/44`、统一离线回归`610/610`通过（`20`项显式live/platform gates跳过）。
- 共享Trace标准步骤14-16与实现审计已完成：Planning preview PLANNER span在结束时补齐canonical plan identity，confirm root以`plan_continuation`链接preview；`FileTraceStore`从canonical files或derived index只读解析preview，不修改PlanRun/PlanStep/GraphState。真实LLM交互使用唯一`LogLlmInteraction.id`作为sensitive artifact reference，并在provider提供时投影安全input/output/total token counts。审计同时修正optional instrumentation异常可能反转业务结果、旧Skill fake因`llm_log`扩签受侵入及`file_logs`不必要依赖RuntimeRequest的问题。focused/architecture回归`99/99`、统一离线回归`613/613`通过（`20`项显式live/platform gates跳过），compileall、diff与依赖扫描通过；真实Direct READ与Planning preview/confirm smoke均通过。Recovery/Eval真实smoke归各自未实施产品模块gate，共享标准最终结论为`go`。

- Storage schema 开发基线已在 2026-07-14 从旧 V1-V8 压缩为单一 canonical V1：新空库一次建立当前 Runtime、Research、Travel 的最终表、约束和索引，不再保留开发期 `ALTER` / 临时表搬运。迁移聚焦测试 `6/6`、统一离线回归 `299/299` 与 compileall 通过；本地旧库先备份并升级到最终结构，再重标 V1，`PRAGMA integrity_check=ok` 且原有 `7` 条 run record 保留。未来真实 schema 变化从 V2 开始追加。

- Stage 6 Executor 实施步骤 2 已完成：新增 `ExecutionLimits`、互斥的 model decisions、`ToolObservation` 安全投影、冻结的 status / stop reason、结构化 `ExecutorResult` 和最小 request-local `ExecutorState`；models 不保存 private reasoning，不依赖 Domain、repository、storage、LangGraph 或 provider SDK。新增 Executor models/contracts 与 Stage 5 architecture/runtime/tool/domain 公共契约共 `26/26` 通过。
- Stage 6 Executor 实施步骤 3 已完成：新增 typed `ExecutorModelInput`、Context/Memory contributions，冻结 model、Context、Memory、confirmation、Recovery、Feedback 六个窄 Protocol；production empty/no-op adapters 不授权、不自动确认、不 replay，测试 fake 只记录和返回精确 typed values。Executor models/contracts/ports 与 Stage 5 architecture/runtime/tool/domain 公共契约共 `31/31` 通过。
- Stage 6 Executor 实施步骤 4 已完成：新增独立、无 checkpointer 的 compiled `StateGraph`，以显式 final/tool/continue/stop/error routes 完成有界 action → observation cycle。每次 model decision 消耗一步；success/failed observation 可回流，deny/confirmation/limit/model/invalid/internal failure 收敛为冻结的结构化结果，重复 call ID 在第二次 Tool 执行前拒绝。合法上限 `max_steps=16` 通过显式 `limit_reached` 停止，不依赖 LangGraph recursion exception。Executor 与 Stage 5 冻结公共契约共 `43/43` 通过。
- Stage 6 Executor 实施步骤 5 已完成：`ReactExecutor` 一次加载 Context/Memory provider、按固定 `AllowedToolSet` 从 request-local Registry 生成 filtered catalog，并在整个 bounded loop 中只复用同一个 `ToolRuntime.gateway`。真实 Gateway integration 已验证同 scope 多 Tool、跨 scope 隔离、catalog 外 Tool 零 handler 调用、safe observation 回流和 provider failure 前置停止；Executor 分层回归 `31/31` 通过。
- Stage 6 Executor 实施步骤 6 已完成：只有 Registry 中、当前 `AllowedToolSet` 内的 WRITE Tool 才调用 synchronous confirmation provider；provider 返回的 exact `ConfirmedAction` 原样交给 Gateway 校验。READ 不请求确认，WRITE 缺失/拒绝确认零 handler 调用；两个 WRITE 分别确认，旧确认不能复用，参数、call ID、run 或 expiry 变化全部 fail-closed。聚焦确认测试 `6/6` 通过。
- Stage 6 Executor 实施步骤 7 已完成：新增 OpenAI-compatible Responses adapter，每步只从 typed LifeOps state 重建 user input、Skill/Context/Memory contributions、filtered catalog、ordered safe observations 和 step index；关闭 parallel calls、最多一个 ToolCall，不保存 provider response 或 `previous_response_id`。final/tool 混合、多个/未知 ToolCall、非法 JSON/arguments 和空结果均 fail-closed；provider failure 与 contract failure 分别映射为 `model_failed` / `invalid_model_action`。adapter/graph/core contract `20/20` 通过。
- Stage 6 Executor 实施步骤 8 已完成：outer allow node 已由 `execute_tool` 替换为 `execute_executor`，在 node-local 解析固定 `AllowedToolSet`、调用注入的 `ReactExecutor`，再把结构化 status/stop reason/last ToolResult 映射到冻结的 `RuntimeResult`。Policy confirmation/deny routes 不调用 Executor，outer `GraphState` 未增加 observations/limits/transcript。生产 bootstrap、RuntimeService 和 RuntimeOrchestrator 已删除旧 `ToolCallSelectionClient` 接缝，旧单 Tool adapter 与测试已删除；受影响 Runtime/Orchestration/Stage 5 E2E `42/42` 通过。
- Stage 6 Executor 实施步骤 9 已完成：在真实 decision、Gateway result 和终止边界追加 `executor.action.selected`、`executor.observation.recorded`、`executor.stopped`，payload 只含 step/action/tool identity/status/error code/retryable/evidence count，不复制 arguments、output、prompt、exception 或 Gateway 明细。Feedback 按 observation → final result 顺序接收；Recovery 只观察终止结果；hook exception 只产生安全 `executor.hook.failed`，不改写主结果或 evidence。Executor suite `48/48`、受影响 Runtime/Tool/Stage 5 suite `63/63` 通过。
- Stage 6 Executor 实施步骤 10 已完成：新增 `9` 个 deterministic/offline 跨 Domain compiled E2E，真实 outer graph 与 Executor subgraph 在同一 request-local scope 中完成 Research fetch → parse → rank → draft、Travel search → compare → draft、Research READ → Travel READ、多 WRITE 逐 action confirmation、无确认零写、失败 observation 回流、catalog deny、step limit、partial/expired provider result 和 itinerary 幂等 retry；`9/9` 通过，未访问真实网络、provider、用户数据库或日志目录。
- Stage 6 Executor 实施步骤 11 已完成：分层回归依次为 Executor models/contracts/ports `16/16`（`0.023s`）、Tool/Domain integration `41/41`（`0.160s`）、Runtime/compiled graph `69/69`（`0.883s`）、architecture/migration contracts `31/31`（`0.266s`）；四层共执行 `157` 次且零失败。统一离线 `unittest discover` 去重后 `294/294`（`2.279s`）通过，失败分类为 contract `0`、integration `0`、runtime/graph `0`、architecture/migration `0`、unexpected `0`。
- Stage 6 日志收口已完成：新增 request-local `LlmInteractionSink` / `RequestLlmLog`，Skill selection 与每步 Executor model decision 都把实际 provider request、结构化 response、provider/model、status 和安全 error code 写入 session `llm.jsonl`；interaction 使用独立 `seq`，provider exception text 不落盘，日志写失败不改变主结果。file-backed offline smoke 已验证 current Runtime → Skill → Executor → Gateway → final 的 `events.jsonl` 顺序，以及 `1` 次 Skill selection + `2` 次 Executor decision 的 `llm.jsonl` 落盘；active `application.log` handler 在 service close 时释放。
- Prompt 分层已补强：outer graph 继续只负责编排且不新增全局 prompt；Skill selector prompt 固定零/多 Skill、跨 Domain、精确 ID 和严格 JSON 路由契约；Executor prompt 吸收 V0 中仍适用于当前能力的 LifeOps 身份、Tool evidence、临时上下文、显式 WRITE、失败处理和简洁回答规则，同时继续保持 ToolCall/final 二选一、filtered catalog 与 private reasoning 边界。相关 adapter、selector 和 orchestration 聚焦测试 `17/17` 通过。
- Stage 6 Executor 实施步骤 12 已完成：两层 compiled graph、bounded loop、filtered catalog、Gateway-only execution、逐 WRITE confirmation、safe observation/evidence、request-local hooks 与三类日志边界均已同步到当前文档。最终统一离线回归 `298/298`（`2.753s`）通过；真实 LLM/provider E2E 未运行，作为非阻塞外部可用性验证单独保留。Stage 6 结论为 `go`。

- Stage 7 PlanningRouter、Planner、PlanRepository、PlanningService、PlanController 与 PlanFinalizer 已完成：简单请求保持 Direct ReAct，复杂请求生成 preview-first revision，信息不足返回 NeedUser；Planner 输出不包含 Tool、arguments 或授权。
- PlanRun/PlanStep 已通过 schema V2/V3 持久化，支持跨连接 preview 读取、revision-aware confirm/modify/cancel、durable confirmed constraints、原子 Step result/budget、interrupted stop 与一次 bounded replan。Planning core 依赖 `PlanRepository` Protocol，不直接绑定 SQLite、Domain 或 LangGraph。
- confirmed PlanRun 共享一个 request-local Tool execution scope，每个 Step 使用独立 ReAct state且只接收声明依赖结果；WRITE 继续逐 action confirmation 并以 Gateway evidence 为事实。Finalizer 只读取全部 revision 的 completed safe summaries/evidence，provider 失败使用 deterministic fallback。
- Stage 7 E2E 已覆盖 Research 主链路、Research READ → Travel READ、preview/confirm、request-local handoff、WRITE/零写、replan/reconfirm/exhausted、预算、安全拒绝、stale revision、restart/interrupted 和 Finalizer fallback。Direct/Plan/NeedUser 与 Research happy-path 已完成真实模型 smoke。
- Stage 7 稳定化关闭 cancel 终态、约束丢失、跨 revision Finalizer 汇总和具体 Repository 耦合问题；Executor Context/Memory/Feedback/Recovery hooks 可接收可选 PlanStep identity，PlanningSnapshotProvider 已成为显式可信 scope seam。本轮没有实现 Stage 8/9 业务。
- Stage 7 最终验证为新增/受影响层 `82/82`、Planner 聚焦回归 `79/79`、统一离线回归 `379/379`、`compileall` 和 `git diff --check` 全部通过。完成标准逐项成立，Stage 8 gate 为 `go`。
- Stage 8 Research MCP 计划在 2026-07-15 完成确认并实施关闭：MCP 主线使用本地短生命周期 stdio Server 包装 Hugging Face public paper search，不使用 OpenAlex/API key；论文复用 `ExternalObservation`、Source/Snapshot 和确认保存链，不新增 schema，不修改 Planner/Executor。模型可见 Research Tool 已原子收敛为 9 个；Context / Memory 后移到 Stage 9，Recovery / Feedback 后移到 Stage 10，Calendar MCP 从当前 V1 路线移除。
- Stage 8 实现了通用 one-shot stdio MCP client、只暴露 `search_papers` 的本地 Server、Hugging Face provider façade、Research `PaperSearchPort`/Adapter 与最终业务 Tool surface。`research.search_papers` 显式输出 paper ID、bounded authors/summary、published time、canonical URL 和 provenance；混合非法 provider item 保留合法 observation 并报告 `invalid_count`，全部非法 fail-closed。搜索默认零写，只有确认后的 `save_source` / `link_items` 才形成长期事实。
- Stage 8 最终验证：新增契约收口聚焦测试 `28/28` 通过；统一离线回归执行 `414` 个测试，`412` 通过、`2` 个显式 live gate 跳过；真实 LLM → Direct route → Executor → Gateway → `research.search_papers` → one-shot stdio MCP → Hugging Face public API happy path 在一次 Tool 请求、零 Tool failure、一次成功和 SQLite 零写条件下通过。`compileall` 与 `git diff --check` 通过后，Stage 8 结论为 `go`，Stage 9 gate 为 `go`。
- Stage 9 设计已于 2026-07-15 确认并记录到 `plans/modules/CONTEXT_MEMORY_PLAN.md`；Stage 9A 于 2026-07-16 完成实现和独立 gate。当前 Context 是不绑定 Domain 的 session conversation context，原始 turns/summary 使用每 session JSONL 而不写 SQLite；RuntimeService 在 current input pre-append fail-fast 后只 assembly 一次，Direct、Planning 和 confirmed PlanStep 复用 frozen assembly。Context payload 不进入 GraphState、SQLite、events 或 application log，Domain candidate provider 未接入。
- Stage 9A 最终验证：8 个 compiled E2E、5 个真实 LLM happy paths、`477/477` 统一离线回归、`compileall` 和 `git diff --check` 全部通过；真实路径覆盖 recent Direct、summary + recent Direct、RuntimeService restart、Planner preview 和共享 PlanStep assembly。审计未发现 no-go 条件，结论为 `go`，本计划冻结的 Context/Provider/Projection/日志接口交给 Stage 9B 使用。
- Stage 9B 实施步骤 1-5 已完成：Stage 9A frozen interfaces 回归保持不变；新增固定 `data/memory/profile.md` 语义的只读 `FileProfileProvider`、immutable Memory models/error contracts、SQLite V4 `memory_index` metadata repository，以及 file-first 所需的 immutable UTF-8 Markdown `MemoryDocumentStore`、SHA-256 verified read、安全系统路径、原子替换失败清理和 orphan audit。Profile 不进入 index，SQLite 不保存全文，重复 version 与 stale lifecycle transition fail-closed。聚焦迁移/仓储/文件测试 `24/24` 通过（另有 `1` 项 Windows symlink permission check 跳过），统一离线回归 `503/503` 通过、`9` 项显式 gate/platform checks 跳过。Stage 9B 仍在施工，尚未实现步骤 6 之后的 save transaction、retrieval、Memory Tool、confirmation/Gateway 接入或 ContextAssembly production provider。
- Stage 9B 实施步骤 6-10 已完成：`MemoryService` 使用 file-first/index-second 写入，index 失败留下不可检索且可显式审计的 orphan；`DeterministicMemoryRetriever` 只读取 committed active rows，逐文件验证 SHA-256，按 tag exact、query substring、term overlap、updated_at、memory_id 稳定排序并遵守 item/token budget。规范化 duplicate 幂等复用既有版本，明确 tag/关键词 conflict 在写前返回 candidate；update 使用 active `expected_version` 并原子提交 superseded + active，archive 只改 lifecycle、不删除文件，history/restart 从 SQLite → file → hash 恢复。步骤 6-10 聚焦测试 `27/27` 通过，统一离线回归 `530/530` 通过、`9` 项显式 gate/platform checks 跳过。当前这些 service/retriever 尚未注册为 Tool 或接入 Runtime，因此不会因普通 conversation、summary 或模型推断自动写入 Memory；下一入口是步骤 11 的 memory Skill 与 5 个 Tool schemas/handlers。
- Stage 9B 实施步骤 11-15 已完成：新增 candidate-only `memory` Skill，以及固定 global scope、无 path/user/session 参数的 `memory.save/search/list/update/archive`；WRITE 通过 request-bound `MemoryWriteContext` 接入现有 Policy → AllowedToolSet → exact confirmation → Gateway → pre/post Guardrail → ToolResult/Evidence 链，deny/missing/mismatch/expired/cross-run 均零写。生产 `ContextAssembler` 已使用冻结 provider slots 接入只读 Profile 和 verified active Memory；Memory events 只记录 tool/call identity、status、memory_id/version、idempotent flag、evidence count 或稳定 error code。8 个 compiled E2E 覆盖 Profile、save、duplicate、restart、conflict/update、archive/history、corrupt file isolation 和 non-explicit zero-write；统一离线回归 `552/552` 通过、`9` 项显式 live/platform gates 跳过。下一入口为步骤 16 的 5 个真实 LLM smokes；在 live gate 前不宣称 Stage 9B 或整个 Stage 9 完成。
- Stage 9B 实施步骤 16-18 已完成：5 条独立真实 LLM paths 覆盖只读 Profile、确认前零写/确认后 file+index+evidence、restart verified retrieval、两回合 conflict→explicit update 和 archive lifecycle。真实 provider 在 update 成功后可能追加一次 stale update；optimistic version 与 non-retryable guard 会拒绝额外版本并收敛 catalog。最终 Stage 9A focused `63` 项、Stage 9B focused `81` 项、受影响 Executor `33` 项均零失败；统一离线回归 `561` 项零失败、`14` 项显式 live/platform gates 跳过，`compileall`、`git diff --check`、无自动写入/path exposure/冻结接口/依赖方向审计全部通过。新增 Memory architecture contract 固化 core/context adapter 不依赖 LangGraph、Planner、Executor、Domain 或 Tool System，Tool/observability 依赖只存在于 `memory/tools.py`。未命中 no-go 条件，Stage 9B 结论为 `go`，整个 Stage 9 关闭。

- Stage 5 稳定化步骤 6-11 已完成：公共 Tool schema、依赖方向、Runtime/Tool/Domain contract 与事件 payload 已增加兼容性门禁；每个 run 显式拥有一个 execution scope，同 run 复用、跨 run 隔离。
- Runtime 公共结果已精简，内部 exception、Intent/Policy 摘要和 trace summary 不再进入 `RuntimeResult`；run lifecycle record 与 Domain WRITE transaction 已分离，LLM/external read 不占用 SQLite 写 transaction，异常 run record 可闭合。
- WRITE confirmation 已升级为 `ConfirmedAction`，绑定 run/call/tool/canonical arguments digest/expiry；Evidence 与 Guardrail model 删除无消费者字典/摘要字段。
- Research Context/Memory 已支持 Topic scoped query；Travel 保存 itinerary 前重新验证 quote expiry，同时保持已成功保存结果的幂等重试。
- Observability 已固定单 active session application FileHandler，删除 routine started/completed 普通日志镜像并精简 Intent/Policy event payload。2026-07-13 统一离线回归 `240/240` 通过。
- Stage 5 冻结基线已建立：分层验证八层共执行 `272` 次（含有意重叠）且全部通过，统一回归去重后 `240/240` 通过；公共 Runtime、Skill、Tool、Domain read contract、KnowledgeReference 与语义事件表面由 compatibility / architecture tests 保护。真实 LLM / HTTP provider E2E 仍为非强制集成验证。

- Skill System 已完成核心模型、错误、metadata registry 和原生 discovery / validation；当前严格支持 `name`、`description` frontmatter 子集，不引入 Deep Agents / LangChain loader 或 middleware。
- discovery 只扫描根目录的直接 Skill 子目录，只读取 `SKILL.md` metadata；完整 body 和附属资源仍保持未加载。
- `app/skills/research/SKILL.md` 和 `app/skills/travel/SKILL.md` 已从初始 skeleton 演进为当前领域 workflow 说明，继续只描述候选能力与事实边界，不声明工具权限。
- Skill selector 已通过 `SkillSelectionClient` 薄接口接收 `RuntimeRequest + 全量 Skill metadata`，支持零到多个 Skill；LifeOps 校验严格输出字段、非空 reason、重复 ID 和未知 ID，不依赖框架 selector。
- selected Skill body 已支持按需加载；reference 只能通过 `references/manifest.json` 中的稳定 ID 读取相对 Skill root 的 Markdown 文件，并校验 traversal、文件类型、空正文和大小限制。
- Skill trace 只记录 selection、body load、reference load 的成功或失败语义事件；不记录机械文件 lifecycle，不泄漏用户原文、LLM selection reason、Skill body 或 reference 正文。
- prompt contribution assembler 已实现：只从 selected-and-loaded Skills 生成 `PromptContribution`，保留选择顺序并拒绝重复 Skill ID；core rules、工具描述、Context budget 和最终 prompt 排序仍不属于 Skill System。
- LangGraph allow 路径已接入 request-local `prepare_skills` 和 `execute_tool`：Policy allow 后执行 Skill selection、selected body loading、contribution assembly、filtered Tool selection 和 Gateway；确认与拒绝分支不调用 selector。
- `SkillService` 已收敛为与 Intent/Policy service 对称的构造依赖：它长期持有 `SkillRegistry` 和 `SkillSelectionClient`，并在 graph 构建时注入；只有每个 run 不同的 `TraceSink` 留在 `OrchestrationContext`。GraphState 只保存后续节点需要的 selection 和 contributions；loaded IDs、AllowedToolSet、ToolCall、ToolResult 不重复保存在 GraphState。
- Skill 阶段失败返回 `runtime.skill_failed`，不会继续 `execute_tool`。
- 生产 bootstrap 已调用 `discover_skills(config.skill_root)`，构建 `SkillRegistry`、`SkillSelectionClient()` 和 `SkillService` 后注入 Runtime；`config/default.json` 只负责 Skill root，模型与 OpenAI-compatible provider 地址由 client 直接从 `.env` 读取。
- `SkillSelectionClient` 使用 OpenAI-compatible Chat Completions JSON 输出，只发送用户请求与全量 Skill ID/description，不发送未选中的 body；provider 输出经过 Pydantic 解析和 LifeOps 业务校验。当前只记录关键 Skill event，原始 provider interaction 等统一 LLM Gateway 出现后再集中写入 `llm.jsonl`，不在 `SkillService` 参数中逐层传递日志对象。
- Skill 永久启用，不再提供 `selection_enabled` 配置或 `SkillService is None` 分支；Runtime、Orchestrator 和 graph 都要求显式注入 `SkillService`。
- `tests/fixtures/skills/` 已建立 schema version 1 的长期 Eval case 形状，覆盖 Research、Travel、跨 Domain、零 Skill，以及未知 ID、重复 ID、空 reason 等结构失败。
- Agent Skills specification 和 Deep Agents Skills 仅作为格式、命名约束与 progressive disclosure 的实现参考；框架 adapter 保留为未来边界。
- Tool System 采用 LifeOps 原生安全核心与可选 LangChain adapter；所有工具经过统一 Tool Gateway 和 pre/post Guardrails。
- Tool System 第一步已完成框架无关的核心模型：Tool definition 与 handler 分离，并定义 call/result/error、execution evidence 和结构化 pre/post guardrail decision。
- Tool System 第二步已完成原生 `ToolRegistry` 与 V1 JSON Schema 子集递归校验：definition/handler 在 registry 绑定，重复和未知工具返回 typed error，模型 catalog 不暴露 handler 或授权信息。
- Tool System 第三步已调整为两维 Tool exposure intersection：selected Skills 选出 `ToolDefinition.skill_ids` 匹配的业务候选，空 `skill_ids` 的通用 Tool 始终作为候选；Policy `allowed_effects` 再按 read / external_read / write 过滤并生成 `AllowedToolSet`。Skill 不授权，Policy 不枚举业务 Tool 名，filtered model catalog 只暴露最终集合。
- Tool System 第四步已完成 framework-independent pre/post Guardrails：pre 只消费 authorization 生成的 `AllowedToolSet`，检查 membership、注册、递归 input schema 和结构化 `ConfirmedAction`；post 检查 result identity、成功状态、递归 output schema 和 WRITE evidence。确认绑定 run/call/tool/canonical arguments digest/expiry。
- Tool System 第五步已完成原生 `ToolGateway` 和语义 events：拒绝/确认不触达 handler，handler exception、非法返回和 post 拒绝统一收敛为安全 `ToolResult`；event 不记录原始 arguments、output 或异常文本。当前没有跨 Run 查询消费者，Gateway 不提前写 `tool_calls`；该表仅作为阶段 2 migration 的历史兼容结构保留。
- Tool System 第六步已完成最小 Research Source 纵向切片：handler contract 接收完整 `ToolCall`；Research tools 绑定 Research Skill，fixture-backed READ 产生 request-local observation 且不落库；受控 WRITE 只按当前 observation ID 保存，不能从参数伪造 provenance，并经过 Policy write effect、Gateway confirmation、SQLite transaction 和 post-Guardrail evidence。
- Research Domain 实施步骤 1-2 已完成：补齐 `ResearchTopic`、`ResearchNote`、`ResearchBriefDraft`、`ResearchBrief`、`KnowledgeLink`、`ResearchRevision` 模型与 SQLite migration；repository/service 已支持 Topic、Note、Brief-Source 引用、受目标存在性检查的 KnowledgeLink 和 append-only Revision。Brief draft 与 Source observation 一样保持 request-local，相关新能力尚未接入 Tool Runtime。
- Research Domain 实施步骤 3 已完成：Research Skill 声明 `hf_daily_papers` / `hf_blog` 两个稳定 source key；严格 JSON manifest loader 会拒绝未知 key、路径逃逸、schema 不匹配、非 HTTPS/非 Hugging Face host 和精确 allowlist 外 URL。该步骤只加载可信元数据，不执行网络抓取。
- Research Domain 实施步骤 4 已完成：新增 typed `ResearchContentPort` 与 Hugging Face HTML adapter，抓取前必须解析可信 manifest 声明，抓取时限制 status、redirect、content type、响应大小和 timeout；raw HTML 只保存在 request-local `FetchedSourceDocument`。Papers / Blog parse、URL/title dedupe 和 score/source-order rank 已改为 typed、deterministic、无副作用函数，并通过 fixture、失败路径及现有 Source Tool 回归验证；尚未接入新 Tools 或 compiled Graph。
- Research Domain 实施步骤 5 已完成：`research.fetch_briefing_source`、`research.parse_items`、`research.rank_items`、`research.build_brief_draft` 已注册为 Research Skill 的 EXTERNAL_READ / READ Tools，输出不暴露 raw HTML，并通过 request-local document/item-set ID 传递可信中间状态。中文 draft 包含来源链接和“基于 Hugging Face 列表页可见信息”边界，整个链路不写 SQLite。当前 Direct Executor 每个 run 只执行一个 Tool，完整四步模型循环等待阶段 6 ReAct Executor；当前已通过同一 service、Registry 和 Gateway 的链路测试。
- Research Domain 实施步骤 6 已完成：`research.save_source`、`research.save_brief`、`research.create_note` 均经过 Policy write effect、Gateway structured confirmation、SQLite transaction 和 post-Guardrail evidence。Brief 只按 request-local `draft_id` 保存，并要求 draft 中每个列表页 source URL 已经独立保存为 `ResearchSource`；缺失来源时 fail-closed，不隐式创建 Source。Note 保存确认后的 title/body。
- Research Domain 实施步骤 7 已完成：`ResearchReadService` 实现仓库共享的 `DomainPlanningReadModel`、`DomainContextProvider`、`DomainMemoryCandidateProvider`。fake consumers 已验证 Planner 读取 Topic 覆盖快照、Context 按预算读取带 provenance candidates、Memory 只读取确认保存的 Note / Brief candidates；消费者不直接写 SQL 或提前实现后续模块。另补充稳定排序的 saved-item limit/offset 分页接口。
- Research、Travel 和未来业务 Domain 已统一采用 `plans/DOMAIN_CONTRACT_STANDARD.md`；共享 Port/Tool/Planning/Context/Memory/安全/测试规范。Research 与 Travel 均已实现 `app/domains/contracts.py` 的三个共享只读 Protocol，Travel scope 固定为 Trip ID。
- Research Domain 实施步骤 8 已按确认范围完成：schema version 1 fixture 可 deterministic 生成 120 Source、240 Note、20 Brief，共 380 条长期数据；已覆盖分页稳定/不重叠、Context budget 稳定、timeout、HTTP 503、empty parse、missing link、unsaved Brief source 和 duplicate Source。用户明确允许跳过的 prompt injection / 恶意内容 fixtures 未实现。
- Research Domain 实施步骤 9 已完成并关闭阶段 5 完整初版：补齐 `list_topics`、`research.search_knowledge`、topic filter、unresolved questions、Source metadata/content-hash 去重和 Source/Snapshot 分离。schema v5 可从 v4 迁移旧 Source/Brief 引用；Brief 固定 snapshot，新抓取可为同 URL 追加 snapshot。compiled Graph 已调用真实 briefing handler且不暴露 raw HTML，catalog 外 WRITE 继续由 Guardrail 拒绝。当时全量快照为 182 项；当前数字见上方稳定化事实。
- Travel Domain 完整初版已完成：schema v8 保存 Trip、constraints、Itinerary/items/decision 和稳定 KnowledgeReference；五个 typed fixture-backed Ports/Tools 统一表达 success/no-results/partial-failure/failed；compare/draft 只消费 request-local IDs；`travel.save_itinerary` 只按当前 draft ID 与 idempotency key 经 structured confirmation/transaction/evidence 保存长期事实。旧聚合 option 路径已删除，Tool Runtime 未增加 Travel 特例。
- Tool System 第八步已完成 LangChain adapter 评估并决定当前不实现：本地 `langchain-core 1.4.9` 的 `StructuredTool` 可以包装 callable 与 args schema，但当前没有 LangChain agent/ToolNode 调用方，LifeOps 已有直接 catalog 和完整 Gateway 语义；adapter 反而需要重复 schema/错误转换并桥接 `AllowedToolSet`、confirmation、trace。未来只有出现真实调用方时再以窄 adapter 和 contract tests 接入。
- Tool System 第九步已完成 compiled Graph 的最小 Direct Executor：V1 选择零或一个 ToolCall，并始终经过 filtered catalog、pre/post Guardrails 和 Gateway；完整 ReAct loop 留到阶段 6。
- 阶段 5 E2E 已证明 compiled Graph 可从 START 经过 Skill、Policy、filtered catalog 和两阶段 Guardrail 调用真实 Research 与 Travel handlers；Travel `search_places` 返回 typed observation/candidate，catalog 外 WRITE Tool 被 Guardrail 以 `tool_not_allowed` 拒绝且 SQLite 无写入。
- 两个内部 Domain 从原路线图的 Tasks + Wellbeing 调整为 Research / Personal Knowledge + Travel。
- Research 首个外部只读场景是 Hugging Face Daily Papers / Blog briefing；临时结果不自动保存为知识或 Memory。
- Travel 先定义 typed external Ports 并使用 fixture adapters；真实 Calendar MCP 仍在阶段 10 接入。
- 阶段 5 后的施工顺序已调整为：阶段 6 ReAct Executor、阶段 7 Plan-and-Execute Planner、阶段 8 Context / Memory、阶段 9 Recovery / Feedback，再进入 Calendar MCP 与 Inspector / Eval / DAG。Executor / Planner 先建立外层控制框架和窄扩展接口，后续状态模块通过接口接入。
- Domain 已明确为业务 models/service/repository/tools 的逻辑分组，不是独立 Agent 或执行边界；同一通用 PlanRun 可以交叉调用 Research 与 Travel tools。
- 简单请求走 Direct ReAct；复杂、多步骤或有依赖请求走 Planner preview → confirm → Controller → Executor。PlanStep 只表达 objective、expected outcome 和 dependencies，不绑定 Tool；WRITE 保持逐 action 授权。
- PlanRun / PlanStep 可为跨进程恢复而持久化，但不是业务事实；跨 Domain 部分成功时不做全局回滚，保留成功 evidence，从失败 step 恢复或 bounded replan。
- LangGraph checkpoint 是未来保存 graph/thread state、interrupt、fault tolerance 和 time travel 的候选机制，不负责撤销已经提交的 Domain WRITE 或外部副作用。

当前状态：

- 当前基础设施代码已经完成阶段 2 初版。
- Runtime Core / Intent / Policy 已完成阶段 3 初版。
- Observability 文件日志已完成阶段 3.5 初版。
- LangGraph Orchestration 已完成阶段 4 初版。
- 阶段 5 的 Skill System、Tool System、Research、Travel 与稳定化步骤 1-15 均已完成，Stage 6 gate 为 `go`。
- 阶段 6 ReAct Executor、阶段 7 Plan-and-Execute Planner、Stage 8 Research MCP 与整个 Stage 9 Context / Memory 均已完成并关闭；下一阶段为 Stage 10 Recovery / Feedback。
- 旧 runtime 已归档到 `legacy_v0/app/`。
- 当前代码放在 `app/`。
- 当前计划放在 `plans/`。
- 当前文档放在 `docs/`。
- 旧 V0 代码、数据、日志、测试、输出、MCP demo server、旧计划和旧文档都作为历史参考保存在 `legacy_v0/`，默认不读取。

已实现的当前 runtime 基础设施：

- `app/common/`：配置读取、ID、UTC 时间、项目错误类型和 JSON 序列化。
- `app/storage/`：SQLite 连接、schema migration、`run_records` / `tool_calls` 基础表和 `SqliteUnitOfWork`。
- `app/observability/`：event JSONL、LLM JSONL、application log 的文件日志模型和 writer。
- `app/runtime/`：`RuntimeRequest`、精简 `RuntimeResult`、`RuntimeService`、run record 写入 helper 和启动 bootstrap。
- `app/intent/`：intent models、规则 classifier、LLM classifier 空实现和 `IntentService`。
- `app/policy/`：policy models 和 `PolicyService`；`allowed_effects` 是动作授权结果。
- `app/orchestration/`：`GraphState`、policy route、普通 node 函数、compiled `StateGraph`、`RuntimeOrchestrator` 和 Intent / Policy / route 语义事件。
- `app/planning/`：Planning route、typed plan models/limits、preview command lifecycle、SQLite repository adapter、串行 Controller、bounded replan、Finalizer 和 Planning 语义事件。
- `app/observability/logger.py`：应用拥有的 request-local `TraceSink` 接口；Graph 外关键阶段可继续使用同一事件边界。
- `config/default.json`：声明默认数据库路径 `data/lifeops.sqlite3` 和默认日志根目录 `logs/sessions`。
- `main.py`：当前 CLI 骨架入口，负责 config、SQLite、migration、文件日志 bootstrap 和单轮输入输出。
- `tests/`：基础设施、Intent、Policy 和 Runtime Core 聚焦测试，以及测试数据库 helper。

## 当前 Runtime

旧根入口已归档：

- `legacy_v0/entrypoints/main_legacy.py`
- `legacy_v0/entrypoints/log_viewer_legacy.py`
- `legacy_v0/entrypoints/product_ui_legacy.py`

如果需要按重构前的状态运行旧根入口，请使用 legacy checkpoint branch。

当前 CLI 骨架入口是：

```powershell
uv run python main.py
```

`main.py` 已接入 ReAct、Plan-and-Execute、真实 Research MCP、session Context 与 Long-term Memory 生产读写边界，支持普通输入以及 `confirm-plan`、`modify-plan`、`cancel-plan` 结构化命令；默认无同步 confirmation provider 时所有 WRITE 仍 fail-closed，异步恢复尚未实现，因此仍不是最终产品 CLI。

当前 `main.py` 已接入 `config/default.json`、SQLite migration 和 `RuntimeService`。`RuntimeService` 当前执行：

```text
RuntimeRequest
-> RuntimeOrchestrator
-> classify_intent
-> decide_policy
-> policy conditional route
-> prepare_skills -> route_planning
   -> direct: execute_executor
   -> plan: PlanPreview
   -> need_user: clarification
-> PlanCommand confirm/modify/cancel
   -> PlanController -> ReactExecutor per Step -> PlanFinalizer
-> finalize
-> RuntimeResult
```

阶段 5 已用真实 Gateway 替换 stub：policy `allow` 后仍需经过 Skill candidate、Policy effect、filtered catalog、pre/post Guardrails 才能执行 Tool。`RuntimeService` 仍是外部入口并负责 run lifecycle、短 Domain WRITE transaction 和 event writer；LangGraph 接管 request-local orchestration。测试使用 `:memory:` SQLite、临时日志目录和 fixture providers，不读写真实 `data/lifeops.sqlite3`。

阶段 4 完成后的状态：

- 阶段 2 Storage / SQLite 已完成初版。
- 阶段 3 Runtime Core / Intent / Policy 已完成初版。
- 阶段 3.5 Observability 文件日志校正已完成初版。
- 阶段 4 LangGraph Orchestration 已完成初版。
- `docs/ARCHITECTURE.md` 已记录 Runtime Core、Intent / Policy、LangGraph Orchestration、Skill、Tool Gateway、Guardrails 和 Domain 纵向切片边界。
- `docs/RUNTIME_CONCEPTS.md` 已记录 Runtime Core、Intent Layer、Policy / Permission Layer、Write Safety、LangGraph Orchestrator、LangGraph vs LangChain、Observability 和 SQLite Local Persistence 学习章节。
- `plans/modules/STORAGE_SQLITE_PLAN.md`、`plans/modules/RUNTIME_CORE_PLAN.md`、`plans/modules/INTENT_POLICY_PLAN.md`、`plans/modules/OBSERVABILITY_LOGGING_PLAN.md` 和 `plans/modules/LANGGRAPH_ORCHESTRATION_PLAN.md` 已记录完成状态。
- Stage 6、Stage 7、Stage 8 与整个 Stage 9 Context / Memory 均已关闭；下一施工模块为 Stage 10 Recovery / Feedback。

当前有效测试命令：

```powershell
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'; uv run python -m unittest discover -s tests -v
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'; uv run python -m compileall app tests
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'; uv run python -m unittest tests.test_orchestration_state tests.test_orchestration_nodes tests.test_orchestration_graph tests.test_intent_service tests.test_policy_service tests.test_runtime_service -v
```

## 目标架构

目标 runtime 链路是：

```text
User Input
-> Intent
-> Policy / Permission
-> LangGraph Orchestrator
-> Context / Memory / State Assembly
-> Planner or Direct Executor
-> Tool / Domain / External Integration
-> Execution Feedback
-> Trace / Inspector / Eval
-> Final Answer
```

详细总计划是：

```text
plans/RUNTIME_REFACTOR_PLAN.md
```

## 当前文档规则

默认阅读顺序：

```text
1. README.md
2. docs/PROGRESS_LOG.md
3. docs/ARCHITECTURE.md
4. plans/RUNTIME_REFACTOR_PLAN.md
5. 当前模块对应的 plans/modules/*_PLAN.md
6. 与任务直接相关的代码、测试和文档
```

默认不要读取 `legacy_v0/docs/PROJECT_CONTEXT_legacy.md`、`legacy_v0/docs/LEARNING_PROGRESS_legacy.md` 或 `legacy_v0/plans/*.md`。
