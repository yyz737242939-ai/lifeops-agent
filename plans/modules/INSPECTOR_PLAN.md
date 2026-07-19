# Stage 11A Inspector / Runtime Debugger 模块计划

文档状态：已完成并关闭，Inspector V1 于2026-07-17取得 `go`。步骤1-12、14-15均已完成并逐步验证；原步骤13的正式serial DAG compiled artifact按产品顺序延后为未来DAG模块的跨模块兼容性回归，不再阻塞Stage 11A关闭，也不代表Scheduler已经实现。本计划严格依赖共享 Trace Contract 与 `app/runtime_reporting` 的`RuntimeReport`，不重新定义执行事实、trace storage 或 Eval 标准。

## 1. 模块背景与面试学习目标

LifeOps 已有 semantic events、LLM interaction logs、application logs、Plan state、Tool evidence，并规划了 canonical `ExecutionFeedback`、只读 Recovery 和统一 Trace/Span/Artifact/Annotation 标准。只有日志仍不足以构成 Inspector：真正的 Inspector 必须把一次 run 重建成可导航的 operation tree/dependency graph，显示事实、停点与因果关系，并通过确定性规则定位 first failure 和 downstream effects。

本模块面向学习和面试，目标是实现一个本地、只读、小而完整的 Runtime Debugger：开发者可以按 run/trace/plan 查询，查看 summary、tree、timeline、details、DAG dependencies、evidence/feedback、integrity warnings 和 deterministic diagnoses。它不追求 LangSmith/Phoenix 的完整平台能力，但必须覆盖业界 Inspector 的主体：trace navigation、span details、artifact drill-down、correlation、root-cause finding、privacy 和与 Eval annotations 的互操作。

面试时应能清楚区分：Log Viewer 只按时间展示记录；Inspector 通过 shared read model 重建结构并分析“为什么得到这个结果”；Eval 再用同一个 `RuntimeReport` 自动判分。

## 2. 共享标准与前置条件

本模块只有在以下共享标准步骤完成并通过 gate 后才开始 shared read-model 接线：

- `TraceRecord`、`SpanRecord`、`SpanEventRecord`、`SpanLinkRecord`、`ArtifactReference`、`AnnotationRecord`；
- `trace_id/span_id/parent_span_id/executor_invocation_id` 与 Plan/DAG correlation；
- append-only trace/annotation artifacts 与 legacy event compatibility；
- `TraceStore` / `TraceReader` / `TraceGraph`；
- `RuntimeFactBundle` / `RuntimeReportBuilder` / `RuntimeReport`；
- schema version、privacy、source priority 与 integrity warnings；
- Direct、Planning、Recovery、Eval、serial DAG topology fixtures。

Inspector不拥有或复制这些models。低层Trace/Reader位于`app/observability/`，高层FactProvider/RuntimeReport位于`app/runtime_reporting/`；`app/inspection/`只依赖二者公开Protocol/models。`app/evals/`直接依赖相同边界，不反向依赖Inspector。

2026-07-17 审计结论：上述 shared prerequisite 已由共享标准步骤1-16及其`go` gate满足；ExecutionFeedback / Recovery产品模块也已完成并关闭。正式serial DAG Scheduler及其compiled artifact尚未实现，但shared serial diamond fixture已经冻结tree containment、`depends_on`、partial evidence和blocked语义。经阶段关闭决策，正式Scheduler case归未来DAG模块完成后的Inspector兼容性回归，不再作为Inspector V1自身的关闭前置。

## 3. 当前实现基线

- `LifeOps Trace Contract v1` 已实现immutable Trace/Span/Event/Link/Artifact/Annotation models、append-only `traces.jsonl` / `annotations.jsonl` 与legacy `events.jsonl` compatibility。
- `TraceIndexBuilder`、derived SQLite index、freshness检查和canonical file fallback已实现；index可删除重建，且不是执行或业务事实源。
- `FileTraceStore` / `TraceReader` / immutable `TraceGraph` 已实现；Reader是schema、identity、parent/cycle、event sequence、link、artifact和annotation target完整性的唯一graph reconstruction边界。
- 独立`app/runtime_reporting`已提供typed `RuntimeFactProvider` / `RuntimeFactBundle`、唯一`RuntimeReportBuilder`和Inspector/Eval共享的immutable `RuntimeReport`。
- Stage 10已将Direct/Planning结果收敛为durable canonical `ExecutionFeedback`，完成structured claim/evidence validation，并由deterministic-only `RecoveryRuntime`提供restart-safe只读解释；Feedback artifact、validation/stop/evidence projection与`recovery_of` trace link均已接入shared contract。
- shared deterministic sample annotations与serial diamond fixture已实现；fixture明确tree containment不同于`depends_on` dependency，保留B evidence、C failed、D blocked且D零Tool attempt，但不代表正式Scheduler已实现。
- `app/inspection`现已提供immutable query/result contracts、stable errors、InspectorService、shared reader composition、text/JSON renderer、10条deterministic diagnosis rules、metadata-only ArtifactReference/Evidence view、独立CLI dispatch及可选shared AnnotationSink persistence；结果直接持有shared `TraceGraph` / `RuntimeReport` / `AnnotationRecord`，没有shadow facts。
- shared `RuntimeReport`以additive `workflow_dependencies`投影`depends_on` links，让Inspector diagnosis与未来Eval不回读raw logs或猜边。
- 当前CLI composition默认使用shared `EmptyRuntimeFactProvider`保持trace-only、零业务storage边界；`InspectorService`可注入现有typed `RuntimeFactProvider`消费canonical ExecutionFeedback/Plan projection。Inspector不自行打开业务SQLite，也不把trace补充信息升级为执行事实。
- sensitive artifact content reader明确未配置；`include_sensitive`仍只返回metadata-only和`not_configured`，不会读取prompt、Tool arguments/output、Memory/Profile或异常原文。
- 正式serial DAG Scheduler及`DAG_SCHEDULER_PLAN.md`仍不存在；shared diamond fixture只作为步骤5/6开发证据。
- 当前`main.py`已有普通Runtime与Recovery CLI；不应为Inspector改造outer graph或把inspect command送入Agent natural-language route。
- `tool_calls`历史表未作为当前事实源；Inspector只能消费shared RuntimeReport，不得启用该表或直接读取raw业务表。

## 4. V0 / legacy 决策

本计划不读取或迁移旧 log viewer。V0 viewer 可能提供界面参考，但当前目标是共享 Trace Contract 上的 Runtime Debugger，不是恢复旧文件浏览器。

若实施 CLI renderer 时需要对照一个具体旧输出行为，应先说明并只读对应 viewer/test；不迁移旧 schema、状态或自动 refresh 控制流。

## 5. 本轮范围

- 定义 Inspector-owned query、service、view options、diagnosis registry 与 render result。
- 使用shared `TraceReader`查找/重建trace，并使用唯一shared `RuntimeReportBuilder`构造报告；TraceStore/file/index fallback封装在Reader之后。
- 支持按 `trace_id`、`run_id` 查询；按 `plan_id` 查看跨 trace continuation；按 session 只列安全概要。
- 提供 summary、tree、timeline、span details、workflow graph、evidence/feedback、annotations 和 integrity views。
- 提供 8-10 条 deterministic diagnosis rules，并保存/展示 diagnostic annotations。
- 提供本地 CLI 与 JSON output，供人阅读和测试自动断言。
- 支持 Direct、Planning、Recovery 和 serial DAG demo。
- 读取 shared derived SQLite index；index不可用时允许显式 file-reader fallback。
- 覆盖 privacy、missing/corrupt artifacts、incomplete spans、source conflict 和 restart。

## 6. 明确不做

- 不实现 Web UI、desktop UI、实时 streaming dashboard 或 remote service。
- 不实现 OpenTelemetry Collector、OTLP receiver/exporter、LangSmith/Phoenix integration。
- 不实现 production monitoring、alerts、metrics warehouse、cost dashboard 或 retention platform。
- 不执行/replay/retry/continue Tool、Plan、DAG node 或 Recovery。
- 不修改 RuntimeResult、ToolResult、ExecutionFeedback、PlanRun/PlanStep、Domain facts 或 annotations target facts。
- 不调用 Policy 获取权限，不加载/复用 confirmation，不构造 AllowedToolSet/ToolCall。
- 不把 Inspector query 送进 Intent/Planner/Executor/LangGraph graph。
- 不使用 LLM 作为 v0 diagnosis；可选 LLM explainer留到后续，并必须产生显式 `producer=llm_judge`/assistant annotation。
- 不自行解析 JSONL 推导 success/evidence/not-run；这些必须来自 shared `RuntimeReportBuilder`。
- 不建立 Inspector 专用事实库、trace tables、action模型或 RuntimeReport变体。
- 不显示 private reasoning；不默认展示 raw prompt、Tool arguments/output、Context/Memory/Profile content、confirmation或异常文本。

## 7. 模块边界与依赖方向

建议结构：

```text
app/observability/              shared owner
  trace models/export/read/index/annotations

app/runtime_reporting/          shared high-level read owner
  fact provider/report models/report builder

app/inspection/                 Inspector owner
  models.py                     query/view/result only
  ports.py                      Inspector-facing reader/annotation ports
  service.py                    orchestration of read/report/diagnose
  diagnostics.py                deterministic rules/registry
  renderers.py                  text/json/tree/timeline/details
  errors.py
```

依赖方向：

```text
main.py inspect command (targeted composition; does not build normal Runtime)
  -> app.inspection
     -> app.observability TraceReader/Annotation
     -> app.runtime_reporting FactProvider/RuntimeReportBuilder

Runtime / Planner / Executor / Tool / Domain
  -X-> app.inspection
```

`app/inspection`不被Runtime、Planner、Executor、Tool、Policy、Context、Memory、Recovery core或Domain import。它不依赖LangGraph、provider SDK或具体SQLite connection；storage/file细节由shared TraceReader/fact Ports封装。`app/observability`也不得为构造RuntimeReport反向import这些高层模块。

## 8. 与现有模块的关系

- **Shared Trace Contract**：`app/observability`唯一拥有trace/span/link/artifact/annotation、index和reader；`app/runtime_reporting`唯一拥有FactBundle/RuntimeReport。
- **ExecutionFeedback**：Inspector只显示其 canonical outcome和validation，不重新判断哪些 action成功。
- **Recovery**：Inspector可展示 Recovery trace/stop/explanation metadata，但不生成用户RecoveryContext、不替代RecoveryService。
- **Eval Harness**：未来读取相同RuntimeReport；Inspector只展示evaluation annotations，不实现grader/runner。
- **DAG Scheduler**：Inspector消费workflow/node/dependency/outcome links；不参与ready scheduling或状态转换。
- **Observability**：Inspector查询canonical files/derived index；不改变producer instrumentation。
- **LLM log**：仅在显式敏感view中通过Artifact access port读取；默认summary/tree不读取。
- **application.log**：只作为明确的engineering-detail artifact，不参与success/root cause事实判定。

## 9. Inspector-owned 数据模型

Inspector只定义查询和展示选择，不复制 shared facts：

```text
InspectionTarget
  trace_id? | run_id? | plan_id?
  session_id?

InspectionView
  summary | tree | timeline | details | graph
  evidence | annotations | integrity | diagnose

InspectionQuery
  target
  views
  span_id?
  include_sensitive=false

InspectionResult
  target
  views
  trace_graphs
  runtime_reports
  span_id?
  include_sensitive=false
  diagnostic_annotations
  warnings
```

`trace_graphs` / `runtime_reports`使用对齐tuple以容纳`plan_id`可能关联的多个trace，同时直接持有shared `TraceGraph` / `RuntimeReport`，不定义任何graph/report变体。本步骤不把renderer output放进result；后续renderer直接消费这些shared read models。不新增 `InspectorAction`、`InspectorEvidence`、`InspectorPlanStep`。

## 10. 对外接口

```python
class InspectorService:
    def inspect(self, query: InspectionQuery) -> InspectionResult: ...

class DiagnosticRule(Protocol):
    @property
    def rule_id(self) -> str: ...
    def evaluate(self, report: RuntimeReport) -> tuple[AnnotationRecord, ...]: ...

class InspectionRenderer(Protocol):
    def render(self, result: InspectionResult) -> str: ...

class SensitiveArtifactReader(Protocol):
    def read(self, reference: ArtifactReference) -> SensitiveArtifact: ...
```

`InspectorService` composition inputs：shared `TraceReader`、`RuntimeFactProvider`、`RuntimeReportBuilder`、deterministic rule registry、optional `AnnotationSink`和renderer registry。Inspector不直接从TraceStore records组图。annotation写失败只影响诊断持久化，不影响即时InspectionResult。

## 11. CLI 入口

推荐结构化CLI，不走Agent natural-language route，也不调用production `build_runtime_service()`：

```powershell
uv run python main.py inspect --run-id <run_id>
uv run python main.py inspect --trace-id <trace_id> --view tree
uv run python main.py inspect --plan-id <plan_id> --view graph
uv run python main.py inspect --run-id <run_id> --view diagnose
uv run python main.py inspect --run-id <run_id> --format json
```

可组合views：

```text
--view summary,tree,evidence,diagnose
```

敏感artifact必须显式：

```text
--include-sensitive --view llm
```

v0可先不提供 `llm` view；如果实现，必须是本地、显式、带privacy warning，不把内容复制到普通output或annotation。

CLI parser只增加独立command dispatch；main只构造Inspector read composition，不初始化真实LLM、MCP、ToolRuntime或正常Runtime database。不得改变`RuntimeRequest`、Intent、Policy或outer graph contract。

## 12. Summary view

必须在一屏内回答：

```text
identity / source / status
intent / policy / route
selected skills
plan/workflow status
executor invocations
tool outcomes
execution feedback
stop point
final-answer validation
primary deterministic finding
trace integrity
```

Summary不显示raw inputs/outputs；缺少事实时显示`unavailable`，不从assistant summary猜测。

## 13. Tree view

Tree按parent-child spans展示operation nesting：

```text
RUNTIME
|- INTENT
|- POLICY
|- PLANNER
`- EXECUTOR
   |- LLM
   `- TOOL
      |- GUARDRAIL pre
      `- GUARDRAIL post
```

每行只显示kind/name/status/duration/stable error或business outcome摘要。业务outcome与OTel-like span status分列，避免把`confirmation_required`误显示成系统异常。

## 14. Timeline view

Timeline按timestamp展示spans/events，支持：

- start/end/duration；
-并列标记不同executor invocation/plan step；
- incomplete span；
-跨trace continuation marker；
-event sequence conflict warning。

它不是raw JSON dump；用户可用details view按identity展开。

## 15. Details 与 Artifact view

Details按span显示：

- IDs、parent、kind、name、status、duration；
- safe attributes；
- child spans/events/links；
- related ArtifactReferences和Annotations；
- source fact references；
- integrity/privacy warnings。

默认Artifact只显示type/storage/sensitivity/availability/hash或safe reference。ExecutionFeedback/evidence可以通过typed safe fact provider显示；LLM/tool raw artifacts必须显式敏感读取。

## 16. Planning / DAG graph view

Graph view用dependency links而非parent tree表达workflow：

```text
node_id | dependencies | outcome | executor span | evidence | blocked_by
```

支持：

- Planning revision和Step dependencies；
-跨tracepreview/confirm continuation；
-serial diamond DAG fan-out/fan-in；
-completed/failed/blocked/skipped/not-run；
-partial success evidence保留；
-未知/missing dependency integrity warning。

v0 CLI使用稳定文本/JSON adjacency representation，不引入图形UI或Mermaid生成依赖。

## 17. Deterministic diagnosis rules

v0冻结以下规则，全部只读`RuntimeReport`：

1. `trace_integrity_invalid`：missing parent、cycle、duplicate/conflicting identity、unknown link target。
2. `first_failure`：按因果/topology和时间定位第一个confirmed failure，不把downstream blocked当primary failure。
3. `unsupported_success_claim`：final validation已发现失败/未执行动作被声明成功。
4. `missing_write_evidence`：WRITE success缺少匹配evidence或post-Guardrail拒绝。
5. `policy_tool_mismatch`：实际Tool span/effect不属于当前Policy/AllowedToolSet事实。
6. `confirmation_boundary_violation`：无current exact confirmation却触达WRITE handler，或requires-confirmation后出现不合法执行。
7. `repeated_action_no_progress`：相同/等价action重复且没有新的observation/evidence/progress。
8. `downstream_blocked`：Plan/DAG依赖失败导致的not-run/blocked节点集合。
9. `source_conflict`：Trace、ExecutionFeedback、Plan/Domain higher-priority facts不一致。
10. `sensitive_data_exposed`：普通trace/index/report出现禁止字段或artifact内容。

每条rule产生shared `AnnotationRecord(annotation_kind="diagnostic", producer="deterministic_rule")`，包含stable rule/reason、target trace/span、severity和safe explanation。Rule不能修改RuntimeReport或source facts。

## 18. Primary failure 与因果边界

v0不尝试通用因果AI。`first_failure`使用确定性规则：

1. integrity/source conflict先标warning，不自动作为业务primary failure；
2. 按parent-child、dependency links和timestamp确定已确认failure；
3. upstream failed span优先于由其导致的blocked/skipped nodes；
4. Guardrail deny/confirmation是预期安全stop，分类为control stop，不误标internal error；
5. provider/internal error、contract invalid、post-Guardrail/evidence failure保留原stable code；
6. 无足够关系时输出`primary_failure_unresolved`，不猜测。

## 19. Annotation 生命周期

- 每次inspect基于输入`RuntimeReport`即时计算deterministic findings；report中的`diagnostic_annotations`只代表此前已持久化结果；
-相同`rule_id + target trace/span + source version`应幂等；
-source trace/report变化时生成新annotation version或标记stale，不覆盖旧事实；
-Eval annotations只展示，不由Inspector重算；
-human/LLM annotations明确producer，不能覆盖deterministic finding；
-annotation sink失败时结果仍显示ephemeral findings并给出warning。

本次新finding先进入`InspectionResult.diagnostic_annotations`，再可选追加shared AnnotationSink。`RuntimeReportBuilder`不调用Inspector rules，Inspector也不为显示新finding定义RuntimeReport变体，避免循环依赖。

## 20. 查询、索引与 fallback

默认查询shared derived SQLite trace index：

- by trace/run/plan/session；
-按span/link/artifact/annotation join；
-不读取主业务SQLite中的raw Domain数据。

index缺失/损坏时：

```text
InspectorService -> shared TraceReader -> FileTraceStore fallback
```

fallback显式报告`index_unavailable`，功能可降级为单session/known trace读取；不得偷偷扫描整个logs root。需要跨session查询时先重建index。

## 21. 权限、隐私与安全

- Inspector是本地开发者工具，但仍默认最小披露；
- query必须精确指定trace/run/plan，session list只显示safe metadata；
-不支持任意path输入，artifact path由trusted reference resolver解析；
-拒绝path traversal、unknown storage kind、hash mismatch和cross-session sensitive access；
-JSON output与text output遵守同一redaction，不因机器格式泄漏更多内容；
-diagnostic explanation不得复制raw prompt/output/exception；
-Inspector无ToolRuntime/PolicyService/confirmation provider/PlanController依赖；
-任何trace/report/annotation都不能恢复WRITE权限或成为业务事实。

## 22. Failure modes 与 safe degradation

| 失败 | 行为 |
|---|---|
| trace/run/plan不存在 | stable `inspection_target_not_found` |
| index unavailable | known session/trace file fallback或明确提示重建index |
| trace schema未知 | fail-closed，不猜payload |
| incomplete/corrupt trace |显示合法部分+integrity warning，不宣称run成功 |
| RuntimeFactProvider失败 |保留TraceGraph view，fact-dependent sections标unavailable |
| RuntimeReportBuilder source conflict |高优先级facts优先+`source_conflict` finding |
| diagnostic rule exception |隔离单rule，其他views/rules继续 |
| annotation sink失败 |即时finding保留，标记not persisted |
| renderer失败 |允许JSON fallback；不修改source data |
| sensitive artifact denied/missing |metadata仍显示，content unavailable |
| application log缺失 |不影响execution diagnosis |

Inspector failure不能改变任何Runtime/Tool/Plan/Domain/Feedback/Recovery事实。

## 23. Focused tests

- InspectionTarget/Query/View/Result validation；
- module dependency/architecture tests，证明Runtime/Planner/Executor/Tool不依赖inspection；
- InspectorService使用fake shared TraceReader/FactProvider/ReportBuilder，不解析JSONL或自行组图；
- summary/tree/timeline/details/graph text与JSON deterministic snapshots；
- Direct、Planning、Recovery、Eval annotation、serial DAG fixtures；
- span status vs business outcome显示；
- first failure/control stop/downstream blocked规则；
- unsupported claim/missing evidence/policy mismatch/confirmation/no-progress/source conflict/privacy规则；
- annotation idempotency/stale/producer separation；
- index fallback/corrupt tail/incomplete span/unknown schema；
- sensitive artifact explicit access、path traversal/hash/cross-session拒绝；
- renderer/rule/annotation sink/fact provider failure isolation；
- negative assertions：零Tool/Policy/confirmation/Controller/LLM调用。

## 24. Compiled E2E

使用共享Trace Contract真实reader/index/report，Runtime/模型/外部数据按场景使用deterministic fixture：

1. Direct final-only summary/tree，零Tool span。
2. Direct Tool success，显示Guardrail、evidence与validated answer。
3. Direct Tool failure，定位first failure和safe downstream。
4. Planning preview→confirm跨trace，按plan查看continuation和多个Executor invocation。
5. Planning partial，completed/failed/not-run与ExecutionFeedback一致。
6. Recovery trace，显示`recovery_of`且诊断确认零执行/授权spans。
7. Eval annotations view，展示passed/failed graders但不重算。
8. Serial diamond DAG，B success/C failure/D blocked，tree与graph语义不同且正确。
9. index删除/损坏后file fallback和重建结果一致。
10. corrupt/incomplete/sensitive artifact场景安全降级。

E2E明确断言Inspector对Runtime/Tool/Plan/Domain/Feedback databases/files零写，只有启用annotation persistence时可追加shared annotation artifact。

## 25. 少量真实运行 smoke

Inspector核心不依赖真实模型。共享trace和Stage 10完成后，仅复用已有真实run artifacts做四条read-only smoke：

1. Direct READ trace；
2. Planning preview/confirm traces；
3. Recovery trace；
4.真实模型产生invalid/failed path时的diagnosis（若现有artifact可用）。

smoke只运行Inspector读取，不再次调用provider、Tool或用户数据库；没有合适failure artifact时不为制造场景触发真实WRITE。

## 26. 文档与学习链接

- `docs/AGENT_LEARNING_LINKS.md`：加入LangSmith trace views、Phoenix tracing和OpenAI Agents SDK tracing作为Inspector产品形态/trace instrumentation对照；核心标准继续由共享计划的OpenTelemetry/OpenInference链接拥有。
- `docs/ARCHITECTURE.md`：实施后增加read-only Inspector、dependency direction、shared RuntimeReport和derived index/file fallback。
- `docs/RUNTIME_CONCEPTS.md`：沉淀Log Viewer vs Inspector、tree vs DAG graph、first failure、artifact/privacy、diagnosis annotation和面试讲法。
- `docs/PROGRESS_LOG.md`：只记录已实施/已验证步骤。
- `README.md`、`plans/RUNTIME_REFACTOR_PLAN.md`、`plans/modules/README.md`：Inspector gate后同步状态和CLI入口。

本模块不修改`RECOVERY_PLAN.md`或共享标准的ownership；如实施发现shared RuntimeReport缺字段，先回到共享计划做additive contract change，不在Inspector内部增加shadow model。

## 27. 分阶段实施步骤

1. **确认Inspector范围与shared prerequisite gate（2026-07-17 已完成）。** shared Trace/RuntimeReport与Stage 10前置均为`go`；正式Scheduler最初被识别为步骤13的外部前置，关闭决策已将其调整为未来DAG模块的兼容性回归，依赖矩阵和不做项无ownership冲突。
2. **实现Inspector-owned query/view/result models与stable validation errors（2026-07-17 已完成）。** 新增最小`app/inspection` package，只引用shared `RuntimeReport` / `AnnotationRecord`；6项聚焦测试与17项TraceReader/runtime_reporting compatibility tests通过，不接storage、CLI、renderer或diagnosis。`output_format`留给renderer/CLI步骤，不提前进入pure query contract。
3. **实现InspectorService with fakes（2026-07-17 已完成）。** 只调用shared TraceReader和`app/runtime_reporting` FactProvider/RuntimeReportBuilder，不直接从TraceStore records组图。
4. **实现summary/tree/timeline/details JSON/text renderer（2026-07-17 已完成）。** renderer直接消费对齐的shared TraceGraph/RuntimeReport。
5. **实现Planning/DAG graph renderer（2026-07-17 已完成）。** shared diamond证明tree containment与`depends_on`分离，不引入scheduler依赖。
6. **实现deterministic diagnosis registry（2026-07-17 已完成）。** 10条rules、stable AnnotationRecord、单rule failure isolation；新增shared RuntimeReport dependency projection。
7. **接入shared derived index与file fallback（2026-07-17 已完成）。** index删除后file结果等价并显式`index_unavailable`，不写业务SQLite。
8. **接入safe ArtifactReference details（2026-07-17 已完成）。** metadata-only；敏感content reader未配置。
9. **增加结构化CLI command（2026-07-17 已完成）。** `main.py inspect`独立dispatch，不构造普通Runtime/Recovery或接Agent route。
10. **补齐privacy、integrity、source conflict与annotation persistence（2026-07-17 已完成）。** defensive redaction、safe degradation、views和optional shared sink均有聚焦测试。
11. **运行focused tests和10条compiled E2E（2026-07-17 已完成）。** 新增`tests/test_inspection_compiled_e2e.py`覆盖Direct final-only、Tool success/failure、Planning continuation/partial、Recovery零执行、Eval annotations、serial diamond、index delete/fallback/rebuild及corrupt/incomplete/privacy degradation；compiled E2E `10/10`、Inspector与shared compatibility slice `56/56`通过。
12. **运行统一离线回归、compileall、diff check和架构审计（2026-07-17 已完成）。** unittest discovery记录`730`项，其中`709`项通过、`21`项按既有live/platform环境开关跳过，零失败/错误；完整compileall、diff check和双向依赖扫描通过。Inspector不反向进入Runtime/Planner/Executor/Policy/Recovery/Tool/Domain，`app/inspection`不自行打开/解析raw JSONL。
13. **延后正式serial DAG compiled artifact（2026-07-17 已决策）。** 当前仓库尚无Scheduler计划或实现；正式node outcomes/depends_on links验证移交未来DAG模块，届时作为Inspector跨模块兼容性回归，不重开或反向阻塞已关闭的Inspector V1。
14. **运行4条read-only canonical artifact smoke（2026-07-17 已完成）。** 当前`logs/sessions`中的15个历史session早于Trace Contract且没有`traces.jsonl`，不能作为有效Inspector证据；改用当前`RequestTelemetry + FileTraceExporter`真实落盘生成的Direct、Planning、Recovery、Eval artifacts逐条验证，`4/4`通过。Inspect阶段零Tool/model/Policy/Planner/Executor调用，不修改source artifacts。
15. **同步文档并执行Inspector go/no-go gate（2026-07-17 已完成）。** 当前范围结论为`go`并关闭；正式DAG compiled case和未来真实field artifacts只作为后续兼容性/可用性回归，不代表当前已有Scheduler或可读取旧pre-contract sessions。

## 28. 每一步完成条件

- 步骤1：shared/local owner无冲突，Inspector无Runtime执行依赖。
- 步骤2：public fields、非法target/view/sensitive组合测试通过。
- 步骤3：同一RuntimeReport产生deterministic InspectionResult，不解析raw logs。
- 步骤4：Direct/Planning/Recovery views稳定，span status/outcome不混淆。
- 步骤5：tree containment与dependency graph分别正确，serial DAG fixture通过。
- 步骤6：10条rules可独立运行，单rule失败不影响其他结果。
- 步骤7：index/file读取结果等价，index可删/可重建。
- 步骤8：artifact privacy/path/hash/session boundaries通过。
- 步骤9：CLI不创建RuntimeRequest、不调用orchestrator/Tool。
- 步骤10：source conflict/incomplete/corrupt/annotation failure安全降级成立。
- 步骤11：10条compiled E2E全通过，Inspector除shared annotations外零写。
- 步骤12：统一离线零意外失败，compileall/diff/architecture checks通过。
- 步骤13：延期事实、未来owner与回归条件明确；fixture不冒充正式Scheduler artifact。
- 步骤14：四类canonical file artifact smoke零Tool/model执行，报告与source facts一致；旧pre-contract sessions明确排除。
- 步骤15：文档只记录已实现事实，Inspector V1 gate有直接结论和后续兼容性入口。

## 29. 最终 go/no-go gate

`go` 必须满足：

- Inspector和未来Eval确实共享同一`TraceReader + RuntimeReportBuilder + RuntimeReport`；
- Inspector没有shadow action/evidence/plan/trace models；
- Direct、Planning、Recovery与Eval canonical artifacts可稳定展示；serial diamond fixture只证明当前共享契约兼容，正式Scheduler artifact归未来DAG模块回归；
- tree、timeline、dependency graph和details可定位到trace/span/fact identity；
- 10条deterministic rules输出stable annotations，first failure不把downstream blocked误当root cause；
- index可重建且file fallback成立；
-默认输出不泄漏敏感artifacts；
- Inspector零Tool、零Policy/authorization、零confirmation、零Planner/Executor执行；
- Inspector/renderer/rule/index/annotation failure不修改任何source facts；
- focused、compiled E2E、统一回归、compileall、diff check和read-only smoke通过；
- 实施没有要求大幅修改LangGraph/Planner/Executor/Gateway框架。

任一消费者重新从logs推导success、Inspector可触发执行、trace index成为事实源、diagnosis覆盖ExecutionFeedback、DAG edges只能靠event顺序猜测、或敏感内容默认泄漏，均为`no-go`。

## 30. 面试演示场景

1. **Log Viewer vs Inspector**：同一events展示从线性列表升级为trace tree/RuntimeReport/diagnosis。
2. **Direct Tool failure**：从Policy→Executor→Tool→Guardrail定位first failure并说明handler是否触达。
3. **False success claim**：ExecutionFeedback提供事实，Inspector显示validator finding，不自行解释success。
4. **Planning跨trace**：preview/confirm通过Span Link关联，多Executor invocation可展开。
5. **Serial DAG**：tree显示scheduler包含nodes，graph显示depends_on；C失败导致D blocked。
6. **Recovery只读**：`recovery_of` link和零执行spans证明Recovery不恢复权限。
7. **Inspector/Eval共享**：Inspector展示Eval annotations，二者引用同一RuntimeReport。
8. **Safe degradation**：删除index、损坏tail或隐藏artifact，仍能保守展示合法facts。

## 31. 已确认默认

1. v0只实现CLI + JSON output，不做Web UI。
2. v0只做deterministic diagnosis，不调用LLM；LLM explainer后移。
3. shared `RuntimeReportBuilder`位于独立`app/runtime_reporting`，`app/inspection`不拥有其实现，底层`app/observability`不反向依赖高层事实模块。
4. 默认使用derived index，known trace/session下支持file fallback；不默认扫描全部logs。
5. 默认只显示safe metadata，敏感LLM/artifact view可在后续步骤决定是否实现。
6. diagnosis只追加shared annotations，不建立Inspector database。
7. Inspector不改Runtime/Planner/Executor/Gateway框架，只增加独立CLI dispatch与shared-reader composition。
8. serial DAG graph view纳入首版并由shared fixture冻结消费契约；独立DAG计划完成后必须用正式compiled artifact重跑跨模块兼容性验证，但不反向改变Inspector V1关闭状态。
