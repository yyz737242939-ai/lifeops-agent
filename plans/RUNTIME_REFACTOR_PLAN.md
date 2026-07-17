# Runtime 重构总计划

本文档是 LifeOps Agent Runtime 的总蓝图和施工总纲。它不替每个模块写完整功能设计；后续真正施工到 Memory、Policy、Eval、DAG 等模块时，应为该模块创建单独的模块计划。本文档负责规定：

- 当前 runtime 的总体目标、阶段边界和完成标准。
- 新旧代码与新旧文档如何隔离。
- 当前 runtime 的总项目代码框架。
- 各模块的职责边界、依赖方向和扩展点。
- 后续模块计划应该如何设计、写在哪里、至少回答哪些问题。
- 学习与面试材料如何沉淀到新的 Markdown 文档体系中。

## 1. 当前总目标

当前 runtime 的主线是把当前从 V0 / demo 逐步长出来的 Agent Runtime，重构成一个小而完整、边界清晰、可测试、可解释、适合学习与面试展示的工程化 runtime。

当前进度：

- 阶段 0 / 阶段 1：归档边界和文档基础已完成。
- 阶段 2：Storage / SQLite 基础设施已完成，详见 `plans/modules/STORAGE_SQLITE_PLAN.md`。
- 阶段 3：Runtime Core / Intent / Policy 初版已完成，详见 `plans/modules/RUNTIME_CORE_PLAN.md` 和 `plans/modules/INTENT_POLICY_PLAN.md`。
- 阶段 3.5：Observability 文件日志校正已完成，详见 `plans/modules/OBSERVABILITY_LOGGING_PLAN.md`。
- 阶段 4：LangGraph Orchestration 骨架已完成，详见 `plans/modules/LANGGRAPH_ORCHESTRATION_PLAN.md`。
- 当前阶段：阶段 5 功能实现与稳定化均已完成；`STAGE5_STABILIZATION_PLAN.md` 已关闭全部 blocking findings，并在 `240/240` 统一离线回归后给出 Stage 6 `go`。
- 当前阶段：阶段 7 Plan-and-Execute Planner 步骤 1-16 已全部完成；Planner 聚焦回归 `79/79`、统一离线回归 `379/379` 通过，Direct/Plan/NeedUser 与 Research happy-path 真实模型验证已有证据。
- 当前阶段：Stage 9A Context Engine 与 Stage 9B Long-term Memory 均已完成并取得独立 `go`；整个 Stage 9 已关闭，下一阶段为面试实践导向的 Stage 10 Execution Feedback / Recovery。

核心执行链路：

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

当前 runtime 的关键原则：

- 先判断 intent，再决定是否 planning，避免关键词误触发。
- Policy 是权限事实源，Planner、LLM 文本、Recovery Context、LangGraph checkpoint 都不是授权来源。
- LangGraph 做编排层，自研 runtime 保留 policy、tool safety、context、memory、executor、recovery、facts source。
- 施工顺序先搭稳定的外层控制框架：Tool 完成后依次实现 ReAct Executor、Plan-and-Execute Planner，再把 Context / Memory、Execution Feedback / Recovery 通过预留窄接口接入；不要求先完成局部状态模块再反推整体编排。
- PlanRun / PlanStep 是跨 Domain 的通用执行策略，可为暂停、恢复和审计持久化，但不是业务事实；长期事实只来自经授权且成功执行的 Domain WRITE。
- Inspector / Eval 是一等公民，不是最后补的日志查看工具。
- 新旧代码、新旧文档必须明确分离。

## 2. 学习路线覆盖

当前 runtime 要覆盖三个学习阶段，但方式不同：

### 阶段 A： 初级 Agent Engineer 能力整理成清晰架构

覆盖：

- Agent Loop。
- Tool System。
- Tool authorization resolution。
- Write Safety。
- Skill / Skill References。
- Context Engine。
- Memory。

当前 runtime 要求：

- 每个能力都有明确模块归属。
- 每个能力都有最小测试。
- 每个能力都能在 `docs/RUNTIME_CONCEPTS.md` 中讲清楚。
- V0 实现不直接照搬，必须经过 V0 -> 当前升级评审。

### 阶段 B： 中级 Agent Engineer 能力收敛和工程化

覆盖：

- MCP。
- Safety State。
- Plan / Execution State。
- Recovery。
- Plan and Execute。
- Planner / Executor / Orchestrator。
- LangChain / LangGraph 。

当前 runtime 要求：

- LangGraph 接入真实主流程，但不吞掉自研 runtime。
- MCP 至少支持 Research 公开论文搜索：LifeOps 通过本地 stdio MCP Server 调用 Hugging Face paper API；Calendar MCP 不属于当前 V1。
- Recovery 先做解释型恢复，不做自动 replay。
- Task / Plan / Recovery 三者边界必须有测试证明。

### 阶段 C： 面试强化层

覆盖：

- Policy / Permission Layer v0。
- Executor 结构化反馈 v0。
- LangGraph / LangChain 使用与概念映射。
- DAG 概念与最小串行 DAG Scheduler。
- Eval Harness v0。
- Inspector / Debugger v0。

当前 runtime 要求：

- 这些能力不只是文档概念，初版都要有可运行最小版本。
- Eval Harness 和 Inspector 必须能解释 runtime 行为，而不是只判断 final answer。
- DAG Scheduler 独立实现，不接管主 Agent 主流程，但有测试、trace、demo。

## 3. 总范围

### 3.1 初版必须完成

- 新代码根目录 `app/`。
- 新入口 `main.py`。
- 新文档目录 `docs/`。
- 新计划目录 `plans/`。
- SQLite 本地持久层作为当前 runtime 的业务事实和关系数据存储；event / LLM / normal 程序日志走文件；JSON 只保留给 fixture、config 和 sample 数据。
- Intent Layer。
- Policy / Permission Layer v0。
- LangGraph Orchestrator。
- Runtime context assembly 初版。
- Memory 初版。
- Research / Personal Knowledge + Travel 内部 domain。
- Research Hugging Face paper MCP read integration。
- Planner / Executor / ExecutionFeedback。
- Trace / Inspector。
- Eval Harness v0。
- 独立串行 DAG Scheduler。
- V0 -> 当前迁移索引。
- RUNTIME_CONCEPTS 学习手册骨架与核心章节。

### 3.2 初版不做

- 产品 UI 迁移。
- Calendar 写入。
- 完整 OAuth 体验打磨。
- 完整旧 Context Engine 全量迁移。
- 高级 Memory Retrieval。
- Multi-Agent。
- 后台调度。
- 并行 DAG。
- 自动 replay / rollback / compensate。

### 3.3 后续版本候选

- 完整 Context compression / ref / index / compactor。
- 更完整 Recovery + LangGraph checkpoint 对照。
- Calendar OAuth 只读完整配置流。
- 产品 UI 接入 当前 runtime。
- 高级 Memory Retrieval。
- LangSmith / OpenTelemetry 对照。
- Multi-Agent spike。

## 4. 新旧隔离策略

### 4.1 代码隔离

新代码不放在旧 runtime 下面，统一放在：

```text
app/
```

旧 V0 代码、数据、日志、测试、MCP demo server、输出和旧计划统一归档：

```text
legacy_v0/
  app/
  data/
  logs/
  mcp_servers/
  outputs/
  plans/
  tests/
  docs/
  entrypoints/
```

新入口：

```text
main.py
```

旧根入口已归档：

```text
legacy_v0/entrypoints/main_legacy.py
legacy_v0/entrypoints/product_ui_legacy.py
legacy_v0/entrypoints/log_viewer_legacy.py
```

目标：

- 新旧 runtime 一眼可分。
- 当前 runtime 可以逐步复用旧代码，但不能隐式依赖旧 `Agent`。
- 后续迁移可以通过 `docs/MIGRATION_INDEX.md` 追踪。

### 4.2 文档隔离

当前文档不混在旧文档体系里：

```text
docs/
plans/
```

旧文档归档到：

```text
legacy_v0/docs/
```

旧 `legacy_v0/docs/PROJECT_CONTEXT_legacy.md`、`legacy_v0/docs/LEARNING_PROGRESS_legacy.md`、`legacy_v0/plans/*.md` 不再作为默认上下文。它们只在迁移旧模块、追溯历史设计、解释 V0 行为时读取。

### 4.3 数据隔离

当前运行数据建议放在：

```text
data/
  lifeops.sqlite3
  fixtures/
  exports/

logs/
  sessions/
    session_<timestamp>/
      metadata.json
      events.jsonl
      llm.jsonl
      application.log
```

规则：

- `data/*.sqlite3` 不入库。
- fixture / schema / sample 可以入库。
- OAuth token、calendar cache、eval run output 不入库。

## 5. 当前总代码框架

当前总目录建议如下。后续模块计划必须遵守这个分层，除非模块计划明确提出并解释变更原因。

```text
app/
  __init__.py

  runtime/
    request.py
    result.py
    session.py
    lifecycle.py

  intent/
    classifier.py
    types.py
    rules.py

  policy/
    engine.py
    types.py
    rules.py
    confirmation.py

  orchestration/
    graph.py
    state.py
    routes.py
    nodes/
      classify_intent.py
      decide_policy.py
      assemble_context.py
      plan.py
      execute.py
      inspect_debug.py
      finalize.py

  planning/
    planner.py
    types.py
    prompts.py
    parser.py

  execution/
    executor.py
    feedback.py
    loop.py
    validation.py

  tools/
    definitions.py
    registry.py
    gateway.py
    guardrails.py
    results.py
    authorization.py
    adapters/
      langchain.py

  domains/
    research/
      models.py
      repository.py
      service.py
      tools.py
      context.py
    travel/
      models.py
      repository.py
      service.py
      tools.py
      ports.py

  integrations/
    huggingface/
      client.py
      parser.py
      adapter.py
    mcp/
      models.py
      errors.py
      client.py
    research_mcp/
      server.py
      provider.py
      adapter.py
    travel_fixture/
      calendar.py
      weather.py
      transport.py
      lodging.py
      places.py

  context/
    assembler.py
    types.py
    sources.py
    report.py

  memory/
    models.py
    repository.py
    retriever.py
    tools.py
    profile.py

  recovery/
    models.py
    repository.py
    context.py
    service.py

  storage/
    sqlite.py
    schema.py
    migrations.py
    repositories.py
    unit_of_work.py

  observability/
    events.py
    trace.py
    event_log.py
    llm_log.py
    logger.py

  inspector/
    reader.py
    formatter.py
    cli.py

  evals/
    case.py
    runner.py
    assertions.py
    report.py

  dag/
    models.py
    scheduler.py
    executor.py
    trace.py

  common/
    ids.py
    time.py
    errors.py
    result.py
    serialization.py

main.py
```

### 5.1 分层规则

- 所有业务 Domain 遵守 `plans/DOMAIN_CONTRACT_STANDARD.md`；统一 Tool、Port、Planning/Context/Memory contracts 和关闭测试，业务字段仍由各 Domain 自己拥有。
- `domains/*` 不直接读写 SQLite connection，只通过 repository / service。
- `domains/*` 不依赖具体 LangChain、MCP 或 HTTP provider 类型；外部能力通过稳定 Port 和 adapter 接入。
- Skill 只提供 prompt contribution、reference/source 声明和功能工作流说明，不执行工具或参与工具授权。
- 所有工具通道必须经过同一个 Tool Gateway 和 pre/post Guardrails。
- `policy` 不调用工具，不写业务数据。
- `planning` 不调用工具，不授权 WRITE。
- `execution` 可以调用 tools，但必须使用 selected Skill candidates、PolicyDecision 和最终 `AllowedToolSet`。
- Planner / Executor 面向 Tool contract，不按 Domain 建立独立执行循环；Planner 与 Tool 的匹配模型留到 Planner 模块施工时设计，同一个 PlanRun 可以包含多个 Domain 的步骤。
- `orchestration` 只做 graph wiring 和 route，不放业务逻辑。
- `inspector` 只读 event log、LLM log、application log 和必要业务事实，不修改状态。
- `evals` 使用 fixture 和测试数据库，不复用真实用户数据。
- `common` / `storage` / `observability` 是基础设施层，不依赖业务 domain。

### 5.2 模块依赖方向

允许的依赖方向：

```text
main
-> runtime
-> orchestration
-> intent / policy / context / planning / execution / inspector
-> tools / domains / memory / recovery / integrations
-> storage / observability / common
```

禁止：

- domain 反向依赖 orchestration。
- storage 反向依赖 domain service。
- policy 调 executor。
- planner 直接调 tool executor。
- inspector 改业务状态。
- eval 修改真实 data。

## 6. 数据与日志存放策略

当前 runtime 使用“数据按用途落位”的策略，而不是把所有信息都写入 SQLite。

SQLite 主要存放：

- 业务事实。
- 适合关系查询的数据。
- 需要 transaction / repository / migration 管理的数据。

日志主要存放到文件：

- `events.jsonl`：结构化 runtime event，用于学习、Inspector、Eval 和复盘 runtime path。
- `llm.jsonl`：原始 LLM request / response，用于回看对话交互具体内容。
- `application.log`：普通程序日志，用于测试、debug 和类似 Java application log 的工程排查。

JSON 不再承担业务长期事实源职责，只在需要 fixture、config、sample 或外部 mock 数据时使用。

原因：

- Python 标准库支持，不增加重依赖。
- 减少旧版大量 JSON load/save/version/atomic write 辅助代码。
- 避免把学习型 event、原始 LLM 对话和 normal debug log 混进业务数据库。
- SQLite 保持为业务事实和关系数据服务；日志文件保持 append-only、可读、易排查。
- 更贴近真实工程，但仍保持本地轻量。

SQLite 存储：

- research_topics / research_sources / research_notes / research_briefs。
- trips / travel_constraints / travel_itineraries / travel_decisions。
- memory_index（Stage 9B 计划新增；只保存索引和 lifecycle metadata，不保存 Memory 全文）。
- tool_calls。
- eval_runs。
- eval_results。

文件日志：

- event JSONL。
- LLM JSONL。
- normal application log。

继续使用 Markdown / JSON / fixture 文件的内容：

- 每 session 的 conversation turns.jsonl 与 summaries.jsonl（Stage 9A 计划）。
- `profile.md` 和不可变 Memory version 文件（Stage 9B 计划）。
- skill / source manifest。
- eval fixture。
- calendar fixture data。
- research / travel fixture data。
- config examples。

后续必须单独创建 `plans/modules/STORAGE_SQLITE_PLAN.md`，设计：

- schema。
- migration 方式。
- repository 接口。
- test database 策略。
- reset / seed / fixture 策略。
- 隐私和 gitignore 策略。

## 7. V0 -> 当前升级矩阵

本总计划只定义升级方向。每个模块正式施工前，必须在对应模块计划中补充细节。

| 模块 | V0 状态 | 当前 runtime 轻量升级方向 | 模块计划 |
|---|---|---|---|
| Agent Loop | 旧 `Agent` 聚合过多职责 | 拆成 runtime / orchestration / execution | `plans/modules/RUNTIME_CORE_PLAN.md` |
| Skill System | 已有 skill routing / reference loader 经验，当前重构计划缺少独立位置 | 兼容 Agent Skills / Deep Agents 文件约定；LifeOps 保留 routing / prompt contribution / progressive references，Skill 不参与工具授权 | `plans/modules/SKILL_SYSTEM_PLAN.md` |
| Tool System | registry 和 business tool 偏大 | LifeOps 原生 definition / registry / Policy authorization / Guardrail / gateway / result；LangChain 只做可选 adapter | `plans/modules/TOOL_SYSTEM_PLAN.md` |
| Policy / Safety | write policy、interaction policy 分散 | 统一 PolicyDecision 和 confirmation model | `plans/modules/INTENT_POLICY_PLAN.md` |
| Context / Memory | V0 有 context budget/summary 与 profile/authorized memory 经验，但聚合和存储偏复杂 | Stage 9A 用 session JSONL + rolling summary 组装一次 bounded conversation context；Stage 9B 用只读 profile + immutable Memory files + SQLite index 接入冻结接口 | `plans/modules/CONTEXT_MEMORY_PLAN.md` |
| Research / Personal Knowledge | V0 Hugging Face News Skill + 临时 source/helper loop | SQLite knowledge facts + provenance + Hugging Face 外部只读 briefing + future Context/Memory ports | `plans/modules/RESEARCH_KNOWLEDGE_DOMAIN_PLAN.md` |
| Travel | 无完整 V0 domain | SQLite Trip / Itinerary facts + fixture-backed external ports + planning-only confirmation boundary | `plans/modules/TRAVEL_DOMAIN_PLAN.md` |
| Planner | V0 transient plan | 保留跨 Domain PlanRun / PlanStep；step 如何匹配候选 tools 留到 Planner 模块设计，Planner 不授权、不执行、不自动写 Domain facts | `plans/modules/PLANNER_PLAN.md` |
| Executor | 包装旧 agent loop | 单步执行 + 结构化反馈 + tool evidence | `plans/modules/EXECUTOR_PLAN.md` |
| Observability Logging | V0 已有三通道文件日志经验，当前重构阶段误放进 SQLite | event JSONL / LLM JSONL / application.log 三通道文件日志 | `plans/modules/OBSERVABILITY_LOGGING_PLAN.md` |
| Recovery | run/action JSON 摘要 | 基于 event logs 和必要业务状态生成解释型 recovery context，不自动 replay | `plans/modules/RECOVERY_PLAN.md` |
| LangGraph | 尚未正式接入 | StateGraph 主编排，自研节点 | `plans/modules/LANGGRAPH_ORCHESTRATION_PLAN.md` |
| Research MCP | 旧 mock package MCP | 官方 SDK stdio client/server + Hugging Face paper search + LifeOps Research Port/Adapter | `plans/modules/RESEARCH_MCP_PLAN.md` |
| DAG | 尚未实现 | 独立串行 DAG Scheduler | `plans/modules/DAG_SCHEDULER_PLAN.md` |
| Eval | 零散 tests | eval case / runner / assertions / reports | `plans/modules/EVAL_HARNESS_PLAN.md` |
| Inspector | log viewer / context inspector 分散 | trace reader + runtime report CLI | `plans/modules/INSPECTOR_PLAN.md` |

## 8. 后续模块计划写作规约

每个模块开始施工前，先创建对应的 `plans/modules/*_PLAN.md`。模块计划不需要重复本总计划，但必须回答以下问题。

### 8.1 模块计划必备章节

```markdown
# <模块> 模块计划

## 1. 目标
这个模块在当前 runtime 中解决什么问题。

## 2. 当前 V0 参考
旧实现在哪里，有什么可以复用，V0 的主要问题是什么。

## 3. 当前范围
初版做什么，不做什么，后续版本留什么。

## 4. Runtime 边界
输入是什么，输出是什么，不负责什么，依赖哪些模块。

## 5. 数据模型 / 存储
是否需要 SQLite 表、repository、fixtures、migration。

## 6. 对外接口
对其他模块暴露哪些类型、函数、service、tools。

## 7. 失败模式
常见失败、权限问题、恢复语义、trace 记录。

## 8. 测试和 Eval
单元测试、集成测试、eval scenario、trace 验证点。

## 9. 文档更新
需要更新 docs/PROGRESS_LOG、ARCHITECTURE、RUNTIME_CONCEPTS、AGENT_LEARNING_LINKS 的哪些部分。

## 10. 实施步骤
小步施工顺序。
```

### 8.2 模块计划必须遵守的默认规则

- 不把模块内部设计写进总计划。
- 不引入跨层依赖，除非模块计划显式说明并获得确认。
- 不为了复用 V0 代码而继承 V0 的职责混乱。
- 模块完成后必须更新 `docs/PROGRESS_LOG.md`。
- 改变当前架构边界时必须更新 `docs/ARCHITECTURE.md`，不再新增 ADR。
- 面试相关学习点必须进入 `docs/RUNTIME_CONCEPTS.md`，外部链接只进入 `docs/AGENT_LEARNING_LINKS.md`。
- 新增核心 Agent 概念时，必须先向用户确认准备沉淀的重点方向；确认后再同步更新 `docs/AGENT_LEARNING_LINKS.md`，沉淀权威官方文档、specification 或高质量官方博客链接。
- 有 runtime 行为变化时必须有测试或 eval。

## 9. 文档体系设计

当前文档目录：

```text
docs/
  PROGRESS_LOG.md
  ARCHITECTURE.md
  RUNTIME_CONCEPTS.md
  MIGRATION_INDEX.md
  agents/

legacy_v0/
  app/
  data/
  logs/
  mcp_servers/
  outputs/
  tests/
  entrypoints/
    main_legacy.py
    log_viewer_legacy.py
    product_ui_legacy.py
  docs/
    PROJECT_CONTEXT_legacy.md
    LEARNING_PROGRESS_legacy.md
  plans/

plans/
  RUNTIME_REFACTOR_PLAN.md
  *_PLAN.md
```

### 9.1 文档职责

| 文档 | 作用 |
|---|---|
| `README.md` | 项目入口、如何运行、当前状态、文档导航 |
| `docs/PROGRESS_LOG.md` | 递增推进记录：只记录已完成、已验证、已学到的项目演进事实 |
| `docs/ARCHITECTURE.md` | 当前架构快照：模块边界、依赖方向、状态生命周期；随实现推进覆盖更新 |
| `docs/RUNTIME_CONCEPTS.md` | 学习手册：每个模块的知识点、实现解释、面试讲法；不直接维护外部链接 |
| `docs/AGENT_LEARNING_LINKS.md` | 已学习或当前阶段正在学习的权威文档、specification 和官方链接索引 |
| `docs/MIGRATION_INDEX.md` | V0 文件/模块/文档到 当前 runtime 的迁移、重写、归档、延后记录 |
| `docs/agents/` | Codex 协作、triage 和 domain-doc 规则 |
| `legacy_v0/` | V0 代码、文档、数据、日志、测试、旧计划和旧入口归档，不作为默认上下文 |
| `plans/RUNTIME_REFACTOR_PLAN.md` | 本总计划 |
| `plans/modules/*_PLAN.md` | 后续每个模块的具体施工计划 |

### 9.2 默认阅读顺序

后续 AI / 人开始当前 runtime 任务时，默认读取：

```text
1. README.md
2. docs/PROGRESS_LOG.md
3. docs/ARCHITECTURE.md
4. plans/RUNTIME_REFACTOR_PLAN.md
5. 当前模块对应的 plans/modules/*_PLAN.md
6. 与任务直接相关的代码、测试、文档片段
```

只在以下情况读取 `legacy_v0/`：

- 迁移旧模块。
- 解释旧行为。
- 对比 V0 / 当前设计取舍。
- 查找历史实现证据。

### 9.3 RUNTIME_CONCEPTS.md 设计

`docs/RUNTIME_CONCEPTS.md` 要写得详细，作为学习和面试手册。每个模块使用固定模板：

```markdown
## <概念 / 模块>

### 解决什么问题

### 核心知识点

### 在 当前 runtime 中如何实现

### 输入 / 输出 / 不负责什么

### 常见失败模式

### 如何测试和观察

### 面试时怎么讲

### 相关项目文件
```

`docs/AGENT_LEARNING_LINKS.md` 负责沉淀跨模块的权威学习链接。新增链接前，先列出候选重点方向并向用户确认，避免提前收录后续模块资料。`docs/RUNTIME_CONCEPTS.md` 负责把这些概念解释成本项目自己的 runtime 语言，不直接维护 URL。两者要互相引用，但不要把大段外部资料复制进仓库。

必须覆盖：

- Agent Loop。
- Intent Layer。
- Policy / Permission Layer。
- Tool System。
- Tool authorization resolution。
- Write Safety。
- LangGraph Orchestrator。
- LangChain adapter。
- Planner。
- Executor。
- Plan / Execution State。
- PlanRun vs Domain Facts。
- Context Engine。
- Memory。
- Recovery。
- MCP。
- Calendar external tool。
- DAG Scheduler。
- Eval Harness。
- Inspector / Debugger。
- Observability。
- SQLite local persistence。

官方文档链接应在该文件中维护，不散落在各模块计划里。模块计划可以引用该文件的相关章节。

## 10. Domain 选择标准

初版内部 domain 选择：

```text
Research / Personal Knowledge
Travel
```

当前 V1 外部 integration：

```text
Hugging Face Paper MCP 只读
```

选择标准：

- 是否有 READ / WRITE。
- 是否能触发 permission / confirmation。
- 是否能进入 planning。
- 是否能不经过 planning 直接 ReAct 执行。
- 是否能扩展成 DAG。
- 是否能产生 recovery 场景。
- 是否能进入 eval。
- 是否有真实生活价值。

Research / Personal Knowledge 适合：

- 长期积累 Topic / Source / Note / Brief 和 provenance。
- Hugging Face Papers / Blog 真实外部只读来源。
- 大 Context、progressive reference、检索和 summarization 测试。
- Domain fact、临时 Context、LLM synthesis 与长期 Memory 的边界。
- fetch -> parse -> dedupe -> rank -> brief -> confirm save 的 Plan-and-Execute / DAG 场景。
- keyword paper search -> request-local observation -> confirm save -> Topic link 的 MCP 场景。
- source failure、内容变化和引用完整性的 Recovery / Eval 场景。

Travel 适合：

- 多约束、候选比较和 itinerary 的复杂 planning。
- Calendar / weather / transport / lodging / place 的 fixture-backed external Port。
- 外部 READ、业务 WRITE、confirmation、过期数据和副作用真实性。
- 并行查询、部分失败、DAG、Recovery 和长期历史 Trip Context。
- Calendar fixture 保持当前 V1；未来若接真实 HTTP/MCP provider，只替换 typed Port Adapter，不修改 Travel Domain。

Hugging Face Paper MCP 适合：

- 外部只读工具。
- stdio MCP initialize / discovery / `tools/call` 学习。
- request-local paper observation、provenance 与确认保存。
- deterministic fixture / public provider smoke 分层验证。
- MCP Tool、LifeOps Tool、Policy 与 Domain fact 的边界讨论。

## 11. Eval Harness 总设计

Eval Harness 是 面试重点之一，不能只是普通测试目录。

分三层：

```text
Unit eval
-> intent / policy / DAG / parser / repository

Scenario eval
-> 单次用户请求跑完整 graph，断言 route、policy、tool、state、trace

Regression eval
-> 固定历史 bug，例如 plan 关键词误路由
```

初版默认使用 deterministic eval，不做大规模 LLM-as-judge。

每个 eval case 至少包含：

- input。
- fixture data。
- expected intent。
- expected policy。
- expected graph path。
- expected tool calls。
- expected state changes。
- expected final answer constraints。
- expected trace evidence。

Eval 输出必须能帮助定位失败层级：

```text
intent
policy
graph
context
tool
state
executor_feedback
final_answer
```

详细设计放入：

```text
plans/modules/EVAL_HARNESS_PLAN.md
docs/RUNTIME_CONCEPTS.md#Eval-Harness
docs/RUNTIME_CONCEPTS.md
```

## 12. 施工阶段

### 阶段 0：分支与归档边界

目标：

- 保存 V0 永久对照。
- 创建 当前 runtime 分支。
- 确定新旧代码和文档隔离方式。

交付：

- checkpoint 分支 / tag。
- `legacy_v0/` 归档结构规划。
- `docs/MIGRATION_INDEX.md` 初版。

### 阶段 1：文档基础

目标：

- 先建立 当前文档体系和模块计划规约。

交付：

- `docs/PROGRESS_LOG.md`。
- `docs/ARCHITECTURE.md`。
- `docs/RUNTIME_CONCEPTS.md` 骨架。
- `docs/AGENT_LEARNING_LINKS.md` 骨架。
- `plans/RUNTIME_REFACTOR_PLAN.md`。
- 更新 `AGENTS.md` 的 默认读取顺序。

### 阶段 2：存储与基础设施

目标：

- 先建立基础设施层，避免业务代码继续混杂 json/log/helper 逻辑。

交付：

- `plans/modules/STORAGE_SQLITE_PLAN.md`。
- `app/storage/`。
- `app/common/`。
- `app/observability/`。
- SQLite schema / migration skeleton。
- test database strategy。

### 阶段 3：Runtime Core / Intent / Policy

目标：

- 先解决入口、误触发、权限事实源。

交付：

- `plans/modules/RUNTIME_CORE_PLAN.md`。
- `plans/modules/INTENT_POLICY_PLAN.md` 或拆成两个计划。
- `app/runtime/`。
- `app/intent/`。
- `app/policy/`。
- intent / policy tests。

### 阶段 3.5：Observability 文件日志校正

目标：

- 把 runtime event、LLM interaction 和 normal 程序日志从 SQLite evidence 表校正为文件日志。
- 明确 SQLite 只默认承载业务事实和适合关系查询的数据。

交付：

- `plans/modules/OBSERVABILITY_LOGGING_PLAN.md`。
- `logs/sessions/session_<timestamp>/events.jsonl`。
- `logs/sessions/session_<timestamp>/llm.jsonl`。
- `logs/sessions/session_<timestamp>/application.log`。
- event / LLM / normal log writer。
- 聚焦测试验证日志文件格式、顺序、脱敏和 debug 可用性。

### 阶段 4：LangGraph Orchestration 骨架

状态：已完成（2026-07-10）。

目标：

- 建立主编排骨架，但节点先可 stub。

交付：

- `plans/modules/LANGGRAPH_ORCHESTRATION_PLAN.md`。
- `app/orchestration/`。
- graph state。
- route nodes。
- graph path trace。
- route tests。

### 阶段 5：Skill System / Tool System 与 Domains（功能与稳定化均已完成）

目标：

- 建立 Skill System、工具系统和 Research / Personal Knowledge、Travel 两个内部 domain。
- Skill System 先明确 skill discovery、routing、prompt assembly、progressive reference loading 和多轮 skill state 的边界；Skill 只说明功能和工作流，不参与工具授权。
- Skill routing 支持一次选择多个 Skill并形成业务候选 Tool；空 Skill 绑定的通用 Tool 独立加入候选。Policy 只按 effect 决定动作权限，二者与 registry 求交得到 `AllowedToolSet`，Guardrail 再检查 confirmation 和具体调用。
- Tool System 再处理 tool definition、Policy authorization resolution、pre/post Guardrails、Tool Gateway、execution evidence 和 domain tool 的运行时边界。
- Skill 文件兼容 Agent Skills / Deep Agents 的 `SKILL.md` 与 progressive disclosure 约定；Tool 使用 LifeOps 原生安全核心和可选 LangChain adapter。
- 两个 Domain 必须为阶段 6-11 的 Executor、Planner、Context、Memory、Recovery、Feedback、Inspector、Eval 和 DAG 提供稳定 Port / read model / evidence 接口；Research 在阶段 8 通过既有 Tool / Port 边界增加 MCP Adapter，不建立专用执行循环。

交付：

- `plans/modules/SKILL_SYSTEM_PLAN.md`。
- `plans/modules/TOOL_SYSTEM_PLAN.md`。
- `plans/modules/RESEARCH_KNOWLEDGE_DOMAIN_PLAN.md`。
- `plans/modules/TRAVEL_DOMAIN_PLAN.md`。
- skill loader / router / prompt assembly / reference loader。
- tool registry / Policy authorization / Guardrails / gateway / LangChain adapter。
- Research repository / service / tools / Hugging Face briefing。
- Travel repository / service / tools / fixture-backed external Ports。

### 阶段 6：ReAct Executor

状态：已完成。两层 compiled graph、bounded action → observation loop、真实 Gateway、逐 WRITE confirmation、跨 Domain E2E、语义 events、request-local LLM interaction log 与统一离线回归均已验证；Stage 7 gate 为 `go`。

目标：

- 在已完成的 Tool Gateway 之上建立通用 ReAct Executor 外层循环。
- 支持 `reason -> ToolCall -> Observation -> reason` 的 bounded loop、明确终止条件和最大步数。
- 先定义 Context provider、Memory provider、Recovery hook 和 Feedback sink 的窄接口，使用 empty/fake 实现保持边界可测；本阶段不实现这些模块。

交付：

- `plans/modules/EXECUTOR_PLAN.md`。
- ReAct execution state / stop reason / loop limits。
- 单次 Tool Gateway 调用与 Observation 回流。
- 跨 Domain Tool 调用和逐 WRITE action confirmation。
- Executor contract tests，以及 Context / Memory / Recovery / Feedback 的 fake adapter tests。

### 阶段 7：Plan-and-Execute Planner

状态：已完成。Direct/Plan/NeedUser route、preview-first PlanRun、revision command、串行 PlanController、一次 bounded replan、PlanFinalizer、语义 observability、Research 主 E2E、最小 cross-domain E2E 与真实模型 smoke 均已验证；最终 Planner 聚焦回归 `79/79`、统一离线回归 `379/379` 通过，Stage 8 gate 为 `go`。

目标：

- 在阶段 6 ReAct Executor 之上实现跨 Domain Plan-and-Execute：简单请求直接进入 Executor，复杂、多步骤或有依赖请求由 Planner 生成计划并逐步调度同一个 Executor。

交付：

- `plans/modules/PLANNER_PLAN.md`。
- 可持久化但不作为业务事实的 PlanRun / PlanStep。
- Planner route、计划生成、逐 step 调度和 final answer handoff。
- PlanStep 到 Executor 的窄输入，以及 Executor 基于 filtered catalog 的候选 Tool 选择。
- bounded replan 的控制接口；正式 Recovery / ExecutionFeedback 在阶段 10 接入。
- Context / Memory 只通过阶段 6 预留接口提供 empty/fake 数据，阶段 9 再接真实 provider，不把尚未实现的模块写进 Planner 核心。

### 阶段 8：Research External Interfaces / Hugging Face MCP

状态：已完成。`plans/modules/RESEARCH_MCP_PLAN.md` 步骤 1-14、最终 9 Tool contract、offline regression、真实 Hugging Face provider smoke、真实 LLM happy path 与文档 gate 均已关闭；Stage 9 gate 为 `go`。

目标：

- 在不改写 Executor / Planner 控制骨架、不升级 SQLite schema 的前提下，补齐 Research 用户业务 Tool，并用官方 MCP SDK、本地短生命周期 stdio Server 和 Hugging Face paper API 实现真实论文搜索。
- 把 MCP result 转换为 request-local `ExternalObservation`；只有确认后的 `save_source` / `link_items` 才形成长期事实。
- 把模型可见 Research Tool 收敛为 9 个，合并 briefing workflow，但保留底层 fetch / parse / rank / draft 机制和独立测试。

交付：

- `plans/modules/RESEARCH_MCP_PLAN.md`。
- 通用 one-shot stdio MCP client、Hugging Face Paper MCP Server 和 Research Adapter。
- `research.search_papers`、`research.build_brief`、Topic/Link/Revision Tools 与最终 9 Tool contract。
- deterministic/offline MCP E2E 与真实 Hugging Face provider smoke。

### 阶段 9：Context / Memory

状态：Stage 9A Context Engine 与 Stage 9B Long-term Memory 已于 2026-07-16 分别完成独立 gate 并取得 `go`；整个 Stage 9 已关闭。

目标：

- Stage 9A 在不改写 Executor / Planner 控制骨架的前提下，实现不绑定 Domain 的 session conversation Context：每个 RuntimeRequest 一次 bounded assembly，Direct、Planning 与 PlanStep 共享；turns/summary 只写 session JSONL。
- Stage 9B 只实现用户编辑的只读 Profile 和用户明确确认保存的长期 Memory；全文写不可变文件，SQLite 只写 index/lifecycle。
- Context、Memory、Planner output、MCP result、conversation summary 和模型文本都不能成为 Tool 授权或 Domain 事实来源。

交付：

- `plans/modules/CONTEXT_MEMORY_PLAN.md`。
- Stage 9A：conversation JSONL repository、rolling summary、Context report/budget/assembly、empty/fake Profile/Memory provider、5 个真实 LLM happy paths和独立 go/no-go。
- Stage 9B：read-only Profile、immutable Memory files、SQLite index、retriever、save/list/search/update/archive Tools、5 个真实 LLM happy paths和独立 go/no-go。
- Stage 9A 不调用 Research/Travel Domain candidate provider；现有 provider contract 保留，但不是 session conversation assembly 的 production 输入。

### 阶段 10：Execution Feedback / Recovery

目标：

- 面向面试前的实操学习，基于 Executor / Planner 的真实停点、Observation、
  PlanRun / PlanStep 和 evidence，完成一个小而完整、可运行、可测试、可讲解的
  Execution Feedback + 解释型 Recovery 闭环。
- Execution Feedback 只把执行结果整理为结构化事实，并校验 final answer 不得把
  失败、未执行或仅建议的动作描述为已经成功。
- Recovery 只读取 durable evidence 和结构化反馈，解释上次执行到哪里、哪些已经
  成功、哪里失败、哪些没有执行，以及用户可以安全采取的下一步。

交付：

- `plans/modules/RECOVERY_PLAN.md`。
- 最小 `ExecutionFeedback` models、collector / builder 和 final answer validator。
- 基于 session events、ExecutorResult、PlanRun / PlanStep 与 Tool evidence 的只读
  `RecoveryContext`。
- 面向 Direct 与 Planning 各一条成功/部分失败/失败停点的解释型恢复路径。
- focused tests、compiled E2E 和少量真实模型 smoke，用于形成可复述的面试证据。

当前阶段明确不做：

- 自动 replay、自动继续执行、自动 retry 或新增 replan 机制；
- compensation、rollback 或把已提交的 Domain / 外部副作用恢复到旧状态；
- LangGraph checkpoint resume、time travel、跨进程 graph state 恢复；
- 后台恢复、异步任务、分布式 workflow、通用 fault-tolerance 平台；
- 从 Recovery Context、历史 Plan 或旧 confirmation 恢复 WRITE 权限。

现有 Planner 可以读取结构化失败事实用于解释，但 Stage 10 不扩展 Planner 控制流；
恢复输出只能说明事实和建议下一步，不能声称建议动作已经执行。

### 阶段 11：Inspector / Eval / DAG

目标：

- 补齐面试强化层。

交付：

- `plans/modules/INSPECTOR_PLAN.md`。
- `plans/modules/EVAL_HARNESS_PLAN.md`。
- `plans/modules/DAG_SCHEDULER_PLAN.md`。
- trace reader。
- eval runner。
- 串行 DAG scheduler。
- demo 场景。

### 阶段 12：面试收口

目标：

- 让项目可讲、可跑、可复盘。

交付：

- `docs/RUNTIME_CONCEPTS.md` 详细版。
- `docs/RUNTIME_CONCEPTS.md` 面试讲法章节。
- 架构图。
- 3-5 个 demo 脚本。
- 初版完成报告。

## 13. 初版完成标准

初版完成必须满足：

- `main.py` 可运行 CLI demo。
- `app/` 新旧边界清晰。
- SQLite 作为 Runtime facts / evidence store 可用。
- Intent / Policy 能阻止 plan 关键词误路由 和未授权写入。
- LangGraph 编排真实接入。
- Research / Personal Knowledge + Travel 可 read/write。
- Hugging Face paper search 可经 MCP 产生 request-local observation，并在确认后保存/关联到 Research Topic。
- Domain fact / PlanRun / Context / Memory 边界有测试。
- 一个 PlanRun 可交叉调用 Research 与 Travel tools，并在部分成功后从失败步骤恢复或 replan。
- Executor 返回 结构化反馈。
- Recovery 可解释上次停点，但不 replay。
- Inspector 能解释一次 run。
- Eval 能断言关键 runtime 行为。
- DAG Scheduler 独立可演示。
- `docs/` 和 `plans/` 文档体系完成。

## 14. 总施工原则

- 这个文件只做总蓝图，不替模块计划做详细设计。
- 每个模块施工前必须先写模块计划。
- 模块计划必须引用本总计划、`docs/ARCHITECTURE.md` 和 `docs/RUNTIME_CONCEPTS.md` 的相关章节。
- 新代码优先放进 `app/`，不要混入 `legacy_v0/app/`。
- 新文档优先放进 `docs/` 和 `plans/`，不要继续扩大旧文档体系。
- 先基础设施，再业务 domain。
- 先 intent / policy，再 planner / executor。
- 先 fixture，再真实外部服务。
- 先 deterministic eval，再考虑 LLM-as-judge。
- 先 trace，再 inspector 展示。
- 不迁移职责不清的旧模块；必要时重写轻量 当前 runtime。
