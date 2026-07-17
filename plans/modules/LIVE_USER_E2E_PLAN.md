# Live User E2E 测试计划

状态：已确认；2026-07-16 完成 LIVE-04 审计修订，实施中。

本计划是 Stage 9 Context / Memory 关闭后的整体验收备份。它不替代各模块 focused、compiled E2E 或独立 real-LLM smoke，而是使用真实用户文本、真实 production model adapters 和真实 runtime composition 验证截至 Stage 9 已实现的主要能力。

## 1. 目标

建立 5 个可重复执行的 live user E2E case，覆盖当前 Runtime 主链路：

- Runtime Core、Intent、Policy 与 outer LangGraph orchestration；
- Skill selection、lazy body loading 与 filtered Tool catalog；
- ReAct Executor、Tool Gateway、pre/post Guardrails、confirmation 与 evidence；
- Plan-and-Execute preview、structured command、PlanStep 与 Finalizer；
- Research Hugging Face MCP、Travel durable core；
- session conversation Context、rolling summary、restart continuity；
- read-only Profile、explicit long-term Memory save、restart retrieval 与 hash verification；
- SQLite、conversation/Memory files、`events.jsonl`、`llm.jsonl` 和 `application.log`。

完成后产出一份实测报告，逐 case 记录真实 provider、实际 ToolCall、confirmation、持久化变化、日志证据、失败分类和最终 go/no-go。

## 2. 当前 V0 / 既有测试参考

本轮不读取或复用 `legacy_v0/` 的 Agent loop。当前可复用证据仅来自现行实现：

- `tests/test_runtime_observability_e2e.py`：真实 RuntimeService file-log 骨架；
- `tests/test_research_mcp_real_llm_smoke.py`：production bootstrap + 真实 LLM + 真实 Hugging Face MCP read-only happy path；
- `tests/test_planning_e2e.py`：preview/confirm、cross-domain、replan 和安全边界；
- `tests/test_context_real_llm_smoke.py`：recent/summary/restart/planning/PlanStep 的真实模型切片；
- `tests/test_memory_real_llm_smoke.py`：Profile、save、restart、update、archive 的真实 Executor model 切片。

这些文件只提供已验证机制和断言形状。新的 live user E2E 不复制 fake Intent/Policy/Skill/Planner 作为主路径，也不把 fixture model 决策算作 live 证据。

Memory duplicate/conflict/update/archive/history 的完整生命周期继续由 compiled E2E
和相互独立的 real-LLM smoke 负责，不再塞入一个整体 live user case。整体 E2E
验证主要用户主线，不重复承担所有模块边界组合。

## 3. 当前范围

### 3.1 本轮实现

- production bootstrap 接收可选 `ActionConfirmationProvider`；默认仍为 fail-closed。
- CLI 提供同步、逐 ToolCall 的用户确认，只展示 Tool identity、effect、risk 和 canonical arguments，不显示 handler 或内部状态。
- 5 个显式 live-gated E2E，全部使用真实：
  - `IntentService`；
  - `PolicyService`；
  - `SkillSelectionClient`；
  - `OpenAIPlanningRouteClient`；
  - `OpenAIPlannerModelClient`；
  - `OpenAIExecutorModelClient`；
  - `OpenAIPlanFinalizerClient`；
  - 需要 summary 时使用 `OpenAIContextSummarizer`；
  - Research 主线使用真实本地 stdio MCP Server 和 Hugging Face public provider。
- 每个 case 使用临时 config、SQLite、conversation、Memory 和 log root，不碰真实用户数据库。
- live E2E 串行执行，不进入默认离线 `unittest discover` 的网络调用路径。

### 3.2 明确不做

- 不实现异步 pending confirmation、LangGraph interrupt/checkpoint resume 或跨请求 ToolCall 恢复。
- 不为 E2E 新增第二套授权或绕过 Gateway 的测试后门。
- 不把 fixture Travel provider 冒充线上能力；production Travel external Ports 当前明确 unavailable。
- 不新增 Calendar MCP、远程 MCP、OAuth、browser/UI automation 或真实外部 WRITE。
- 不把模型最终文本作为业务写入成功事实。
- 不根据测试文本中的内部 Tool 名加入 production route shortcut 或强制
  `tool_choice`；真实用户不需要知道内部 Tool 名。
- 不把 post-Tool provider failure 改写成成功；此类结果必须保留失败状态并在
  报告中分类为 `INFRA_BLOCKED`。
- 不在本轮建立通用 Stage 11 Eval Harness、LLM-as-judge 或分数型 benchmark。

## 4. Runtime 边界

正式 live case 的外部入口仍是 `build_runtime_service(...)` 生成的 `RuntimeService`。允许的测试注入只有：

- 临时 config path；
- 实现现有 `ActionConfirmationProvider` Protocol 的 scripted user confirmation；
- case-local request/session/run/turn identity。

scripted confirmation 表示自动化测试中的真实用户 approve/reject 决策，不能：

- 修改 ToolCall；
- 增加 `AllowedToolSet`；
- 绕过 pre/post Guardrail；
- 自己调用 handler；
- 为非 WRITE Tool 伪造 confirmation；
- 跨 run/call/tool/arguments 或 expiry 复用确认。

CLI confirmation 只负责把用户选择转换成精确 `ConfirmedAction`。Policy 仍是 effect 授权事实源，Tool Gateway 仍是唯一执行入口。

## 5. 数据模型 / 存储

本轮不新增 SQLite schema。

每个 E2E case 使用独立临时目录：

```text
<case-root>/
  config.json
  lifeops.db
  conversations/
  memory/
    profile.md
    entries/<memory_id>/v<version>.md
  logs/session_*/
    events.jsonl
    llm.jsonl
    application.log
```

测试断言的 durable 证据：

- SQLite：`run_records`、Plan tables、Research/Travel facts、`memory_index`；
- JSONL：conversation turns/summaries、events、LLM interactions；
- immutable files：Memory version Markdown 与重新计算的 SHA-256；
- Tool evidence：成功 WRITE observation 中的 `ExecutionEvidence`。

测试结束默认清理临时目录；失败信息必须打印 case、run、status、error code、Tool skeleton 和日志路径。报告只保存压缩后的非敏感证据，不复制完整 LLM prompt/response 或 Memory content。

## 6. 对外接口

计划新增或调整：

```python
build_runtime_service(
    config_path="config/default.json",
    *,
    confirmation_provider: ActionConfirmationProvider | None = None,
) -> RuntimeService
```

```python
class CliActionConfirmationProvider:
    def confirm(
        self,
        run_id: str,
        call: ToolCall,
        tool_definition: ToolDefinition,
    ) -> ConfirmedAction | None:
        ...
```

默认 `None` 继续映射为 `NoOpActionConfirmationProvider`。测试使用私有 `_ScriptedUserConfirmationProvider`，不进入 production package。

CLI 只接受明确的 `yes` / `y` 批准；空输入、EOF、其他文本和异常均视为拒绝。批准生成短期、精确绑定的 `ConfirmedAction`。

## 7. 失败模式

### 7.1 产品失败

- 真实模型没有选择预期 Skill / route / Tool；
- Tool 参数不满足 schema；
- confirmation 未精确绑定或被错误复用；
- denied/expired confirmation 后仍发生 handler/数据库/文件写入；
- Context marker 丢失、summary 自动写 Memory、restart 无法恢复；
- Plan preview 前执行 Tool，或 PlanStep 看到未声明依赖；
- Research/Travel/Memory 写入缺失 evidence；
- event/LLM/run record 顺序或状态不一致；
- assistant 文本声称成功但无 durable evidence。

### 7.2 外部 / 环境阻断

- 缺少 provider key/base URL/model；
- DNS、TLS、timeout、429、provider 5xx；
- Hugging Face/MCP public provider unavailable；
- provider 不支持当前 Responses/function-call contract。

外部阻断不得记为 PASS，也不得混入产品 bug。测试报告使用 `INFRA_BLOCKED`；本地 contract、routing、safety 或 persistence 错误使用 `PRODUCT_FAIL`。

### 7.3 稳定性策略

- 固定本轮实际 model ID 并记录，不用模糊 alias 作为报告证据；
- case 串行执行；
- 使用唯一 marker 和隔离数据；
- 断言 route/Tool/status/evidence/SQLite/files/events，不精确匹配自由文本；
- 外部结果只断言 contract 和 provenance，不断言动态论文标题/数量；
- 只对明确的 transport/rate-limit 故障允许整 case 重跑一次，semantic/product failure 不自动重跑；
- case driver 不自动改写用户请求、不自动纠正模型、不自动确认意外出现的
  Plan preview；任何 semantic deviation 直接作为该次结果；
- LIVE-04 拆成两个独立短切片：04A 只验证一次真实用户 WRITE，04B 使用
  canonical `MemoryService` 在 case-local 临时库预置一条已验证 Memory 后，只验证
  production runtime 的 restart recall；两条分别运行、分别计时、分别给出结论；
- 单条 live slice 超过 5 分钟即由外层 runner 终止并先记为 `TIMEOUT`，不得在同一
  测试进程内继续修改 prompt 或自动重跑；随后按最后一条 LLM/Tool 证据分类：卡在
  transport/provider 为 `INFRA_BLOCKED`，重复 semantic action 或本地状态机不终止为
  `PRODUCT_FAIL`；transport/rate-limit 只允许人工重跑当前失败 slice 一次；
- 初次 gate 要求同一配置连续 3 轮全部通过；若成本或 provider 限制导致无法完成，报告明确保留稳定性 gate 未关闭。

## 8. 测试和 Eval

### 8.1 LIVE-01：真实 Research MCP Direct read-only

用户目标：通过 Research Skill 搜索 public Hugging Face agent-runtime papers，只读、不建 Plan、不保存。

验收：

- route 为 Direct；
- `research.search_papers` 成功；
- 返回至少一个合法 canonical paper URL；
- Plan/Research/Travel/Memory 零写；
- Skill/Executor LLM interactions 和完整 event skeleton 存在；
- 敏感 content 不进入 semantic events。

### 8.2 LIVE-02：真实 Travel WRITE + cross-domain Plan

先由用户明确创建一个 Trip 并 approve `travel.create_trip`。随后发起两步只读目标：Research paper search → `travel.get_trip`，要求 preview 后使用结构化 `confirm-plan` 执行。

验收：

- Trip WRITE 有精确 confirmation 和 evidence；
- preview 阶段没有执行 PlanStep；
- confirmed PlanRun 完成且依赖顺序正确；
- Research 使用真实 MCP；Travel 只读取 durable Trip，不调用 unavailable external provider；
- confirmed PlanStep 共享当前 request 的同一 assembly；
- 不保存 Source 或 Itinerary。

### 8.3 LIVE-03：真实 Context long-session summary + restart

同 session 完成足够多的真实聊天 turn，写入 old/recent 唯一 marker；关闭并重建 production runtime 后询问两者。

验收：

- 原始 user/assistant turns 按序写 JSONL；
- 超过预算后真实 Summarizer 生成合法 rolling summary；
- assembly 包含 summary、recent、current；
- 重启后回答包含两个 marker；
- summary 不进入 Memory 或业务表；
- Context payload 不进入 events、Plan facts 或 GraphState。

### 8.4 LIVE-04：真实 Profile / Memory save 与 restart recall

LIVE-04 是一个逻辑 case，但实现为两个互不依赖的 live slice。这样保存阶段的
模型偏差或 provider 故障不会污染 recall 诊断，recall 失败也不会要求重新支付并
重跑 WRITE。两条用户文本均不包含内部 Tool 名。

#### LIVE-04A：一次真实用户 Memory save

用户只做一个自然语言操作：明确要求长期记住一个唯一偏好，并批准一次 WRITE。
该 slice 到 durable save 及最终回答结束，不继续做 duplicate、restart 或 lifecycle。

验收：

- 只批准并执行一次 `memory.save`；重复或意外 WRITE 直接失败；
- save 产生唯一 active index、不可变文件、confirmation ref 和 evidence ref；
- 测试重新计算文件 SHA-256 并与 index 一致；
- 任意意外 Plan preview、自动重试或 post-Tool provider failure 都不能算 PASS。
- `memory.save` 的每 run 一次限制必须由 request-local Tool contract 强制执行，
  不能只依赖模型 prompt；首次 attempt 后不得再次出现在后续 Executor catalog。

#### LIVE-04B：独立 restart recall

测试通过 production `MemoryService` 的 canonical file-first/index-second 路径，在新的
case-local 临时库预置一条 active Memory；这只是确定性 fixture setup，不计作 live
WRITE 证据，也不绕过 04A 的 confirmation 验收。随后关闭 setup connection，构建
production runtime，在全新 session 中同时询问只读 Profile 和该 Memory。

验收：

- production runtime 从 SQLite index + immutable file 读取 hash-verified active Memory；
- 回答包含 Profile 与 Memory 两个唯一 marker；
- recall slice 零 ToolCall、零 confirmation、零新增 Memory 版本；
- recall 失败只归因于 Context retrieval / runtime / model recall，不与 WRITE selection
  或 confirmation 混为一个失败。

以下能力不属于本 case，继续由 `tests/test_memory_compiled_e2e.py` 和
`tests/test_memory_real_llm_smoke.py` 分条验证：duplicate、conflict/update、
archive/history、corrupt-file degradation。

### 8.5 LIVE-05：真实 fail-closed 与 safe degradation

覆盖模糊计划输入、Travel unavailable provider、用户拒绝或过期的 Memory WRITE confirmation。

验收：

- 模糊输入在安全边界停止，不创建 Plan/ToolCall；
- unavailable Travel observation 使用稳定安全错误，模型不得伪造候选；
- denied/expired confirmation 零写；
- run record、events 和 RuntimeResult 状态一致；
- exception、arguments、Memory content 不泄漏到 semantic events。

### 8.6 分层验证顺序

1. confirmation adapter/CLI focused tests；
2. bootstrap/runtime/Executor affected offline tests；
3. 现有 Research/Planning/Context/Memory compiled E2E；
4. 统一离线 `unittest discover`；
5. 现有 Memory real-LLM smoke 按独立能力切片执行，不拼成长链；
6. 5 个 live user E2E 单条执行，其中 LIVE-04A / 04B 必须作为两条独立命令；
7. live suite 串行整组执行；
8. 在 provider/成本允许时做 3 次连续稳定性 gate。

LIVE-04 只允许通过带 wall-clock timeout 的 slice runner 执行：

```powershell
uv run python tests/run_live_user_slice.py 04a --timeout-seconds 300
uv run python tests/run_live_user_slice.py 04b --timeout-seconds 300
```

runner 超时返回 exit code `124`；被终止进程不会执行 `TemporaryDirectory` cleanup，
因此失败现场会留在系统临时目录供只读诊断。完成诊断后再人工清理，不在 runner
中做递归删除。

## 9. 文档更新

计划创建时：

- 将本计划加入 `plans/modules/README.md`；
- 在 `docs/AGENT_LEARNING_LINKS.md` 增加 live E2E 的官方 evaluation best-practices 链接；已有 function calling、MCP、Context/Memory 链接继续复用。

测试完成后：

- 新增 `docs/E2E_LIVE_USER_TEST_REPORT_20260716.md`；
- `docs/PROGRESS_LOG.md` 只记录已运行、已通过、已失败或已阻断的事实；
- 若 production Tool confirmation 改变当前用户入口边界，更新 `docs/ARCHITECTURE.md`；
- 在 `docs/RUNTIME_CONCEPTS.md` 解释 plan confirmation 与 action confirmation 的区别，以及 live E2E 为什么断言 durable state 而不是自然语言文案；
- 只有 gate 真正关闭后才在 README/总路线图写入 live E2E 已完成。

本轮新增官方学习依据：OpenAI Evaluation best practices。它强调 task-specific eval、真实分布、自动化结构断言、完整日志和持续评测；本计划采用本地状态/Tool/evidence 作为主要自动 grader，不引入被官方标记为将退役的 hosted Evals platform。

## 10. 实施步骤

1. 固化本计划、模块索引和学习链接。
2. 冻结 confirmation UX：同步、当前 run、逐 ToolCall、yes/no、默认拒绝。
3. 给 production bootstrap 注入可选 `ActionConfirmationProvider`，默认行为不变。
4. 实现 CLI confirmation adapter，并补 approve/reject/EOF/exception/identity focused tests。
5. 补 bootstrap contract，证明同一 provider 同时服务 Direct 和 confirmed PlanStep WRITE。
6. 建立 live E2E shared harness：临时 config、唯一 IDs、日志读取、SQLite/file assertions、外部失败分类。
7. 实现 LIVE-01 Research Direct。
8. 实现 LIVE-02 Travel WRITE + cross-domain Plan。
9. 实现 LIVE-03 Context summary + restart。
10. 实现 LIVE-04A 单次 save 与 LIVE-04B 独立 restart recall 两个短切片。
11. 实现 LIVE-05 fail-closed / degradation。
12. 运行 focused 和受影响离线回归，修复本地行为。
13. 逐条运行真实 LLM/provider case，保留每条证据和耗时。
14. 串行运行全 live suite；条件允许时连续 3 轮。
15. 编写 E2E 报告，更新 Progress/Architecture/Concepts/README/路线图的真实状态。

## 11. 最终 gate

`go` 必须同时满足：

- production/CLI WRITE confirmation 可由真实用户明确 approve/reject，默认 fail-closed；
- 5 个 case 均实际调用真实模型；
- LIVE-01/02 的 Research 查询实际经过真实 Hugging Face MCP；
- 所有 WRITE 都有精确 confirmation、Gateway、Guardrail 和 evidence；
- Context/Memory/Plan/Domain fact/authorization 边界无回归；
- focused、compiled E2E 和统一离线回归通过；
- live 报告可以从 events、LLM logs、SQLite 和 files 复核；
- 没有把外部 provider failure 伪装成产品 PASS。

若任一 WRITE 只能靠测试绕过 production confirmation、任一 live case 使用 fake model decision、或测试写入真实用户数据，则结论必须为 `no-go`。
