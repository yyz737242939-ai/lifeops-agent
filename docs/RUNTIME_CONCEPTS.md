# Runtime 概念

本文档是 Runtime 的详细学习和面试手册。

本文档只记录已经随项目推进学到、实现过或正在用于当前阶段解释的概念。外部链接统一维护在 `docs/AGENT_LEARNING_LINKS.md`，本文档不直接维护 URL。

每个概念使用以下模板：

```markdown
## <概念 / 模块>

### 解决什么问题

### 核心概念

### 当前 runtime 实现

### 输入 / 输出 / 不负责什么

### 常见失败模式

### 如何测试和观察

### 面试解释

### 相关项目文件
```

## 必需章节

- Agent Loop
- Intent Layer
- Policy / Permission Layer
- Tool System
- Capability
- Write Safety
- LangGraph Orchestrator
- LangChain Adapter
- Planner
- Executor
- Task State
- Task vs Plan
- Context Engine
- Memory
- Recovery
- MCP
- Calendar External Tool
- DAG Scheduler
- Eval Harness
- Inspector / Debugger
- Observability
- SQLite Local Persistence

## 当前 runtime 项目参考

- `plans/RUNTIME_REFACTOR_PLAN.md`
- `docs/ARCHITECTURE.md`
- `docs/MIGRATION_INDEX.md`
- `docs/AGENT_LEARNING_LINKS.md`

## Runtime Core

### 解决什么问题

Runtime Core 固定单轮请求的入口、生命周期和返回边界。它回答“用户这一轮输入如何变成一个可追踪的 run，以及当前 run 为什么返回这个结果”。

### 核心概念

- `session_id`：短生命周期会话容器，可以包含多个 turn。
- `turn_id`：用户一轮输入。
- `run_id`：runtime 处理某个 turn 的一次执行尝试。
- `RuntimeRequest`：当前 run 的结构化输入。
- `RuntimeResult`：当前 run 的可展示输出，不是业务事实来源。

### 当前 runtime 实现

当前实现位于：

- `main.py`
- `app/runtime/models.py`
- `app/runtime/service.py`
- `app/runtime/bootstrap.py`
- `app/runtime/run_store.py`

`RuntimeService.handle(...)` 当前执行：

```text
RuntimeRequest
-> IntentService
-> PolicyService
-> RuntimeResult
```

传入 SQLite connection 时，它可以写入 `run_records`。传入 event log 或配置 `log_root` 时，它会把结构化 runtime event 写入 `events.jsonl`。当前 orchestration 和 tool execution 仍是 stub。

### 输入 / 输出 / 不负责什么

输入是已经构造好的 `RuntimeRequest`。

输出是 `RuntimeResult`，其中可以包含 intent / policy 摘要。

Runtime Core 不负责自然语言深度理解，不授权写入，不执行业务工具，不把 assistant final answer 升级为事实。

### 常见失败模式

- Intent classification 抛错。
- Policy evaluation 抛错。
- run record 或 trace event 写入失败。
- 把 `RuntimeResult.message` 误认为业务写入成功证据。

### 如何测试和观察

当前测试包括：

- `tests/test_runtime_service.py`

可以通过 `events.jsonl` 观察一次 run 的开始、intent、policy、stub orchestration 和完成事件。需要关系查询时，`run_records` 仍可记录 run 状态。

### 面试解释

可以这样讲：本项目先把 agent runtime 的外壳做清楚。Runtime Core 不直接“聪明地回答问题”，而是负责把一轮输入变成 request、run、result 和 evidence。这样后续 LangGraph、Planner、Executor 都只是挂进明确生命周期里的模块，不会吞掉授权和事实来源边界。

### 相关项目文件

- 本项目：`app/runtime/`
- 本项目：`plans/modules/RUNTIME_CORE_PLAN.md`

## Intent Layer

### 解决什么问题

Intent Layer 判断用户大概想做什么，避免因为单个关键词误触发 planning 或 write。

### 核心概念

- `IntentType`：当前支持 `chat`、`read`、`write_request`、`plan_request`、`clarification_needed`、`unsupported`。
- `ClassifierResult`：某个 classifier 的单独判断信号。
- `IntentDecision`：`IntentService` 合成后的最终 intent 判断。

### 当前 runtime 实现

当前实现位于：

- `app/intent/models.py`
- `app/intent/classifiers.py`
- `app/intent/service.py`

`RuleBasedIntentClassifier` 是当前真实判断路径。它使用动作、对象和语气组合做保守判断。`LlmIntentClassifier` 当前是空实现，只返回 `not_available`，不调用真实模型。

### 输入 / 输出 / 不负责什么

输入是 `RuntimeRequest`。

输出是 `IntentDecision`。

Intent 不授权写入，不调用工具，不写 SQLite，不把 LLM classifier 结果升级成权限事实。

### 常见失败模式

- 规则过窄导致漏判。
- 裸关键词导致误触发。
- 用户一句话包含多个意图。
- LLM classifier 未来返回非法结构。

### 如何测试和观察

当前测试包括：

- `tests/test_intent_service.py`

重点样例包括：

- `我计划明天跑步` 不触发 `plan_request`。
- `帮我规划明天的安排` 返回 `plan_request`。
- `把明天跑步加入任务` 返回 `write_request` 和 write candidate。
- `计划一下` 返回 `clarification_needed`。

### 面试解释

可以这样讲：Intent 是语义层，只回答“用户可能想做什么”。它可以使用规则、LLM structured output 或相似样例检索，但这些都只是信号。是否允许写入必须交给 Policy。

### 相关项目文件

- 本项目：`app/intent/`
- 本项目：`plans/modules/INTENT_POLICY_PLAN.md`

## Policy / Permission Layer

### 解决什么问题

Policy / Permission Layer 判断系统现在被允许做什么。它把写入授权从 Planner、assistant 文本、LLM 输出和 checkpoint 中剥离出来，成为独立事实源。

### 核心概念

- `PolicyAction`：`allow`、`deny`、`requires_confirmation`。
- `PermissionScope`：当前候选 scope，例如 `task.write_candidate`、`memory.write_candidate`、`wellbeing.write_candidate`。
- `PolicyDecision`：当前请求的授权判断。

### 当前 runtime 实现

当前实现位于：

- `app/policy/models.py`
- `app/policy/service.py`

`PolicyService.evaluate(request, intent)` 只读取当前 `RuntimeRequest` 和 `IntentDecision`。明确写入请求可以返回有限候选 scope；疑似写入但对象不明确时返回 `requires_confirmation`；未知 intent 默认不 allow。

### 输入 / 输出 / 不负责什么

输入是 `RuntimeRequest` 和 `IntentDecision`。

输出是 `PolicyDecision`。

Policy 不调用工具，不调用 Planner，不写业务 repository，也不读取 LangGraph checkpoint 作为授权来源。

### 常见失败模式

- 把 LLM classifier 的 write signal 当成授权。
- 把 Planner 输出当成授权。
- 把 assistant final answer 的“已保存”当成事实。
- 写入对象不明确却默认 allow。

### 如何测试和观察

当前测试包括：

- `tests/test_policy_service.py`
- `tests/test_runtime_service.py`

测试验证非写入 intent 不产生 write authorization，LLM classifier / metadata / planner 模拟字段不能绕过 Policy，`requires_confirmation` 不声称已经写入。

### 面试解释

可以这样讲：Intent 判断“用户可能想干什么”，Policy 判断“系统现在被允许干什么”。即使未来 LLM classifier 很强，它也只能提供 intent signal。真正的写入授权来自 Policy，并且必须绑定当前用户输入。

### 相关项目文件

- 本项目：`app/policy/`
- 本项目：`plans/modules/INTENT_POLICY_PLAN.md`

## Write Safety

### 解决什么问题

Write Safety 防止系统在没有明确授权时修改用户数据，也防止 assistant 文本、Planner 输出或 checkpoint 被误读成写入事实。

### 核心概念

- 当前用户输入中的明确授权。
- Policy 返回的有限 scope。
- 成功 WRITE tool result。
- 可复盘的 runtime evidence。

### 当前 runtime 实现

阶段 3 当前只建立授权模型和主链路。`PolicyDecision` 可以允许候选写 scope，但 Runtime Core 仍返回 `runtime.orchestration.stubbed`，不会执行真实 tool 或业务写入。

### 输入 / 输出 / 不负责什么

输入是当前 request、intent decision 和 policy decision。

输出是“是否允许继续”的授权判断。

Write Safety 不等于自然语言理解，不等于完整权限平台，也不等于多轮 confirmation 状态机。

### 常见失败模式

- 看到 `write_request` 就直接写入。
- `plan_request` 生成计划后自动创建任务。
- Recovery Context 自动 replay 写操作。
- LangGraph checkpoint 被当成授权状态。

### 如何测试和观察

当前测试通过 `tests/test_policy_service.py` 和 `tests/test_runtime_service.py` 验证 policy 边界。后续 Eval Harness 会把误触发样例沉淀成长期回归 case。

### 面试解释

可以这样讲：本项目把“理解用户想做什么”和“允许系统做什么”拆开。这样即使分类器或 Planner 猜错了，也不会自动变成写入权限。

### 相关项目文件

- 本项目：`docs/ARCHITECTURE.md`
- 本项目：`app/policy/`

## Observability

### 解决什么问题

Observability 让 runtime 行为可以被解释和复盘。它回答“这次 run 经过了哪些阶段、哪里失败、LLM 原始请求和响应是什么”。

### 核心概念

- event log：少量必要字段，便于机器读取、Inspector 展示和 Eval 断言。
- LLM interaction log：保存 request / response JSON，便于人工排查。
- normal application log：普通程序日志，便于测试和 debug。
- Runtime evidence：能解释运行路径和结果的记录，但不自动等于业务事实。

### 当前 runtime 实现

当前实现位于：

- `app/observability/events.py`
- `app/observability/file_logs.py`
- `app/observability/logger.py`

`LogTraceEvent` 写入 `events.jsonl`。`LogLlmInteraction` 写入 `llm.jsonl`。Python 标准 `logging` 写入 `application.log`。三类日志默认在同一个 session log directory 下，但不混成一个文件。

### 输入 / 输出 / 不负责什么

输入是 `run_id`、`seq`、事件类型、payload 或 LLM request-response。

输出是 append-only 文件日志，可按 `session_id` / `run_id` / `seq` 读取和复盘。

Observability 不负责授权写入，不负责改变业务状态，也不把 assistant 文本或 LLM response 自动升级成事实。

### 常见失败模式

- payload 不能 JSON 序列化。
- session log directory 不可写。
- application logger 重复添加 handler，导致重复日志。
- 原始 LLM log 过大或包含敏感字段，后续接入真实外部凭证前需要脱敏策略。

### 如何测试和观察

当前测试包括：

- `tests/test_observability_file_logs.py`

它验证 metadata、`events.jsonl`、`llm.jsonl`、`application.log` 和 logging 幂等性。

### 面试解释

可以这样讲：本项目把 observability 分成三条文件日志。event log 给系统和 Inspector 判断 runtime 路径，LLM log 给人回看原始模型交互，application log 给工程 debug。日志是观测材料，不绕过 policy，也不是业务写入授权来源；SQLite 主要留给业务事实和适合关系查询的数据。

### 相关项目文件

- 本项目：`app/observability/`
- 本项目：`plans/modules/OBSERVABILITY_LOGGING_PLAN.md`

## SQLite Local Persistence

### 解决什么问题

SQLite Local Persistence 为本地 runtime 提供轻量、可测试、可查询的业务事实和关系数据存储。

### 核心概念

- schema migration：管理数据库表结构版本，不迁移旧业务数据。
- repository / store：负责读写特定表。
- unit of work：管理一组写入的 commit / rollback。
- test database：测试使用 `:memory:` 或临时文件数据库，不触碰真实用户数据。

### 当前 runtime 实现

当前实现位于：

- `config/default.json`
- `app/common/config.py`
- `app/storage/sqlite.py`
- `app/storage/schema.py`
- `app/storage/migrations.py`
- `app/storage/unit_of_work.py`

默认数据库路径由 `config/default.json` 的 `database.path` 声明，当前是 `data/lifeops.sqlite3`。

### 输入 / 输出 / 不负责什么

输入是配置中的数据库路径或测试显式传入的 SQLite path。

输出是配置好的 SQLite connection、已应用的 schema version 和可被 store 使用的基础表。

Storage 不负责 intent、policy、planning、tool execution 或业务语义。

### 常见失败模式

- 配置缺少 `database.path`。
- 数据库路径不可写。
- 数据库 schema version 比当前代码更新。
- migration 中途失败。
- 在已有事务里再次开启 unit of work。

### 如何测试和观察

当前测试包括：

- `tests/test_common.py`
- `tests/test_storage_sqlite.py`
- `tests/test_storage_migrations.py`
- `tests/test_storage_unit_of_work.py`
- `tests/test_helpers.py`

测试数据库 helper 位于 `tests/helpers.py`。

### 面试解释

可以这样讲：本项目不用 ORM，先用 Python 标准库 `sqlite3` 建一个透明的本地持久层。启动时先连接数据库，再跑 schema migration，之后 repository / store 假设表结构已经准备好。写入通过 unit of work 统一 commit 或 rollback，避免半截运行证据落库。

### 相关项目文件

- SQLite / Local Persistence 相关链接维护在 `docs/AGENT_LEARNING_LINKS.md`。
- 本项目：`app/storage/`
- 本项目：`plans/modules/STORAGE_SQLITE_PLAN.md`
