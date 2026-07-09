# Runtime Core 模块计划

## 当前状态

阶段 3 Runtime Core 初版已完成。

当前边界：

- Runtime event 写入 `events.jsonl`。
- LLM interaction 写入 `llm.jsonl`。
- normal 程序日志写入 `application.log`。
- SQLite 不承载 runtime event / LLM log；它主要承载业务事实和适合关系查询的数据。

已完成：

- `main.py` 已作为当前 CLI 骨架入口。
- `app/runtime/` 已包含 `RuntimeRequest`、`RuntimeSession`、`RuntimeResult`、`RuntimeService`、run record helper 和 bootstrap。
- `RuntimeService` 已接入 `IntentService` 和 `PolicyService`。
- 每次 run 可以写入 `run_records`，并把结构化 runtime event 写入 `events.jsonl`。
- 当前 orchestration / execution 明确保持 stub，并通过 `runtime.orchestration.stubbed` 暴露。
- Runtime Core 聚焦测试已覆盖成功 run、confirmation、intent failure、policy failure 和 stub execution。
- `docs/PROGRESS_LOG.md`、`docs/ARCHITECTURE.md` 和 `docs/RUNTIME_CONCEPTS.md` 已同步当前边界。

仍保留到后续阶段：

- 真实 LangGraph orchestration 放到阶段 4。
- Planner、Executor、Tool System 和业务 domain 写入放到后续模块。
- 多轮 confirmation / persistent session store 后续按明确需求设计。

阶段 3 收口验证：

- 已运行 `uv run python -m compileall app tests`。
- 按用户要求，本次不运行全量测试。

## 1. 目标

本模块对应 `plans/RUNTIME_REFACTOR_PLAN.md` 的“阶段 3：Runtime Core / Intent / Policy”中的 Runtime Core 部分。

目标是建立当前 runtime 的最小可运行入口和运行边界，让后续 Intent、Policy、LangGraph、Planner、Executor、Context、Memory 和 Domain 都能挂在一个清晰的 request / result / run lifecycle 上。

阶段 3 初版结束时，项目应具备：

- `main.py` 作为当前 CLI demo 入口。
- `app/runtime/` 作为 request lifecycle、session lifecycle、run lifecycle 和 result model 的归属。
- 一轮用户输入可以形成 `RuntimeRequest`，经过 Intent 和 Policy，返回 `RuntimeResult`。
- 每次 run 可以形成结构化 runtime event，并写入文件日志。
- session 初版保持 request-local / process-local，不新增持久化 sessions 表。
- LangGraph、Planner、Executor、Tool System 和 Domain 写入先保留扩展点，不在本阶段提前实现。

本模块不是完整 Agent Loop。它先解决入口、生命周期、边界和 evidence 写入问题。

## 2. 当前 V0 参考

阶段 3 默认不读取 `legacy_v0/`。只有在后续施工时需要追溯旧入口参数、旧 Agent 聚合行为或旧 CLI 输出格式时，才按 `AGENTS.md` 的 Legacy 读取规则读取相关片段。

当前可依据的参考是：

- `README.md`：CLI 入口是 `uv run python main.py`。
- `docs/PROGRESS_LOG.md`：`main.py` 已存在，当前 Runtime Core / Intent / Policy 仍是阶段 3 stub execution。
- `docs/ARCHITECTURE.md`：定义 `main -> runtime -> orchestration -> intent / policy / ...` 的高层依赖方向。
- `docs/ARCHITECTURE.md`：当前 runtime 使用显式分层，不能隐式依赖 legacy agent；启动流程会连接 SQLite、执行 migration，并初始化文件日志。
- `plans/modules/STORAGE_SQLITE_PLAN.md`：`run_records`、`tool_calls` 和 unit of work 是当前 SQLite storage 底座；event / LLM 日志由 `OBSERVABILITY_LOGGING_PLAN.md` 文件化。

V0 的主要问题预计是：

- 旧入口容易直接进入大 Agent 聚合对象，入口、routing、planning、execution、state 和 observability 边界不清。
- 一次 run 的 request、result、session、trace 和最终回答容易混在一起。
- 运行证据和业务事实容易被 assistant 文本或 planner 输出污染。

阶段 3 的升级方式是建立新的轻量 Runtime Core，而不是搬运旧 Agent Loop。

## 3. 当前范围

初版做：

- 创建 `main.py` 作为当前 CLI 骨架入口。
- 创建 `app/runtime/` 包，定义 request、result、session、run lifecycle 和 runtime service。
- 启动时加载 `config/default.json`，连接 SQLite，执行 migration，初始化 observability writer。
- 接受一轮用户输入，创建 `RuntimeRequest`。
- 为每次 request 生成 `session_id` 和 `run_id`。
- 调用 Intent service 和 Policy service。
- 返回结构化 `RuntimeResult`，CLI 打印 final message。
- 写入关键 runtime event 到 `events.jsonl`，让 Inspector / Eval 后续可以解释一次 run。
- 在 orchestration / execution 尚未实现时，返回明确的 stub response。

初版不做：

- 不实现真实 LangGraph orchestration。
- 不实现 Planner、Executor、Tool System 或业务 domain 写入。
- 不实现多轮对话状态管理。
- 不实现 persistent session store 或 `sessions` 表。
- 不把 assistant final answer、Planner 输出、LangGraph checkpoint 或 conversation summary 当成事实来源。
- 不把 Runtime Core 做成复杂平台框架。

后续版本可做：

- 接入 `app/orchestration/` 的 LangGraph StateGraph。
- 接入 Context / Memory / State Assembly。
- 接入 Planner / Direct Executor。
- 接入 Tool System、Domain repository 和 ExecutionFeedback。
- 让 Inspector 基于 event log 和必要的业务事实生成更完整的 runtime report。
- 如果多轮确认和长会话成为明确需求，再设计 session store。

## 4. Runtime 边界

输入：

- CLI 获取的一轮用户文本。
- 当前进程生成或传入的 `session_id`。
- config 中的 SQLite 数据库路径。
- Intent service。
- Policy service。
- observability file log writer。

输出：

- `RuntimeRequest`：当前 request 的结构化输入。
- `RuntimeResult`：本轮 runtime 可展示结果。
- `run_records`：当前实现中的一次 run 持久化记录。
- `events.jsonl`：Intent、Policy、stub routing、失败等 runtime 路径 event。

依赖：

```text
main
-> runtime
-> intent / policy
-> storage / observability / common
```

Runtime Core 可以：

- 加载配置。
- 初始化 SQLite 和 migration。
- 创建 run id / session id。
- 调用 Intent 和 Policy。
- 记录 runtime event。
- 包装错误为结构化 result。

Runtime Core 不负责：

- 不判断具体业务 intent 的语义细节。
- 不授权写入。
- 不调用工具。
- 不生成计划。
- 不执行业务写入。
- 不保存长期 memory。
- 不读取 LangGraph checkpoint 作为事实来源。

关键边界：

- `RuntimeRequest` 是 request-local 输入对象，不是长期 conversation memory。
- `RuntimeResult` 是本轮对用户展示的结果，不是业务事实来源。
- `session_id` 初版用于关联当前进程或当前请求链路，不写入 SQLite。
- `run_id` 是日志和可选持久化记录的主关联键，应被 `events.jsonl`、`llm.jsonl` 和必要的关系数据引用。
- Runtime Core 只相信 Policy 返回的授权结果，不从 Intent、Planner、assistant 文本或 checkpoint 推断授权。

## 5. 数据模型 / 存储

初版不新增 SQLite schema。

当前阶段使用已存在的基础 storage 表，并通过文件日志记录 runtime event：

```text
run_records
tool_calls
events.jsonl
llm.jsonl
application.log
```

阶段 3 Runtime Core 使用方式：

- `run_records` 记录每次 run 的开始、结束、状态、摘要和错误码。
- `events.jsonl` 记录 runtime 生命周期关键事件。
- `llm.jsonl` 初版为空文件；后续真实 LLM request / response 写入该文件。
- `application.log` 记录 runtime started / completed / failed 等 normal 程序日志。
- `tool_calls` 初版不写入，因为本阶段不执行真实工具。

建议 trace event：

- `runtime.run.started`
- `runtime.request.created`
- `runtime.intent.started`
- `runtime.intent.completed`
- `runtime.policy.started`
- `runtime.policy.completed`
- `runtime.orchestration.stubbed`
- `runtime.run.completed`
- `runtime.run.failed`

request-local 状态：

- 原始用户输入。
- `RuntimeRequest`。
- `RuntimeSession`。
- `IntentDecision`。
- `PolicyDecision`。
- stub orchestration result。
- exception / error context。

可以写入持久化记录的状态：

- run id、status、summary、error code。
- 压缩后的 event payload，写入 `events.jsonl`。
- 后续真实 tool evidence。
- 后续真实 LLM interaction log，目标是写入 `llm.jsonl`。

不能写入业务数据库或不能作为事实来源的状态：

- 临时 intent classifier 中间分数。
- assistant final answer 文本作为业务事实。
- Planner 输出作为授权事实。
- LangGraph checkpoint 作为业务事实或授权事实。
- conversation summary 作为长期 memory。
- 未经明确授权的写入候选。

## 6. 对外接口

计划暴露的最小接口：

```text
app/runtime/models.py
- RuntimeRequest
- RuntimeResult
- RuntimeSession
- RuntimeStatus

app/runtime/service.py
- RuntimeService
- RuntimeService.handle(request: RuntimeRequest) -> RuntimeResult

app/runtime/bootstrap.py
- build_runtime_service(...) -> RuntimeService

main.py
- main() -> int
```

模型建议字段：

```text
RuntimeRequest
- turn_id
- run_id
- session_id
- user_input
- created_at

RuntimeSession
- session_id
- started_at
- metadata

RuntimeResult
- run_id
- session_id
- status
- message
- intent
- policy
- error_code
- trace_summary
```

接口原则：

- Runtime service 接收已经构造好的 `RuntimeRequest`，便于测试绕过 CLI。
- CLI 只做 I/O 和 exit code，不放业务逻辑。
- `RuntimeResult` 可以包含 Intent / Policy 的摘要，但不能把它们升级为业务事实。
- 错误使用项目内错误类型或结构化 error code，不让裸异常泄露到 CLI。

## 7. 失败模式

预期失败：

- 配置加载失败。
- SQLite 路径不可写。
- migration 失败。
- run record 创建失败。
- trace event 写入失败。
- Intent service 抛错。
- Policy service 抛错。
- 用户输入为空或不可处理。
- stub orchestration 未实现但被误认为真实执行。

处理原则：

- 启动配置、连接和 migration 失败时，CLI 返回非零 exit code。
- run 已创建后发生失败，应尽量写入 `runtime.run.failed` trace 并更新 run status。
- Intent / Policy 失败不能默认为允许写入。
- trace 写入失败初版可以抛错，让测试暴露问题；后续再考虑降级。
- stub response 必须明确说明当前阶段尚未执行真实工具或业务写入。

失败 trace 建议：

- `runtime.bootstrap.failed`
- `runtime.intent.failed`
- `runtime.policy.failed`
- `runtime.run.failed`

## 8. 测试和 Eval

最小测试：

- `RuntimeRequest` / `RuntimeResult` 可以构造并包含 run/session id。
- `RuntimeService.handle(...)` 调用 Intent service 和 Policy service。
- 每次成功 run 写入 runtime event；是否写入 `run_records` 取决于后续是否需要关系查询。
- 每次成功 run 写入按序 runtime event 到 `events.jsonl`。
- Intent 失败时返回 error result，且不调用 Policy 或不产生授权。
- Policy 失败时返回 error result，且不执行后续 stub。
- session id 不写入 SQLite sessions 表，因为初版没有该表。
- CLI 测试使用临时数据库或 `:memory:`，不触碰真实 `data/lifeops.sqlite3`。

暂不做 Eval：

- Runtime Core 提供可被后续 Eval 读取的 event log。
- 完整 Eval Harness 留到 `plans/modules/EVAL_HARNESS_PLAN.md`。

验证命令建议：

```powershell
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'; uv run python -m unittest discover -s tests -v
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'; uv run python -m compileall app tests
```

施工时可先运行阶段 3 新增的聚焦测试，再按影响范围决定是否运行当前有效测试集。

## 9. 文档更新

阶段 3 Runtime Core 完成后应更新：

- `docs/PROGRESS_LOG.md`：记录 `main.py`、`app/runtime/`、阶段 3 有效测试命令和当前仍是 stub execution。
- `docs/ARCHITECTURE.md`：补充 Runtime Core、RuntimeRequest、RuntimeResult、session/run lifecycle 边界。
- `docs/RUNTIME_CONCEPTS.md`：补充 Agent Loop / Runtime Core / request-result lifecycle 的学习章节。
- `docs/AGENT_LEARNING_LINKS.md`：补充 Agent Runtime、run lifecycle、observability 和本地 persistence 相关权威学习链接；

通常不需要更新：

- `README.md`：除非 `uv run python main.py` 已经成为正式可演示入口。
- `docs/RUNTIME_CONCEPTS.md`：沉淀阶段 3 已经学到的 Runtime Core / request lifecycle / stub execution 解释。
- `CHANGELOG.md`：除非用户明确要求记录里程碑。

如实施时改变架构边界，应更新 `docs/ARCHITECTURE.md`。

## 10. 实施步骤

建议小步施工顺序：

1. [x] 创建 `plans/modules/RUNTIME_CORE_PLAN.md` 和 `plans/modules/INTENT_POLICY_PLAN.md`。
2. [x] 创建 `app/runtime/` 空包和 models/service/bootstrap 文件。
3. [x] 定义 `RuntimeRequest`、`RuntimeSession`、`RuntimeResult` 和 status 枚举。
4. [x] 实现 runtime service 的最小 handle 流程，先使用可注入的 Intent / Policy stub。
5. [x] 接入 event 文件日志和 `run_records` 写入 helper。
6. [x] 创建 `main.py`，完成 config、SQLite、migration、runtime service 的启动骨架。
7. [x] 接入真实阶段 3 Intent service 和 Policy service。
8. [x] 补 Runtime Core 聚焦测试，使用 `tests/helpers.py` 的测试数据库。
9. [x] 更新 `docs/PROGRESS_LOG.md`、`docs/ARCHITECTURE.md` 和 `docs/RUNTIME_CONCEPTS.md`。
10. [x] 运行最小相关测试和 compile 检查。

## Grill-me 检查清单

- 为什么阶段 3 先做 Runtime Core，而不是直接做 LangGraph？
  - 因为当前需要先固定入口、request/result、event log 和授权边界。LangGraph 后续只接入 orchestration，不应该吞掉 runtime 自己的事实源和 policy 边界。

- 为什么 session 初版不入库？
  - 因为阶段 3 还没有多轮 confirmation、long-term conversation 或 inspector session 查询需求。session 先体现在文件日志目录和 request-local id 中，避免过早 schema 设计。

- 为什么 RuntimeResult 不是事实来源？
  - 因为它是给用户看的本轮输出。业务事实必须来自 repository、成功 WRITE result 和用户授权后的写入证据。

- main.py 应该放多少逻辑？
  - 只放 CLI I/O、bootstrap 和 exit code。真正 runtime 行为放在 `app/runtime/`，便于测试和后续 UI / Eval 复用。

- stub response 会不会误导？
  - 必须在 message 和 trace 中明确 `runtime.orchestration.stubbed`，说明本阶段尚未执行真实工具或业务写入。
