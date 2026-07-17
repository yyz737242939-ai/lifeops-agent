# Stage 11B Eval Harness 模块计划

文档状态：范围已确认，已完成与共享标准、Inspector计划及当前Runtime/test composition的适配审查，待实施。本计划依赖`app/observability`的共享Trace Contract和`app/runtime_reporting`的FactProvider/RuntimeReportBuilder，不重新定义执行事实、trace storage、Inspector diagnosis或Recovery语义。

## 1. 模块背景与面试学习目标

LifeOps 已有 focused tests、deterministic compiled E2E、真实模型 smoke 和少量 Skill eval fixtures，但还没有统一的 case contract、grader、run report 和 regression 入口。普通测试证明一个函数或固定路径是否符合断言；Eval Harness 还要回答：面对一组代表性用户任务，Runtime 是否走了正确 route、遵守权限、调用正确 Tool、产生必要 evidence、改变预期 state，并且 final answer 没有超出执行事实。

本模块目标是实现一个本地、小而完整、可重复、可定位失败的 Eval Harness。重点学习 dataset/case、runner、deterministic grader、trajectory/fact evaluation、regression、real-LLM smoke 与 LLM-as-judge 边界，不建设 hosted eval platform。

面试时应能讲清：

- test、compiled E2E、Eval 与 live smoke 的关系；
- agent eval 为什么不能只比较最终文本；
- Inspector 与 Eval 如何共用一个 `RuntimeReport`；
- product failure、harness error、environment unavailable 和 expected safety stop 如何区分；
- 为什么确定性 grader 优先，LLM judge 只能是显式增强。

## 2. 共享标准与前置条件

以下公共概念由 `TRACE_INSPECTION_EVAL_STANDARD_PLAN.md` 唯一拥有：

- `TraceRecord/SpanRecord/SpanEventRecord/SpanLinkRecord`；
- `ArtifactReference/AnnotationRecord`；
- `TraceGraph`与`TraceStore/TraceReader`由`app/observability`拥有；
- `RuntimeFactBundle/RuntimeReport/RuntimeFactProvider/RuntimeReportBuilder`由`app/runtime_reporting`拥有；
- canonical trace/annotation files、derived SQLite index；
- facts、evidence、feedback、trace、annotation 的优先级。

Eval Harness 只拥有 `EvalCase/EvalSuite/EvalRun/CaseResult/GradeResult/EvalReport`、loader、runner、graders 和 report renderer。每个 `GradeResult` 投影为 shared `AnnotationRecord`，不能形成第二套评价记录标准。

实施前置 gate：

1. shared trace reader、fact provider 和 report builder 已稳定；
2. Direct 与 Planning 能生成可重复读取的 `RuntimeReport`；
3. `ExecutionFeedback` 未完成时，可先运行不依赖 feedback 的 grader，但不得伪造替代事实；
4. DAG未实现时可用shared diamond fixture开发grader；Eval最终production gate等待正式serial DAG compiled case。

## 3. 当前实现基线

当前仓库已有：

- `unittest` focused tests；
- 使用真实 Runtime/Planner/Executor/Gateway wiring 和 deterministic providers 的 compiled E2E；
- 受环境变量 gate 控制的 real-LLM、MCP 和 live-user E2E；
- `tests/fixtures/skills/*.json` 与 `test_skill_eval_fixtures.py`；
- 对 `RuntimeResult`、events、evidence、Plan state、SQLite state 和文件结果的分散断言；
- 规划中的统一 Trace、RuntimeReport 和 Annotation 标准。

当前缺口：

- 没有统一、可版本化的 `EvalCase/EvalSuite` schema；
- 每个 E2E 自行读取 result/events/database，缺少共享 grader；
- 没有 eval run identity、统一 report、exit code 和失败分类；
- route/tool/evidence/state/answer/trace assertions 不能组合复用；
- regression case 缺少 bug lineage；
- live failure 容易混淆产品失败与 provider/environment 问题；
- Inspector 无法按 eval run/suite/case 汇总评价。

## 4. V0 / legacy 决策

本轮不读取 `legacy_v0/`。当前 tests、compiled E2E、live E2E 与 shared trace 计划已足够设计 V1 Harness。只有迁移一个当前 tests 未覆盖、仍有价值的历史 regression case 时，才先说明原因并只读对应 legacy fixture/test；不迁移旧 runner、日志 schema 或报告格式。

## 5. 本轮范围

- 定义 Eval-owned models、versioned manifest 和 expectation contract。
- 实现本地 suite loader、runner、grader registry、aggregation、text/JSON report。
- 通过正常 Runtime public entry 执行 case，并产生 `source=eval` target trace。
- 使用唯一 shared read path 构造 grader 输入。
- 实现共享计划冻结的 12 类 deterministic graders。
- 将 grade 保存为 shared evaluation annotation，并用 `evaluation_of` link 关联 target trace。
- 区分 component fixture、compiled runtime、regression、real-LLM smoke。
- 覆盖 Direct、Planning、Recovery 和 serial DAG 代表场景。
- 复用当前 temp database/files、deterministic providers 和 live gates。

## 6. 明确不做

- 不建设 hosted service、dashboard、队列、worker、多租户或大规模 dataset 平台。
- 不接入 OpenAI Evals、LangSmith、Phoenix 等远端平台。
- 不默认并行运行 case；V0 串行优先保证隔离和复现。
- 不自动 retry、replay、replan、修复 prompt 或修改被测系统。
- 不把 grade 写回 RuntimeResult、ExecutionFeedback、Plan、ToolResult 或 Domain facts。
- 不把 expectation、grader feedback 或 eval metadata 注入模型业务 prompt。
- 不读取真实用户 database、Profile、Memory、confirmation 或历史 session 作为 fixture。
- 不以 LLM judge 替代 Policy、Tool、evidence、state、permission 等确定性断言。
- 不用全文字符串相等作为所有 final answer 的主要 grader。
- 不为 Eval 大改 LangGraph、Planner、Executor、Gateway 或 Domain framework。

## 7. 模块边界与依赖方向

建议结构：

```text
app/observability/              shared owner
  trace/read/index/annotations

app/runtime_reporting/          shared high-level read owner
  fact provider/report models/report builder

app/evals/                      Eval Harness owner
  models.py                     case/suite/run/result/report
  ports.py                      runtime factory/report sink/clock
  loader.py                     versioned manifests
  runner.py                     suite/case lifecycle
  graders.py                    deterministic graders
  aggregation.py                pass/fail/skip/error
  renderers.py                  text/json
  errors.py

evals/suites/                   versioned manifests
tests/fixtures/evals/           deterministic fixtures
```

依赖方向：

```text
main.py eval command (targeted eval composition)
  -> app.evals
     -> EvalRuntimeFactory -> normal RuntimeService public path
     -> shared TraceReader/AnnotationSink
     -> app.runtime_reporting FactProvider/ReportBuilder
     -> isolated test repositories/providers

Runtime / Planner / Executor / Tool / Domain
  -X-> app.evals
```

Harness可以作为外部调用者运行Runtime；Runtime core不能import eval models、expectations、graders或fixtures。EvalRuntimeFactory复用`RuntimeService`公开constructor和test adapters，不调用会固定真实LLM/MCP/用户路径的production `build_runtime_service()`。

## 8. 与现有模块的关系

- **Shared read boundary**：Observability唯一拥有trace/annotation/reader；`app/runtime_reporting`唯一拥有fact bundle/report。
- **Inspector**：只显示既有 Eval annotations；不运行 suite、不重算 grade。
- **ExecutionFeedback**：grader 比较 canonical outcome，不重建 action success。
- **Recovery**：运行正常只读 Recovery 入口并断言零执行 span，不替代 RecoveryService。
- **Planner/Executor**：通过 public interface 被测，不增加 eval-only branch。
- **Policy/Gateway**：使用真实 permission、confirmation、handler reachability 和 evidence 事实评分。
- **Context/Memory**：只用 isolated fixtures；eval metadata 不进入 assembly/content。
- **DAG**：grader 消费 node outcome 与 `depends_on` links，不依赖 scheduler implementation。
- **Observability**：grader 不自行解析 JSONL 或直接查询业务 tables。
- **现有 tests**：保留 focused tests；只把适合跨场景复用的 E2E 提炼为 eval case。

## 9. Eval 分层

| suite 类型 | 被测范围 | provider/data | 主要用途 |
|---|---|---|---|
| `component_fixture` | 单 component/public function | deterministic fake | parser/router/selector contract |
| `compiled_runtime` | 完整 Runtime path | deterministic providers + temp stores | 主离线行为 gate |
| `regression` | 曾发生的具体 bug | 最小复现场景 | 防止历史问题回归 |
| `real_llm_smoke` | 真实 model adapter | live provider，默认 READ | 验证现实兼容性 |

`unittest` 是执行和断言框架；Eval Harness 是 case、runner、grader、report 与 lineage。compiled E2E 可以由 `unittest` 调用，也可以作为 suite case，两者不是互斥关系。

## 10. Eval-owned 数据模型

```text
EvalCase
  schema_version
  case_id / title / description
  execution_mode
  input
  fixture_ref?
  expectations
  grader_ids
  tags
  timeout_seconds
  required=true
  regression_ref?

EvalSuite
  schema_version
  suite_id / version / description
  case_refs
  default_grader_ids

EvalRun
  eval_run_id
  suite_id / suite_version
  source_revision?
  environment_fingerprint
  started_at / ended_at?
  status

CaseResult
  eval_run_id / suite_id / case_id
  target_trace_id?
  evaluator_trace_id?
  status(passed|failed|skipped|error)
  grade_results
  duration_ms
  error_code? / safe_explanation?

GradeResult
  grade_id
  grader_id / grader_version
  status(passed|failed|warning|skipped|error)
  score? / label? / reason_code?
  safe_explanation?
  target_trace_id / target_span_id?
  fact_references

EvalStateSnapshot
  probe_id
  safe_values

EvalStateDelta
  before: tuple[EvalStateSnapshot]
  after: tuple[EvalStateSnapshot]
  changes

EvaluationSubject
  runtime_report
  state_delta?

EvalReport
  run / suite_summary / case_results
  counts / failed_grade_index / warnings
```

这些模型只描述evaluation lifecycle，不复制Runtime、Tool、Evidence、Plan、Feedback、Trace或RuntimeReport模型。`EvalStateSnapshot/Delta`是隔离测试workspace中的oracle：由manifest白名单probe产生，只用于StateChangeGrader，不是Runtime执行事实，不进入Inspector/RuntimeReport/Annotation，也不能覆盖ToolResult/Evidence。

## 11. Case input 与 expectation contract

`EvalCase.input` 只包含正常 Runtime request 或 component call 的公开输入。fixture 通过 trusted registry reference 选择 test-only provider/data，不允许 manifest 指定任意 Python import、callable、path 或 command。

```text
EvalExpectations
  intent?
  policy?
  route?
  plan_lifecycle?
  workflow_dependencies?
  tool_calls?
  state_changes?
  evidence?
  execution_feedback?
  final_answer?
  trace_contract?
  privacy?
```

每个字段只由对应 grader 解释。缺少 expectation 时 grader 不猜目标；privacy/trace integrity 等 invariant grader 可以由 suite 默认启用。

## 12. Matcher 语义

V0 只提供少量确定性 matcher：

- `equals`：enum、status、error code、route；
- `contains_all/contains_none`：Tool、Skill、evidence type；
- `ordered`：确实要求因果顺序的 action/step；
- `count/min_count/max_count`：attempt、confirmation、evidence；
- `status_by_id`：PlanStep/DAG node lifecycle；
- `fact_delta`：隔离 store 的 before/after typed projection；
- `linked_to`：evidence、feedback 和 span links；
- `claim_supported`：answer claim 对照 Feedback/evidence；
- `topology`：required/forbidden spans、parents、links；
- `redacted`：禁止字段/内容不存在。

禁止默认 fuzzy text similarity、关键词命中即成功、从 application.log 推导事实，或把整份 snapshot 差异当业务正确性。

## 13. Protocol / Port / Service

```python
class EvalSuiteLoader(Protocol):
    def load(self, suite_ref: str) -> EvalSuite: ...

class EvalRuntimeFactory(Protocol):
    def create(self, case: EvalCase, workspace: EvalWorkspace) -> EvalRuntime: ...

class EvalGrader(Protocol):
    @property
    def grader_id(self) -> str: ...
    @property
    def version(self) -> str: ...
    def grade(self, case: EvalCase, subject: EvaluationSubject) -> GradeResult: ...

class EvalReportSink(Protocol):
    def write(self, report: EvalReport) -> None: ...

class EvalRunner:
    def run(self, suite: EvalSuite, options: EvalRunOptions) -> EvalReport: ...
```

Runner注入loader、workspace factory、runtime factory、shared TraceReader、runtime-reporting fact/report Ports、annotation Port、state probe registry、grader registry、report sink、clock和ID factory。

## 14. Case 执行流程

1. 校验 suite/case schema、IDs、graders 和 fixture references；
2. 创建 case 独占 temp workspace、SQLite、session logs、Context/Memory files；
3. 准备deterministic provider/data，并通过manifest白名单state probes记录before snapshot；
4. 构造正常 RuntimeRequest，只在 observability context 标记 eval lineage；
5. 通过 production-like composition 执行正常 Runtime path；
6. 获得target trace，并通过shared TraceReader和runtime-reporting path构造`RuntimeReport`；
7. 通过相同白名单probes记录after snapshot并构造Eval-owned `EvalStateDelta`；
8. 以`EvaluationSubject(RuntimeReport, optional state_delta)`运行graders，隔离单grader exception；
9. 把grade追加为shared annotations，建立evaluator trace/link；state delta内容不写annotation；
10. 聚合CaseResult/EvalReport；
11. 关闭service/handlers，清理或显式保留失败workspace。

默认不 retry。timeout、provider failure 与 assertion failure保持独立分类。

## 15. 隔离与可复现性

- 每个 offline case 独占 temp root、database、session、provider instance 和 mutable state；
- case 不共享 confirmation、idempotency、repository 或 request-local state；
- suite/case/fixture/grader version 与 source revision 写入 lineage；
- fixed clock/ID 只用于 test adapters，不改变 production contract；
- provider/model/config 的安全 metadata 形成 environment fingerprint；
- fingerprint 不含 API key、完整环境变量、用户路径或 secret；
- V0 串行运行；未来并行必须先证明 workspace 完全隔离。

## 16. Deterministic graders

V0 registry 与共享计划一致：

1. `IntentGrader`：intent/clarification contract。
2. `PolicyGrader`：allow/deny/confirmation/effect/allowed-tool boundary。
3. `RouteGrader`：Direct/Plan/NeedUser/Recovery route。
4. `PlanLifecycleGrader`：revision 与 completed/failed/pending/not-run。
5. `WorkflowDependencyGrader`：node outcome、dependency、blocked、partial evidence。
6. `ToolCallGrader`：selected/attempted/handler-reached Tool、count/order/forbidden calls。
7. `StateChangeGrader`：读取Eval-owned typed before/after delta，判断预期写或零写；不要求Domain schema增加run_id。
8. `EvidenceGrader`：success/WRITE 与 durable evidence 的 identity/link/type。
9. `ExecutionFeedbackGrader`：outcome、stop point、action/step classification 一致性。
10. `FinalAnswerGroundingGrader`：success claim 有事实支持，建议不冒充执行。
11. `TraceContractGrader`：identity、topology、status、links、integrity。
12. `PrivacyGrader`：普通 trace/report/index 不含禁止内容。

除StateChangeGrader外，grader只读取`EvalCase + RuntimeReport`。StateChangeGrader额外读取`EvaluationSubject.state_delta`；delta由Runner调用trusted probe registry生成，grader自身不得打开SQLite/files。该oracle不属于Inspector/Eval共享Runtime标准，也不参与事实优先级裁决。

## 17. Aggregation 与 gate

V0 不用加权总分决定 gate：

- required grader 任一 `failed/error` -> case failed；
- optional grader failure -> warning，除非 suite 将其提升为 required；
- required case failed/error -> suite failed；
- offline required case 不允许 skipped；
- live external prerequisite unavailable 可 skipped，但不能计为 passed；
- expected safety stop 匹配 expectation 时可以 passed，不等同 RuntimeStatus.OK；
- harness schema/setup/reader/grader exception 是 error，产品断言不符是 failed；
- warning 不覆盖 failed。

CLI exit code：`0=required passed`、`1=grade failure`、`2=harness/config error`、`3=required environment unavailable`。

## 18. Evaluation trace 与 Annotation

```text
target Runtime trace
  source=eval
  eval_run_id / eval_suite_id / eval_case_id

EVALUATOR evaluation.case
|- evaluation_of -> target root span
|- EVALUATOR grader.<grader_id>
`- AnnotationRecord per GradeResult
```

`GradeResult -> AnnotationRecord` 保持 status、score/label、reason、target identity、grader version、source fingerprint 和 eval lineage。完整 expectations、raw provider output 或敏感 diff 不进入普通 annotation。

annotation/export failure不改变即时 grade；CaseResult只增加`annotation_not_persisted` warning。target trace缺失时，trace-dependent graders返回error，不从其他日志猜测。

## 19. Report 与 CLI

```powershell
uv run python main.py eval --suite runtime_core
uv run python main.py eval --suite regression --case <case_id>
uv run python main.py eval --suite live_smoke --format json
uv run python main.py eval --suite runtime_core --keep-failed-workspaces
```

text/JSON report 最少显示 suite/version/run/environment、counts、失败 case/grader/reason、target trace/span/fact、safe expected vs actual、failure classification 和 Inspector 查询 identity。

report 写入显式 temp/output 目录，是 evaluation artifact而非 Runtime事实。shared annotations 是可按 target trace 查询的评价结果；不新增第二套 canonical eval event database。

main CLI只负责command dispatch。`eval`命令构造EvalRuntimeFactory/Harness，不先调用production `build_runtime_service()`；每个case再由factory使用`RuntimeService`公开constructor、deterministic adapters和临时配置完成composition。无子命令时保持现有interactive CLI行为。

## 20. Dataset、fixture 与 regression 生命周期

- manifest 必须有 schema version、stable ID 和 suite version；
- case语义改变时升级version，不静默改 expectation；
- fixture只保存合成/公开/test数据；
- fixture reference经registry解析，不允许任意path/import；
- regression case记录 regression ref、原failure category 和最小行为；
- flaky case必须分类为product、provider或harness instability，不能靠提高retry隐藏；
- unknown旧schema显式迁移或fail-closed。

现有 Skill fixture 先通过 adapter成为component suite；等价验证前不删除原测试。

## 21. Direct 最小场景

1. final-only：Direct、零Tool、零state change、trace完整。
2. READ success：允许Tool一次、safe result/evidence、answer claim有支持。
3. WRITE confirmation：确认前零handler/零写，当前exact confirmation后写一次并有evidence。
4. Tool failure：不能声称成功，state与feedback正确。
5. false success：无Tool/evidence却声称完成，被Grounding grader拦截。
6. policy/catalog deny：forbidden Tool零handler调用，安全stop正确评分。

## 22. Planning 最小场景

1. preview：PlanRun revision持久化，零Tool/Domain write。
2. confirm：多个PlanStep/Executor invocation关联正确。
3. partial：completed/failed/pending/not-run分离，成功evidence保留。
4. stale revision/confirmation：零非法执行，不复用旧权限。
5. bounded replan：只评分现有控制流，Harness不触发额外replan。
6. restart/interrupted：durable Plan/Feedback/evidence重建结果一致。

## 23. Recovery 与 DAG 场景

Recovery case证明：能解释目标/停点/success/failure/not-run/evidence；Recovery trace零Tool、Policy authorization、confirmation和Executor execution；不恢复旧confirmation或WRITE权限。

serial diamond DAG case证明：parent-child表达scheduler containment，`depends_on`表达dependency；B成功、C失败、D blocked；B evidence保留，D零Tool attempt；grader不靠event顺序猜edge。

## 24. Real-LLM smoke

- 复用现有 Direct READ、Planning preview/confirm 和 Recovery explain 路径；
- live WRITE仅允许temp test store、test confirmation provider和可回收fixture；
- 继续用相同deterministic graders评分；
- provider/model/config安全metadata进入fingerprint；
- timeout/rate limit/network/provider error单独分类；
- 不以最终措辞完全一致判定pass。

真实 smoke 保持少量，用于发现模型/API现实偏差，不替代 offline regression suite。

## 25. LLM-as-judge 边界

V0 不实现通用 LLM judge。未来仅用于清晰度、帮助性、解释覆盖等难以确定性评价的维度；权限、Tool、state、evidence、confirmation和success claim仍由deterministic graders裁决。

若后续启用，judge必须读取redacted report projection和明确rubric，输出structured GradeResult，产生独立LLM span与`producer=llm_judge` annotation，固定model/rubric/version，并且不能覆盖deterministic failure或触发被测Runtime重试。

## 26. 权限、隐私与安全

- EvalRunner只能由显式eval命令在isolated workspace中主动运行；
- `source=eval`不授予权限，Policy/AllowedToolSet/confirmation照常执行；
- fixture setup与target Tool execution分离，setup不是执行成功事实；
- 不加载真实Profile/Memory/user database/session/confirmation；
- manifest禁止secret、任意path、import、callable和shell command；
- raw prompt/output/Tool args只允许受保护artifact，普通report/annotation只含safe摘要；
- eval report/failed workspace采用显式retention；
- grade/annotation不能授权、执行、rollback或修改业务事实。

## 27. Failure modes 与 safe degradation

| 失败 | 行为 |
|---|---|
| manifest/schema未知 | fail-closed，`eval_manifest_invalid` |
| duplicate/missing case/grader | suite config error，运行前停止 |
| fixture setup失败 | case error，Runtime不启动 |
| Runtime exception | 保留target trace（若有），明确产品/环境分类 |
| target trace缺失 | trace-dependent graders error |
| fact provider失败 | fact graders error；纯trace grader继续 |
| source conflict | 显式warning/failure，按共享事实优先级保守处理 |
| 单grader exception | 该grade error，其他grader继续 |
| annotation sink失败 | 即时grade/report保留，标not persisted |
| report sink失败 | 返回in-memory report并以harness error退出 |
| timeout | case error，关闭service并保留safe diagnostics |
| external unavailable | live case skipped/unavailable，不算pass |
| cleanup失败 | warning，不改grade |

Harness failure不得改写 target Runtime/Tool/Plan/Feedback/evidence/Domain facts。

## 28. Semantic events、日志与隐私

只记录 safe lifecycle：

```text
eval.run.started/completed
eval.case.started/completed
eval.grader.completed/failed
eval.report.written/failed
```

字段仅包括 eval IDs/version/status/reason/duration/target identity。禁止完整input、raw expected/actual、provider response、Tool args/output、Context/Memory/Profile、confirmation token、exception text和private reasoning。

完整grade进入report artifact；可查询评价进入shared annotation。不创建`eval_events.jsonl`作为第二套canonical trace。

## 29. Focused tests

- Eval models/schema/identity/version validation；
- manifest trusted references、duplicate/unknown/path/import拒绝；
- state probe registry白名单、before/after snapshot、cross-case isolation和delta redaction；
- deterministic matchers；
- 11类runtime-fact grader使用pure RuntimeReport fixtures；StateChangeGrader使用RuntimeReport + EvalStateDelta fixture；
- safety stop与unexpected failure分类；
- aggregation和exit codes；
- runner isolation/cleanup/timeout/keep-failed；
- Runtime/reader/fact/report/grader/sink failure isolation；
- GradeResult到AnnotationRecord lineage/idempotency；
- report text/JSON deterministic snapshot/redaction；
- architecture test：Runtime等不依赖`app.evals`；
- negative assertions：eval metadata不进入prompt/Policy/Tool args/Domain facts。

## 30. Compiled E2E

1. Skill selection component suite兼容现有fixture。
2. Direct final-only。
3. Direct READ success + evidence/grounding。
4. Direct WRITE confirmation前零写、后一次写。
5. Tool failure/false success被定位。
6. Planning preview→confirm跨trace。
7. Planning partial completed/failed/not-run。
8. Recovery explain零执行权限spans。
9. serial diamond DAG dependency/outcome。
10. 一个历史 regression case产生stable reason。
11. restart/index rebuild后grade一致。
12. trace/annotation/report/grader failure isolation。

所有 case 独立store/session，不读写真实用户数据。

## 31. 少量真实模型 smoke

offline gate通过后运行4条：Direct READ、Planning preview/confirm、Recovery explain、一个failure/policy stop。每次run独立报告；允许少量重复观察nondeterminism，但不做多数投票或用重跑隐藏失败。

## 32. 文档与学习链接

计划确认时更新 `docs/AGENT_LEARNING_LINKS.md`，加入 Eval lifecycle、dataset/experiment/evaluator、grader 与 agent trajectory评价资料。

实施时更新：

- `docs/ARCHITECTURE.md`：Harness依赖方向、isolated workspace、shared report；
- `docs/RUNTIME_CONCEPTS.md`：test vs eval、deterministic grader、LLM judge、failure分类；
- `docs/PROGRESS_LOG.md`：只记录已完成suite/grader/E2E/smoke/gate；
- `README.md`：实现后加入eval命令；
- `plans/RUNTIME_REFACTOR_PLAN.md`、`plans/modules/README.md`：同步Stage 11B状态；
- `INSPECTOR_PLAN.md`：只在共享接口名称变化时更新annotation展示引用。

## 33. 分阶段实施步骤

1. 确认范围、suite类型、models、graders、aggregation和不做项。
2. 实现纯models/errors/manifest loader。
3. 实现matchers与grader contracts。
4. 实现12类deterministic graders。
5. 实现aggregation、text/JSON report和exit contract。
6. 实现isolated workspace与RuntimeFactory。
7. 实现单case Runner lifecycle。
8. 实现suite lifecycle、evaluator trace/link和Annotation映射。
9. 适配现有Skill fixture，保留原测试。
10. 加入Direct compiled cases。
11. 加入Planning/Recovery cases。
12. 先接入serial DAG fixture开发grader；DAG计划完成后再接正式scheduler compiled case。
13. 加入regression suite与独立CLI dispatch。
14. 运行focused tests与12条compiled E2E。
15. 运行统一离线回归、compileall、diff check、architecture audit。
16. 运行4条real-LLM smoke。
17. 用正式serial DAG compiled case替换fixture作为production gate证据。
18. 同步文档并执行go/no-go gate。

## 34. 每一步完成条件

- 1：owner、inputs、expectations、fact priority和gate无冲突。
- 2：invalid/unknown/duplicate/path/import全部fail-closed。
- 3：grader不解析raw repositories/logs。
- 4：12类grader输出stable reason/target identity。
- 5：required/optional/skip/error和exit codes通过。
- 6：case完全隔离，不加载用户state/confirmation；RuntimeFactory不调用production bootstrap。
- 7：normal Runtime path产生唯一shared report供grader使用。
- 8：evaluation link/annotations可被Inspector读取，sink失败不改grade。
- 9：现有Skill fixture等价，未提前删除测试。
- 10：Direct安全/evidence/grounding可重复。
- 11：Planning partial和Recovery零执行正确。
- 12：fixture dependency由links/facts评分，不靠event顺序。
- 13：CLI不把expectation注入Runtime/model。
- 14：compiled E2E零意外失败、无cross-case leakage。
- 15：统一离线、compileall、diff、依赖审计通过。
- 16：live结果区分grade/provider/environment。
- 17：正式serial DAG node outcomes/links通过相同grader，fixture不再是最终gate唯一证据。
- 18：文档只记录已实现事实，gate结论明确。

## 35. 最终 go/no-go gate

`go` 必须满足：

- Inspector/Eval确实共享同一TraceReader、FactProvider、ReportBuilder和RuntimeReport；
- Eval没有shadow Tool/Plan/Evidence/Feedback/Trace模型或第二套success语义；
- 12类deterministic graders能定位trace/span/fact；
- Direct、Planning、Recovery和正式serial DAG compiled case成立；fixture只用于前期开发；
- product failure、harness error、skip/unavailable和safety stop分类清楚；
- 每case隔离，无真实用户数据或旧confirmation复用；
- eval metadata/expectations/grades不影响Policy、prompt、Tool或Domain facts；
- annotation/report/reader/grader失败不改target facts；
- live smoke与offline gate分层；
- focused、compiled、统一回归、compileall、diff和architecture audit通过；
- 没有大幅修改现有Runtime框架。

以下任一为`no-go`：grader各自解析JSONL/SQLite产生不同结论；expectation进入prompt或授权；fixture/live读取真实用户数据；LLM judge覆盖确定性失败；retry隐藏失败；加权总分让权限红线仍pass；report/annotation成为业务事实；为Harness引入远端平台或大规模框架改造。

## 36. 面试演示场景

1. test vs Eval：断言框架与case/runner/grader/report的区别。
2. trajectory evaluation：route→Policy→Tool→evidence→state→answer。
3. false success：模型声称完成但零evidence，grader失败且Inspector定位同一annotation。
4. Planning partial：completed/failed/not-run与部分evidence。
5. Recovery safety：解释停点但零执行、旧confirmation不复用。
6. serial DAG：C失败使D blocked，dependency grader读links。
7. regression：历史bug固化为stable case/reason。
8. failure classification：grade、harness、provider、safety stop。
9. Inspector/Eval共模：同一RuntimeReport既评分又调试。
10. safe degradation：annotation/index/report失败不改业务facts。

## 37. 已确认默认

1. V0只做本地CLI + text/JSON report。
2. 串行case，每case独立temp workspace；并行后移。
3. 以12类deterministic graders为主，不实现LLM judge。
4. 不使用加权总分；required grader/case任一失败即失败。
5. 现有Skill fixture先适配不删除，其他tests只提炼代表case。
6. compiled runtime suite是主离线gate，real-LLM smoke独立且少量。
7. Runner通过Runtime public interface和isolated factory运行；除StateChangeGrader读取Eval-owned state delta外，grader只通过shared RuntimeReport读执行事实。
8. report是evaluation artifact，Annotation是shared查询结果；都不是Runtime业务事实。
9. eval metadata只进入observability context。
10. 实施只增加`app/evals`、manifests、CLI dispatch和test composition，不大改现有框架。
11. 不为StateChangeGrader修改Domain schema或统一增加run_id；state delta只由Eval白名单probe在隔离workspace生成。
