# Runtime 架构

本文档记录当前架构快照和当前架构边界。它故意比模块实施计划更高层。

本文档不是递增历史。随着 runtime 推进，过时的架构描述应被替换为当前事实；项目演进过程记录在 `docs/PROGRESS_LOG.md`。

## 核心边界

当前 runtime 将职责拆分为显式层次：

```text
runtime
intent
policy
orchestration
context
memory
planning
execution
tools
domains
integrations
recovery
observability
inspector
evals
dag
storage
common
```

## 新代码根目录

当前代码放在：

```text
app/
```

Legacy 代码保留在：

```text
legacy_v0/app/
```

当前 runtime 不应隐式依赖 legacy 的 `legacy_v0/app/agents/agent.py`。

## 依赖方向

允许的高层依赖方向：

```text
main
-> runtime
-> orchestration
-> intent / policy
-> context / planning / execution / inspector
-> tools / domains / memory / recovery / integrations
-> storage / observability / common
```

默认禁止：

- domain 模块依赖 orchestration；
- policy 执行工具；
- planner 授权写入；
- inspector 修改 runtime 或业务状态；
- evals 使用真实用户数据；
- storage 依赖 domain service。

## Runtime Core

Runtime Core 是当前单轮 request lifecycle 的入口层，当前实现位于：

- `main.py`
- `app/runtime/models.py`
- `app/runtime/service.py`
- `app/runtime/bootstrap.py`
- `app/runtime/run_store.py`

`RuntimeRequest` 是当前 turn/run 的结构化输入，包含 `session_id`、`turn_id`、`run_id` 和 `user_input`。它不是长期 conversation memory。

`RuntimeResult` 是本轮可展示结果，包含 status、message、intent 摘要、policy 摘要和 trace summary。它不是业务事实来源。

当前 `RuntimeService.handle(...)` 的链路是：

```text
RuntimeRequest
-> RuntimeOrchestrator
-> StateGraph
-> classify_intent
-> decide_policy
-> policy conditional route
-> stub_execute / requires_confirmation / deny
-> finalize
-> RuntimeResult
```

传入 SQLite connection 时，Runtime Core 可以写入 `run_records`。传入 event log 或配置 `log_root` 时，Runtime Core 会把 runtime event 写入 `events.jsonl`。未传入 connection 时，它仍可通过文件 event log 记录运行路径，也可以保持 request-local 纯内存运行，便于聚焦测试。

当前 tool execution 仍是 stub。`runtime.orchestration.stubbed` 表示阶段 4 graph 已完成编排，但没有执行真实工具或业务写入。

## LangGraph Orchestration

LangGraph Orchestration 当前实现位于：

- `app/orchestration/state.py`
- `app/orchestration/routes.py`
- `app/orchestration/nodes/`
- `app/orchestration/graph.py`

`RuntimeService` 仍是唯一外部入口，负责 SQLite transaction、run record、request event writer 和最终 `RuntimeResult`。`RuntimeOrchestrator` 只负责把现有 Intent / Policy / stub result lifecycle 映射到 compiled `StateGraph`。

当前 graph 路径是：

```text
START
-> classify_intent
-> decide_policy
-> allow -----------------> prepare_skills -> stub_execute \
-> requires_confirmation -> requires_confirmation --+-> finalize -> END
-> deny ------------------> deny -------------------/
```

Intent、Policy 或 Skill preparation 失败时，graph 在对应节点后直接进入 `END`。Skill 失败不会进入 `stub_execute`；确认和拒绝分支不会调用 Skill selector。

`GraphState` 只保存当前 request 的编排数据：request、intent、policy、route、Skill selection、loaded Skill IDs、prompt contributions、result、error、graph path 和紧凑 trace summary。它不保存 `SkillService`、Skill registry/client、长期 Memory、Task 事实、工具执行事实或授权替代来源。

`IntentService`、`PolicyService` 和 `SkillService` 是 graph 构建期依赖。`SkillService` 长期持有 `SkillRegistry` 与 `SkillSelectionClient`，统一执行 selection、lazy loading 和 contribution assembly。`OrchestrationContext` 只携带每个 run 不同的应用 `TraceSink`；它通过 LangGraph `context_schema` / `Runtime` 提供给节点，不进入 `GraphState` 或 checkpoint。Intent / Policy node 在真实 service 返回后分别写 `intent.classified` / `policy.decided`，失败时写对应 failed event；Policy 分支确定后写 `orchestration.route.selected`。机械化的 graph/node started/completed 不进入稳定事件契约。

LangGraph 不负责 Policy 决策、业务事实、工具安全、真实执行或持久化；这些边界仍由 LifeOps 自研 runtime 拥有。

## Skill System

Skill System 当前实现位于 `app/skills/`。`SkillDefinition`、`LoadedSkill`、`SkillSelection`、`SkillReferenceDefinition` 和 `PromptContribution` 是框架无关的 LifeOps 类型；`SkillRegistry` 提供确定性 metadata 查询和重复 ID 防护。

`discover_skills(root)` 使用 LifeOps 原生薄实现扫描根目录的直接子目录。当前只读取每个 `SKILL.md` frontmatter 中的 `name` 和 `description`，校验 Agent Skills 命名约束、父目录同名、必填项和未知字段；不读取 Markdown body、reference、script 或 asset。Deep Agents / LangChain Skills 只作为文件约定和 progressive disclosure 参考，不是 runtime 依赖。

当前内置 Skill skeleton 是 `research` 和 `travel`。它们的 `SKILL.md` body 只描述领域用途、临时结果与持久化事实边界以及 planned workflow；尚未实现的 source、helper、Travel Port、tool 和 capability 不作为可用能力暴露。

`select_skills(request, skill_metadata, llm)` 把 `RuntimeRequest` 和全量 Skill metadata 交给 `SkillSelectionClient`。该 client 在初始化时从 `.env` 读取 `OPENROUTER_API_KEY`、`OPENROUTER_BASE_URL` 和 `MODEL`，通过 OpenAI-compatible Chat Completions 请求 JSON 结果；请求只包含用户请求以及全部 Skill ID/description。provider 返回值先经过 Pydantic 结构解析，随后由 LifeOps 校验只能包含 `selected_skill_ids` 和非空 `reason`，并拒绝重复或未知 ID。该接口不预先按 Intent、关键词或 Domain 缩小候选集，也不依赖 Agent 框架。

`load_skill(definition)` 只在选中后读取对应 `SKILL.md` body。`read_skill_reference(definition, reference_id)` 只接受 `references/manifest.json` 白名单中的稳定 ID，并限制为 Skill root 内的 Markdown 相对路径。body/reference 均有空内容和字符数上限校验；正文不进入 trace payload。

`build_prompt_contributions(loaded_skills)` 按 selection/load 顺序把 `LoadedSkill.body` 和声明式 capability hints 转换为独立 `PromptContribution`。它只消费实际已加载的 Skill，拒绝重复 Skill ID；不拼接 core rules、工具描述或最终 system prompt，也不决定 Context budget 和最终排列顺序。

当前 request-local Skill 链路是：

```text
Skill root
-> direct child SKILL.md
-> strict metadata validation
-> SkillDefinition
-> SkillRegistry
-> LLM selection + LifeOps validation
-> selected body / declared reference lazy loading
-> PromptContribution list
-> existing stub execution
```

生产 bootstrap 根据 `config/default.json` 的 `skills.root` 总是执行 discovery，并直接构造 `SkillSelectionClient()`、Registry 与必需的 `SkillService`；模型和 provider 地址不再通过 bootstrap 或 JSON 配置逐层传参。不存在 Skill 开关或空 service 分支。`prepare_skills` 只位于 Policy allow 路径。稳定事件只包含 `skill.selected`、`skill.loaded`、`skill.reference.loaded` 及其失败事件，不记录机械化文件读取 lifecycle。LLM selection reason 保留在 request-local `SkillSelection` 中，不写 event payload，避免间接复述用户原文。原始 provider interaction 等统一 LLM Gateway 出现后再集中进入 `llm.jsonl`。最终完整 prompt assembly 仍未实现。Skill metadata 不提供工具授权；未来 capability、Policy 和 Guardrail 仍由 Tool System 统一求交与执行。

## Intent / Policy

Intent Layer 当前实现位于：

- `app/intent/models.py`
- `app/intent/classifiers.py`
- `app/intent/service.py`

Intent 判断用户可能想做什么，例如 `chat`、`read`、`write_request`、`plan_request`、`clarification_needed`。`IntentService` 会调用规则 classifier 和 LLM classifier 接口。当前 `LlmIntentClassifier` 是空实现，只返回 `not_available`，不调用真实模型。

Policy / Permission Layer 当前实现位于：

- `app/policy/models.py`
- `app/policy/service.py`

Policy 判断系统现在被允许做什么。它只基于当前 `RuntimeRequest` 和 `IntentDecision` 产出 `PolicyDecision`，不能从 Planner、assistant 文本、LLM classifier、Recovery Context 或 LangGraph checkpoint 获得写入授权。

当前允许的写入 scope 只是候选授权模型：

```text
task.write_candidate
memory.write_candidate
wellbeing.write_candidate
```

这些 scope 不代表对应 domain 已经实现，也不代表真实工具已经执行。

## 基础设施层

`common`、`storage` 和 `observability` 是当前 runtime 的基础设施层：

- `common` 提供配置读取、ID、时间、错误和 JSON 序列化，不依赖业务模块。
- `storage` 提供 SQLite 连接、schema migration 和 transaction boundary，不依赖 domain service。
- `observability` 提供 event / LLM / normal 程序日志的写入和读取，不负责业务状态变更。

真实数据库默认路径由 `config/default.json` 的 `database.path` 声明。当前默认值是：

```text
data/lifeops.sqlite3
```

测试必须使用 `:memory:` 或临时文件数据库，不复用真实用户数据库。

真实日志默认根目录由 `config/default.json` 的 `logs.root` 声明。当前默认值是：

```text
logs/sessions
```

## 事实来源

Runtime 的事实来源是：

- 基于 SQLite 的业务 repository；
- 成功的 WRITE tool result；
- 用户明确授权且由成功 ToolResult / ExecutionEvidence 支持的 Domain WRITE。

不是事实来源：

- assistant final answer 文本；
- Planner 输出；
- LangGraph checkpoint state；
- Recovery Context；
- conversation summary。
- 原始 LLM request-response log。

## Observability

当前 observability 分成三类日志：

- `events.jsonl`：结构化 runtime event，只保存少量必要字段和紧凑 payload，用于解释 runtime 路径和失败层级。
- `llm.jsonl`：原始 LLM / agent request-response 记录，用于人工排查最原始对话，不作为业务事实或写入授权来源。
- `application.log`：普通程序日志，用于测试和 debug。

三类日志默认写入 `logs/sessions/session_<timestamp>_<session_id>/`。SQLite 不再默认承载 runtime event log 或 LLM log。

`TraceSink` 是应用拥有的 request-local event 接口。Graph 内 node 通过 `OrchestrationContext` 使用同一个 sink；Graph 外未来的 Executor、Tool Safety、repository 或 integration 关键阶段也可以直接写同一个 sink，不需要为了可观察性变成 LangGraph node。Event 在真实逻辑边界实时追加，不根据最终 state 事后补写。

## Runtime 不变量

- 用户数据安全优先。业务写入必须来自用户当前输入中的明确授权。
- Intent 只提供语义信号，不授权写入。
- Policy 是当前写入授权事实源；Executor 未来只能执行 Policy 允许的操作。
- 不能只凭 assistant 文本判断成功。Runtime 状态和成功的 WRITE action 才是“已保存”或“已更新”的事实来源。
- Skill、Tool、Capability、Context、Runtime State、业务数据和长期 Memory 必须保持分离。
- Conversation Summary 不是 Long-term Memory。Context compaction 结果不能自动升级为长期记忆。
- LangGraph checkpoint state、Planner 输出和 Recovery Context 不是业务事实来源，也不是写入授权来源。
- `TraceSink` 是运行依赖，不进入 `GraphState`；event payload 不写完整 GraphState 或原始用户输入。
- 修改 Runtime 行为、Context 处理、Memory、写入安全或工具执行时，需要聚焦的回归测试。

## PlanRun vs Domain Facts

`PlanRun` / `PlanStep` 是跨 Domain 的通用 runtime 执行策略。它们可以为了暂停、恢复、fault tolerance 和审计而持久化，但不会因此成为 Research 或 Travel 业务事实。

Research / Travel 是业务逻辑分组：各自拥有 models、service、repository 和 tools。Planner / Executor 位于 Domain 之上，一个 PlanRun 可以交叉调用多个 Domain 的 tools。

PlanStep 不自动转换成长期 Task。只有绑定当前用户授权、通过 Tool Guardrails、成功执行并产生 evidence 的 Domain WRITE，才能创建或修改 Source、Note、ResearchBrief、Trip、Itinerary 等长期事实。

LangGraph checkpoint 保存 graph/thread state，可用于恢复和 time travel；已经提交到 Domain repository 或外部系统的副作用不会因为恢复旧 checkpoint 而自动回滚。

## 架构维护规则

- 当前架构事实写在本文档。
- 历史推进和完成状态写在 `docs/PROGRESS_LOG.md`。
- 学习解释写在 `docs/RUNTIME_CONCEPTS.md`。
- 外部学习链接写在 `docs/AGENT_LEARNING_LINKS.md`。
