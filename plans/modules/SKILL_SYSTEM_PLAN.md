# Skill System 模块计划

## 1. 目标

本模块解决 Runtime 如何发现、选择和按需加载 Skill 的问题。阶段 5 的 Skill 文件兼容 Agent Skills 的 `SKILL.md` / frontmatter / progressive disclosure 约定；不把 Skill 等同于 Tool，也不为使用官方实现而整体切换到 Deep Agents harness。

Skill 的职责是提供当前请求需要的领域说明、prompt contribution 和声明式 reference/source/helper 清单；Tool System 负责真实工具定义、安全检查和执行。

框架取舍：

- 使用轻量原生实现，并为未来替换 LLM 或接入框架保留薄接口。
- Agent Skills specification 和 Deep Agents Skills 只作为资源格式、校验规则和 progressive disclosure 的参考；LifeOps 不复用 `SkillsMiddleware`、framework backend 或 harness。

阶段 5 的 frontmatter 兼容子集：

- 必填且仅支持 `name`、`description`；未知字段明确失败，不静默忽略。
- `name` 遵循 Agent Skills 的长度、字符、连字符和父目录同名约束。
- `description` 非空且不超过 1024 字符，支持单行、引号字符串和 `>` / `|` block scalar。
- `license`、`compatibility`、`metadata` 和实验性的 `allowed-tools` 暂不进入 LifeOps 核心模型；未来确有需求时由独立 adapter 扩展。
- discovery 只读取 metadata，不加载 Markdown body、reference、script 或 asset。

阶段 5 首批 Skill：

- `research`：研究、个人知识、Hugging Face Papers / Blog 简报。
- `travel`：旅行约束收集、候选比较和 itinerary 规划。

## 2. 当前 V0 参考

只在迁移和对照时读取：

- `legacy_v0/app/skills/skill_loader.py`
- `legacy_v0/app/skills/skill_router.py`
- `legacy_v0/app/skills/reference_loader.py`
- `legacy_v0/app/skills/source_loader.py`
- `legacy_v0/app/skills/skill_state.py`
- `legacy_v0/app/prompts/prompt_builder.py`
- `legacy_v0/app/skills/news/`
- `legacy_v0/tests/test_skill_loader.py`
- `legacy_v0/tests/test_skill_router.py`
- `legacy_v0/tests/test_agent_news_skill.py`

保留的机制：

- discovery 与 body 延迟加载分离；
- 启动时只加载全部 Skill metadata，完整 body 按需加载；
- reference、source、helper 只能读取 manifest 白名单；
- 大 source 使用临时 reference，不把原始 HTML 塞进 prompt；
- Hugging Face 失败时明确失败，不编造来源内容。

不直接迁移：

- V0 聚合式 prompt / tool / state 接线；
- Skill 自己执行工具或授权写入；
- inherited skill state 自动决定当前 turn 的 Skill；
- 把临时 briefing 或 tool output 自动保存为 Memory。

## 3. 当前范围

### 3.1 初版做

- 定义 `SkillDefinition`、`LoadedSkill`、`SkillSelection`、`SkillReferenceDefinition`、`PromptContribution`。
- 从 `app/skills/*/SKILL.md` 发现 metadata，校验目录名、声明名和重复项。
- Runtime 启动时加载全部 Skill 的 `name`、`description` 等轻量 metadata。
- 用户提问后，由 LLM 直接基于用户请求和全部 Skill metadata 选择零到多个 Skill；不先按 Intent、规则或 Domain 筛选候选集。
- 只加载 selected skill body；未选中的 Skill 只暴露轻量 metadata。
- reference/source/helper 通过 manifest ID 访问，拒绝任意路径和任意 URL。
- Research Skill 声明 Hugging Face Daily Papers / Blog 来源及 parse / rank / dedupe helpers。
- Travel Skill 声明 Travel domain tools 和 fixture-backed external read capabilities。
- prompt assembly 只组合 core rules、selected Skill contribution 和必要的工具描述。
- 记录 `skill.selected`、`skill.loaded`、`skill.reference.loaded` 及失败事件。

### 3.2 初版不做

- 不实现 Tool execution。
- 不实现规则、关键词、Intent、embedding 或 rerank 等前置 Skill 筛选。
- 不支持用户显式声明、指定或强制启用某个 Skill。
- Skill 层不实现 Guardrail、权限判断或工具授权；这些约束统一由 Tool System 保证。
- 不接 MCP 或任意插件市场。
- 不让 Skill 直接读 SQLite、Context Store 或 Memory Store。
- 不实现自动 Skill 学习、自动改写 SKILL.md 或用户自定义 Skill UI。
- 不把多轮 Skill state 做成长期业务事实。

## 4. Runtime 边界

```text
Runtime startup
      ↓
load all Skill metadata into SkillRegistry
      ↓
RuntimeRequest + all Skill metadata
      ↓
LLM selects zero or more Skills
      ↓
load selected Skill body/reference on demand
      ↓
PromptContribution
      ↓
Planner / Executor / Tool System
```

Skill 选择只决定向 LLM 加载哪些任务说明和知识，不承担授权或 Guardrail。工具是否存在、是否允许调用以及调用前后的安全检查，统一由 Tool System 负责。

### 4.1 未来适配接口

- Context 阶段可把 selected Skill 的 `PromptContribution` 当作一种 context source，但 Context Engine 决定预算和最终顺序。
- Memory 和 Context 阶段未来可为 LLM 提供请求上下文，但不负责预筛选 Skill metadata。
- Planner 只消费 Skill instructions 和 capability catalog，不直接加载文件。
- Executor 只接收已解析的 Tool capability，不依赖 Skill loader。
- Recovery 可记录上一 run 的 selected Skill 作为解释材料，但重跑时由 LLM 重新选择。
- Inspector / Eval 读取 selection reason 与 loaded IDs，不读取隐藏的完整 Skill body。

## 5. 数据模型 / 存储

Skill manifest、SKILL.md、references 和 source declarations 存放在 `app/skills/`，不新增 SQLite 表。

建议结构：

```text
app/skills/
  models.py
  registry.py
  loader.py
  selector.py
  references.py
  prompt_assembler.py
  research/
    SKILL.md
    references/
    sources.json
  travel/
    SKILL.md
    references/
```

Skill route 和 load evidence 进入 `events.jsonl`；原始 Skill body、reference 正文和 source HTML 不进入 event payload。

reference 白名单使用 Skill 内的 `references/manifest.json`：根对象只包含 `references`，每个稳定 ID 只声明相对 Skill root 的 Markdown `path` 和 `description`。未声明 ID、绝对路径、`..` traversal、非 Markdown 文件、空正文和超限正文均明确失败。

稳定 trace 只记录关键语义节点：`skill.selected` / `skill.selection.failed`、`skill.loaded` / `skill.load.failed`、`skill.reference.loaded` / `skill.reference.load.failed`。不增加 discovery started/completed、逐字段 validation 或文件读取 lifecycle 事件；payload 不含用户原文、LLM selection reason、Skill body 或 reference 正文。selection reason 只保留在 request-local `SkillSelection` 中。

## 6. 对外接口

预期接口，最终命名以实现为准：

```python
discover_skills(root) -> list[SkillDefinition]
select_skills(request, skill_metadata, llm) -> SkillSelection
load_skill(skill_id) -> LoadedSkill
read_skill_reference(skill_id, ref_id) -> SkillReference
build_prompt_contributions(loaded_skills) -> list[PromptContribution]
```

Skill System 输出 LifeOps 类型，同时保持 `SKILL.md` 资源格式与 Agent Skills 约定兼容。若后续 Deep Agents / LangChain agent 或 middleware 需要动态 prompt，由独立 adapter 转换，不让核心 Policy、Capability 或 Domain 模型继承框架类型。

## 7. 失败模式

- frontmatter 缺字段、未知字段或格式错误；
- folder name 与 declared name 不一致；
- duplicate Skill ID；
- LLM 返回不存在、重复或格式错误的 Skill ID；
- reference/source/helper ID 未声明；
- path traversal 或非白名单 URL；
- selected Skill body 过大；
- inherited state 污染当前 turn；
- LLM 漏选跨 Domain 请求需要的 Skill，或加载无关 Skill；
- 外部 source 获取失败后模型编造结果。

选择结果必须经过结构校验；无效 Skill ID 不得进入加载阶段。工具安全失败由 Tool System 处理。

## 8. 测试和 Eval

- metadata discovery / validation；
- LLM 基于全部 metadata 选择零到多个 Skill，并返回结构化结果与简短 reason；
- Research 与 Travel 的正例、负例和多意图样例；
- 同一请求同时选择 Research + Travel，并加载两者完整 body；
- selected metadata 与 body lazy loading 分离；
- reference/source/helper 白名单和 traversal 防护；
- prompt 不包含未选中的 Skill body；
- 非 selected Skill 不因历史状态被自动加载；
- Hugging Face source 失败不产生虚构 briefing；
- selection/load event 不泄漏原始用户输入或完整 reference。

阶段 9 Eval 复用固定 fixture，断言 selected skills、reason、loaded skill IDs 和 trace evidence。

## 9. 文档更新

- 完成实现后更新 `docs/PROGRESS_LOG.md` 和 `docs/ARCHITECTURE.md`。
- 在 `docs/RUNTIME_CONCEPTS.md` 完善 Skill、Skill Routing、Progressive Reference Loading、Capability 章节。
- 阶段 5 学习链接维护在 `docs/AGENT_LEARNING_LINKS.md`，模块计划不散落 URL。
- 框架和 Domain 边界维护在本模块计划与 `plans/RUNTIME_REFACTOR_PLAN.md`，不新增 decisions / ADR 文档。

## 10. 实施步骤

1. [已完成] 定义 Skill 模型、错误和 registry。
2. [已完成] 对照 Agent Skills specification 和 Deep Agents Skills 实现，确定兼容 frontmatter 子集与 adapter 边界。
3. [已完成] 使用 LifeOps 原生薄实现完成 discovery / metadata validation；框架 loader / middleware 只作参考，不作为运行时依赖。
4. [已完成] 建立 Research / Travel Skill skeleton；当前只包含可发现 metadata、领域说明、边界和 planned workflow，不提前声明或执行尚未实现的工具。
5. [已完成] 实现基于全部 Skill metadata 的 LLM selection、LifeOps 结构校验和关键语义 trace；`SkillSelectionClient` 初始化时从 `.env` 读取模型与 OpenAI-compatible provider 配置，通过 Chat Completions 请求 JSON，并在本地使用 Pydantic 解析，不引入 Agent 框架。
6. [已完成] 实现 body / reference lazy loading、大小限制、manifest ID 白名单和 traversal 防护。
7. [已完成] 实现 framework-independent prompt contribution assembler；只把 selected-and-loaded Skill body 与 capability hints 转为 `PromptContribution`，保留选择顺序并拒绝重复 ID，不负责 core rules、工具描述、Context budget 或最终 prompt 排序。
8. [已完成] 接入 orchestration 和生产 bootstrap：Skill 永久启用，启动时总是 discover `app/skills/` 并构建 Registry / `SkillService`。request-local `prepare_skills` 仅在 allow 路径执行 selection/load/contribution；`SkillService` 是 Runtime 必需依赖，只有 `TraceSink` 通过 `OrchestrationContext` 传入。失败以 `runtime.skill_failed` 在 stub execution 前终止。
9. [已完成] 补聚焦测试和版本化长期 Eval fixture 形状；固定覆盖 Research、Travel、跨 Domain、零选择、未知 ID、重复 ID 和空 reason。
10. [已完成] 更新当前架构、概念、学习链接和推进事实，并完成全量回归与离线 bootstrap smoke 验证。
