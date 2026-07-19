# Stage 11B Eval Harness 模块计划

文档状态：2026-07-19 步骤1-17已完成，Stage 11B最终gate为`go`并关闭。本计划只新增 Eval Harness 自有 models、composition、runner、graders、reports、manifests 与 CLI dispatch；Stage 10 Execution Feedback / Recovery、Stage 11A Inspector、shared Trace Contract、`app/runtime_reporting`、Runtime/Planner/Executor/Policy/Tool/Domain 的现有设计与公共接口全部保持冻结。本实现通过现有 `TraceReader`、`RuntimeFactProvider`、`RuntimeReportBuilder`、`RuntimeReport`、repository Ports 和 test composition 接缝完成适配，没有重新定义执行事实、trace storage、Inspector diagnosis或Recovery语义。

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

实施前置 gate（2026-07-19 已满足）：

1. shared `TraceReader`、`RuntimeFactProvider`、`RuntimeReportBuilder` 和 immutable `RuntimeReport` 已实现并由 Inspector V1 验证；
2. Direct、Planning、Recovery canonical traces 可重复读取，`ExecutionFeedbackFactSource` / `RecoveryResultFactSource` 已通过 typed provider 接缝提供当前冻结范围内的安全投影；
3. Inspector 已能显示 shared evaluation annotations 且不重算 grade；
4. shared serial diamond fixture 已冻结 dependency/link/blocked 语义。正式 DAG Scheduler 尚未规划或实现，因此只作为未来跨模块兼容性回归，不阻塞本 Eval Harness V0 关闭；
5. 当前 `RuntimeReport` 对 route、intent、policy、selected skills 和逐 action Feedback 只提供空值或汇总级投影。本模块不得修改这些冻结接口，也不得回读 raw JSONL/SQLite 补洞；对应 grader 必须按第 16 节 readiness matrix 收窄或延期。

## 3. 当前实现基线

当前仓库已有：

- `unittest` focused tests；
- 使用真实 Runtime/Planner/Executor/Gateway wiring 和 deterministic providers 的 compiled E2E；
- 受环境变量 gate 控制的 real-LLM、MCP 和 live-user E2E；
- `tests/fixtures/skills/*.json` 与 `test_skill_eval_fixtures.py`，继续作为既有 component contract tests；本轮不把它们强行包装成 RuntimeReport case；
- 对 `RuntimeResult`、events、evidence、Plan state、SQLite state 和文件结果的分散断言；
- 已完成并冻结的统一 Trace、RuntimeReport、Annotation、Execution Feedback / Recovery 与 Inspector 标准。

当前缺口：

- 没有统一、可版本化的 `EvalCase/EvalSuite` schema；
- 每个 E2E 自行读取 result/events/database，缺少共享 grader；
- 没有 eval run identity、统一 report、exit code 和失败分类；
- 当前冻结 `RuntimeReport` 可覆盖 execution path、Plan/workflow、Tool/evidence、Feedback汇总、validation、Recovery、trace/privacy；不能精确覆盖 intent/policy/Skill 决策或逐 action Feedback；
- regression case 缺少 bug lineage；
- live failure 容易混淆产品失败与 provider/environment 问题；
- Inspector 已能按 trace 显示带完整 eval lineage 的 evaluation annotations，但尚无 suite runner/report。

## 4. V0 / legacy 决策

本轮不读取 `legacy_v0/`。当前 tests、compiled E2E、live E2E 与 shared trace 计划已足够设计 V1 Harness。只有迁移一个当前 tests 未覆盖、仍有价值的历史 regression case 时，才先说明原因并只读对应 legacy fixture/test；不迁移旧 runner、日志 schema 或报告格式。

## 5. 本轮范围

- 定义 Eval-owned models、versioned manifest 和 expectation contract。
- 实现本地 suite loader、runner、grader registry、aggregation、text/JSON report。
- 通过正常Runtime/Recovery public entry执行case；target trace保持冻结入口的既有TraceSource，另建`source=eval` evaluator trace。
- 使用唯一 shared read path 构造 grader 输入；Eval-owned state delta 只作为隔离测试 oracle。
- 实现第 16 节冻结的 10 类、与当前 `RuntimeReport` 可用字段兼容的 deterministic graders。
- 将 grade 保存为 shared evaluation annotation，并用 `evaluation_of` link 关联 target trace。
- 区分compiled runtime、regression、real-LLM smoke；component fixture继续留在既有unittest。
- 覆盖 Direct、Planning、Recovery 和 shared serial diamond 代表场景；正式 DAG Scheduler case留作未来兼容性回归。
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
- 不修改 shared Trace/RuntimeReport models、`RuntimeReportBuilder`、ExecutionFeedback/Recovery/Inspector 的现有接口或行为；发现缺失字段时返回稳定 `skipped/unavailable`，不建立 shadow projection。
- 不在 V0 迁移现有 Skill component fixtures；原测试保留，未来只有出现独立 component-subject 计划时再适配。

## 7. 模块边界与依赖方向

建议结构：

```text
app/observability/              shared owner
  trace/read/index/annotations

app/runtime_reporting/          shared high-level read owner
  fact provider/report models/report builder

app/evals/                      Eval Harness owner
  models.py                     case/suite/run/result/report
  ports.py                      target executor/fact-provider factory/report sink/clock
  loader.py                     versioned manifests
  workspace.py                  per-case isolated paths/stores/lifecycle
  adapters.py                   isolated test composition and typed fact sources
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
     -> EvalTargetExecutorFactory -> normal RuntimeService / RecoveryRuntime public path
     -> shared TraceReader/AnnotationSink
     -> app.runtime_reporting FactProvider/ReportBuilder
     -> isolated test repositories/providers

Runtime / Planner / Executor / Tool / Domain
  -X-> app.evals
```

Harness可以作为外部调用者运行Runtime；Runtime core不能import eval models、expectations、graders或fixtures。`EvalTargetExecutorFactory`复用`RuntimeService` / `RecoveryRuntime`现有公开constructor、public methods和test adapters，不调用会固定真实LLM/MCP/用户路径的production `build_runtime_service()`，也不要求Runtime增加eval-only参数。

## 8. 与现有模块的关系

- **Shared read boundary**：Observability唯一拥有trace/annotation/reader；`app/runtime_reporting`唯一拥有fact bundle/report。
- **Inspector**：只显示既有 Eval annotations；不运行 suite、不重算 grade。
- **ExecutionFeedback**：复用现有`ExecutionFeedbackFactSource`的overall status、counts、validation、stop point与evidence投影；V0不声称逐action classification可见，也不重建action success。
- **Recovery**：运行正常只读 Recovery 入口并断言零执行 span，不替代 RecoveryService。
- **Planner/Executor**：通过 public interface 被测，不增加 eval-only branch。
- **Policy/Gateway**：继续通过真实permission/confirmation/Gateway链执行；由于当前`RuntimeReport.policy_decision`未投影具体决策，V0只评分可观察的Tool attempts、stop point、state delta和evidence，不宣称读取了Policy内部决定。
- **Context/Memory**：只用 isolated fixtures；eval metadata 不进入 assembly/content。
- **DAG**：V0 grader只消费shared diamond fixture中的node outcome与`depends_on` links，不依赖scheduler implementation；正式Scheduler完成后追加兼容性回归。
- **Observability**：grader 不自行解析 JSONL 或直接查询业务 tables。
- **现有 tests**：保留 focused/component tests；只把能通过当前shared RuntimeReport表达的代表性compiled E2E提炼为eval case。

## 9. Eval 分层

| suite 类型 | 被测范围 | provider/data | 主要用途 |
|---|---|---|---|
| `compiled_runtime` | 完整 Runtime path | deterministic providers + temp stores | 主离线行为 gate |
| `regression` | 曾发生的具体 bug | 最小复现场景 | 防止历史问题回归 |
| `real_llm_smoke` | 真实 model adapter | live provider，默认 READ | 验证现实兼容性 |

`unittest` 是执行和断言框架；Eval Harness 是 runtime case、runner、grader、report 与 lineage。compiled E2E 可以由 `unittest` 调用，也可以作为suite case，两者不是互斥关系。现有Skill component fixtures继续由原测试拥有，不在V0引入第二种EvaluationSubject。

## 10. Eval-owned 数据模型

```text
EvalCase
  schema_version
  case_id / title / description
  execution_mode(runtime_request|plan_command_sequence|recovery)
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
  status(passed|failed|skipped|unavailable|error)
  grade_results
  duration_ms
  error_code? / safe_explanation?

GradeResult
  grade_id
  grader_id / grader_version
  status(passed|failed|warning|skipped|unavailable|error)
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

这些模型只描述evaluation lifecycle，不复制Runtime、Tool、Evidence、Plan、Feedback、Trace或RuntimeReport模型。`execution_mode`只选择Eval-owned target executor adapter，不进入`RuntimeRequest`或业务prompt。`EvalStateSnapshot/Delta`是隔离测试workspace中的oracle：由manifest白名单probe产生，只用于StateChangeGrader，不是Runtime执行事实，不进入Inspector/RuntimeReport/Annotation，也不能覆盖ToolResult/Evidence。

## 11. Case input 与 expectation contract

`EvalCase.input`只包含正常Runtime request、Plan command sequence或Recovery调用所需的公开输入。fixture通过trusted registry reference选择test-only provider/data，不允许manifest指定任意Python import、callable、path或command。

```text
EvalExpectations
  execution_path?
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

每个字段只由对应 grader 解释。缺少 expectation 时 grader 不猜目标；privacy/trace integrity 等 invariant grader 可以由 suite 默认启用。V0 manifest不接受`intent`、`policy`或`selected_skills` expectation，因为当前冻结RuntimeReport未提供这些决策事实；unknown字段按schema fail-closed，不能静默忽略。

## 12. Matcher 语义

V0 只提供少量确定性 matcher：

- `equals`：enum、status、error code、execution path；
- `contains_all/contains_none`：Tool、evidence type、reason code；
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

class EvalTargetExecutor(Protocol):
    def execute(self) -> EvalTargetResult: ...
    def close(self) -> None: ...

class EvalTargetExecutorFactory(Protocol):
    def create(self, case: EvalCase, workspace: EvalWorkspace) -> EvalTargetExecutor: ...

class EvalFactProviderFactory(Protocol):
    def create(self, case: EvalCase, workspace: EvalWorkspace) -> RuntimeFactProvider: ...

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

`EvalTargetResult`只保存target类型和已有公开identity（`run_id/session_id/turn_id`，以及Recovery/Plan需要的已有ID），不复制`RuntimeResult`、`RecoveryResult`或Plan models。Runner注入loader、workspace factory、target executor factory、fact-provider factory、shared TraceReader、shared report builder、annotation Port、state probe registry、grader registry、report sink、clock和ID factory。

## 14. Case 执行流程

1. 校验 suite/case schema、IDs、graders 和 fixture references；
2. 创建 case 独占 temp workspace、SQLite、session logs、Context/Memory files；
3. 准备deterministic provider/data，并通过manifest白名单state probes记录before snapshot；
4. 按`execution_mode`构造正常`RuntimeRequest`、`PlanCommand`序列或Recovery调用；Eval IDs/expectations不进入这些业务输入；
5. 通过production-like isolated composition执行正常Runtime/Recovery public path；target trace保持当前入口的既有`TraceSource`和attributes，不修改冻结Runtime telemetry设计；
6. 通过target `run_id`等已有identity获得target trace，并通过shared TraceReader、case-owned typed FactProvider和唯一shared RuntimeReportBuilder构造`RuntimeReport`；
7. 通过相同白名单probes记录after snapshot并构造Eval-owned `EvalStateDelta`；
8. 以`EvaluationSubject(RuntimeReport, optional state_delta)`运行graders，隔离单grader exception；
9. 单独创建`source=eval` evaluator trace，在其现有RUNTIME root下建立EVALUATOR case/grader spans，把grade追加为shared annotations，并用`evaluation_of` link指向target root；完整eval lineage位于evaluator trace、Annotation和EvalReport，state delta内容不写annotation；
10. 聚合CaseResult/EvalReport；
11. 关闭service/handlers，清理或显式保留失败workspace。

默认不retry。V0不承诺从Runner线程强制终止任意卡死的同步Runtime调用：offline adapters必须是deterministic bounded实现，provider/network adapters必须使用自身已有timeout；Runner在可返回的lifecycle phase之间检查deadline并分类`eval_case_timeout`。需要操作系统级hard timeout的live smoke继续由现有外层test/subprocess runner负责，不在本模块引入worker平台。

## 15. 隔离与可复现性

- 每个 offline case 独占 temp root、database、session、provider instance 和 mutable state；
- case 不共享 confirmation、idempotency、repository 或 request-local state；
- suite/case/fixture/grader version 与 source revision 写入 lineage；
- fixed clock/ID 只用于 test adapters，不改变 production contract；
- provider/model/config 的安全 metadata 形成 environment fingerprint；
- fingerprint 不含 API key、完整环境变量、用户路径或 secret；
- V0 串行运行；未来并行必须先证明 workspace 完全隔离。

## 16. Deterministic graders 与当前接口 readiness

V0 registry只包含当前冻结`RuntimeReport`和Eval-owned state delta能够诚实支持的10类grader：

1. `ExecutionPathGrader`：从`plan_report/workflow_report/executor_invocations/recovery_report`判断`final_only/direct/planning/recovery`可观察执行路径；不冒充读取Planner route decision。
2. `PlanLifecycleGrader`：读取由isolated Plan repository Port投影到shared `RuntimeFactBundle.plan_runs_and_steps`的revision与completed/failed/pending/not-run。
3. `WorkflowDependencyGrader`：读取`workflow_report/workflow_dependencies`中的node outcome、dependency、blocked和partial evidence。
4. `ToolCallGrader`：读取shared `tool_attempts`中的Tool identity、effect、status、count/order/forbidden attempts；`handler_reached`只在现有safe Tool span attributes明确提供时评分，缺失时不得推断。
5. `StateChangeGrader`：读取Eval-owned typed before/after delta，判断预期写或零写；不要求Domain schema增加run_id。
6. `EvidenceGrader`：读取shared`EvidenceReport`与Feedback evidence投影，判断success/WRITE所需identity/link/type。
7. `ExecutionFeedbackGrader`：读取当前冻结的overall outcome、path、counts、validation和stop point；V0不评分逐action classification，因为shared report未公开该明细。
8. `FinalAnswerGroundingGrader`：只读取canonical`final_answer_validation`的claim status、accepted count和reason count；不读取raw answer，不做措辞质量判断。
9. `TraceContractGrader`：复用shared contract语义，评分identity、topology、status、links和integrity。
10. `PrivacyGrader`：检查普通TraceGraph/RuntimeReport/Annotation/Report projection不含计划列出的禁止字段；不打开sensitive artifact content。

readiness matrix：

| 评价维度 | V0 canonical input | 本轮结论 |
|---|---|---|
| execution path | shared RuntimeReport已有结构化sections | 实现`ExecutionPathGrader`，只判可观察路径 |
| Plan lifecycle | isolated Plan repository Port -> shared RuntimeFactBundle -> shared builder | 实现Eval-owned typed FactSource adapter；不改shared models/builder |
| workflow/DAG | shared workflow projections + `depends_on` | 用diamond fixture实现；正式Scheduler后回归 |
| Tool/evidence | shared tool spans、EvidenceReport、Feedback evidence | 实现 |
| Feedback/grounding | frozen Feedback summary、validation、stop point | 实现汇总级grader，不扩张为逐action/raw text |
| state change | Eval-owned whitelist probes | 实现；不进入RuntimeReport/Annotation |
| trace/privacy | TraceGraph + RuntimeReport + shared annotations | 实现 |
| intent decision | 当前`RuntimeReport.intent_decision=None` | V0延期；不得读events.jsonl补洞 |
| policy decision | 当前`RuntimeReport.policy_decision=None` | V0延期；用Tool/stop/state/evidence验证外部安全结果，但不命名为Policy grade |
| planning route / selected skills | 当前`route=None`、`selected_skills=()` | V0延期；不修改冻结shared设计 |
| component fixture | 无RuntimeReport subject | 保留原unittest，V0不迁移 |

除StateChangeGrader外，grader只读取`EvalCase + RuntimeReport`。`PlanLifecycleGrader`看到的Plan facts必须在grader运行前经`EvalFactProviderFactory`使用isolated repository Port投影并由唯一shared builder合并；grader自身仍不得打开SQLite。StateChangeGrader额外读取`EvaluationSubject.state_delta`；delta由Runner调用trusted probe registry生成，grader自身不得打开SQLite/files。该oracle不属于Inspector/Eval共享Runtime标准，也不参与事实优先级裁决。

## 17. Aggregation 与 gate

V0 不用加权总分决定 gate：

- required grader `failed` -> case failed；
- required grader `error/unavailable` -> case error，不能计为环境跳过；
- optional grader failure -> warning，除非 suite 将其提升为 required；
- optional grader `unavailable` -> case warning并保留reason；
- required case failed/error -> suite failed；
- offline required case 不允许 skipped；
- live external prerequisite unavailable -> case `unavailable`；required live case使CLI返回3，不能计为passed；
- expected safety stop 匹配 expectation 时可以 passed，不等同 RuntimeStatus.OK；
- harness schema/setup/reader/grader exception 是 error，产品断言不符是 failed；
- warning 不覆盖 failed。

CLI exit code：`0=required passed`、`1=grade failure`、`2=harness/config error`、`3=required environment unavailable`。

## 18. Evaluation trace 与 Annotation

```text
target Runtime/Recovery trace
  保持现有入口的TraceSource与attributes

独立 source=eval evaluator trace
`- RUNTIME root（沿用RequestTelemetry冻结拓扑）
   `- EVALUATOR evaluation.case
      |- eval_run_id / eval_suite_id / eval_case_id
      |- evaluation_of -> target root span
      |- EVALUATOR grader.<grader_id>
      `- AnnotationRecord per GradeResult
```

`GradeResult -> AnnotationRecord` 保持status、score/label、reason、target identity、grader version、source fingerprint和完整eval lineage。target trace本身不需要新增eval attributes；完整expectations、raw provider output或敏感diff不进入普通annotation。

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

main CLI只负责command dispatch。`eval`命令构造`EvalTargetExecutorFactory`与Harness，不先调用production `build_runtime_service()`；每个case再由factory使用`RuntimeService`/`RecoveryRuntime`公开constructor、deterministic adapters和临时配置完成composition。无子命令时保持现有interactive CLI行为。

## 20. Dataset、fixture 与 regression 生命周期

- manifest 必须有 schema version、stable ID 和 suite version；
- case语义改变时升级version，不静默改 expectation；
- fixture只保存合成/公开/test数据；
- fixture reference经registry解析，不允许任意path/import；
- regression case记录 regression ref、原failure category 和最小行为；
- flaky case必须分类为product、provider或harness instability，不能靠提高retry隐藏；
- unknown旧schema显式迁移或fail-closed。

现有Skill fixture继续由`test_skill_eval_fixtures.py`等原测试拥有。本轮既不删除也不迁移；未来若需要component eval，必须先单独冻结非RuntimeReport subject contract，不能在本计划中临时扩张。

## 21. Direct 最小场景

1. final-only：Direct、零Tool、零state change、trace完整。
2. READ success：允许Tool一次、safe result/evidence、answer claim有支持。
3. WRITE confirmation：确认前零Tool attempt/零写，当前exact confirmation后写一次并有evidence；只有existing safe trace明确提供时才额外断言handler reachability。
4. Tool failure：不能声称成功，state与feedback正确。
5. false success：无Tool/evidence却声称完成，被Grounding grader拦截。
6. policy/catalog deny：forbidden Tool零attempt/零写，Feedback stop point正确；V0不声称读取PolicyDecision内部字段。

## 22. Planning 最小场景

1. preview：PlanRun revision持久化，零Tool/Domain write。
2. confirm：多个PlanStep/Executor invocation关联正确。
3. partial：completed/failed/pending/not-run分离，成功evidence保留。
4. stale revision/confirmation：零非法执行，不复用旧权限。
5. bounded replan：只评分现有控制流，Harness不触发额外replan。
6. restart/interrupted：durable Plan/Feedback/evidence重建结果一致。

## 23. Recovery 与 DAG 场景

Recovery case证明：能解释目标/停点/success/failure/not-run/evidence；Recovery trace零Tool、Policy authorization、confirmation和Executor execution；不恢复旧confirmation或WRITE权限。

shared serial diamond case证明：parent-child表达scheduler containment，`depends_on`表达dependency；B成功、C失败、D blocked；B evidence保留，D零Tool attempt；grader不靠event顺序猜edge。该fixture是V0正式gate证据，但不代表Scheduler已实现；未来Scheduler模块完成后必须复用相同grader做兼容性回归。

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
- evaluator trace的`source=eval`不授予target任何权限；target仍按现有Policy/AllowedToolSet/confirmation路径执行；
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
| phase deadline超限或provider timeout返回 | case error，关闭service并保留safe diagnostics；不宣称可中断任意卡死线程 |
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
- 9类report grader使用pure RuntimeReport fixtures；StateChangeGrader使用RuntimeReport + EvalStateDelta fixture；
- safety stop与unexpected failure分类；
- aggregation和exit codes；
- runner isolation/cleanup/phase deadline/provider-timeout/keep-failed；
- Runtime/reader/fact/report/grader/sink failure isolation；
- GradeResult到AnnotationRecord lineage/idempotency；
- report text/JSON deterministic snapshot/redaction；
- architecture test：Runtime等不依赖`app.evals`；
- negative assertions：eval metadata不进入prompt/Policy/Tool args/Domain facts。

## 30. Compiled E2E

1. Direct final-only。
2. Direct READ success + evidence/grounding。
3. Direct WRITE confirmation前零写、后一次写。
4. Tool failure/false success被定位。
5. Planning preview→confirm跨trace。
6. Planning partial completed/failed/not-run。
7. Recovery explain零执行权限spans。
8. shared serial diamond dependency/outcome。
9. 一个历史regression case产生stable reason。
10. restart/index rebuild后grade一致。
11. trace/annotation/report/grader failure isolation。

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
- `INSPECTOR_PLAN.md`：本轮不修改；Inspector已冻结并已能展示shared evaluation annotations。

## 33. 分阶段实施步骤

1. **确认冻结边界与readiness matrix。** 本步骤只核对当前shared接口和case范围，不修改任何已完成模块设计。
2. **实现纯models/errors/manifest loader。** 冻结三种execution mode、stable IDs/version、trusted fixture refs、expectations与unknown-field fail-closed。
3. **实现isolated workspace、state probe registry与Eval-owned typed FactSource adapters。** adapters只通过isolated repository Ports构造现有`RuntimeFactBundle`，不定义shadow facts、不打开用户storage。
4. **实现matchers与grader contracts。** matcher只处理typed safe values，不解析logs/repositories。
5. **实现10类deterministic graders。** 严格遵守第16节字段可用性与skip/unavailable语义。
6. **实现aggregation、text/JSON report和exit contract。** required/optional/failure/error/unavailable保持分离。
7. **实现`EvalTargetExecutorFactory`和单caseRunner lifecycle。** 先覆盖`runtime_request`，验证normal public path、close、cleanup和phase deadline。
8. **实现`plan_command_sequence`与`recovery` target adapters。** 复用现有public constructors/methods，不增加eval-only Runtime branch。
9. **实现suite lifecycle、独立evaluator trace、`evaluation_of` link和Annotation映射。** target trace不增加eval metadata。
10. **加入Direct compiled cases。** 覆盖final-only、READ、WRITE confirmation、failure/false success和deny/zero-write。
11. **加入Planning与Recovery cases。** 覆盖preview/confirm、partial、restart和Recovery零执行权限spans。
12. **加入shared serial diamond fixture case。** dependency只由shared report links/facts评分；正式Scheduler留作未来兼容性回归。
13. **加入一个历史regression suite与独立CLI dispatch。** 不迁移component fixtures。
14. **运行focused tests与11条compiled E2E。** 修复所有意外失败并检查cross-case leakage。
15. **运行统一离线回归、compileall、diff check和architecture audit。** 审计已冻结模块无行为/接口改动。
16. **运行4条real-LLM smoke。** 使用既有provider timeout和外层hard-timeout runner，分类grade/provider/environment。
17. **同步Eval相关文档并执行go/no-go gate。** 正式DAG不作为本轮关闭前置；未来DAG模块完成后追加同grader兼容性回归。

## 34. 每一步完成条件

- 1：owner、inputs、expectations、fact priority和gate无冲突；本计划之外尚无本模块产生的改动。
- 2：invalid/unknown/duplicate/path/import全部fail-closed。
- 3：workspace/probes/fact adapters完全隔离；只使用existing Ports/shared models，不复制事实语义。
- 4：matcher/grader不解析raw repositories/logs，缺失字段显式unavailable。
- 5：10类grader输出stable reason/target identity，延期维度没有伪grade。
- 6：required/optional/skip/error/unavailable和exit codes通过。
- 7：runtime_request正常public path产生唯一shared report；case可关闭、清理或保留失败workspace。
- 8：Planning/Recovery adapters只调用既有public接口，零eval-only execution branch。
- 9：evaluation link/annotations可被Inspector读取，sink失败不改grade，target trace无新增eval字段。
- 10：Direct安全/evidence/grounding可重复。
- 11：Planning partial和Recovery零执行正确。
- 12：fixture dependency由links/facts评分，不靠event顺序；明确不宣称Scheduler存在。
- 13：CLI不把expectation注入Runtime/model，原Skill fixture tests保持原样。
- 14：11条compiled E2E零意外失败、无cross-case leakage。
- 15：统一离线、compileall、diff、依赖审计通过，冻结模块无非必要修改。
- 16：live结果区分grade/provider/environment，不以Harness内部retry隐藏失败。
- 17：文档只记录已实现事实，gate结论明确；未来DAG兼容回归被登记但不阻塞关闭。

## 35. 最终 go/no-go gate

`go` 必须满足：

- Inspector/Eval确实共享同一TraceReader、FactProvider、ReportBuilder和RuntimeReport；
- Eval没有shadow Tool/Plan/Evidence/Feedback/Trace模型或第二套success语义；
- 第16节10类deterministic graders能在当前可用字段范围内定位trace/span/fact，延期维度没有shadow grader；
- Direct、Planning、Recovery和shared serial diamond compiled case成立；正式Scheduler完成后再运行相同grader兼容性回归；
- product failure、harness error、skip/unavailable和safety stop分类清楚；
- 每case隔离，无真实用户数据或旧confirmation复用；
- eval metadata/expectations/grades不影响Policy、prompt、Tool或Domain facts；
- annotation/report/reader/grader失败不改target facts；
- live smoke与offline gate分层；
- focused、compiled、统一回归、compileall、diff和architecture audit通过；
- 没有大幅修改现有Runtime框架。
- 除`app/evals`、eval manifests、Eval CLI dispatch与test composition外，没有本模块引起的已冻结设计或公共接口变更。

以下任一为`no-go`：grader各自解析JSONL/SQLite产生不同结论；expectation进入prompt或授权；fixture/live读取真实用户数据；LLM judge覆盖确定性失败；retry隐藏失败；加权总分让权限红线仍pass；report/annotation成为业务事实；为Harness引入远端平台或大规模框架改造。

2026-07-19最终证据：10类grader与manifest/runner/report/annotation lifecycle聚焦回归`56/56`通过，compiled E2E `11/11`通过，统一离线discovery `787`项零失败、`22`项按显式live/platform gate跳过；compileall、diff与dependency audit通过。Direct READ、Planning preview/confirm、Recovery explain、Policy stop四条real-LLM JSON报告均为`passed`，无provider/environment/hard-timeout失败。实现改动保持在`app/evals`、`evals/manifests`、Eval CLI dispatch和test composition边界内；最终结论为`go`。

## 36. 面试演示场景

1. test vs Eval：断言框架与case/runner/grader/report的区别。
2. trajectory evaluation：可观察execution path→Tool→evidence→state→validated answer；不伪装成读取未投影的Intent/Policy内部决定。
3. false success：模型声称完成但零evidence，grader失败且Inspector定位同一annotation。
4. Planning partial：completed/failed/not-run与部分evidence。
5. Recovery safety：解释停点但零执行、旧confirmation不复用。
6. shared diamond：C失败使D blocked，dependency grader读links；明确它不是Scheduler实现。
7. regression：历史bug固化为stable case/reason。
8. failure classification：grade、harness、provider、safety stop。
9. Inspector/Eval共模：同一RuntimeReport既评分又调试。
10. safe degradation：annotation/index/report失败不改业务facts。

## 37. 已确认默认

1. V0只做本地CLI + text/JSON report。
2. 串行case，每case独立temp workspace；并行后移。
3. 以当前冻结接口可支持的10类deterministic graders为主，不实现LLM judge；intent/policy/planning-route/Skill精确评分延期。
4. 不使用加权总分；required grader/case任一失败即失败。
5. 现有Skill fixture保留原测试且本轮不适配，其他tests只提炼代表runtime case。
6. compiled runtime suite是主离线gate，real-LLM smoke独立且少量。
7. Runner通过Runtime public interface和isolated factory运行；除StateChangeGrader读取Eval-owned state delta外，grader只通过shared RuntimeReport读执行事实。
8. report是evaluation artifact，Annotation是shared查询结果；都不是Runtime业务事实。
9. eval lineage只进入Eval-owned evaluator trace、shared evaluation Annotation和EvalReport；不注入target RuntimeRequest、prompt、Policy、Tool或Domain facts。
10. 实施只增加`app/evals`、manifests、CLI dispatch和test composition，不大改现有框架。
11. 不为StateChangeGrader修改Domain schema或统一增加run_id；state delta只由Eval白名单probe在隔离workspace生成。
