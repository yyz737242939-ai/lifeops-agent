# Research / Personal Knowledge Domain 模块计划

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

### 3.1 初版做

- 通用 `Research / Personal Knowledge` Domain，不绑定单一网站。
- `Topic`、`Source`、`Note`、`ResearchBrief`、`KnowledgeLink`、`Revision` 最小模型。
- SQLite repository / service 和聚焦 READ/WRITE tools。
- Hugging Face Daily Papers / Blog 白名单 external-read adapter。
- parse、dedupe、rank、topic filter 和中文 source-linked briefing。
- 临时 briefing 默认只属于当前 run；用户明确保存后才成为 `ResearchBrief`。
- 用户明确保存选中条目后才成为 `Source`。
- Source 保存 URL、source type、fetched/published metadata、content hash/summary 和 provenance；原始 HTML 不进 SQLite。
- Note 可以关联 Topic、Source 和其他 Note。
- 提供确定性的 `PlanningReadModel` 和 `DomainContextProvider`，阶段 5 只定义接口和基础查询。
- 固定 fixture 和批量 seed 形状，支持几百条 Source/Note 的长期 Context 测试。

### 3.2 初版不做

- 不下载或保存完整论文全文。
- 不自动定时抓取、通知或自动保存所有热点。
- 不做 embedding、向量数据库、semantic retrieval 或完整 RAG。
- 不自动把 Source / Note / Brief 升级为 Memory。
- 不让模型 summary 覆盖来源事实。
- 不抓取任意 URL；只允许声明来源。

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
MemoryRecord                 = 阶段 6 的跨 session 记忆
LLM synthesis               = 临时生成物，未确认前不是事实
```

Domain 不依赖 LangGraph、Planner、Context Engine 或 Memory implementation。

### 4.1 未来适配接口

- Context Engine 通过 `DomainContextProvider.query_candidates(...)` 获取有预算信息和 provenance 的候选，不直接扫表。
- Memory 通过 `MemoryCandidateProvider` 获取用户明确内容的候选，不能自动写 Memory。
- Planner 通过 `ResearchPlanningReadModel` 获取 Topic、资料覆盖、最近 brief 和未解决 research question。
- Executor 只能经 ToolGateway 调 Research tools。
- Research 不定义 `ResearchPlanRun` / `ResearchExecutor`；通用 Planner 与 Tool 的匹配方式留到 Planner 模块施工时设计。
- Recovery 读取成功 tool evidence 与已保存事实，不从临时 LLM 文本恢复写入。
- DAG 可表达 fetch → parse → dedupe → rank → brief，但 persistence 仍需独立授权步骤。
- Eval 使用 fixture/source snapshot，不依赖当天真实热点。

## 5. 数据模型 / 存储

候选 SQLite 表：

- `research_topics`
- `research_sources`
- `research_notes`
- `research_briefs`
- `research_links`
- `research_revisions`

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
save_source(..., provenance)
create_note(...)
save_brief(...)
link_items(...)
list_topics(...)
search_saved_items(query, filters, limit)
get_planning_read_model(topic_id)
query_context_candidates(query, budget_hint)
```

Tool 方向：

- `fetch_huggingface_source`
- `parse_huggingface_items`
- `rank_research_items`
- `build_research_brief_draft`
- `save_research_source`
- `save_research_brief`
- `create_research_note`
- `search_research_knowledge`

前四个是 READ/临时处理；保存和创建是 WRITE，必须被 Policy 明确点名允许并产生 evidence。

## 7. 失败模式

- 网络、timeout、HTTP status、content type 或页面结构变化；
- source/helper 非白名单；
- parser 返回空列表；
- 重复 URL 或内容 hash；
- provenance 缺失；
- raw HTML 过大或包含 prompt injection；
- 保存临时 briefing 时缺少用户授权；
- source 已更新但旧 brief 仍引用旧快照；
- Context 查询无限扩张；
- Note、Source、Memory 和 summary 边界混淆。

## 8. 测试和 Eval

- V0 Hugging Face Papers / Blog 正常和失败 fixture；
- source manifest / host whitelist / traversal；
- parse/rank/dedupe deterministic 行为；
- 中文 briefing 包含来源、链接和“基于列表页可见信息”边界；
- 不抓取成功时不声称已获取热点；
- 临时结果不自动保存；
- WRITE allowed tool / confirmation / transaction / evidence；
- URL 去重、revision 和引用完整性；
- 100-500 条 seed 下的分页、预算和 context candidate 稳定性；
- Planner/Context/Memory 未来 contract tests 使用 fake consumer，而不实现后续模块。

## 9. 文档更新

- 完成后更新 `docs/ARCHITECTURE.md`、`docs/PROGRESS_LOG.md`、`docs/RUNTIME_CONCEPTS.md`。
- Hugging Face 官方 API/source、source safety 和 progressive loading 学习链接维护在 `docs/AGENT_LEARNING_LINKS.md`。
- Domain / Memory / Context 边界维护在本模块计划与 `plans/RUNTIME_REFACTOR_PLAN.md`，不新增 decisions / ADR 文档。

## 10. 实施步骤

1. 定义领域模型、状态和不变量。
2. 增加 migration、repository 和 service。
3. 建立 Research Skill 与 source manifest。
4. 迁移/重写 Hugging Face fetch / parse / rank / dedupe 小机制。
5. 先打通临时 briefing READ 路径。
6. 接入经授权保存 Source / Brief / Note 的 WRITE 路径。
7. 增加 planning/context/memory candidate ports，但不实现后续消费者。
8. 增加长期 seed 和 failure fixtures。
9. 完成聚焦测试和文档同步。
