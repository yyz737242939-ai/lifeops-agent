# Stage 10 Execution Feedback / Recovery 模块计划

文档状态：步骤 1-17 已完成并验证，Stage 10最终gate为`go`。Stage 10只交付结构化Execution Feedback与解释型Recovery，不实现执行恢复，也不单独建立Trace/Inspector/Eval标准；下一阶段为Stage 11 Inspector / Eval / DAG。

## 1. 模块背景与面试学习目标

Stage 6 已建立有界 `ReactExecutor`、真实 `ToolObservation` / `ExecutorResult`、Feedback sink 与 Recovery hook；Stage 7 已建立 durable `PlanRun` / `PlanStep`、evidence-aware Finalizer 和 interrupted stop 语义。当前缺口是：Direct 执行的完整 observations 仍是 request-local，assistant final text 尚未经过统一的 evidence-aware 校验，restart 后也没有一个只读入口把已有执行事实解释给用户。

本阶段面向面试准备和动手学习，目标是做出一个小而完整的闭环：在当前执行结束时形成结构化事实、校验模型的成功声明、持久化最小必要记录；之后由只读 Recovery 从这些事实解释停点和安全下一步。面试时应能说明事实源、授权源、durable/request-local 分界、部分成功、safe degradation，以及为什么这不是 checkpoint/replay 平台。

## 2. 当前实现基线

- `ToolResult` 与 `ExecutionEvidence` 是 handler 实际观察或改变内容的结构化结果；WRITE success 已由 post-Guardrail 强制要求 evidence。
- `ToolObservation` 是 Executor-owned 的安全投影；`ExecutorResult` 包含 status、stop reason、ordered observations、last Tool result、final message 与 error code。
- `ExecutorFeedbackSink.record(...)` 按 observation 后 final result 的顺序被调用；`ExecutorRecoveryHook.on_stop(...)` 只观察终止结果。两者失败只产生 `executor.hook.failed`，不改写主结果。
- Direct outer node 当前把 `ExecutorResult.final_message` 直接映射为 `RuntimeResult.message`，尚无统一 final-answer validator。
- `PlanRun` / revision / `PlanStep` 已持久化；Step 保存 status、stop reason、safe result summary、error code 和 evidence refs。running Step 在显式读取时可收敛为 `plan_execution_interrupted`，但不会 replay。
- `PlanFinalizer` 已验证 WRITE success claim 必须引用已知 evidence；该思想可以复用，但 Direct 与 Planning 需要共享一套更一般的 claim validation core。
- `events.jsonl` durable 但 content-free，只保存 identity、status、error code 和 evidence count；它适合 observability，不足以单独重建 Direct restart Recovery。
- `run_records` 只保存输入 hash、Runtime summary 与 error code；assistant summary 不是成功事实。闲置的 `tool_calls` 表不在本阶段启用。
- `plans/modules/TRACE_INSPECTION_EVAL_STANDARD_PLAN.md` 已定义 Feedback、Recovery、Inspector、Eval 与未来 serial DAG 共用的 Trace/Span/Event/Link/Artifact/Annotation、identity、file exporter、derived index、TraceReader 和 RuntimeReport 标准；本计划是该共享标准的下游消费者，不重复拥有这些通用模型。

## 3. V0 参考及 legacy 决策

已知 V0 使用 run/action JSON 摘要构造只读 Recovery Context，并阻止无成功 observation 的写入成功声明；它证明“小型解释型 Recovery”可独立于 replay 存在。

本计划不读取或迁移 `legacy_v0`：当前 Executor/Planner/Gateway/evidence/Policy 接口已经提供更清晰的事实和授权边界，V0 的 JSON store、旧 Agent 入口与 continue/replay 语义不适合作为当前实现模板。只有未来需要专门比较旧 claim detector 行为时，才有限读取对应旧 validator 测试，不读取整个 legacy。

## 4. 本轮范围

- 定义最小 immutable `ExecutionFeedback`、action outcome、source-linked `ExecutionFeedbackEvidence`、validation result 与 `RecoveryContext`。
- 从 Direct `ExecutorResult` / observations / Tool results 构造反馈。
- 从 Planning `PlanRun` / revisions / PlanSteps 与每 Step Executor result 构造反馈并关联 durable plan state。
- 复用现有 Feedback sink 作为request-local collector；由RuntimeOutcomeFinalizer在每个run结束时一次性持久化canonical feedback。semantic events继续只是安全投影。
- 使用共享标准提供的 `trace_id`、`span_id`、`executor_invocation_id`、Plan identity、schema version 和 ArtifactReference 进行关联；不在 Recovery 模块内另建 correlation contract。
- 对 Direct 与 Planning final answer 使用共享的结构化 success-claim validator。
- 提供显式、只读、session-scoped 的 Recovery service/runtime 入口，支持指定 `run_id` 与最近一次可恢复 run。
- 生成解释：原目标、停点、成功/失败/未执行动作、durable evidence 和安全下一步。
- 覆盖成功、失败、部分成功、hook/sink degradation 与 restart。
- 将 ExecutionFeedback 暴露为共享 Trace Contract 可引用的 typed artifact，并把 final-answer validation / Recovery lifecycle 投影为共享 span/event；Inspector 与 Eval 后续通过统一 `RuntimeReportBuilder` 消费。

## 5. 明确不做

- 自动 replay、retry、继续执行或新增/扩展 replan 控制流。
- compensation、rollback，或撤销已提交的 Domain / 外部副作用。
- LangGraph checkpoint resume、time travel、跨进程 graph state 恢复。
- 后台恢复、异步任务、分布式 workflow 或通用 fault-tolerance 平台。
- 从 RecoveryContext、历史 Plan、旧 confirmation、旧 ToolCall 或旧 AllowedToolSet 恢复 WRITE 权限。
- 把 RecoveryContext、assistant text、event payload 或 Plan 状态当作业务事实来源。
- 持久化 raw Tool arguments/output、prompt、transcript、Context/Memory content、confirmation digest 或异常文本。
- 启用旧 `tool_calls` 表，或建立第二套逐事件执行日志。
- 在本模块内定义 Trace/Span/SpanLink、ArtifactReference、Annotation、TraceStore、TraceReader、RuntimeReport 或 Eval grader。
- 为 Recovery 单独建立 SQLite trace index、JSONL reader 或 Inspector-facing report。

## 6. ExecutionFeedback 与 Recovery 的职责边界

`ExecutionFeedback` 属于当前执行的结果边界：消费已经完成的 Executor/Planner/Tool 事实，生成 canonical、可持久化的安全 snapshot，并校验 final answer 的结构化成功声明。它不能改变 ToolResult、PlanStep lifecycle、Domain facts 或授权。

`Recovery` 属于后续读取边界：按 session 和 run 读取 feedback、Plan rows 与必要 evidence descriptor，组装只读 `RecoveryContext`，再生成事实解释。它不能调用 Tool、构造 ToolCall、恢复 execution scope、确认或 PlanController。

共享 Trace Contract 属于 observability/read-model 边界：记录 operation path、timing、hierarchy、跨 trace links、artifact references 和 annotations。它不替代 ExecutionFeedback 的 canonical execution outcome；ExecutionFeedback/Recovery 也不拥有 Inspector/Eval 的 trace reconstruction 和 diagnosis。

事实优先级为：Domain/external committed fact 与 `ToolResult`/`ExecutionEvidence` > durable `PlanRun`/`PlanStep` lifecycle > canonical `ExecutionFeedback` snapshot > semantic events。assistant text 永远不提升事实等级。

## 7. 与现有模块的关系

- **Executor**：继续拥有 request-local loop 和 `ExecutorResult`；Feedback builder 只消费公开 models/hooks，不读取 graph internals。
- **Planner**：继续拥有 route、preview、Controller、replan 与 Finalizer；Feedback 不改变 Step 调度。Recovery 读取全部 relevant revisions，区分 completed、failed/stopped、pending/not-run/superseded。
- **RuntimeService**：composition root注入一个可选`RuntimeOutcomeFinalizer`，在Direct/Plan core取得draft result后、completed event/assistant turn/run record前应用validated answer；RecoveryService可独立composition，避免继续膨胀Runtime constructor。
- **Observability**：继续接收兼容当前`TraceSink.append`的`RequestTelemetry`；新增span能力通过shared optional helper使用，不批量修改现有producer/fake。events不成为canonical feedback store。
- **共享 Trace 标准**：本模块消费 shared `TraceContext` 和 identity，在 Feedback finalized 时发布 `execution_feedback` ArtifactReference，在 Recovery 时创建 `RECOVERY` span 与 `recovery_of` link。Trace/export/index failure 不得阻止 feedback repository 或 Recovery deterministic fallback。
- **Runtime reporting / Inspector / Eval**：`app/runtime_reporting`通过typed Feedback read Port构造统一EvidenceReport/RuntimeReport；Inspector/Eval不直接查询Feedback tables，也不从events猜action success/evidence/not-run。
- **Policy**：仍是当前请求的授权事实源。Recovery 请求不产生执行权限，且不进入普通 Policy → Tool execution 链。
- **Tool Gateway**：仍是唯一 Tool 执行入口；Stage 10 只读其结果，不增加旁路。
- **Context / Memory**：RecoveryContext 不写 conversation summary 或 Long-term Memory；若解释模型需要上下文，只接收本次 bounded recovery projection，不能反向成为授权或业务事实。
- **Domain**：已提交副作用保持原样；Recovery 最多展示 evidence descriptor/reference，不直接修改或推断 Domain rows。

## 8. 数据模型

建议在 `app/recovery/` 内保持两个清晰子边界：`feedback_models/builder/repository/finalizer`负责当前run outcome，`recovery_models/context/service`负责之后只读解释。小项目不必拆成两个顶层package，但文件和imports不得混成一个service。

```text
ExecutionFeedback
  feedback_id, trace_id, run_id, session_id, path(direct|planning)
  goal_summary, overall_status, stop_reason, error_code
  executor_invocation_ids, plan_id?, revision?, stop_step_id?
  actions: tuple[ExecutionActionFeedback]
  plan_steps: tuple[ExecutionPlanStepFeedback]
  validation: FinalAnswerValidation
  created_at

ExecutionActionFeedback
  sequence, executor_invocation_id, source_span_id, call_id, tool_name
  tool_effect, outcome, plan_revision?, plan_step_id?
  error_code?, retryable?, evidence: tuple[ExecutionFeedbackEvidence]

ExecutionFeedbackEvidence
  evidence_type, summary, reference?, source_call_id, source_evidence_index

ExecutionPlanStepFeedback
  revision, step_id, position, objective, expected_outcome
  status, stop_reason?, error_code?, evidence_refs

ExecutionClaim
  claim_id, kind, source_run_id, session_id, call_id?
  plan_id?, plan_revision?, plan_step_id?, evidence_refs

FinalAnswerValidation
  claim_status(valid|invalid), output_mode(model|deterministic_fallback)
  reason_codes, accepted_claim_ids

RecoveryContext
  source_trace_id, source_run_id, session_id, goal_summary, path
  stop_point, succeeded_actions, failed_actions, not_run_actions
  durable_evidence, safe_next_steps, generated_at

RecoveryResult
  context, explanation, output_mode(deterministic|model|deterministic_fallback)
  error_code?
```

`outcome` 冻结为 `succeeded | failed | denied | requires_confirmation`。PlanStep 的 `pending`、`stopped`、`failed`、`goal_not_achieved`、`superseded` 等保持 Planner 原始语义；Recovery projection 再明确映射为 completed / failed / not-run，不覆盖 repository row。

`ExecutionEvidence` 继续是 ToolResult/Gateway 的 canonical fact；`ExecutionFeedbackEvidence` 只是其 durable safe snapshot，字段从具体 evidence逐项投影并保留call/index来源。未来`app/runtime_reporting.EvidenceReport`统一向Inspector/Eval展示。不得再定义无来源identity的`DurableEvidence`同义模型。

`trace_id`、`source_span_id`、`executor_invocation_id`、Plan/DAG identity 的格式、唯一性和 propagation 由共享 Trace Contract 拥有；本模块只保存关联值。final-answer validation 是 Runtime 实际采用/降级行为的一部分，仍属于 durable ExecutionFeedback；Inspector diagnosis 和 Eval grade 则属于共享 `AnnotationRecord`，不能反写 validation fact。

`FinalAnswerValidation` 将“claim 是否有效”和“最终答案来源”拆开：`claim_status` 只取 `valid | invalid`，`output_mode` 只取 `model | deterministic_fallback`。false-success 或 validator 内部失败均为 `claim_status=invalid`，同时使用 deterministic fallback；不得用单个 `fallback` 状态掩盖原 draft 无效的事实。

`RecoveryResult` 是一次只读解释请求的 request-local 返回值，不建立第二个 durable repository。当前只产生deterministic explanation，且文本仍是低优先级展示；canonical source 是feedback historical snapshot、原Plan lifecycle rows与evidence descriptor。若需要展示到共享 read model，只投影 typed fact/reference，不把解释文本升级为执行事实。

### 8.1 步骤 1：共享 Trace prerequisite 核对结论

结论为 `go`：Trace Contract v1 已提供稳定的 `trace_id` / `span_id`、`run_id` / `session_id`、`executor_invocation_id` semantic attribute、`plan_id` / `revision` / `step_id`、Tool `call_id` / evidence identity、`ArtifactReference`、schema v1、sensitivity/privacy vocabulary、`recovery_of` link 和 optional projection seam。Recovery core 只需消费这些 value/reference，不依赖 Inspector、Eval、TraceReader、derived index、RuntimeReportBuilder、OpenTelemetry/OpenInference 或 provider SDK。

shared trace exporter、canonical trace file、derived index 或 RuntimeReport 读取失败只减少 observability/read-model 可用性，不能改变 canonical feedback、Tool/Plan/Domain facts 或当前 deterministic fallback。Feedback repository transaction 也不得与 trace exporter/index transaction 绑定。

当前代码有一个后续接入 seam，但不构成 shared-foundation no-go：`executor_invocation_id` 已在 Executor invocation span 入口生成，现有 `ExecutorFeedbackSink.record(...)` / `ExecutorRecoveryHook.on_stop(...)` 尚未接收该值。冻结规则是由 Executor invocation boundary **一次生成并显式传递同一个 ID** 给 span 与 collector；builder、collector、repository 不得重新生成，也不得按 span 顺序、step index 或 call ID 推断。步骤 3 的纯 builder input 必须显式要求该 identity；实际 hook/collector wiring 留到步骤 6。

outer Policy 的 deny / requires-confirmation 也不会产生 ToolCall。步骤 3 的纯 builder input 因此必须接收 typed run gate outcome；步骤 7 再从 current final state 的 route/policy/runtime facts 传入。不得从 assistant message 猜测 gate，也不得为零执行 gate 伪造 `call_id` 或 action row。

### 8.2 步骤 2：冻结 ownership matrix

source priority 使用本计划第 6 节和共享标准第 18 节的顺序；“关联”表示该字段只负责 correlation，不能单独证明成功。

| 字段 / 概念 | owner | canonical source | durability | sensitivity | source priority | consumer | failure behavior |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `trace_id` / `span_id` / `run_id` / `session_id` | shared Observability / Runtime identity | `RequestTelemetry.trace_context` 与 immutable Trace records | Trace canonical files durable；feedback header 保存必要 correlation | internal | 关联，不参与 success 判定 | Feedback、Recovery、RuntimeReport | exporter/index 失败不改 feedback；缺少必需 run/session correlation 时 feedback finalize fail-closed |
| `executor_invocation_id` | Executor invocation boundary，格式/semantic key 归 shared Trace Contract | Executor 进入 `execute` / `execute_step` 时一次生成的同一 value | feedback/action durable；span attribute durable | internal | 关联 | collector、builder、Recovery、RuntimeReport | 不得重生成或推断；collector 缺失时 durability fail-closed、当前执行事实不变 |
| `plan_id` / `revision` / `step_id` | Planner / PlanRepository | durable `PlanRun` / `PlanStep` 与 current `PlanStepExecutionInput` | durable | internal | 2 | Planning feedback、Recovery | unknown/cross-session/stale mismatch fail-closed；不从 trace 或文本修补 Plan lifecycle |
| Tool `call_id` / tool name / status | ToolCall + Gateway / `ToolResult` | current `ToolResult`，`ToolObservation` 仅作安全投影 | Tool result request-local；safe action snapshot durable | internal；arguments/output 默认 sensitive 且不持久化 | 1 | action builder、validator、Recovery | duplicate/unknown/cross-run reference invalid；不得合并不同 call |
| `ExecutionEvidence` | Tool / Gateway | post-Guardrail `ToolResult.evidence`；已提交 Domain/external fact保持自身 owner | 原对象 request-local或由 Domain 持久化；safe descriptor另行投影 | internal 到 restricted，按来源最小披露 | 1 | feedback evidence projector、Plan lifecycle | WRITE success 无 evidence fail-closed；投影失败不删除原 evidence / Domain fact |
| `PlanRun` / `PlanStep` lifecycle | Planner / PlanRepository | repository rows，包括原始 status、stop reason、error、evidence refs | durable | internal | 2 | Planning builder、Recovery | corrupt/conflicting row fail-closed；Recovery projection不得覆盖 repository status |
| request-local collector | ExecutionFeedback 子边界，实现现有 Feedback sink | ordered `ToolObservation` + terminal `ExecutorResult` +显式 invocation/plan identity | request-local；run finalize 后 discard | 可能含 sensitive Tool output，禁止跨 run/落库 | 临时采集，不是独立事实层 | RuntimeOutcomeFinalizer | sink failure不改执行；snapshot不完整时validator保守fallback、durability unavailable |
| `ExecutionFeedback` | ExecutionFeedback 子边界 | builder 对 Tool/Executor/Plan/current gate facts 的一次 run-level safe projection | canonical durable | internal；只含 safe summaries/descriptors | 3 | validator、Recovery、typed Feedback fact provider | 同 run 幂等；内容冲突/跨 session fail-closed；trace/index失败不影响它 |
| Feedback action outcome | ExecutionFeedback snapshot；原始 action fact owner 不变 | `ToolResult.status` / `ToolObservation.status`；零 Tool outer gate来自 typed Policy/runtime gate | durable child row | internal | 1 的投影 | validator、Recovery | 不允许用 final text改写；零 Tool gate不创建 synthetic action |
| `ExecutionFeedbackEvidence` | ExecutionFeedback 子边界 | 逐项投影具体 `ExecutionEvidence`，保留 `source_call_id + source_evidence_index` | durable child row | safe internal descriptor/reference | 1 的投影；低于原 evidence | Recovery、RuntimeFactProvider | source identity缺失/冲突 fail-closed；不得复制 raw output或提升事实等级 |
| final-answer validation result | ExecutionFeedback validator/finalizer | deterministic structured claims 对 current feedback 的判定 | durable，属于 feedback | internal；不保存 raw draft/prompt | 3，且低于 Tool/Plan facts | RuntimeOutcomeFinalizer、Recovery、Eval read model | invalid/validator failure均使用保守 fallback；不反转 execution facts |
| `ArtifactReference` / `recovery_of` | shared Trace Contract | finalized feedback safe reference；Recovery trace显式 span link | append-only trace canonical files；可由 index重建 | 默认 internal，按 artifact可提升 | 关联 | TraceReader、RuntimeReport、Inspector/Eval | projection/export/index失败只降级 observability，不阻止 feedback/Recovery fallback |
| `RecoveryContext` | Recovery 子边界 | feedback historical snapshot + safe evidence descriptors 的 bounded read-only projection | request-local；可有 shared artifact reference但不建业务 repository | internal；不含授权、arguments/output、prompt、confirmation | derived，低于 1-3 | deterministic explanation | source冲突fail-closed或明确 unavailable；不得补写、执行或推断权限 |
| `RecoveryResult` | Recovery 子边界 | `RecoveryContext` + deterministic explanation | request-local；只有 safe trace projection可持久 | internal；当前无model I/O | 文本最低优先级 | CLI / caller、RuntimeReport projection | explanation构造失败返回safe unavailable；不修改 context 或 source facts |
| assistant final text | Runtime presentation / conversation repository | validated model text或deterministic fallback | conversation可 durable，但不是执行事实 | sensitive conversation content | 最低 | 用户界面、Context history | 永远不能反推 action success、evidence、Plan status或权限 |
| `AnnotationRecord` | shared Trace/Eval/Inspector standard | deterministic rule、LLM judge或human annotation | append-only annotation store | internal/sensitive按说明 | 6-7 | Inspector/Eval | 不能成为 ExecutionFeedback，不能改写validation/Tool/Plan facts |
| AllowedToolSet / ToolRuntime / confirmation / Policy authorization | 当前请求的 Policy / Tool runtime | current request-local resolution和exact confirmation | request-local；不进入 feedback/recovery durable payload | restricted | 授权层，独立于恢复事实优先级 | 当前 Executor/Gateway only | Recovery不得读取、重建、复用或授予；历史注入一律fail-closed |

`RuntimeFactProvider` / `RuntimeReportBuilder` 只是下游 typed read boundary：Feedback/Recovery core不 import它们；provider 读取 canonical feedback 后形成 `FactProjection` / `EvidenceReport`，builder 不查询 feedback tables，也不从 events 猜 outcome。

### 8.3 Direct / Planning outcome 分类冻结

| scope | completed | failed | denied | requires-confirmation | not-run |
| --- | --- | --- | --- | --- | --- |
| Direct action | 有真实 `call_id` 且 `ToolResult.status=succeeded` | 有真实 `call_id` 且 status=`failed` | 有真实 `call_id` 且 status=`denied` | 有真实 `call_id` 且 status=`requires_confirmation` | 不创建虚构 action；只有已知候选但没有 Tool attempt 的 run-level projection可说明未执行 |
| Direct run | `ExecutorResult.completed/final_answer`；零 Tool 信息回答允许 completed但 actions为空 | terminal failed，或无成功且 action failed | outer Policy deny，或 Executor `safety_denied` | outer Policy gate，或 Executor `confirmation_required` | 只作为“没有执行动作”的解释维度；若 gate 已知，overall仍优先 denied / requires-confirmation |
| Planning Step | repository `PlanStep.completed` | `failed`、`goal_not_achieved`，或非权限类 `stopped`；保留原 status/stop reason | `stopped + safety_denied` | `stopped + confirmation_required` | `pending` / `superseded` / `cancelled` 且没有 invocation/action/evidence；原 status仍保留 |
| Planning run | 全部 relevant Step completed | 没有 completed且终止于失败类 Step | 没有 completed且终止于 denied Step | 没有 completed且终止于 confirmation Step | preview/cancel等零执行路径；不得把 pending当 failed |

只要同一 Direct run 或 Planning run 同时存在至少一个 verified completed/succeeded fact和任一 failed/denied/requires-confirmation/not-run fact，`ExecutionFeedback.overall_status=partial`。`partial` 不抹掉具体 action/Step 分类。若 Plan row 与 collector 对同一 Step 冲突，按原 Tool/Plan事实优先级保留高优先级事实并使 feedback finalization fail-closed，不自行“修正” repository。

`overall_status` 冻结为 `completed | partial | failed | denied | requires_confirmation | not_run`。validator reason codes 最小冻结为 `claim_declaration_missing`、`claim_action_not_succeeded`、`claim_step_not_completed`、`claim_evidence_missing`、`claim_reference_unknown`、`claim_scope_mismatch`、`validator_failed`；同一次validation可有多个去重且稳定排序的reason。只要本run存在execution action而model draft没有声明structured claims，就以`claim_declaration_missing` fail-closed；纯说明型零action回答保持兼容。模块级safe failure codes最小冻结为`execution_feedback_identity_missing`、`execution_feedback_source_incomplete`、`execution_feedback_source_conflict`、`execution_feedback_persistence_failed`、`recovery_source_unavailable`、`recovery_source_conflict`、`recovery_explainer_failed`。unknown与cross-session lookup对外统一为`recovery_source_unavailable`，避免泄漏其他session是否存在；shared trace exporter/index错误保持Observability自有code，不改写为Feedback/Recovery产品失败。

### 8.4 步骤 3-4 实现确认（2026-07-17）

- 新增`app/recovery/models.py`：冻结Direct/Planning path、action/Step/overall outcome、source-linked evidence、structured claims、validation、RecoveryContext/RecoveryResult等immutable models；preliminary feedback允许`validation=None`，只有后续RuntimeOutcomeFinalizer采用的结果才能持久化final validation。
- 新增`app/recovery/builder.py`：builder input显式接收`executor_invocation_id`、source span、typed outer gate、Plan rows/Executor invocations与Tool System拥有的`ToolEffect`值；builder不读取Registry/AllowedToolSet/GraphState/Runtime、trace exporter或storage。缺少effect/Executor facts使用`execution_feedback_source_incomplete`，identity/Step/evidence冲突使用`execution_feedback_source_conflict`。
- action保存`tool_effect`只为执行WRITE evidence规则，不保存ToolDefinition、catalog或授权。Planning action显式关联revision/step；PlanStep evidence refs必须来自同Step action evidence，pending/superseded/cancelled不得拥有Executor invocation。
- 新增`app/recovery/validator.py`：action/PlanStep success claims必须属于current run/session与精确call/plan/revision/step；WRITE claim必须引用同action/Step evidence；failed/denied/requires-confirmation/not-run、unknown、cross-scope和cross-evidence均fail-closed。invalid或validator内部异常使用只读feedback生成deterministic fallback，不执行Tool或修改原事实。
- 当前`PlanFinalizerOutput`只结构化声明WRITE success与evidence refs；纯adapter将这些refs按唯一PlanStep owner转成shared claims，再复用同一validator。read-only/普通文本不通过关键词扫描生成claim；完整PlanFinalizer structured-claim wiring仍由后续RuntimeOutcomeFinalizer/Planning aggregate步骤完成。
- 新增聚焦测试`21/21`通过，覆盖冻结Fixture 1-5的当前步骤可实现部分、outer gate零synthetic action、source/evidence冲突、WRITE evidence、false success、partial/not-run、cross-run/session、validator failure和PlanFinalizer WRITE claim复用；未实现或运行repository/restart/RecoveryService/CLI/真实模型场景。

### 8.5 步骤 5-6 实现确认（2026-07-17）

- storage schema升级到V5，只新增`execution_feedback`、`execution_feedback_actions`、`execution_feedback_evidence`三张canonical safe outcome表；不新增trace/index表，不保存assistant final text、Tool arguments/output、confirmation或AllowedToolSet。
- `SqliteExecutionFeedbackRepository`只接受已有final validation的Feedback；支持run级精确幂等、冲突fail-closed、session-scoped `get_for_run/get_latest`、文件SQLite重启读取和损坏数据安全失败。unknown与cross-session统一返回`recovery_source_unavailable`。
- Planning Feedback header只保存`plan_id/revision/stop_step_id`引用；save时与现有`plan_runs/plan_steps`逐字段核对，read时从Plan owner rows重建Step projection，没有复制完整Plan JSON或建立第二套lifecycle事实。
- `RequestExecutionFeedbackCollector`按`run_id + executor_invocation_id`保留有序observations、terminal `ExecutorResult`、source span、Tool System提供的effect与optional PlanStep identity；snapshot缺失terminal/effect或identity发生冲突时fail-closed，`discard`只清除目标run的request-local buffer。
- 现有`ExecutorFeedbackSink`显式传递同一个run/invocation/span identity；Tool effect从request-local Registry边界传入，不进入model catalog。hook异常仍由既有隔离逻辑记录`executor.hook.failed`，不改写Tool/Executor结果。collector尚未由Runtime组合或执行run-level finalize/discard；该唯一收口属于步骤7，当前未改变Runtime/Planner/Gateway/CLI行为。
- 步骤5-6相关聚焦切片`70/70`通过，覆盖V1-V5迁移、旧表不重写、隐私列负向断言、Direct/Planning round-trip、restart、幂等/冲突/session isolation、collector顺序/隔离/discard/fail-closed与既有Executor hooks回归；未进入步骤7。

### 8.6 步骤 7-8 实现确认（2026-07-17）

- 新增`app/recovery/finalizer.py`作为唯一run-level收口：读取collector/typed Plan repository，构造preliminary Feedback，执行shared validator，一次best-effort save并在`finally`中discard目标run；repository失败不改写Tool/Executor/Plan事实或已验证当前结果。
- `RuntimeService`在Direct与structured Plan command取得draft后立即调用OutcomeFinalizer，位置早于`runtime.run.completed/failed`、assistant turn与`finish_run_record`；context准备失败按零执行`not_run`处理。未配置finalizer时保持既有composition兼容。
- Direct final output新增Executor-owned request-local `FinalAnswerActionClaim` transport；OpenAI adapter提供`lifeops_submit_final_answer(message, execution_claims)` control，claim只携带call/evidence引用。OutcomeFinalizer再注入current run/session并转换成Feedback-owned `ExecutionClaim`，不通过文本关键词猜成功；普通说明和兼容provider text使用零claim路径。
- Planning `PlanFinalizerOutput`只通过request-local `PlanningRuntimeDraft`跨越Controller→Runtime seam，随后投影回普通`RuntimeResult`；不增加outer `GraphState`字段，也不进入用户可见`tool_result`或durable Plan rows。OutcomeFinalizer合并旧revision completed rows、当前revision rows和多个Executor invocations，只生成一条run-level Feedback，并复用`draft_from_plan_finalizer`校验WRITE/evidence claim。
- preview/awaiting-confirmation形成Planning `requires_confirmation`且零synthetic action；completed/failed/pending分别投影completed/failed/not-run。Feedback只保存通用安全goal摘要，不复制raw user input或Plan goal。
- production bootstrap复用同一个collector注入Executor与OutcomeFinalizer，并共享现有SQLite/PlanRepository；未发布Feedback ArtifactReference、validation trace span/event，因此明确停在步骤9之前。
- 相关切片`163/163`通过；统一离线回归`662/662`通过（另有20条真实模型/外部smoke按环境开关跳过）。覆盖Direct structured WRITE claim、failed action false-success fallback、repository degradation、实际Runtime durable Direct、实际structured Plan command单run aggregate、multi-revision completed history、partial/not-run、PlanFinalizer claim、assistant/run-record顺序及既有Executor/Planning/replan/Trace回归。

### 8.7 步骤 9-13 实现确认（2026-07-17）

- finalized feedback在当前Runtime trace内发布content-free built/validated-or-fallback/persisted-or-failed events和`execution_feedback` ArtifactReference；projection/exporter失败被隔离，不改变canonical feedback或当前安全结果。
- `RecoveryContextBuilder`只从session-owned durable `ExecutionFeedback`构造只读解释输入，显式区分succeeded/failed actions和completed/failed/not-run Plan steps；`RecoveryService`当前只提供deterministic explanation，不接Tool、Policy、confirmation、Controller、Inspector、Eval或provider SDK。
- 新增独立`RecoveryRuntime`和CLI命令`recover-last` / `recover <run_id>`；Recovery-only命令不会构建普通Runtime，unknown/cross-session读取fail-closed，重启读取不保存第二份feedback且不修改Plan rows。
- 每次Recovery创建新的RUNTIME root与RECOVERY span，通过`recovery_of`关联source trace，并投影request-local `recovery_context` ArtifactReference；依赖审计和trace断言证明不存在Tool/Policy/Guardrail/Executor/Planner span。
- semantic attributes/events只含identity、枚举、稳定error code和counts；负向测试覆盖goal/model answer/evidence summary、Tool arguments/output、confirmation和异常文本不进入shared trace。步骤9-13聚焦切片共`80/80`通过，尚未进入步骤14 compiled E2E。

### 8.8 步骤 14-15 测试确认（2026-07-17）

- 新增`tests/test_recovery_compiled_e2e.py`，使用真实outer Runtime graph、Executor subgraph、ToolRuntime/Gateway、Planning Controller、SQLite Feedback/Plan repositories、trace files和RecoveryRuntime，外部模型与Tool来源保持deterministic fixture。
- 十条compiled E2E `10/10`通过：Direct success/evidence、false-success fallback、partial；Planning completed与completed/failed/not-run；restart只读Recovery零新增执行/授权调用；collector/repository degradation；cross-session fail-closed；exporter/index failure隔离；typed RuntimeReport读取Feedback。
- 新增`ExecutionFeedbackFactSource`作为Recovery-owned typed `RuntimeFactSource`：只通过repository Port读取canonical feedback并核对trace ArtifactReference，不解析events、不直接查询Feedback tables，也不把derived index升级为事实源。
- 最终工作树统一离线回归`685/685`通过；另有`20`条真实模型/外部环境smoke按既有环境开关跳过。`python -m compileall -q app tests main.py`与`git diff --check`通过。
- 依赖审计确认RecoveryService/RecoveryRuntime无ToolRuntime、Policy、confirmation、PlanController、Inspector或Eval依赖；未新增checkpoint/replay/resume/rollback/time-travel能力，未修改`legacy_v0/`。步骤15结束后尚未进入步骤16真实模型smoke。

### 8.9 步骤 15.5 兼容性与解耦审计修复（2026-07-17）

- storage schema升级到V6，新增`execution_feedback_plan_steps`历史快照表。`PlanRun`/`PlanStep`仍是Planner lifecycle owner；Feedback只在finalize时保存已经核对过的safe outcome projection，restart读取不再被后续可变Plan row漂移改写。
- 有execution action但零structured claims的model draft以`claim_declaration_missing` fail-closed，避免兼容文本在失败事实之上绕过validator；零action说明型回答不受影响。
- `ExecutionFeedbackRepository` Port移到`app/recovery/ports.py`，SQLite实现留在repository模块；Recovery保持deterministic-only，不引入provider SDK或未接线的explainer协议。
- `ExecutionFeedbackFactSource`补齐validation、stop point和evidence投影；`RecoveryResultFactSource`只投影request-local safe facts。Trace artifact与durable feedback指向同一evidence reference时，`RuntimeReport`稳定去重。
- Executor feedback sink与Runtime outcome finalizer通过签名过滤兼容旧实现，内部`TypeError`不重试，避免重复副作用；request-local collector增加并发锁并以双run测试证明隔离。
- 修复后聚焦切片`87/87`通过；统一离线回归`692/692`通过（另有20条真实模型/外部smoke按环境开关跳过）。

### 8.10 步骤 16 真实模型 smoke 确认（2026-07-17）

- 真实Direct READ success通过：真实Planning router保持single-tool request为Direct，真实Executor模型生成current-call structured claim，公共Research MCP返回结果；source trace、LLM/Tool spans、Feedback ArtifactReference、durable valid Feedback、restart deterministic Recovery与`recovery_of` link一致。
- 真实Planning preview/confirm completed通过：保留上一模块的`plan_continuation`与LLM metadata contract，同时验证单条run-level Planning Feedback、historical Step snapshot和restart Recovery。
- 真实Tool failure + confirmation denial通过：provider failure未被assistant改写为成功，旧confirmation/WRITE权限未被Recovery复用；Recovery trace只有`RUNTIME + RECOVERY`。
- 真实Planning partial通过：第一步Research READ成功、后续Travel provider失败并经过受限replan后，Feedback仍按action-level失败保留`partial`，Recovery同时解释verified success与failure/not-run，不被最终Plan completion覆盖。
- smoke中修复三处真实adapter语义：single named Tool call不得误路由Plan；successful observation被答案使用时必须声明current call claim且只能复制真实non-null evidence reference；Planning overall outcome必须合并Step与action outcomes。
- smoke后统一离线回归`696/696`通过，另有`21`条环境开关测试跳过；步骤16没有发现未解释的Trace/Feedback/Recovery产品偏差。

## 9. Protocol / Port / Service 接口

```python
class ExecutionFeedbackBuilder(Protocol):
    def from_direct(...) -> ExecutionFeedback: ...
    def from_plan(...) -> ExecutionFeedback: ...

class RequestExecutionFeedbackCollector(ExecutorFeedbackSink, Protocol):
    def snapshot(self, run_id: str) -> CollectedExecutionFacts: ...
    def discard(self, run_id: str) -> None: ...

class ExecutionFeedbackRepository(Protocol):
    def save(self, feedback: ExecutionFeedback) -> None: ...
    def get_for_run(self, session_id: str, run_id: str) -> ExecutionFeedback: ...
    def get_latest(self, session_id: str) -> ExecutionFeedback | None: ...

class FinalAnswerValidator(Protocol):
    def validate(self, draft: FinalAnswerDraft, feedback: ExecutionFeedback) -> ValidatedFinalAnswer: ...

class RuntimeOutcomeFinalizer(Protocol):
    def finalize(
        self,
        request: RuntimeRequest,
        draft: RuntimeResult,
        *,
        trace_id: str,
        trace: TraceSink | None = None,
        gate_outcome: RunGateOutcome | None = None,
        plan_finalizer_output: PlanFinalizerOutput | None = None,
    ) -> RuntimeResult: ...

class RecoveryContextBuilder(Protocol):
    def build(self, feedback: ExecutionFeedback) -> RecoveryContext: ...

class RecoveryService:
    def explain_run(self, session_id: str, run_id: str | None = None) -> RecoveryResult: ...
```

现有 `ExecutorFeedbackSink` 由 request-local-aware production collector实现：按`run_id + executor_invocation_id + optional plan_step`收集observations和每次ExecutorResult，但不在每次Executor结束时保存run-level canonical feedback。Planning同一Runtime run可包含多个Executor invocation，若sink直接finalize会重复/冲突写同一`run_id`。

唯一run-level收口点是`RuntimeOutcomeFinalizer`：在Runtime取得draft `RuntimeResult`后读取collector snapshot；Direct调用`from_direct`，Planning根据`tool_result.plan_id/revision`通过typed PlanRepository读取全部相关steps再调用`from_plan`；随后执行answer validation、一次性保存canonical feedback并返回validated RuntimeResult。它不修改PlanController/replan调度。

`ExecutorRecoveryHook` 保持只读通知/兼容 seam，不承担存储、aggregate或解释主逻辑，避免两个hook竞争事实所有权。

Trace integration只通过shared RequestTelemetry/SpanRecorder capability：Feedback finalized后记录safe ArtifactReference与validation span/event；RecoveryService接收shared TraceContext，建立`RECOVERY` span和`recovery_of` link。仅实现旧`append()`的test fake仍可运行。Recovery core/repository不依赖exporter、derived index、runtime_reporting、Inspector或Eval implementation。

## 10. durable state 与 request-local state

业务/runtime SQLite 新增 `execution_feedback`、`execution_feedback_actions`、`execution_feedback_evidence`与`execution_feedback_plan_steps`。Planning lifecycle继续以现有 `plan_runs` / `plan_steps` 为 owner；最后一张表只保存finalize时已与owner rows核对的safe historical outcome projection，防止restart解释被之后的Plan状态变化改写，不复制完整Plan JSON。feedback header 可保存 shared trace correlation、plan identity、stop point、validation outcome；action/evidence/step snapshot使用可查询 child rows，不把 opaque JSON blob 作为唯一事实源。

这些 feedback tables 是 canonical safe execution outcome，不是 trace store。共享标准的 trace metadata 仍写 append-only session files；未来 SQLite trace index 位于 observability logs 边界、可从 files 重建，不能与 feedback repository transaction 绑定。

必须 durable：trace/run/session correlation、path、goal 的安全摘要、overall stop、executor/action identity/outcome/error、safe evidence descriptor、plan/step identity、validator outcome、timestamps。这样 Direct 与 Planning 均可在 restart 后生成必要解释。

只需 request-local：collector中的完整`ExecutorResult`/ToolObservation、Tool output/arguments、AllowedToolSet、confirmation、ToolRuntime、ExecutorState、GraphState、prompt/transcript、ContextAssembly、模型draft、Recovery model input/output object。collector在run finalization后必须discard；不得跨run复用。

`ExecutionFeedback` 是执行事实的安全 snapshot，不取代原始 ToolResult、Plan repository 或 Domain facts。保存采用短 transaction；同一 `run_id` 的 finalized feedback 幂等，内容冲突 fail-closed。

## 11. Direct 执行流程

```text
ReactExecutor action -> ToolGateway -> ToolResult/Evidence
-> ToolObservation -> existing Feedback sink buffers safe action fact
-> ExecutorResult
-> Runtime draft result
-> RuntimeOutcomeFinalizer (single run-level boundary)
-> ExecutionFeedbackBuilder.from_direct creates preliminary facts
-> validate structured final claims against preliminary facts
-> persist finalized canonical feedback once
-> valid model text OR deterministic safe fallback
-> RuntimeResult
```

`RuntimeOutcomeFinalizer`位于当前`RuntimeService._handle_core`取得graph result之后、记录`runtime.run.completed`之前；validated result随后才进入conversation assistant turn和`finish_run_record`。这样无需修改各node的`RuntimeResult(...)`构造点，未校验文本也不会先写入conversation。

零 Tool 的信息性回答允许没有 action claims。存在 Tool 时，成功只能来自 current run 的 succeeded action；失败、denied、requires-confirmation 不得被描述为已完成。collector/repository失败不改写ExecutorResult/ToolResult；只要request-local snapshot仍完整，validator继续执行，Recovery durability相应降级并写安全事件。

## 12. Planning / PlanStep 执行流程

每个 `PlanStep` 继续由独立 Executor invocation 执行，并通过 `plan_step` identity 把 action feedback 关联到 plan/revision/step。PlanController 仍以结构化 Executor result 和 WRITE evidence 决定 Step status；Feedback 不参与调度。

Plan终止时同一个`RuntimeOutcomeFinalizer`根据draft result中的`plan_id/revision`通过typed PlanRepository读取当前及必要旧revision facts，并合并collector中的多个Executor invocations，形成一次plan-level feedback：保留completed Step，标出failed/stopped Step，并把尚未claim的pending Step投影为not-run。replan前completed facts/evidence不丢失，superseded Step不误报为失败或执行过。

PlanFinalizer产出结构化claims后由RuntimeOutcomeFinalizer使用共享validator；invalid claim返回deterministic plan fallback，不反转已经完成的PlanRun/Step或Domain fact。PlanController不新增Feedback repository或调度hook。

## 13. final answer 校验规则

模型 final output 扩展为 `FinalAnswerDraft(message, execution_claims)`；每个 claim 必须结构化引用当前 run 的 `call_id` / `plan_step_id` 和 evidence refs。validator 不用中英文成功关键词扫描作为安全核心。

确定性规则：

1. 未声明执行成功的普通说明/建议可通过；建议必须保持未来式，不能进入 success claims。
2. action success claim 必须对应 current run、相同 ToolCall 且 outcome 为 succeeded。
3. WRITE success claim 至少引用一个该 action 实际产生的 evidence；READ/external-read 若声称取得具体结果，也必须关联 succeeded action，允许 evidence 为空时只描述“调用成功”，不得虚构 durable fact。
4. failed、denied、requires-confirmation、pending/not-run/superseded action 或 Step 不能出现在 accepted success claims。
5. Planning Step success claim 必须对应 completed Step；涉及 WRITE 时 evidence refs 必须是该 Step 已知集合的子集。
6. 未知、跨 run、跨 session、重复冲突或缺失引用均 invalid。
7. invalid 时不自动让模型重试、不执行 Tool；返回 deterministic fallback，逐项列出已证实成功、失败、未执行和安全下一步。
8. validator failure 自身 fail-closed：保留执行事实，使用最保守 deterministic summary。

纯文本启发式只可作为非安全 lint/eval，不作为 blocking authorization/fact rule。

## 14. 解释型 Recovery 生成流程

```text
explicit recover-last / recover <run_id>
-> session ownership check
-> load ExecutionFeedback
-> if planning, load finalized Feedback PlanStep snapshot
-> build immutable RecoveryContext
-> deterministic completeness/safety validation
-> deterministic explanation
```

Recovery 输出固定回答七件事：上次目标、执行路径与停点、已成功动作、失败动作、未执行动作、durable evidence、用户可安全采取的下一步。safe next steps 只能是重新发起新请求、查看/确认事实、修正输入或放弃；不得表示已经 retry/continue/rollback。

第一版入口由独立`RecoveryService`和CLI structured command承载，不要求给现有RuntimeService增加Recovery查询方法，也不进入普通Intent/Planner/Executor route。main dispatch构造targeted Recovery read composition，不初始化LLM/ToolRuntime或任何Recovery模型adapter。`run_id=None`只读取当前session最近一条finalized feedback，不能跨session猜测。

## 15. 权限与安全边界

- Recovery service 的依赖中不注入 `ToolRuntime`、Gateway、PolicyService、confirmation provider、Planner 或 PlanController。
- `RecoveryContext` 不含 AllowedToolSet、ConfirmedAction、arguments digest、旧 ToolCall arguments 或可执行 callable。
- Recovery 输出不能授权 WRITE；用户若要重试，必须发起全新 RuntimeRequest，重新经过 Intent、Policy、Skill、AllowedToolSet、confirmation 与 Gateway。
- session ownership mismatch、unknown run、non-finalized feedback 均 fail-closed。
- 已提交副作用不回滚；失败后的部分成功必须明确保留。
- evidence reference 只作为说明性 provenance；Recovery 不以它绕过 Domain repository 或重新执行外部查询。

## 16. 失败模式和 safe degradation

| 失败 | 行为 |
|---|---|
| Feedback collector/repository 写失败 | 保留原 ExecutorResult/ToolResult/Domain fact；写 `execution.feedback.failed`，当前回答在snapshot完整时仍用request-local validator；restart Recovery可能不可用 |
| duplicate same feedback | 幂等返回既有记录 |
| same run conflicting feedback | fail-closed，不覆盖既有 canonical record |
| validator invalid claim | deterministic safe fallback，不重试模型 |
| validator exception | 最保守 fallback，不改执行事实 |
| feedback 缺失 | `recovery_feedback_not_found`，不从 assistant summary 猜测 |
| Plan rows 与 feedback 不一致 | 以 Plan/Tool/Domain higher-priority facts 为准，标记 `recovery_source_conflict` 并保守解释 |
| evidence reference 缺失 | 保留 safe descriptor；不伪造 durable target |
| malformed/corrupt row | 隔离该 run，返回稳定错误，不扫描其他 session 补齐 |
| deterministic Recovery explanation 构造失败 | safe unavailable，不执行或猜测 |
| semantic event/log writer 失败 | application log 安全诊断；不改变 feedback 或 RecoveryResult |

## 17. semantic events、日志和隐私边界

事件 envelope、schema version、Trace/Span/Event selection、ArtifactReference 与 privacy classification 由 `TRACE_INSPECTION_EVAL_STANDARD_PLAN.md` 拥有。本模块只冻结 Feedback/Recovery 的业务语义名称和安全 attributes。

新增建议 span/events：

- `execution.feedback.built`
- `execution.feedback.persisted`
- `execution.feedback.failed`
- `execution.final_answer.validated`
- `execution.final_answer.fallback`
- `recovery.context.loaded`
- `recovery.context.failed`
- `recovery.explanation.completed`
- `recovery.explanation.failed`

payload 只含 run/plan/step identity、path、status、stop reason、action/evidence counts、validation status、fallback flag 和稳定 error code。不记录 goal text、model answer、evidence summary/reference、Tool arguments/output、RecoveryContext content、confirmation 或异常文本。

拓扑要求：

- Feedback builder/validator 作为当前 Runtime/Executor/Plan span 下的 operation/event，不另起无关联 trace；
- finalized Feedback 通过 `ArtifactReference(artifact_type="execution_feedback")` 关联 source span；
- Recovery 使用独立 root trace/`RECOVERY` span，并通过 `recovery_of` Span Link 指向 source trace；
- Recovery trace 中不得出现 Tool、authorization、confirmation、Executor 或 PlanController execution span；
- deterministic fallback 是 Recovery/validation span 的 attribute/event，不生成虚假 Tool/evidence span。

当前Recovery无provider request/response；普通 `events.jsonl` content-free，`application.log` 只写运维诊断。日志失败不改变 canonical facts。

## 18. focused tests

- models：枚举、identity、排序、唯一性、跨 run/session 引用与 privacy constraints。
- builder：Direct success/failure/partial；Plan completed/failed/pending/superseded；ExecutionEvidence到ExecutionFeedbackEvidence的source-linked投影。
- repository：migration、round-trip、restart、latest-by-session、idempotency、conflict、corrupt row、cross-session deny。
- collector/finalizer：多observation、Direct一次finalize、Planning多Executor invocation只产生一个run-level feedback、finalize后discard、跨run隔离；validated result早于completed event/assistant turn/run record。
- validator：success + evidence；Tool failed 却 claim success；模型无 evidence 声称 WRITE success；unknown/cross-run claims；READ 无 evidence 的有限措辞；deterministic fallback。
- Planning：completed/failed/pending-not-run 分类；旧 revision completed evidence 保留；superseded 不误判执行。
- Recovery：解释停点但 Tool/Gateway/confirmation/Policy/Controller 调用均为零；不恢复权限或旧 confirmation。
- isolation：Feedback/Recovery hook 与 repository failure 不改写原始 ExecutorResult、ToolResult、PlanStep 或业务事实。
- shared trace contract：trace/run/session/executor/plan/call correlation；Feedback artifact reference；Recovery `recovery_of` link；schema/privacy negative assertions。
- ownership：Recovery core/repository 不依赖 TraceReader、derived index、Inspector、Eval、DAG scheduler 或 OpenTelemetry/OpenInference SDK。

### 18.1 步骤 2：六个核心 focused / demo fixtures 冻结

六个 fixture 使用固定的 `session_1`，source run 使用 `run_source_1`，Recovery 请求使用新的 `run_recovery_1`。ID 可在单测内替换，但同一 fixture 内的 trace/run/session/invocation/call/plan/evidence 关联必须精确一致。所有 fixture 均禁止 raw Tool arguments/output、prompt/transcript、Context/Memory content、credentials、authorization headers、confirmation digest、AllowedToolSet、private reasoning 和 exception text进入feedback、trace attributes/events或RecoveryContext。

#### Fixture 1：Direct Tool success + evidence

- 输入事实：Direct route；`execinv_1`；`ToolResult(call_1, research.save_source, succeeded)`；一个 `ExecutionEvidence(write_effect, safe summary, source/ref_1)`。
- action / step outcome：action `call_1=succeeded`；run `completed`；无 PlanStep。
- evidence：feedback只保存source-linked safe descriptor，`source_call_id=call_1`、`source_evidence_index=0`，保留safe reference但不复制Tool output。
- model draft claim：结构化声明`call_1`已成功，并精确引用该evidence。
- expected validation：`claim_status=valid`、`output_mode=model`；accepted claim只含`call_1`。
- expected deterministic fallback：正常路径不采用；若validator异常，只陈述`call_1`和匹配evidence已验证成功，不增加其他成功事实。
- expected durable feedback：overall `completed`、一个succeeded action、一个evidence snapshot、无failed/not-run、validation durable。
- expected Recovery explanation facts：原目标、已成功action、durable evidence descriptor、无失败停点；下一步只能是建议。
- expected trace / artifact / link：source trace含`execution_feedback` ArtifactReference；后续Recovery trace以`recovery_of`指向source trace。
- 禁止出现：写入参数、Tool output、confirmation内容/摘要、旧授权、未发生的第二个action。

#### Fixture 2：Direct Tool failure + false success claim

- 输入事实：Direct route；`execinv_1`；`ToolResult(call_1, research.search_papers, failed)`，safe error code=`research_provider_failed`，无evidence。
- action / step outcome：action `call_1=failed`；run `failed`；无PlanStep。
- evidence：空；不得从error message、assistant text或trace event合成evidence。
- model draft claim：错误地声明`call_1`已经取得结果/成功完成。
- expected validation：`claim_status=invalid`、reason包含failed-action claim、`output_mode=deterministic_fallback`、accepted claims为空。
- expected deterministic fallback：明确Tool失败、没有已验证成功或durable evidence，并给出不带执行承诺的安全下一步。
- expected durable feedback：overall `failed`、一个failed action、safe error code、invalid validation与fallback mode。
- expected Recovery explanation facts：停在`call_1`失败；没有执行成功；下一步是可选重试/检查输入的建议，不声称已重试。
- expected trace / artifact / link：source trace仍可投影feedback artifact；Recovery以link关联，trace status不代替业务failed outcome。
- 禁止出现：provider exception text、伪造evidence、失败被annotation/model text改写为成功、自动retry。

#### Fixture 3：Direct first success + later failure

- 输入事实：同一`execinv_1`内按序出现`call_1=succeeded`并有`evidence_1`，随后`call_2=failed`并有safe error code。
- action / step outcome：`call_1=succeeded`、`call_2=failed`；run overall `partial`。
- evidence：只为`call_1`保存source-linked safe snapshot；`call_2`无evidence。
- model draft claim：正确声明第一个动作成功、第二个动作失败，不声明全局完成。
- expected validation：`claim_status=valid`、`output_mode=model`；只接受`call_1` success claim。
- expected deterministic fallback：逐项列出`call_1`已证实成功、`call_2`失败；不rollback或抹掉第一个evidence。
- expected durable feedback：ordered actions保持1/2顺序，overall `partial`，success/failure和error/evidence关联不丢失。
- expected Recovery explanation facts：显示部分成功停点；已提交副作用保持原样；后续建议不代表执行。
- expected trace / artifact / link：两个Tool attempt关联同一executor invocation；feedback artifact和Recovery link指向同一source run/trace。
- 禁止出现：全局rollback、把第二个失败说成未运行、把第一个成功evidence删除、跨call复用evidence。

#### Fixture 4：Planning fully completed

- 输入事实：`plan_1/revision=1`；两个按依赖顺序的PlanStep均为`completed`，分别关联`execinv_1/call_1`与`execinv_2/call_2`；WRITE Step带匹配evidence ref。
- action / step outcome：两个action succeeded；两个Step completed；PlanRun completed；overall `completed`。
- evidence：action evidence从具体ExecutionEvidence投影；PlanStep evidence refs必须是对应action evidence集合的子集。
- model draft claim：声明两个Step完成，WRITE claim引用已知evidence。
- expected validation：`claim_status=valid`、`output_mode=model`；所有accepted claims均属于current run/plan/revision。
- expected deterministic fallback：按Step位置列出两个completed结果及safe evidence，不复述raw result。
- expected durable feedback：一个plan-level feedback，包含两个invocation、两个completed Step、ordered actions和validation；不为每Step重复保存run-level feedback。
- expected Recovery explanation facts：计划全部完成、无失败/未运行Step、可展示durable evidence descriptor。
- expected trace / artifact / link：planning hierarchy保留plan/revision/step/invocation identities；feedback artifact一次；Recovery link指向source trace。
- 禁止出现：将Plan goal/assistant final text当evidence、跨revision claim、重复run-level feedback、恢复旧Plan执行scope。

#### Fixture 5：Planning completed + failed/stopped + pending/not-run

- 输入事实：`plan_1/revision=1`；Step 1 completed并有evidence；Step 2为`stopped`且`stop_reason=limit_reached`（变体可用`failed`）；Step 3保持`pending`且无invocation/action/evidence。
- action / step outcome：Step 1 completed；Step 2 classified failed并保留原`stopped/limit_reached`；Step 3 classified not-run；overall `partial`。
- evidence：只保留Step 1的verified evidence；Step 2/3不得借用。
- model draft claim：错误地声明整个计划已完成，包含Step 2和Step 3 success claims。
- expected validation：`claim_status=invalid`、reasons覆盖failed/stopped claim与not-run claim、`output_mode=deterministic_fallback`；只可接受独立且引用正确的Step 1 claim。
- expected deterministic fallback：按顺序列出Step 1完成、Step 2失败/停点、Step 3未执行，并说明安全下一步只是建议。
- expected durable feedback：保留PlanRun/Step原始status、stop reason、error code与Step 1 evidence；projection另列completed/failed/not-run，不覆盖rows。
- expected Recovery explanation facts：准确说明部分成功、停止位置和未运行项；pending不误报为failed，superseded变体也不误报为执行过。
- expected trace / artifact / link：只为实际执行的Step产生Executor/Tool spans；Step 3零execution span；feedback artifact与Recovery link有效。
- 禁止出现：为Step 3伪造call/invocation、把pending当failed或completed、跨Step evidence、自动continue/replan/replay。

#### Fixture 6：Restart read-only Recovery，所有执行/授权调用为零

- 输入事实：进程重启后只提供`session_1 + run_source_1`；repository已有Fixture 5式canonical feedback与Plan rows；source trace/artifact可用或derived index故障后从canonical source降级读取。
- action / step outcome：Recovery请求不创建action或PlanStep outcome；只复述source run的completed/failed/not-run分类。
- evidence：只读取durable safe descriptor/reference；不加载raw Tool output，不把artifact本身升级为evidence。
- model draft claim：不适用；Recovery当前deterministic-only，不声明Recovery请求执行了Tool，source feedback原有validation保持不变。
- expected validation：Recovery不新增execution success claim；任何“已重试/已继续/已写入”claim均拒绝。若不运行model，此项标记为deterministic-only而非伪造valid结果。
- expected deterministic fallback：即使explainer、trace exporter或derived index失败，也从可用canonical feedback/Plan rows说明source停点；canonical source不可读时明确`recovery_unavailable`，不猜测。
- expected durable feedback：source feedback只读且字节/字段不变；RecoveryResult request-local，不创建第二份feedback或修改Plan rows。
- expected Recovery explanation facts：source目标、已完成、失败停点、未运行项、safe evidence和非执行性下一步；Tool/Gateway/Policy/confirmation/PlanController counters全为0。
- expected trace / artifact / link：新Recovery trace只含RUNTIME + RECOVERY span、RecoveryContext artifact reference和`recovery_of` link；当前deterministic-only实现不含LLM，也不含Tool/Policy/Guardrail/Executor/Planner execution span。
- 禁止出现：AllowedToolSet、ToolRuntime、ToolCall、confirmation、Policy authorization、Controller调用、checkpoint/replay/resume/rollback、旧WRITE权限、source assistant text作为事实源。

## 19. compiled E2E

使用真实 outer graph、Executor subgraph、Gateway/Guardrails、Planning Controller、SQLite repository、feedback persistence 与 RecoveryService；模型与外部来源使用 deterministic fake/fixture：

1. Direct Tool success + evidence → validated success → restart 后解释成功。
2. Direct Tool failure + false success claim → fallback，Recovery 解释失败。
3. Direct first success + later failure → 分别列出成功和失败。
4. Planning 全部 completed → validated final answer。
5. Planning completed Step + failed/stopped Step + pending Step → 区分 completed/failed/not-run。
6. restart 后从 feedback + Plan rows 解释 interrupted stop，所有执行/授权调用计数为零。
7. collector/repository failure → 主执行事实不变、当前回答安全降级、restart 明确 unavailable。
8. cross-session run lookup / old confirmation injection → fail-closed、零 Tool 调用。
9. shared trace exporter/index failure → Feedback/Recovery canonical facts 和当前安全输出不变。
10. 同一source run的`RuntimeReport`可通过`app/runtime_reporting`读取Feedback artifact；Inspector/Eval fixtures不重新解析events或Feedback tables推断outcome。

这些 E2E 明确不配置 checkpointer、不 replay、不访问真实网络或用户数据库。

## 20. 少量真实模型 smoke 与 deterministic Recovery check

在 focused + compiled E2E 与统一离线回归通过后，单独运行三条受控真实模型 smoke与一条deterministic check：

1. Direct READ success：模型产生可验证 claim。
2. Direct failed Tool：模型不得把失败说成成功；若输出非法 claim 则触发 fallback。
3. Planning partial：Finalizer/Recovery 正确表达 completed、failed、not-run。
4. restart Recovery explanation：deterministic-only地根据durable context解释，零模型、Tool、confirmation调用。

真实 smoke 同时验证 shared trace identity、Feedback ArtifactReference、Recovery `recovery_of` link 与敏感 payload 负向断言；Trace exporter/derived index 的失败仍按 observability external failure 单独报告，不混同 Feedback/Recovery 产品事实。

真实 smoke 使用 fixture/只读 Tool 或隔离临时 SQLite，不依赖生产数据；provider/config/external failure单独报告，不混同代码回归。模型输出不稳定时以结构化 validator 与产品事实断言为 grader，不以文案相似度判定。

## 21. 文档更新

- `docs/AGENT_LEARNING_LINKS.md`：计划确认时加入 structured output/claim validation、eval/grader、checkpoint/replay 副作用边界的官方资料。
- `plans/modules/TRACE_INSPECTION_EVAL_STANDARD_PLAN.md`：作为 shared identity、Trace/Span/Event/Link/Artifact/Annotation、storage/index 和 RuntimeReport 的唯一 owner；本计划不复制其通用定义。
- `docs/ARCHITECTURE.md`：实施后增加 canonical ExecutionFeedback、只读 Recovery、事实优先级、显式入口与依赖方向。
- `docs/RUNTIME_CONCEPTS.md`：实施后沉淀 execution feedback、evidence-grounded answer、解释型 Recovery、部分成功和 checkpoint 对照的面试讲法。
- `docs/PROGRESS_LOG.md`：只在各步骤完成并验证后记录事实。
- `README.md`、`plans/RUNTIME_REFACTOR_PLAN.md`、`plans/modules/README.md`：最终 gate 后同步 Stage 10 状态和下一阶段入口。

本计划没有改变 Policy/Gateway/Planner/Executor/Context 的既有所有权；ExecutionFeedback/Recovery 是共享 Trace Contract 的下游事实/解释模块。实施收口时必须同时更新 `docs/ARCHITECTURE.md` 与 `docs/RUNTIME_CONCEPTS.md`，说明 Feedback canonical outcome、Recovery只读边界及其与 trace/artifact/RuntimeReport 的关系，不能只更新进度文字。

## 22. 分阶段实施步骤

1. **通过共享 Trace foundation prerequisite gate（2026-07-17 已核对）**：共享计划的 pure IDs/models、TraceContext、schema/privacy vocabulary 与 compatibility exporter 已冻结；不要求 Inspector/Eval/derived index 完成。
2. **冻结 Recovery ownership matrix 与 focused fixtures（2026-07-17 已完成）**：列出 Feedback/Recovery 自有字段和 shared contract 引用，固定六个核心演示场景。
3. **实现纯 models 与 builder（2026-07-17 已完成）**：Direct/Planning feedback、evidence projection、stop/not-run 分类；只消费 shared identity value，不接 trace exporter/storage/runtime。
4. **实现 shared claim validator 与 deterministic fallback（2026-07-17 已完成）**：覆盖Direct与Planning structured claims；现有PlanFinalizer WRITE claim通过纯adapter复用核心规则，不接Runtime行为。
5. **新增 Feedback SQLite migration 与 repository（2026-07-17 已完成）**：header/action/evidence tables、restart、idempotency、conflict 与 session isolation；不创建 trace index。
6. **接入 existing Feedback sink collector（2026-07-17 已完成）**：按run/invocation/plan_step缓存observation/result，提供snapshot/discard；实际run-level finalize后调用discard留给步骤7唯一收口，不在Executor内保存run-level feedback。
7. **实现RuntimeOutcomeFinalizer并接入Direct core（2026-07-17 已完成）**：draft facts→validate→一次save→validated result；位置早于completed event、assistant turn和run record。
8. **接入 Planning run-level aggregate（2026-07-17 已完成）**：finalizer通过PlanRepository read Port合并多Executor/多revision，关联trace/executor/plan/step，不修改Controller/replan lifecycle。
9. **发布 shared trace projection（2026-07-17 已完成）**：Feedback ArtifactReference、validation span/events；exporter failure不影响 canonical feedback。
10. **实现 RecoveryContextBuilder / RecoveryService（2026-07-17 已完成）**：显式 read-only API、deterministic explanation、零执行依赖。
11. **接入 CLI structured recovery command（2026-07-17 已完成）**：`recover-last` / `recover <run_id>`，session-scoped，不走普通 route。
12. **接入 Recovery trace semantics（2026-07-17 已完成）**：独立 RECOVERY span、`recovery_of` link、零 Tool/authorization spans。
13. **补齐 semantic attributes 与隐私负向断言（2026-07-17 已完成）**。
14. **运行 focused tests 与 compiled E2E（2026-07-17 已完成）**。
15. **运行统一离线回归、compileall、diff check 与架构审计（2026-07-17 已完成）**。
16. **分开运行三条真实模型 smoke与一条deterministic restart Recovery check（2026-07-17 已完成）**。
17. **同步文档并执行最终 go/no-go gate（2026-07-17 已完成，结论`go`）**。

## 23. 每一步完成条件

- 步骤 1（已满足）：Recovery 可引用稳定 trace/executor identity、schema/privacy contract，且不依赖未实现 Inspector/Eval。
- 步骤 2（已满足）：字段矩阵、失败码、六场景 expected facts 已冻结，无 shared/local owner 冲突；后续实现不得绕过本节列出的接入seam。
- 步骤 3（已满足）：纯函数测试证明 success/failure/not-run/evidence 投影，不依赖 LangGraph/SQLite/provider/exporter。
- 步骤 4（已满足）：Direct/Planning false-success、scope/evidence冲突和validator failure均fail-closed，fallback只引用已验证事实；现有PlanFinalizer WRITE claim可复用shared core。
- 步骤 5（已满足）：新空库、增量升级、restart、幂等、冲突和跨 session 测试通过；无 trace tables。
- 步骤 6（当前范围已满足）：collector顺序、run/invocation隔离、snapshot和discard正确；异常不改变Tool/Executor facts。repository的run唯一约束阻止同一Planning run产生冲突副本；Runtime的一次finalize后discard由步骤7接线验证。
- 步骤 7（已满足）：Direct draft在completed event/assistant turn/run record前必经validator；零Tool回答不被误伤，structured false-success claim fail-closed，finalize后collector已discard。
- 步骤 8（已满足）：Plan partial/revision/evidence分类正确且只保存一个run-level feedback；PlanFinalizer draft保持request-local，既有Controller/Finalizer/replan回归通过。
- 步骤 9（已满足）：Feedback artifact/span/event correlation 正确；exporter/index failure不改变 feedback。
- 步骤 10（已满足）：Recovery service 的依赖图和测试均证明无 Tool/Policy/confirmation/Controller/Inspector/Eval。
- 步骤 11（已满足）：CLI 可显式恢复最近或指定 run，unknown/cross-session fail-closed。
- 步骤 12（已满足）：Recovery `recovery_of` link正确且 trace中零执行/授权 span。
- 步骤 13（已满足）：attributes/events/artifact privacy断言通过，日志失败隔离成立。
- 步骤 14（已满足）：十条 compiled E2E 全通过，产品事实、trace projection与 explanation一致。
- 步骤 15（已满足）：统一离线零意外失败；compileall、diff check、架构/依赖检查通过。
- 步骤 16（已满足）：Direct success、Tool failure、Planning partial真实模型路径与deterministic restart Recovery均通过；claims、evidence、fallback、trace correlation和只读边界有直接断言。
- 步骤 17（已满足）：README、Progress Log、Architecture、Runtime Concepts、总路线图与模块索引均同步已实现事实；Stage 10最终结论为`go`，下一阶段入口为Stage 11。

## 24. 最终 go/no-go gate

最终结论（2026-07-17）：`go`。以下条件均已有focused tests、compiled E2E、统一离线回归、真实模型smoke、compileall、diff与依赖审计证据；Stage 10作为第一个Execution Feedback / Recovery版本关闭。

`go` 必须同时满足：

- Direct 与 Planning 都产生 canonical feedback，restart 后可读取必要解释。
- success claim 只来自 current run 的 succeeded action/completed Step；WRITE success 有匹配 evidence。
- false success、failed、denied、requires-confirmation 和 not-run 均不会被输出为已成功。
- Planning 部分成功保持 completed facts，同时明确 failed 与 pending/not-run。
- Recovery 只读、零 Tool、零旧授权/confirmation 复用、零 replay。
- hook/repository/explanation failure 不改写 ExecutorResult、ToolResult、Plan rows 或 Domain facts。
- semantic events 与 logs 不泄露受保护内容。
- Feedback/Recovery 使用共享 Trace Contract，且没有自建 TraceReader/RuntimeReport/index/annotation体系。
- Feedback ArtifactReference、validation projection、Recovery `recovery_of` link 可被共享 reader消费；shared exporter/index失败不影响 canonical facts。
- focused、compiled E2E、统一离线、compileall、diff check 全通过；真实 smoke 无未解释的产品语义偏差。

任一事实源冲突导致成功被误报、Recovery 可触达执行能力、旧授权可复用、restart 依赖 assistant text、或 sink failure 反转业务事实，均为 `no-go`。真实 provider 暂时不可用但离线边界完整时单独标记 external blocker，不自动等同代码 no-go。

## 25. 面试演示和讲解场景

1. **证据支持的成功**：展示 ToolResult/Evidence → Feedback → validated final answer → restart Recovery 的完整链。
2. **模型说成功但事实失败**：展示结构化 claim 被 validator 拒绝并使用 deterministic fallback，说明 assistant text 不是事实源。
3. **Direct 部分成功**：一个 action 已提交、后续 action 失败；说明不做全局 rollback，也不抹掉成功 evidence。
4. **Planning 部分成功**：画出 completed Step、failed Step、pending/not-run Step，说明 Plan lifecycle 与 Domain facts 的区别。
5. **只读 Recovery**：restart 后解释停点和下一步，同时用 fake counters 证明 Tool、Policy、confirmation、Controller 均未调用。
6. **safe degradation**：故意让 Feedback repository 或deterministic explanation构造失败，证明原始执行结果和业务事实不被 observability/recovery 辅助模块改写。
7. **与 LangGraph checkpoint 对照**：说明 checkpoint/replay 解决的是 workflow state/resume；本阶段只保存可解释执行事实，不重新执行节点，因此无需 checkpoint 也能达到面试型 Recovery 目标。
