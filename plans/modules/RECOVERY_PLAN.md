# Stage 10 Execution Feedback / Recovery 模块计划

文档状态：范围已确认，已按共享标准和当前 Runtime/Executor/Planner 代码接缝完成适配审查，待实施。Stage 10 只交付结构化 Execution Feedback 与解释型 Recovery，不实现执行恢复，也不单独建立 Trace/Inspector/Eval 标准。

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
  sequence, executor_invocation_id, source_span_id, call_id, tool_name, outcome
  error_code?, retryable?, evidence: tuple[ExecutionFeedbackEvidence]

ExecutionFeedbackEvidence
  evidence_type, summary, reference?, source_call_id, source_evidence_index

ExecutionPlanStepFeedback
  revision, step_id, position, objective, expected_outcome
  status, stop_reason?, error_code?, evidence_refs

ExecutionClaim
  claim_id, kind, call_id?, plan_step_id?, evidence_refs

FinalAnswerValidation
  status(valid|invalid|fallback), reason_codes, accepted_claim_ids

RecoveryContext
  source_trace_id, source_run_id, session_id, goal_summary, path
  stop_point, succeeded_actions, failed_actions, not_run_actions
  durable_evidence, safe_next_steps, generated_at
```

`outcome` 冻结为 `succeeded | failed | denied | requires_confirmation`。PlanStep 的 `pending`、`stopped`、`failed`、`goal_not_achieved`、`superseded` 等保持 Planner 原始语义；Recovery projection 再明确映射为 completed / failed / not-run，不覆盖 repository row。

`ExecutionEvidence` 继续是 ToolResult/Gateway 的 canonical fact；`ExecutionFeedbackEvidence` 只是其 durable safe snapshot，字段从具体 evidence逐项投影并保留call/index来源。未来`app/runtime_reporting.EvidenceReport`统一向Inspector/Eval展示。不得再定义无来源identity的`DurableEvidence`同义模型。

`trace_id`、`source_span_id`、`executor_invocation_id`、Plan/DAG identity 的格式、唯一性和 propagation 由共享 Trace Contract 拥有；本模块只保存关联值。final-answer validation 是 Runtime 实际采用/降级行为的一部分，仍属于 durable ExecutionFeedback；Inspector diagnosis 和 Eval grade 则属于共享 `AnnotationRecord`，不能反写 validation fact。

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
    def finalize(self, request: RuntimeRequest, draft: RuntimeResult) -> RuntimeResult: ...

class RecoveryContextBuilder(Protocol):
    def build(self, session_id: str, run_id: str | None = None) -> RecoveryContext: ...

class RecoveryExplainer(Protocol):
    def explain(self, context: RecoveryContext, *, llm_log=None) -> str: ...

class RecoveryService:
    def explain_run(self, session_id: str, run_id: str | None = None) -> RecoveryResult: ...
```

现有 `ExecutorFeedbackSink` 由 request-local-aware production collector实现：按`run_id + executor_invocation_id + optional plan_step`收集observations和每次ExecutorResult，但不在每次Executor结束时保存run-level canonical feedback。Planning同一Runtime run可包含多个Executor invocation，若sink直接finalize会重复/冲突写同一`run_id`。

唯一run-level收口点是`RuntimeOutcomeFinalizer`：在Runtime取得draft `RuntimeResult`后读取collector snapshot；Direct调用`from_direct`，Planning根据`tool_result.plan_id/revision`通过typed PlanRepository读取全部相关steps再调用`from_plan`；随后执行answer validation、一次性保存canonical feedback并返回validated RuntimeResult。它不修改PlanController/replan调度。

`ExecutorRecoveryHook` 保持只读通知/兼容 seam，不承担存储、aggregate或解释主逻辑，避免两个hook竞争事实所有权。

Trace integration只通过shared RequestTelemetry/SpanRecorder capability：Feedback finalized后记录safe ArtifactReference与validation span/event；RecoveryService接收shared TraceContext，建立`RECOVERY` span和`recovery_of` link。仅实现旧`append()`的test fake仍可运行。Recovery core/repository不依赖exporter、derived index、runtime_reporting、Inspector或Eval implementation。

## 10. durable state 与 request-local state

业务/runtime SQLite 新增 `execution_feedback`、`execution_feedback_actions`、`execution_feedback_evidence`；Planning Step 详情继续以现有 `plan_runs` / `plan_steps` 为 owner，不复制完整 Plan JSON。feedback header 可保存 shared trace correlation、plan identity、stop point、validation outcome；action/evidence 使用可查询 child rows，不把 opaque JSON blob 作为唯一事实源。

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
-> if planning, join PlanRun/PlanStep facts
-> build immutable RecoveryContext
-> deterministic completeness/safety validation
-> optional read-only RecoveryExplainer
-> validate explanation against RecoveryContext
-> explanation or deterministic fallback
```

Recovery 输出固定回答七件事：上次目标、执行路径与停点、已成功动作、失败动作、未执行动作、durable evidence、用户可安全采取的下一步。safe next steps 只能是重新发起新请求、查看/确认事实、修正输入或放弃；不得表示已经 retry/continue/rollback。

第一版入口由独立`RecoveryService`和CLI structured command承载，不要求给现有RuntimeService增加Recovery查询方法，也不进入普通Intent/Planner/Executor route。main dispatch构造targeted Recovery read composition，不初始化LLM/ToolRuntime；只有显式启用可选explainer时才注入对应模型adapter。`run_id=None`只读取当前session最近一条finalized feedback，不能跨session猜测。

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
| Recovery explainer provider 失败/非法输出 | deterministic Recovery fallback |
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
- `recovery.explanation.completed`
- `recovery.explanation.failed`

payload 只含 run/plan/step identity、path、status、stop reason、action/evidence counts、validation status、fallback flag 和稳定 error code。不记录 goal text、model answer、evidence summary/reference、Tool arguments/output、RecoveryContext content、confirmation 或异常文本。

拓扑要求：

- Feedback builder/validator 作为当前 Runtime/Executor/Plan span 下的 operation/event，不另起无关联 trace；
- finalized Feedback 通过 `ArtifactReference(artifact_type="execution_feedback")` 关联 source span；
- Recovery 使用独立 root trace/`RECOVERY` span，并通过 `recovery_of` Span Link 指向 source trace；
- Recovery trace 中不得出现 Tool、authorization、confirmation、Executor 或 PlanController execution span；
- deterministic fallback 是 Recovery/validation span 的 attribute/event，不生成虚假 Tool/evidence span。

Recovery explainer 的真实 provider request/response 若启用，继续进入敏感 `llm.jsonl`；普通 `events.jsonl` content-free，`application.log` 只写运维诊断。日志失败不改变 canonical facts。

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

## 20. 少量真实模型 smoke

在 focused + compiled E2E 与统一离线回归通过后，单独运行四条受控 smoke：

1. Direct READ success：模型产生可验证 claim。
2. Direct failed Tool：模型不得把失败说成成功；若输出非法 claim 则触发 fallback。
3. Planning partial：Finalizer/Recovery 正确表达 completed、failed、not-run。
4. restart Recovery explanation：只读模型根据 durable context 解释，零 Tool/confirmation 调用。

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

1. **通过共享 Trace foundation prerequisite gate**：共享计划的 pure IDs/models、TraceContext、schema/privacy vocabulary 与 compatibility exporter 已冻结；不要求 Inspector/Eval/derived index 完成。
2. **冻结 Recovery ownership matrix 与 focused fixtures**：列出 Feedback/Recovery 自有字段和 shared contract 引用，固定六个核心演示场景。
3. **实现纯 models 与 builder**：Direct/Planning feedback、evidence projection、stop/not-run 分类；只消费 shared identity value，不接 trace exporter/storage/runtime。
4. **实现 shared claim validator 与 deterministic fallback**：先覆盖 Direct；再让 PlanFinalizer adapter 复用核心规则。
5. **新增 Feedback SQLite migration 与 repository**：header/action/evidence tables、restart、idempotency、conflict 与 session isolation；不创建 trace index。
6. **接入 existing Feedback sink collector**：按run/invocation/plan_step缓存observation/result，finalize后discard；不在Executor内保存run-level feedback。
7. **实现RuntimeOutcomeFinalizer并接入Direct core**：draft facts→validate→一次save→validated result；位置早于completed event、assistant turn和run record。
8. **接入 Planning run-level aggregate**：finalizer通过PlanRepository read Port合并多Executor/多revision，关联trace/executor/plan/step，不修改Controller/replan lifecycle。
9. **发布 shared trace projection**：Feedback ArtifactReference、validation span/events；exporter failure不影响 canonical feedback。
10. **实现 RecoveryContextBuilder / RecoveryService**：显式 read-only API、deterministic explanation、零执行依赖。
11. **接入 CLI structured recovery command**：`recover-last` / `recover <run_id>`，session-scoped，不走普通 route。
12. **接入 Recovery trace semantics**：独立 RECOVERY span、`recovery_of` link、零 Tool/authorization spans。
13. **补齐 semantic attributes 与隐私负向断言**。
14. **运行 focused tests 与 compiled E2E**。
15. **运行统一离线回归、compileall、diff check 与架构审计**。
16. **分开运行四条真实模型 smoke**。
17. **同步文档并执行最终 go/no-go gate**。

## 23. 每一步完成条件

- 步骤 1：Recovery 可引用稳定 trace/executor identity、schema/privacy contract，且不依赖未实现 Inspector/Eval。
- 步骤 2：字段矩阵、失败码、六场景 expected facts 经用户确认，无 shared/local owner 冲突。
- 步骤 3：纯函数测试证明 success/failure/not-run/evidence 投影，不依赖 LangGraph/SQLite/provider/exporter。
- 步骤 4：所有 false-success cases fail-closed，fallback 只引用已验证事实。
- 步骤 5：新空库、增量升级、restart、幂等、冲突和跨 session 测试通过；无 trace tables。
- 步骤 6：collector顺序、run/invocation隔离和discard正确；异常不改变Tool/Executor facts，同一Planning run不被重复finalize。
- 步骤 7：Direct draft在completed event/assistant turn/run record前必经validator；零Tool回答不被误伤。
- 步骤 8：Plan partial/revision/evidence分类正确且只保存一个run-level feedback；既有Controller/Finalizer回归通过。
- 步骤 9：Feedback artifact/span/event correlation 正确；exporter/index failure不改变 feedback。
- 步骤 10：Recovery service 的依赖图和测试均证明无 Tool/Policy/confirmation/Controller/Inspector/Eval。
- 步骤 11：CLI 可显式恢复最近或指定 run，unknown/cross-session fail-closed。
- 步骤 12：Recovery `recovery_of` link正确且 trace中零执行/授权 span。
- 步骤 13：attributes/events/artifact privacy断言通过，日志失败隔离成立。
- 步骤 14：十条 compiled E2E 全通过，产品事实、trace projection与 explanation一致。
- 步骤 15：统一离线零意外失败；compileall、diff check、架构/依赖检查通过。
- 步骤 16：四条 smoke 分别报告路径、claims、evidence、fallback、trace correlation和外部失败。
- 步骤 17：所有文档只记录已实现事实，Stage 10 gate 有直接结论。

## 24. 最终 go/no-go gate

`go` 必须同时满足：

- Direct 与 Planning 都产生 canonical feedback，restart 后可读取必要解释。
- success claim 只来自 current run 的 succeeded action/completed Step；WRITE success 有匹配 evidence。
- false success、failed、denied、requires-confirmation 和 not-run 均不会被输出为已成功。
- Planning 部分成功保持 completed facts，同时明确 failed 与 pending/not-run。
- Recovery 只读、零 Tool、零旧授权/confirmation 复用、零 replay。
- hook/repository/explainer failure 不改写 ExecutorResult、ToolResult、Plan rows 或 Domain facts。
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
6. **safe degradation**：故意让 Feedback repository 或 explainer 失败，证明原始执行结果和业务事实不被 observability/recovery 辅助模块改写。
7. **与 LangGraph checkpoint 对照**：说明 checkpoint/replay 解决的是 workflow state/resume；本阶段只保存可解释执行事实，不重新执行节点，因此无需 checkpoint 也能达到面试型 Recovery 目标。
