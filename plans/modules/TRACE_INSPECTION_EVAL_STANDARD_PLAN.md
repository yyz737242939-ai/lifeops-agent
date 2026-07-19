# LifeOps Trace / Inspection / Eval 共享标准计划

文档状态：步骤 1-16 已完成，shared-standard gate 为 `go`。本计划只冻结 Feedback、Recovery、Inspector、Eval 与未来最小 DAG demo 共用的 telemetry、read model 和 annotation 标准；步骤 8 只提供现有 hook telemetry 与 downstream projection seam，不代表 ExecutionFeedback / Recovery 产品模块已经实现，步骤 13 只提供shared serial diamond fixture，不代表DAG scheduler已经实现。Recovery/Eval 的真实模型 smoke 属于各自产品模块 gate，不反向阻塞共享标准。

## 1. 背景与目标

LifeOps 已有三通道文件日志、typed `ToolResult` / `ExecutionEvidence`、`ExecutorResult`、durable `PlanRun` / `PlanStep`、Context report，以及待实施的 `ExecutionFeedback` / `RecoveryContext`。这些材料已经能解释部分运行路径，但当前仍缺少一份统一标准来回答：一次 run 如何表示为 trace、模块调用如何表示为 span、跨请求 Plan/DAG 关系如何关联、敏感内容如何引用、Inspector 如何读取、Eval 如何对同一运行事实判分。

本计划的目标是建立一套小而完整、接近业界主体概念、适合本地学习和面试讲解的 `LifeOps Trace Contract v1`：

- 以 OpenTelemetry 的 Trace / Span / Span Event / Span Link / Attributes / Status / Context Propagation 为通用骨架；
- 参考 OpenInference 的 `AGENT` / `LLM` / `TOOL` / `GUARDRAIL` / `EVALUATOR` 等 GenAI span 语义；
- 增加 LifeOps-owned 的 Intent、Policy、Planner、Executor、ExecutionFeedback、Recovery、evidence 与权限边界；
- 让 Inspector、Eval Harness、Recovery 和未来 Monitoring 读取同一套标准，不分别发明状态模型；
- 保持 Runtime 执行事实、telemetry、敏感 artifacts、诊断 annotations 与业务事实分离；
- 不追求完整 OpenTelemetry/OpenInference compliance，不引入生产级 observability 平台。

面试学习目标是能够画出并解释：instrumentation → exporter → trace artifacts → derived index → TraceReader → RuntimeReport → Inspector / Eval / diagnosis 的完整链路，以及为什么 trace 不是授权源、annotation 不是执行事实、DAG dependency 不是简单的 parent-child span。

## 2. 业界标准参考与 LifeOps 取舍

### 2.1 采用的核心概念

OpenTelemetry 核心：

- Trace：一次端到端请求的操作集合；
- Span：一个有开始/结束时间的 operation；
- parent span：表示调用/包含层级；
- Span Event：span 生命周期中的重要瞬时事件；
- Attributes：typed key/value metadata；
- Span Status：`UNSET | OK | ERROR`；
- Span Link：跨 trace 或非树形关系；
- Resource / Instrumentation Scope：描述产生 telemetry 的应用和 instrumentation；
- Exporter / Processor / Backend：采集、导出、存储和查询边界。

OpenInference 参考：

- AI-aware span kinds：`AGENT`、`LLM`、`TOOL`、`GUARDRAIL`、`RETRIEVER`、`EVALUATOR`、`PROMPT` 等；
- LLM provider/model、token usage、Tool identity、input/output attributes 和 privacy controls 的语义命名；
- evaluation 作为可关联到原始 trace/span 的独立观测结果。

### 2.2 明确不追求

- 不宣称通过 OpenTelemetry/OpenInference conformance；
- 不实现 OTLP wire protocol、Collector 部署或 vendor backend；
- 不照搬全部 prompt/messages/tool arguments attributes；
- 不记录 private reasoning；
- 不把所有 Domain、Plan、Context 或 Memory object 序列化进 spans；
- 不为未来分布式 tracing 提前引入网络、采样或 multi-service baggage 复杂度。

LifeOps v1 采用“概念和数据形状接近、命名可映射、边界可解释”的学习型子集。

## 3. 当前实现基线

- `LogRuntimeEvent` 已统一 `id/timestamp/session_id/run_id/turn_id/seq/event_type/level/payload`，写入 `events.jsonl`。
- `LogLlmInteraction` 独立写入敏感 `llm.jsonl`，记录 provider/model/request/response/status/error code。
- `application.log` 只承担工程诊断。
- 当前 semantic events 已覆盖 Intent、Policy、route、Skill、Planning、Executor、Tool Gateway、Context、Memory 与 runtime stop。
- `run_id + seq` 可重建线性顺序，但没有 `trace_id/span_id/parent_span_id`、operation duration、Span Link 或统一 event schema version。
- Planning event 带 `plan_id/revision/step_id`，但 Executor/Tool events 尚无统一 `executor_invocation_id`，多 PlanStep 下的 `step_index` 不能单独作为全局 identity。
- `run_records` 只保存 run lifecycle 摘要；`plan_runs/plan_steps` 是 durable execution-strategy state；`tool_calls` 表存在但 Gateway 不写。
- Observability 现行边界明确：原始 event、LLM interaction、application logs 走文件；如果未来需要跨 session 查询，应增加 derived index，而不是让 SQLite 成为第二个原始日志源。
- `RECOVERY_PLAN.md` 已定义 `ExecutionFeedback`、action/evidence/validation 与只读 `RecoveryContext`，但尚未引用统一 Trace/Span/Annotation contract。

## 4. V0 / legacy 决策

本共享标准不读取或迁移 `legacy_v0`。V0 的 viewer、run/action JSON 或旧 trace 只能说明历史需求，不能提供当前 Executor/Planner/Gateway/Context/Memory 的统一模型。当前计划直接基于现行 typed contracts 和 semantic events 设计。

如果实施时需要迁移旧 log viewer 的单个展示行为，应先单独说明原因，只读取对应文件/测试；不把 V0 schema 作为兼容目标。

## 5. 本轮规划范围

- 冻结 `LifeOps Trace Contract v1` 的 models、IDs、status、span kinds、attributes、events、links、artifacts 与 annotations。
- 冻结 Direct、Planning、Recovery、Eval 和未来 serial DAG 的 trace topology。
- 规定 Runtime facts、ExecutionFeedback、trace、artifact、RuntimeReport、diagnosis 和 evaluation result 的 owner/priority。
- 定义 append-only trace artifact exporter、derived SQLite index、TraceReader 与 RuntimeReportBuilder 边界。
- 定义 Inspector、Eval Harness、Recovery 对共享 read model 的消费方式。
- 定义 privacy、redaction、schema version、compatibility、corruption 与 safe degradation。
- 给出 phased implementation、focused tests、compiled E2E、go/no-go 与面试 demo。

## 6. 明确不做

- 本计划不实现 Inspector UI/CLI、Eval runner/graders、Recovery service 或 DAG scheduler；它们按各自模块计划实施。
- 不实现完整 OpenTelemetry SDK/Collector/OTLP、LangSmith、Phoenix 或其他 vendor integration。
- 不实现 distributed tracing、remote context propagation、sampling、tail sampling、metrics backend、alerts 或 production monitoring。
- 不实现 trace replay、time travel、checkpoint resume、自动 retry/continue/rollback/compensation。
- 不保存 raw credentials、authorization headers、confirmation digest、Tool secrets、private reasoning。
- 不让 trace、RuntimeReport、annotation、Eval result、RecoveryContext 或 Inspector output成为 Policy/WRITE 授权源。
- 不启用旧 `tool_calls` 表作为新 trace store。
- 不让 Runtime 同时手写两套不一致的 telemetry records。

## 7. 总体架构

```text
Runtime / Planner / Executor / Gateway / Context / Memory
                         |
       existing TraceSink.append compatibility
                         |
               RequestTelemetry
             /                    \
            v                      v
 legacy semantic events       SpanRecorder
                                   |
                 TraceRecord pipeline
                  /              \
                 v                v
      append-only trace files   optional live viewers
                 |
          TraceIndexBuilder
                 |
       rebuildable SQLite index
                 |
             TraceReader
                 |
             TraceGraph
                 |
       app/runtime_reporting
 RuntimeFactProvider + RuntimeReportBuilder
                 |
            RuntimeReport
          /       |        \
         v        v         v
  Inspector     Eval   Monitoring later
      |           |
      v           v
Diagnostic   Evaluation
Annotation   Annotation

RecoveryService
  -> typed Feedback/Plan/Evidence read Ports
  -> linked read-only Recovery trace
```

关键原则：

- 现有 producers 继续依赖支持 `append(event_type, payload)` 的兼容 Port；`RequestTelemetry` 同时实现兼容 event append 与新 span recording，避免一次性修改所有调用者和测试 fake；
- 新 span instrumentation 通过 capability-aware helper/context manager 渐进接入；仅实现旧 `append()` 的 fake/sink 必须继续可用，span helper 对其安全 no-op；
- canonical telemetry artifact 是 append-only file，不同步依赖 trace database；
- SQLite trace index 是可删除、可重建的查询加速层，不是执行事实源；
- sensitive artifacts 独立存放，trace 只保存安全 reference；
- annotations 是派生判断，不覆盖原始 trace、ExecutionFeedback、Plan state 或 Domain facts。

模块 ownership：

```text
app/observability/
  Trace/Span/Event/Link/Artifact/Annotation models
  RequestTelemetry / SpanRecorder
  exporter / TraceStore / TraceReader / index

app/runtime_reporting/
  RuntimeFactBundle / RuntimeFactProvider
  RuntimeReport / RuntimeReportBuilder
  EvidenceReport and typed safe projections
```

`app/observability` 保持底层基础设施，不 import Planning、Executor、Tool、Recovery 或 Domain models。需要组合这些高层事实的 read model 位于 `app/runtime_reporting`；Inspector/Eval依赖该层，Runtime执行模块不反向依赖它。Recovery core直接使用自己的typed read Ports，不依赖runtime_reporting；其结果之后可被runtime_reporting读取展示。

## 8. Identity 与 correlation 标准

### 8.1 核心 identity

```text
session_id              conversation/session identity
turn_id                 one user/command turn
run_id                  one RuntimeRequest lifecycle
trace_id                observability trace identity
span_id                 one operation identity
parent_span_id          containment/call hierarchy
executor_invocation_id  one independent Executor invocation
call_id                 one ToolCall identity
plan_id/revision/step_id planning identity
workflow_id/node_id     future DAG identity
artifact_id             sensitive/large artifact identity
annotation_id           diagnostic/evaluation identity
eval_run_id             one Eval Harness suite execution identity
```

v1 默认每个 `RuntimeRequest` 创建一个 root trace，允许 `trace_id == run_id` 的简单 adapter，但公共模型不把两者视为同一字段。

### 8.2 Context propagation

使用 request-local immutable `TraceContext` 通过现有 service/context/Port 显式传递：

```text
TraceContext(trace_id, current_span_id, run_id, session_id, turn_id)
```

它不能进入 Policy input、Tool arguments、Domain models、Memory content 或 outer `GraphState` 的业务字段；需要跨 node 的 tracing context 通过 runtime context/composition seam 提供。

### 8.3 跨请求关联

Plan preview、confirm command、Recovery 和 Eval 可能属于不同 traces，使用 Span Link / domain-safe attributes 关联：

```text
plan_continuation
recovery_of
evaluation_of
derived_from
depends_on
```

`session_id`/`plan_id` 是查询键，不替代显式 link semantics。

## 9. 核心数据模型

### 9.1 `TraceRecord`

```text
TraceRecord
  schema_version
  trace_id
  session_id
  turn_id
  run_id
  root_span_id
  source(interactive|compiled_e2e|real_llm_smoke|eval)
  started_at
  ended_at?
  status(unset|ok|error)
  error_code?
  resource_attributes
```

### 9.2 `SpanRecord`

```text
SpanRecord
  schema_version
  trace_id
  span_id
  parent_span_id?
  name
  lifeops_span_kind
  started_at
  ended_at?
  status(unset|ok|error)
  error_code?
  attributes
```

`SpanRecord.status` 表达 operation telemetry status，不直接承载业务 outcome。例如 Executor 按设计停在 `confirmation_required`，span 可以是 `OK`，业务 stop reason 放在 typed attributes/ExecutionFeedback；provider exception 则 span status 为 `ERROR`。

### 9.3 `SpanEventRecord`

```text
SpanEventRecord
  schema_version
  event_id
  trace_id
  span_id
  sequence
  name
  timestamp
  level
  attributes
```

### 9.4 `SpanLinkRecord`

```text
SpanLinkRecord
  schema_version
  link_id
  source_trace_id
  source_span_id
  target_trace_id
  target_span_id?
  link_type
  attributes
```

### 9.5 `ArtifactReference`

```text
ArtifactReference
  schema_version
  artifact_id
  trace_id
  span_id?
  artifact_type
  storage_kind
  safe_reference
  content_hash?
  sensitivity(public|internal|sensitive|restricted)
  created_at
```

### 9.6 `AnnotationRecord`

```text
AnnotationRecord
  schema_version
  annotation_id
  target_trace_id
  target_span_id?
  annotation_kind(diagnostic|evaluation|human_feedback|warning)
  producer(deterministic_rule|llm_judge|human)
  evaluator_id?
  producer_version?
  source_fingerprint?
  eval_run_id?
  eval_suite_id?
  eval_case_id?
  status(passed|failed|warning|informational|skipped|error)
  severity(info|warning|error|critical)?
  score?
  label?
  reason_code?
  safe_explanation?
  created_at
```

LLM-generated annotation 必须标记 `producer=llm_judge`，不能与 deterministic finding 混为一体。

## 10. Span kind 与 LifeOps semantic conventions

冻结 v1 span kinds：

```text
RUNTIME
INTENT
POLICY
SKILL
PLANNER
EXECUTOR
LLM
TOOL
GUARDRAIL
CONTEXT
MEMORY
RECOVERY
EVALUATOR
```

与 OpenInference 的映射：

| LifeOps kind | OpenInference 对照 | 用途 |
|---|---|---|
| `RUNTIME` | `AGENT` / `CHAIN` | root request lifecycle |
| `INTENT` | `CHAIN` | classification operation |
| `POLICY` | `GUARDRAIL` / `CHAIN` | authorization decision，但不是内容 moderation |
| `SKILL` | `CHAIN` | selection/load/assembly |
| `PLANNER` | `AGENT` / `CHAIN` | route/plan/finalizer |
| `EXECUTOR` | `AGENT` | bounded action-observation invocation |
| `LLM` | `LLM` | provider model call |
| `TOOL` | `TOOL` | Gateway-controlled ToolCall |
| `GUARDRAIL` | `GUARDRAIL` | pre/post Tool validation |
| `CONTEXT` | `RETRIEVER` / `CHAIN` | assembly/provider projection |
| `MEMORY` | `RETRIEVER` / `TOOL` | read/write 依具体 operation |
| `RECOVERY` | `CHAIN` | read-only explanation |
| `EVALUATOR` | `EVALUATOR` | grader/judge operation |

LifeOps attributes 使用 namespaced typed keys：

```text
lifeops.runtime.run_id
lifeops.session.id
lifeops.turn.id
lifeops.plan.id
lifeops.plan.revision
lifeops.plan.step.id
lifeops.executor.invocation_id
lifeops.executor.step_index
lifeops.executor.stop_reason
lifeops.tool.call_id
lifeops.tool.name
lifeops.tool.effect
lifeops.tool.outcome
lifeops.evidence.count
lifeops.feedback.validation_status
lifeops.workflow.id
lifeops.workflow.node.id
lifeops.workflow.node.outcome
lifeops.eval.run_id
lifeops.eval.suite.id
lifeops.eval.case.id
```

实现时应对照当时最新 OpenTelemetry GenAI conventions；标准仍处 development 时，优先保留 LifeOps-owned stable keys，并维护映射，不直接让外部 experimental key 成为内部冻结 contract。

## 11. Span、Event、Attribute 的选择规则

- 有明确 start/end、需要 latency/status、可包含子操作：Span；
- span 生命周期内某个重要时间点：Span Event；
- 描述整个 span 的稳定、低基数 metadata：Attribute；
- 大型或敏感内容：ArtifactReference；
- 非树形 dependency/跨 trace：Span Link；
- 诊断、grader、人工判断：Annotation。

示例：

```text
TOOL span: research.save_brief
  attributes: call_id, tool_name, effect
  child: pre-GUARDRAIL span
  event: handler.started
  event: handler.completed
  child: post-GUARDRAIL span
  artifact: safe ToolResult/evidence reference
```

不得把每条现有 semantic event 机械升级为 span，也不得把所有 span 压回一条 event。

## 12. Direct trace topology

```text
RUNTIME runtime.handle
|- INTENT intent.classify
|- POLICY policy.decide
|- SKILL skill.prepare
|  `- LLM skill.select
|- PLANNER planning.route
|  `- LLM planning.route
|- EXECUTOR executor.invoke
|  |- LLM executor.decide.1
|  |- TOOL <tool_name>
|  |  |- GUARDRAIL pre
|  |  `- GUARDRAIL post
|  `- LLM executor.decide.2
|- EVALUATOR final_answer.validate (deterministic operation may be CHAIN/EVALUATOR)
`- Span Event runtime.completed
```

每个 Executor invocation 必须有稳定 `executor_invocation_id`；model decision step index 只在 invocation 内唯一。

## 13. Planning trace topology

Plan preview trace：

```text
RUNTIME
`- PLANNER preview
   `- LLM planner
```

confirm trace：

```text
RUNTIME
`- PLANNER controller
   |- EXECUTOR plan-step-1
   |- EXECUTOR plan-step-2
   `- LLM plan-finalizer
```

confirm root/Controller span 通过 `plan_continuation` link 指向 preview trace；每个 Executor span attributes 带 `plan_id/revision/step_id`。Plan dependency 是 Planning state 的事实，可同时投影为 safe span links，但不把 request-local observations复制成 trace facts。

## 14. Recovery trace topology

```text
RUNTIME recovery.request
`- RECOVERY recovery.explain
   |- Span Link: recovery_of -> source trace
   |- ArtifactReference: RecoveryContext
   `- optional LLM recovery.explainer
```

Recovery trace 不包含 Tool、Policy authorization、confirmation 或 Executor child span。若出现这些 span，contract test 必须失败。

## 15. Eval trace 与 annotation topology

Eval case 的被测 RuntimeRequest 使用正常 trace，并额外标记：

```text
source=eval
eval_run_id
eval_suite_id
eval_case_id
variant_id?
```

Eval runner/graders 自身可以产生独立 EVALUATOR trace，通过 `evaluation_of` link 指向 target trace；每个 grader 结果保存为 `AnnotationRecord`。deterministic grader 不需要 LLM span；LLM-as-judge 必须有 LLM child span、敏感 artifact reference 和 `producer=llm_judge`。

Eval metadata 只进入 observability context，不影响 Intent、Policy、Planner、Tool catalog 或模型业务输入。

## 16. DAG compatibility

未来最小 serial DAG 使用同一 Trace Contract，不改变 Trace/Span 基础模型：

- Scheduler 是 `PLANNER` 或未来扩展 `WORKFLOW` span；
- 每个 DAG node 是独立 Executor/operation child span；
- parent-child 表达 scheduler 包含 node execution；
- `depends_on` Span Links 表达 DAG edges；
- attributes 带 `workflow_id/node_id/attempt/outcome`；
- outcome 至少区分 `pending | ready | running | succeeded | failed | blocked | skipped`；
- OTel span status 与 workflow outcome 继续分离；
- partial success evidence 不因其他 branch failure 被覆盖。

首个 diamond demo：

```text
       B
      / \
A ---    --- D
      \ /
       C
```

Scheduler 串行执行 ready nodes，不实现并发；C failure 时 B 的成功/evidence 保留，D 投影为 `blocked`。Inspector/Eval 首版必须能消费这一形状。

## 17. ExecutionFeedback 与共享标准

`ExecutionFeedback` 不是 Span 的替代品，也不是 annotation：

- Tool/Plan/Domain facts 表达实际结果；
- `ExecutionFeedback` 是当前执行的 canonical safe outcome snapshot；
- Trace 表达 operation path、timing、hierarchy 和 correlation；
- RuntimeReport 将 Trace 与 ExecutionFeedback/Plan state组合；
- Annotation 表达对 RuntimeReport 的派生判断。

Evidence 冻结为三层，避免 Recovery、Inspector、Eval 各自发明同义模型：

```text
ExecutionEvidence
  = ToolResult/Gateway 的 canonical execution fact，继续由 app.tools.models 拥有

ExecutionFeedbackEvidence
  = ExecutionFeedback 持久化的 safe snapshot，保留来源 identity，不升级事实等级

EvidenceReport
  = app.runtime_reporting 生成的统一只读投影，供 Inspector/Eval 使用
```

`ExecutionFeedbackEvidence` 必须从具体 `ExecutionEvidence` 投影；`EvidenceReport` 必须保留 source kind/reference 和冲突 warning。Inspector/Eval 不直接查询 Feedback evidence rows 或 Tool/Domain tables。

共享引用：

```text
Trace/Span -> ArtifactReference(execution_feedback)
RuntimeReport.execution_feedback -> canonical feedback object
Annotation.target_trace/span -> diagnosis/evaluation target
```

`RECOVERY_PLAN.md` 已按此 ownership 调整：通用 identity、artifact、annotation 与 trace contract 由本计划拥有；Recovery plan 只拥有 feedback builder/validator/repository、RecoveryContext 和 RecoveryService。高层 Runtime read model 的实现归 `app/runtime_reporting`。

## 18. 事实源与优先级

```text
1. committed Domain/external fact + ToolResult/ExecutionEvidence
2. PlanRun/PlanStep lifecycle
3. canonical ExecutionFeedback safe snapshot
4. Trace/Span/Event records
5. RuntimeReport derived view
6. deterministic Annotation
7. LLM/human Annotation
8. assistant/Inspector/Recovery text
```

低优先级层不得覆盖高优先级事实。source conflict 必须显式标记并保守降级，不静默择一；trace/index/annotation failure 不改写 RuntimeResult、ToolResult、Plan state 或业务事实。

## 19. 存储与 exporter 策略

### 19.1 Canonical artifacts

继续以 session files 为原始 observability artifacts：

```text
logs/sessions/session_<...>/
  metadata.json
  traces.jsonl       # Trace/Span/SpanEvent/SpanLink/ArtifactRef records
  events.jsonl       # migration compatibility，最终可由 trace events 导出
  llm.jsonl          # sensitive LLM artifacts
  annotations.jsonl  # diagnostic/eval/human annotations
  application.log
```

实施时先提供 compatibility exporter，避免一次性破坏现有 `events.jsonl` tests/reader；只有新 Trace Contract、Inspector/Eval reader 和迁移测试稳定后，才决定是否让 `events.jsonl` 退化为兼容 projection 或继续长期保留。

### 19.2 Derived SQLite index

提供可选、可重建的本地索引：

```text
logs/index/lifeops_trace_index.sqlite3
  traces
  spans
  span_events
  span_links
  artifact_references
  annotations
  indexed_files
```

索引由 `TraceIndexBuilder` 从 canonical files 构建，不在 Runtime 主 transaction 中同步双写；删除索引后可完整重建。索引损坏只影响查询性能/可用性，不改变执行事实。

### 19.3 不使用的表

不复用当前 `tool_calls` 历史兼容表，因为其字段、owner、privacy 和 transaction 语义与 Trace Contract 不匹配。

## 20. Protocol / Port / Service 接口

```python
class TraceSink(Protocol):
    # 保留当前 app.observability.logger.TraceSink 名称和签名。
    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> None: ...

class SpanRecorder(Protocol):
    def start_span(self, input: StartSpanInput) -> SpanHandle: ...
    def add_event(self, event: SpanEventInput) -> None: ...
    def add_link(self, link: SpanLinkInput) -> None: ...
    def add_artifact_reference(self, artifact: ArtifactReference) -> None: ...
    def end_span(self, input: EndSpanInput) -> None: ...

class RequestTelemetry(TraceSink, SpanRecorder, Protocol):
    pass

class TraceExporter(Protocol):
    def export(self, records: tuple[TraceRecordItem, ...]) -> None: ...

class AnnotationSink(Protocol):
    def record(self, annotation: AnnotationRecord) -> None: ...

class TraceStore(Protocol):
    def load_records(self, trace_id: str) -> tuple[TraceRecordItem, ...]: ...
    def find_trace_ids_by_run(self, run_id: str) -> tuple[str, ...]: ...
    def find_trace_ids_by_plan(self, plan_id: str) -> tuple[str, ...]: ...

class TraceReader(Protocol):
    def get_trace(self, trace_id: str) -> TraceGraph: ...
    def find_by_run(self, run_id: str) -> TraceGraph: ...
    def find_by_plan(self, plan_id: str) -> tuple[TraceGraph, ...]: ...

class TraceIndexBuilder(Protocol):
    def index_session(self, session_dir: Path) -> IndexReport: ...

class RuntimeFactProvider(Protocol):
    def load(self, trace: TraceGraph) -> RuntimeFactBundle: ...

class RuntimeReportBuilder(Protocol):
    def build(self, trace: TraceGraph, facts: RuntimeFactBundle) -> RuntimeReport: ...
```

`RequestTelemetry` 是 production composite：实现当前 `TraceSink.append(...)` 兼容接口，并委托 `SpanRecorder` 记录 span。现有  event producers 不要求一次性改签名；新增 instrumentation 使用 shared optional span helper，不直接依赖 exporter。最终 producers 仍只接收一个 request-local telemetry object，不同时手写 legacy event 与 trace file。

`TraceStore` 只负责 canonical records 的定位/读取；`TraceReader` 负责 schema validation、corrupt-tail处理、parent/link校验和 `TraceGraph` 重建。Inspector/Eval 依赖 `TraceReader`，不能从 Store records 各自组图。

## 21. `TraceGraph` 与 `RuntimeReport` 共享 read model

`TraceGraph` 是 telemetry-level read model：

```text
TraceGraph
  trace
  root_span
  spans_by_id
  children_by_parent
  links
  artifacts
  annotations
  integrity_warnings
```

`RuntimeFactBundle` 是 shared、read-only 的事实装配结果：

```text
RuntimeFactBundle
  run_record?
  plan_runs_and_steps
  workflow_state?
  execution_feedback?
  recovery_result?
  execution_feedback_evidence
  evidence_reports
  fact_source_warnings
```

它只通过 typed repositories/read Ports读取，不把业务SQLite rows、raw Tool output或artifact content直接暴露给consumer。其 implementation 属于 `app/runtime_reporting`，不放进底层 `app/observability`。Inspector与Eval必须共享同一`RuntimeFactProvider`，不能分别查询Plan/Feedback/Domain并重新决定事实优先级。

`RuntimeReport` 是 LifeOps-level derived read model：

```text
RuntimeReport
  identity
  route
  intent_decision
  policy_decision
  selected_skills
  context_report
  plan_report?
  workflow_report?
  executor_invocations
  tool_attempts
  execution_feedback?
  recovery_report?
  evidence
  final_answer_validation
  stop_point
  diagnostic_annotations
  evaluation_annotations
  integrity_warnings
```

Inspector 和 Eval Harness 必须使用同一个 `RuntimeReportBuilder`。禁止二者各自从 JSONL 推导 success/failure、evidence 或 not-run。

`diagnostic_annotations` / `evaluation_annotations` 只包含构建报告时已经持久化并由 `TraceReader` 读到的 shared annotations。Inspector 本次运行新计算的 ephemeral findings 放在 `InspectionResult.diagnostic_annotations`，可选持久化；`RuntimeReportBuilder` 不调用 Inspector rule，避免循环依赖。

## 22. Inspector 消费边界

Inspector 只读 `TraceGraph` / `RuntimeReport`，负责：

- tree、DAG graph、timeline、details；
- span/artifact drill-down（按 sensitivity/权限）；
- first failure、downstream blocked、no-progress、missing evidence 等 deterministic diagnosis；
- 展示 ExecutionFeedback、Recovery stop、Eval annotations；
- trace integrity warnings。

Inspector 不修改 trace facts、不执行 Tool、不 replay、不授权、不把自己的摘要持久化成 execution fact。

## 23. Eval Harness 消费边界

Eval Harness 负责：

- `EvalCase` / `EvalSuite` / runner；
- 执行普通 Runtime path并获得 trace identity；
- 通过共享 `RuntimeReport` 调用 deterministic graders；
- `StateChangeGrader`可额外读取Eval-owned、isolated-workspace `EvalStateDelta`；该test oracle不进入RuntimeReport/Annotation，不要求Domain schema增加run identity，也不能覆盖execution facts；
- 保存 `GradeResult` 为 evaluation annotations；
- 区分 compiled deterministic E2E、real-LLM smoke 和 regression eval；
- 失败报告定位到 trace/span/event/fact identity。

初版 graders：

```text
IntentGrader
PolicyGrader
RouteGrader
PlanLifecycleGrader
WorkflowDependencyGrader
ToolCallGrader
StateChangeGrader
EvidenceGrader
ExecutionFeedbackGrader
FinalAnswerGroundingGrader
TraceContractGrader
PrivacyGrader
```

初版不以大规模 LLM-as-judge 为主；LLM judge 是可选 evaluator，不能替代确定性权限、Tool execution、evidence 和 state assertions。

## 24. Privacy 与安全边界

### 24.1 默认可见 metadata

- IDs、operation/span kind、status、stable error code；
- Tool name/effect、evidence count；
- model/provider identity、token counts（provider 可用时）；
- Plan/DAG node identity、dependency IDs、outcome；
- duration、fallback flag、grader labels。

### 24.2 默认不进入 Trace attributes/events

- raw user input；
- prompt/messages/provider response；
- Tool arguments/output；
- Context/Memory/Profile content；
- evidence safe summary/reference（除非专门 artifact access）；
- confirmation/digest/authorization secrets；
- exception text/stack；
- private reasoning。

### 24.3 Artifact access

Inspector 默认只显示 artifact metadata；显式 `--llm` / `--sensitive` 等未来入口必须在本地权限/交互边界内实现。Eval graders优先使用 typed safe facts，不默认读取敏感 artifacts。

## 25. Failure modes 与 safe degradation

| 失败 | 行为 |
|---|---|
| TraceSink/exporter 失败 | 保留主执行结果；写安全 application diagnostic；不得改写 Tool/Plan/Domain facts |
| span 未正常结束 | reader 标记 incomplete span；不得猜测 success |
| unknown parent/link target | `trace_integrity_invalid` warning；隔离错误关系 |
| duplicate same record | 幂等读取/索引 |
| duplicate identity conflicting content | fail-closed，保留冲突 warning，不覆盖 canonical line |
| truncated/corrupt JSONL tail | 保留此前合法 records，标记 source corruption |
| derived SQLite index failure | fallback 到 file reader；索引可删除重建 |
| artifact missing/corrupt | span path仍可读，artifact 标记 unavailable |
| Runtime facts 与 trace 冲突 | 高优先级事实胜出，生成 `source_conflict` finding |
| deterministic grader exception | 单 grader failed，其他 graders继续；不影响 target trace |
| LLM judge failure | annotation unavailable/fallback；不改变 deterministic grade |
| annotation sink failure | 不改变 original trace/report/eval target facts |
| schema version unknown | reader fail-closed 或只读已知 envelope，不默默猜 payload |

## 26. Schema version 与 compatibility

- 每个 trace record 显式携带 `schema_version=1`；
- envelope 与 semantic attributes 分别维护 compatibility；
- v1 内只允许 additive optional fields；删除/改名/语义变化需要新版本或 migration；
- event/span kind、link type、artifact type、annotation reason code 使用冻结 vocabulary；
- reader 对未知 optional attributes 忽略并保留，未知 required version fail-closed；
- compatibility tests 冻结 public model fields、serialized shape、privacy negative assertions 与旧 `events.jsonl` projection。

## 27. Observability 与 metrics 边界

本计划主要实现 traces/log correlation，不实现完整 metrics signal。Span duration、LLM token usage、error/outcome 等 attributes 可供后续派生 metrics，但不提前建设 monitoring backend。

未来 Monitoring 可以从同一 index/report 聚合：failure rate、P95 latency、Tool timeout、unsupported success claims、confirmation rate；它不是 Inspector 或 Eval 的本轮范围。

## 28. Focused tests

- model validation：IDs、timestamps、parent、status、typed attributes、enum vocabulary；
- topology：root uniqueness、parent-child cycle、missing parent、cross-trace parent reject；
- links：plan continuation、recovery_of、evaluation_of、depends_on；
- span/event/attribute selection contract；
- Direct/Planning/Recovery/Eval/DAG topology pure fixtures；
- `executor_invocation_id` uniqueness 与 step index scope；
- exporter append/order/idempotency/corrupt tail；
- compatibility：现有只实现`TraceSink.append`的producer/fake继续工作；optional span helper在无SpanRecorder时安全no-op；
- artifact privacy、hash/reference、missing artifact；
- derived index round-trip/rebuild/delete/fallback；
- TraceReader/RuntimeReportBuilder deterministic output；
- architecture：`app/observability`不importPlanning/Executor/Tool/Recovery/Domain；高层组合仅存在于`app/runtime_reporting`；
- annotation producer/status/target validation；
- event schema version/compatibility；
- sink/index/annotation failure isolation；
- negative assertions：无 raw prompt/user input/Tool arguments/confirmation/private reasoning。

## 29. Compiled E2E

使用真实 Runtime/Planner/Executor/Gateway/Context/Memory 边界与 deterministic providers：

1. Direct final-only：root/Intent/Policy/Skill/Planner/Executor/LLM topology完整，零 Tool span。
2. Direct Tool success：pre/handler/post path、evidence artifact、feedback validation。
3. Direct Tool failure：ERROR/outcome 分离、first failure annotation。
4. Planning preview → confirm 跨 traces：plan_continuation link、多个 executor invocation。
5. Planning partial：completed/failed/not-run facts与 trace一致。
6. Recovery：recovery_of link、零 Tool/Policy authorization span。
7. Eval case：evaluation_of link、deterministic grader annotations。
8. Serial diamond DAG：depends_on links、B success/C failure/D blocked、partial evidence保留。
9. trace exporter/index failure：RuntimeResult/ToolResult/Domain facts不变。
10. restart：从 files重建 index/report，Inspector/Eval读取结果稳定。

## 30. 少量真实模型 smoke

共享标准实现并通过离线 gate 后，复用现有受控 live paths，不新增大规模 suite：

- shared-standard gate 必须运行当前已实现的 Direct READ with Tool 与 Planning preview/confirm；
- Recovery explanation 在 `RECOVERY_PLAN.md` 实现后运行；
- Eval grader 读取真实 trace 的 smoke 在 `EVAL_HARNESS_PLAN.md` 实现后运行；
- 在下游产品尚未实现时，本计划只用 deterministic Recovery/Eval contract fixtures 证明 shared models、links、annotations 和 report compatibility，不伪造真实入口。

smoke 只验证真实 adapter产生的 trace topology、LLM artifact link、token/provider metadata和最终事实一致性。provider/external failure单独报告，不以 trace文案相似度判定。

## 31. 文档更新

计划确认时：

- `docs/AGENT_LEARNING_LINKS.md`：加入 OpenTelemetry traces/signals/semantic conventions 与 OpenInference specification/semantic conventions。

实施时：

- `docs/ARCHITECTURE.md`：更新 Observability 边界、Trace Contract、derived index、facts/artifacts/annotations 和 consumer dependency；
- `docs/RUNTIME_CONCEPTS.md`：新增 tracing、span/event/link、semantic conventions、artifact、annotation、Inspector/Eval共享 read model 和面试讲法；
- `docs/PROGRESS_LOG.md`：仅记录已完成/已验证步骤；
- `README.md`、`plans/RUNTIME_REFACTOR_PLAN.md`、`plans/modules/README.md`：各 gate 后同步阶段状态和阅读入口；
- `plans/modules/RECOVERY_PLAN.md`、`INSPECTOR_PLAN.md`、`EVAL_HARNESS_PLAN.md`：引用本共享标准并保持 ownership/接口一致；
- 后续新增 `DAG_SCHEDULER_PLAN.md`。

本计划会改变当前“仅 semantic events + file reader”的 Observability 架构边界，因此实施前必须显式更新/取代 `OBSERVABILITY_LOGGING_PLAN.md` 中相关后续假设，不能让两个计划同时声称自己拥有 trace storage/read model。

## 32. 分阶段实施步骤

1. **确认共享标准与 ownership matrix。** 确认 Trace/Span/Event/Link/Artifact/Annotation、file canonical + derived index、DAG compatibility 与不做项。
2. **更新下游计划引用。** 收敛 Recovery/Inspector/Eval 计划；创建 DAG计划。只消除 ownership/适配冲突，不提前编码。
3. **实现纯 trace models 与 schema vocabulary。** 无 Runtime、SQLite、LangGraph 或 provider 依赖。
4. **实现 request-local TraceContext 与 ID propagation。** 先覆盖 Direct，证明不进入授权/业务 state。
5. **实现兼容 RequestTelemetry 与 append-only exporters。** 保留当前 `TraceSink.append`、旧测试 fakes 与 `events.jsonl`；新增 span capability、trace/annotation files。
6. **迁移核心 Runtime/Intent/Policy/Skill spans。** 保持现有 semantic events 与测试行为。
7. **迁移 Planner/Executor/LLM/Tool/Guardrail spans。** 加入 executor invocation、plan step、artifact links。
8. **接入 ExecutionFeedback/Recovery trace semantics。** 不扩张 Stage 10 控制流。
9. **实现 TraceIndexBuilder 与 derived SQLite schema。** 证明可删除重建和 file fallback。
10. **实现 TraceStore/TraceReader/TraceGraph。** Store只读records，Reader统一校验和组图。
11. **实现独立 `app/runtime_reporting`。** 通过typed read Ports构造RuntimeFactBundle、EvidenceReport和RuntimeReport，冻结Inspector/Eval共享输入。
12. **加入 annotation core 与 deterministic sample rules/graders。** 只证明 contract，不完成正式 Inspector/Eval产品。
13. **用 serial diamond DAG fixture 验证 links/outcomes。** Scheduler正式实现仍属于 DAG计划。
14. **运行 focused/compiled E2E/统一回归/compileall/diff check。**
15. **运行少量真实模型 smoke。**
16. **同步架构/概念/进度文档并执行 gate。**

## 33. 每一步完成条件

- 步骤 1：字段 owner、consumer、durability、sensitivity、source priority 无未决冲突。
- 步骤 2：Recovery/Inspector/Eval/DAG plans只引用共享 contract，不复制通用模型。
- 步骤 3：纯 model/schema/compatibility/privacy tests通过。
- 步骤 4：IDs在 Direct全链路稳定；Policy/Tool arguments/GraphState无 trace authority leakage。
- 步骤 5：现有append callers/fakes无需批量改签名；文件顺序、crash tail、writer failure和legacy projection测试通过。
- 步骤 6：Runtime root到 route topology完整，原有 event contract回归通过。
- 步骤 7：多 PlanStep invocation唯一可关联，Tool/Guardrail/LLM层级与敏感引用正确。
- 步骤 8：Feedback/Recovery事实与 trace一致，Recovery零执行 span。
- 步骤 9：index可重建、可删除、损坏可fallback，不进入 Runtime transaction。
- 步骤 10：Store/Reader职责清晰，同一records重复组图deterministic。
- 步骤 11：`app/observability`无Planning/Tool/Recovery/Domain反向依赖；Inspector/Eval共享同一report。
- 步骤 12：diagnostic/evaluation annotations不改原始 facts。
- 步骤 13：DAG dependency link、partial success、blocked semantics被共享模型表达。
- 步骤 14：所有离线验证零意外失败。
- 步骤 15：真实 trace topology/metadata无未解释偏差。
- 步骤 16：文档 ownership一致，无旧架构描述冲突。

## 34. 最终 go/no-go gate

`go` 必须满足：

- Direct、Planning、Recovery、Eval、serial DAG fixture均可用同一 Trace Contract表达；
- Trace/Span/Event/Link/Artifact/Annotation概念和官方标准可清晰映射；
- Inspector与Eval使用同一 `RuntimeReportBuilder`；
- current `TraceSink.append`调用者/fakes保持兼容，TraceContext不进入outer GraphState；
- `app/observability`保持低层依赖方向，`app/runtime_reporting`承担高层事实组合；
- `executor_invocation_id`、Plan/DAG identity和跨 trace links可稳定关联；
- canonical files与derived index owner清晰，index可重建且不影响执行；
- trace/annotation失败不改写 Runtime/Tool/Plan/Domain事实；
- sensitive content不进入普通 attributes/events/index；
- Policy/confirmation/Recovery/trace/annotation权限不混淆；
- focused、compiled E2E、统一回归、compileall、diff check通过；
- 文档和模块计划不再维护平行状态/trace标准。

出现以下任一情况为 `no-go`：

- Inspector、Eval、Recovery各自重新解析日志并产生不同 success语义；
- DAG dependency只能靠事件邻近关系猜测；
- trace/index成为执行或授权事实源；
- Runtime同步双写两个不可重建且可能冲突的 canonical stores；
- raw prompt/Tool arguments/confirmation/private reasoning泄漏到普通 trace index；
- annotation覆盖原始执行结果；
- 为满足“业界标准”引入 Collector/OTLP/vendor平台而使学习型实现失控。
- 为StateChangeGrader给所有Domain facts增加run_id或让grader直接解释用户数据库。

## 35. 面试演示场景

1. **Direct Trace Tree**：从 Runtime root 展开 Intent/Policy/Executor/LLM/Tool/Guardrail，解释 span与event区别。
2. **Planning 跨 Trace**：preview与confirm通过 Span Link关联，多个 Executor invocation可唯一定位。
3. **Evidence 与 Artifact**：Tool成功事实、ExecutionFeedback snapshot、敏感 artifact reference和trace metadata分层。
4. **Recovery 是只读消费者**：`recovery_of` link指向原 trace，trace中没有 Tool/authorization span。
5. **Inspector/Eval共享 RuntimeReport**：同一 unsupported success claim同时显示为 diagnosis和failed grader annotation。
6. **Serial DAG**：parent-child表达调度包含关系，depends_on link表达B/C到D依赖；C失败导致D blocked。
7. **Safe degradation**：删除 derived index后从files重建；故意让 exporter/index失败，主执行事实不变。
8. **业界映射**：说明 LifeOps如何覆盖 OpenTelemetry/OpenInference主体概念，以及为何没有实现 OTLP/Collector/大规模平台。

## 36. 已确认默认

以下默认已经确认并冻结：

1. 使用 OpenTelemetry-inspired core + OpenInference-inspired GenAI kinds，不宣称标准 compliance。
2. canonical telemetry 继续走 append-only session files；SQLite只作为可重建 derived index。
3. 新增 `traces.jsonl` / `annotations.jsonl`，现有 `events.jsonl` 先保留 compatibility projection，是否最终退役延后决定。
4. `trace_id` 与 `run_id` v1可同值生成，但公共模型保持概念分离。
5. Inspector、Eval必须共享 `TraceReader + RuntimeFactProvider + RuntimeReportBuilder`；后两者位于独立 `app/runtime_reporting`，不放入底层Observability。
6. deterministic diagnosis/grader优先；LLM judge/explainer只作为显式 annotation增强。
7. Trace Contract预先支持 DAG links/outcomes，但正式 DAG scheduler在 Feedback/Recovery之后、Inspector/Eval之前实现。
8. 敏感内容继续留在专用 artifacts；普通 trace/index只保存安全 metadata/reference。
9. 保持当前`TraceSink.append`兼容；新span能力通过`RequestTelemetry/SpanRecorder`渐进接入，不批量破坏现有调用者和tests。
10. Inspector/Eval可先用diamond fixture开发；两者最终production go gate等待正式serial DAG compiled case。
