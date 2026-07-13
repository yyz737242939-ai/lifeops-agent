# Research / Personal Knowledge Domain 最终设计说明

本设计遵守 `plans/DOMAIN_CONTRACT_STANDARD.md`。Research planning/context/memory scope ID 是 Topic ID；Context / Memory 支持全局或 Topic scoped query，未知 Topic 明确失败而不退化为全局查询。

## 当前实现状态

Research / Personal Knowledge Domain 阶段 5 完整初版已完成并通过验证：

- `ExternalObservation`、`ResearchSource`、`ResearchSourceSnapshot`、Topic、Note、Brief、Link、Revision 与 read candidate 模型；
- schema v5 将 Source identity 与 fetch snapshot 分离，Brief 固定引用保存时的 snapshot；同 URL 新内容追加 snapshot，相同 content hash 拒绝；
- fixture-backed `ResearchSourcePort`，只读取显式声明的 source key；
- `research.fetch_source` 临时 READ 与 `research.save_source` 受控 WRITE；
- WRITE 只接受当前 service 已获取的 observation ID，不能由 Tool 参数伪造 provenance；
- Skill candidate Tool、Policy allowed effect、Gateway confirmation、transaction 和 `ExecutionEvidence` 聚焦测试。

Research Skill 已声明 Hugging Face Daily Papers / Blog 两个稳定 source key，并通过严格 JSON manifest、相对路径和精确 URL allowlist 校验。typed HTML adapter、deterministic parse/dedupe/topic-filter/rank、中文 brief draft、知识搜索和经确认的 Source / Brief / Note WRITE 已打通。PlanningReadModel 已包含覆盖计数、最近 Brief 和 unresolved questions；Context/Memory candidate provider、380 条 deterministic seed、provider failure 和引用完整性 fixtures 已完成。真实 briefing handler 已通过 compiled Graph 与 Guardrail 回归。按当前确认范围不实现恶意内容 fixtures；完整多 Tool briefing 循环仍属于阶段 6 ReAct Executor。

## 1. 目标

本模块建立可长期积累、可追溯来源的个人研究知识域，并恢复 Hugging Face Daily Papers / Blog 热点简报作为第一个真实外部只读场景。Domain 只从业务角度组织 Research models、service、repository 和 tools，不拥有独立 Planner / Executor；它可以与 Travel tools 出现在同一个通用 PlanRun 中。

## 2. 当前 V0 参考

- `legacy_v0/app/skills/news/`
- `legacy_v0/app/skills/source_loader.py`
- `legacy_v0/app/tools/tool.py` 中 source/helper 工具
- `legacy_v0/tests/test_agent_news_skill.py`
- `legacy_v0/tests/test_news_source_manifest.py`
- `legacy_v0/tests/test_news_helpers.py`

V0 已验证的流程：读取 briefing/source/copyright reference，白名单抓取 `hf_daily_papers` 和 `hf_blog`，解析、去重、排序，生成带链接的中文简报；失败不编造；大 HTML 使用 ephemeral reference；结果默认不进入长期 Memory。

阶段 5 在此基础上新增显式 Domain repository、provenance 和用户确认保存边界，不迁移 V0 聚合式 Agent loop。

## 3. 当前范围

### 3.1 阶段 5 完整范围

- 通用 `Research / Personal Knowledge` Domain，不绑定单一网站，也不拥有独立 Agent / Planner / Executor。
- `Topic`、`Source`、`Note`、`ResearchBrief`、`KnowledgeLink`、`Revision` 最小模型。
- SQLite repository / service 和聚焦 READ/WRITE tools。
- Hugging Face Daily Papers / Blog 白名单 external-read adapter；网络访问封装在 typed Port/adapter，Domain service 不直接依赖 SDK/HTTP client。
- parse、dedupe、rank、topic filter 和中文 source-linked briefing。
- 临时 observation / briefing 默认只属于当前 run；用户明确保存后才成为 `Source` / `ResearchBrief`。
- Source 保存 URL、source type、fetched/published metadata、content hash/summary 和 provenance；原始 HTML 不进 SQLite 或 event payload。
- Note 可以关联 Topic、Source 和其他 Note。
- 为阶段 6 Executor 提供 Tools；为阶段 7 Planner 提供 `DomainPlanningReadModel[ResearchPlanningSnapshot]`；为阶段 8 Context / Memory 提供共享只读 candidate provider 接口。
- 固定 fixture 和批量 seed 形状，支持几百条 Source/Note 的长期 Context 测试。

### 3.2 阶段 5 不做

- 不下载或保存完整论文全文。
- 不自动定时抓取、通知或自动保存所有热点。
- 不做 embedding、向量数据库、semantic retrieval 或完整 RAG。
- 不自动把 Source / Note / Brief 升级为 Memory。
- 不让模型 summary 覆盖来源事实。
- 不抓取任意 URL；只允许声明来源。
- 不实现阶段 6 ReAct loop、阶段 7 Planner、阶段 8 Context/Memory consumer 或阶段 9 Recovery；Domain 只提供稳定 Tool、read model 和 candidate provider contract。

## 4. Runtime 与领域边界

```text
Hugging Face list page
        ↓ external read
ExternalObservation（临时）
        ↓ parse/rank/dedupe
ResearchBriefDraft（临时）
        ↓ 用户明确保存 + Policy + ToolGateway
ResearchBrief / Source（业务事实）
```

```text
Source / Note / ResearchBrief = 用户明确保存的 Domain 事实
ContextSelection             = 当前 run 的临时选择
MemoryRecord                 = 阶段 8 的跨 session 记忆
LLM synthesis               = 临时生成物，未确认前不是事实
```

Domain 不依赖 LangGraph、Planner、Context Engine 或 Memory implementation。

### 4.1 未来适配接口

- Context Engine 通过 `DomainContextProvider.query_context_candidates(...)` 获取有预算信息和 provenance 的候选，不直接扫表。
- Memory 通过 `DomainMemoryCandidateProvider.query_memory_candidates(...)` 获取用户明确内容的候选，不能自动写 Memory。
- Planner 通过 `DomainPlanningReadModel.get_planning_snapshot(topic_id)` 获取 Topic、资料覆盖、最近 brief 和未解决 research question。
- Executor 只能经 ToolGateway 调 Research tools。
- Research 不定义 `ResearchPlanRun` / `ResearchExecutor`；通用 Planner 与 Tool 的匹配方式留到 Planner 模块施工时设计。
- Recovery 读取成功 tool evidence 与已保存事实，不从临时 LLM 文本恢复写入。
- DAG 可表达 fetch → parse → dedupe → rank → brief，但 persistence 仍需独立授权步骤。
- Eval 使用 fixture/source snapshot，不依赖当天真实热点。

## 5. 数据模型 / 存储

阶段 5 目标 SQLite 表：

- `research_topics`
- `research_sources`
- `research_notes`
- `research_briefs`
- `research_links`
- `research_revisions`

每张表仍必须在对应模型/service 实际施工时新增 migration 和 repository test，不能只因列在计划中就视为完成。

核心约束：

- URL/source identity 可去重；
- Source 与抓取快照分离；
- revision append-only 或带 version，不静默覆盖历史；
- 删除优先软删除/归档，保留引用完整性；
- provenance 字段不可由 LLM 自行伪造。

fixture 放在 `tests/fixtures/research/`；原始抓取结果只存在 request-local/reference artifact，不进入 event payload。

## 6. 对外接口

Repository / service 方向：

```python
create_topic(...)
fetch_source(source_key)
save_source(observation_id)
create_note(...)
save_brief(...)
link_items(...)
list_topics(...)
search_saved_items(query, filters, limit)
get_planning_snapshot(topic_id)
query_context_candidates(query, budget_hint)
```

Tool 方向：

- `research.fetch_source`
- `research.parse_items`
- `research.rank_items`
- `research.build_brief_draft`
- `research.save_source`
- `research.save_brief`
- `research.create_note`
- `research.search_knowledge`

当前还注册 `research.fetch_briefing_source`，用于返回不含 raw HTML 的 request-local document / observation IDs；原 `research.fetch_source` 保留最小 Source 纵向切片兼容。

external fetch 是 EXTERNAL_READ；本地 parse/rank/build/search 是 READ 或 request-local 处理；保存和创建是 WRITE。所有模型可见 Tool 先由 selected Skill candidate 与 Policy effect 求交，再经过 Guardrail 和 Gateway；WRITE 还必须绑定匹配当前 action 的 `ConfirmedAction` 并产生 evidence。

## 7. 失败模式

- 网络、timeout、HTTP status、content type 或页面结构变化；
- source/helper 非白名单；
- parser 返回空列表；
- 重复 URL 或内容 hash；
- provenance 缺失；
- raw HTML 过大或包含 prompt injection；当前实现限制大小且不把 raw HTML 暴露给 Tool output，恶意内容 fixture 按用户确认不纳入本阶段。
- 保存临时 briefing 时缺少用户授权；
- source 已更新但旧 brief 仍引用旧快照；
- Context 查询无限扩张；
- Note、Source、Memory 和 summary 边界混淆。

## 8. 测试和 Eval

- Hugging Face Papers / Blog 正常和失败 fixture；
- source manifest / host whitelist / traversal；
- parse/rank/dedupe deterministic 行为；
- 中文 briefing 包含来源、链接和“基于列表页可见信息”边界；
- 不抓取成功时不声称已获取热点；
- 临时结果不自动保存；
- WRITE Skill candidate / Policy effect / confirmation / transaction / evidence；
- Tool 参数不能伪造 provenance；
- URL 去重、revision 和引用完整性；
- 100-500 条 seed 下的分页、预算和 context candidate 稳定性；
- Executor / Planner / Context / Memory 的 contract tests 使用 fake consumer，不提前实现消费者；
- Graph 到真实 handler 的端到端成功与 Guardrail 拒绝路径。

## 9. 文档更新

- 完成后更新 `docs/ARCHITECTURE.md`、`docs/PROGRESS_LOG.md`、`docs/RUNTIME_CONCEPTS.md`。
- Hugging Face 官方 API/source、source safety 和 progressive loading 学习链接维护在 `docs/AGENT_LEARNING_LINKS.md`。
- Domain / Memory / Context 边界维护在本模块计划与 `plans/RUNTIME_REFACTOR_PLAN.md`，不新增 decisions / ADR 文档。

## 10. 实施步骤

1. [已完成] 定义领域模型、状态和不变量；已包含临时 `ExternalObservation` / `ResearchBriefDraft`，以及持久化 `ResearchSource` / `ResearchTopic` / `ResearchNote` / `ResearchBrief` / `KnowledgeLink` / `ResearchRevision`。
2. [已完成] 增加 migration、repository 和 service；已包含 Topic、Note、Brief、Brief-Source 引用、KnowledgeLink 和 append-only Revision 的 SQLite 基础，并在 service 中保持 observation / brief draft 的 request-local 保存边界。
3. [已完成] 建立 Research Skill 与 source manifest；`hf_daily_papers` / `hf_blog` 通过稳定 key 映射到 Skill 内 JSON 声明，加载时校验 traversal、严格字段、Hugging Face HTTPS host 和精确 URL allowlist，当前不执行网络访问。
4. [已完成] 迁移/重写 Hugging Face fetch / parse / rank / dedupe 小机制：`HuggingFaceResearchContentPort` 只抓取 manifest 声明的精确 URL，限制 status、redirect、content type、大小、timeout 和解码失败；`ResearchService` 通过 request-local `document_id` 暂存 `FetchedSourceDocument`；纯处理函数输出 typed `ResearchItem` 并提供 deterministic dedupe/rank。
5. [已完成] 临时 briefing fetch/parse/rank/build 已打通：`research.fetch_briefing_source` 返回不含 raw HTML 的 document metadata，`research.parse_items` / `research.rank_items` 只接受当前 service 持有的 request-local ID，`research.build_brief_draft` 生成包含来源链接和“基于列表页可见信息”边界的中文 draft；四个 Tool 均经过 Skill candidate、Policy effect、Guardrail 和 Gateway，且不写 SQLite。阶段 5 Direct Executor 尚不能在一个 run 内连续调度四个 Tool。
6. [已完成] 经授权保存 Source / Brief / Note 已打通：briefing fetch 同时生成 request-local `observation_id`，用户可先经 `research.save_source` 保存列表页 Source；`research.save_brief` 只接受当前 service 持有的 `draft_id`，且所有 draft source URL 必须已存在于 `research_sources`；`research.create_note` 保存确认后的 title/body。三个 WRITE Tool 都要求 Policy write effect、绑定 run/call/tool/arguments/expiry 的 `ConfirmedAction`、transaction 和对应 `ExecutionEvidence`。
7. [已完成] `ResearchReadService` 实现共享 `DomainPlanningReadModel[ResearchPlanningSnapshot]`、`DomainContextProvider[ResearchContextCandidate]` 和 `DomainMemoryCandidateProvider[ResearchMemoryCandidate]`；fake Planner、Context、Memory consumer contract tests 验证消费者只依赖统一接口。另提供带 kinds、limit、offset 的 `search_saved_items` 只读分页。
8. [已完成，按确认排除恶意内容 fixtures] 增加 schema version 1 的 380 条 deterministic Source/Note/Brief seed shape、timeout / HTTP 503 / empty parse provider failure fixtures，以及 missing link / unsaved Brief source / duplicate Source 引用完整性 fixtures；验证分页不重叠、预算稳定和失败不写入。按用户当前决定不实现 prompt injection 或其他恶意内容 fixtures。
9. [已完成] 完成 Domain 聚焦测试、真实 briefing handler compiled Graph 成功路径与 catalog 外 WRITE Guardrail 拒绝路径；稳定化后补充 Topic scoped read 与跨 execution scope 临时 ID 隔离。历史 `182` 项仅是当时快照，当前统一回归数字以稳定化计划和推进日志为准。
