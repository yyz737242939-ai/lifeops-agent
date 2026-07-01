# Skill References 与 Hugging Face News Briefing 实现计划

本文档用于后续继续施工。它把下一阶段学习目标和一个新的真实业务 domain 绑定起来：

```text
高级 Skill 机制
-> 渐进式读取 Skill Reference
-> 受控线上来源读取
-> Skill 声明的只读 helper
-> Hugging Face Papers + Blog 每日 AI 简报
```

目标不是做一个通用爬虫，也不是把新闻摘要写成一个大 Prompt，而是让 Skill 从“领域规则文本”升级成一个可声明资料、来源和只读能力的领域包。

## 0. 当前事实与施工边界

当前仓库已有：

- `app/skills/*/SKILL.md`：Todo、Finance、Wellbeing、Activity 领域规则。
- `app/skills/skill_loader.py`：发现 Skill 元数据，并在选中后加载 Skill 正文。
- `app/skills/skill_router.py`：基于当前输入进行确定性 Skill 路由。
- `app/skills/skill_state.py`：支持 Skill 继承、替换、清理和 Ref-only 状态。
- `app/prompts/prompt_builder.py`：按本轮 Skill 组装 Prompt。
- `app/tools/capability_builder.py`：按 Skill 和当前用户授权生成工具可见性。
- `app/context/*`：Context Engine 已负责本轮工作上下文装配、压缩、索引和观察。
- `app/memory/*`：Memory v1 已完成，只读 Profile 与用户授权 Semantic Memory 和业务数据保持分离。

本阶段新增一个业务 domain：

```text
news / ai_briefing
具体功能就是总结当天的热点新闻和博客等内容，然后给出总结，并附带正文链接。不需要给出正文内容。
```

第一批真实线上来源只包括 Hugging Face：

```text
https://huggingface.co/papers
https://huggingface.co/blog
```

本阶段明确不做：

- 不做通用任意 URL 抓取。
- 不做后台定时任务。
- 不做账号登录、浏览器自动化或绕过访问限制。
- 不抓取需要付费、登录或明显禁止自动访问的内容。
- 不保存新闻内容到长期 Memory。
- 不把抓取结果自动写入业务数据。
- 不把 Skill Reference、线上页面正文或 helper 输出追加进 `Agent.messages`。
- 不引入向量数据库、embedding 或复杂语义检索。

重要边界修正：

```text
早期只读脚本计划默认“无网络”。
本阶段为了真实 Hugging Face 来源，引入受控网络读取，但只允许访问 Skill Source Manifest 声明过的白名单来源。
```

## 1. 总体目标

完成后，用户可以询问：

```text
总结今天 Hugging Face 上的热门论文和热门博客。
今天 HF Daily Papers 有哪些值得关注的 Agent / LLM / 多模态方向？
把 Hugging Face Blog 最近的热门文章整理成中文简报。
```

Agent 的理想工作流：

```text
用户请求
-> Skill Router 选中 news
-> Prompt Builder 注入 news Skill 入口规则
-> 模型根据入口规则按需读取 Skill Reference
-> 模型调用受控 source/helper 工具读取 Hugging Face Papers 或 Blog
-> helper 解析、排序、去重、结构化返回
-> 模型按 reference 规则输出中文 AI 简报
```

核心学习点：

- Skill 可以像入口文档一样指导模型“什么时候读哪个 reference”。
- Runtime 必须控制 reference 读取范围，不能让模型自由读文件。
- Skill 可以声明只读 helper，但 helper 不是任意 shell。
- 线上读取必须由 source manifest 白名单控制，不能让模型传任意 URL。
- 所有 reference/source/helper 行为都要可观察、可测试。

## 2. 建议目录结构

```text
app/skills/news/
  SKILL.md
  references/
    briefing_policy.md
    source_policy.md
    copyright_policy.md
    output_templates.md
    topic_ai_research.md
    topic_agent_llm.md
  sources/
    huggingface_papers.yaml
    huggingface_blog.yaml
  helpers/
    news_helpers.py
```

后续如果需要把 domain store 独立出来，再增加：

```text
app/domains/news_source.py
app/domains/news_types.py
```

第一版尽量避免过早增加可写 store。新闻简报是 READ 能力，不是持久业务数据。

## 3. Skill Reference 设计

### 目标

让 `SKILL.md` 成为领域入口，而不是所有规则的堆叠处。

示例心智模型：

```text
如果用户要普通每日简报，读取 briefing_policy。
如果用户问来源可信度和引用边界，读取 source_policy 和 copyright_policy。
如果用户要求固定格式，读取 output_templates。
如果用户特别关注 Agent / LLM，读取 topic_agent_llm。
如果用户特别关注 AI 研究趋势，读取 topic_ai_research。
```

### Reference Manifest

第一版可以把 reference 声明写在 `SKILL.md` frontmatter 或 Skill 专属 manifest 中。推荐先选一种简单格式，避免平台化过早：

```yaml
references:
  briefing_policy:
    path: references/briefing_policy.md
    description: Rules for daily AI briefing summaries.
  output_templates:
    path: references/output_templates.md
    description: Output formats for concise Chinese briefings.
```

规则：

- 只能读取当前选中 Skill 声明过的 `ref_id`。
- 只能读取当前 Skill 目录下的 Markdown 文件。
- 拒绝绝对路径。
- 拒绝 `..` 路径穿越。
- 限制最大字符数。
- 读取行为进入日志诊断，但 reference 正文不写入 `Agent.messages`、Memory 或 Rolling Summary。

### Tool 形式

新增一个通用只读工具：

```text
read_skill_reference(ref_id: str)
```

它由当前 turn 的 `loaded_skills` 和 Skill Reference Manifest 决定可读范围。

## 4. Source Manifest 与受控网络读取

### 目标

支持真实读取 Hugging Face，但拒绝任意 URL。

建议 source 声明：

```yaml
id: hf_daily_papers
name: Hugging Face Daily Papers
url: https://huggingface.co/papers
kind: html
allowed: true
description: Trending AI papers from Hugging Face Daily Papers.
```

```yaml
id: hf_blog
name: Hugging Face Blog
url: https://huggingface.co/blog
kind: html
allowed: true
description: Hugging Face community and team blog articles.
```

规则：

- 模型只能传 `source_id`，不能传任意 URL。
- Runtime 根据当前选中 Skill 的 Source Manifest 解析真实 URL。
- 只允许 `https://huggingface.co/papers` 和 `https://huggingface.co/blog`。
- 设置超时。
- 限制响应大小。
- 使用明确的 User-Agent。
- 网络失败返回结构化错误，不允许模型假装已经读取。
- 后续可增加简单限流，但第一版不需要后台缓存。

### Tool 形式

新增受控读取工具：

```text
fetch_news_source(source_id: str)
```

返回结构化结果：

```text
source_id
url
fetched_at
status
content_type
content_excerpt_or_ref
error
```

如果页面较大，可以复用现有 Context Ref 思路：摘要进上下文，完整 HTML 放 Ref，解析 helper 通过受控链路读取。

## 5. Skill Helper 设计

### 目标

把确定性、机械性的工作交给受控脚本，而不是让模型直接在 HTML 文本里猜。

第一版 helper：

```text
parse_hf_daily_papers(html_ref_or_text, limit)
parse_hf_blog(html_ref_or_text, limit)
rank_news_items(items, limit)
dedupe_news_items(items)
```

输出统一结构：

```text
id: str
source_id: str
title: str
url: str
author_or_org: str | None
published_or_relative_time: str | None
score_or_votes: int | None
topic_hint: str | None
raw_position: int
```

规则：

- helper 只读。
- helper 不能写文件。
- helper 不能访问网络。
- helper 不能读取任意路径。
- helper 参数必须有 schema。
- helper 输出必须 JSON-safe。
- helper 有超时和结构化错误。
- Executor 执行前二次校验：当前 Skill 是否选中、helper 是否声明、参数是否合法。

### Helper Manifest

可以先在 Skill manifest 中声明：

```yaml
helpers:
  parse_hf_daily_papers:
    module: helpers.news_helpers
    function: parse_hf_daily_papers
    read_only: true
    timeout_seconds: 3
  parse_hf_blog:
    module: helpers.news_helpers
    function: parse_hf_blog
    read_only: true
    timeout_seconds: 3
```

第一版不要支持任意模块路径。只允许 Skill 自有 `helpers/` 下声明过的 helper。

## 6. Prompt 与 Context 接入

接入原则：

- `SKILL.md` 仍只在 Skill 被选中后加载。
- reference 由模型通过 `read_skill_reference` 按需读取。
- reference 读取结果作为本轮工具 observation 参与当前回答，但不进入长期 Memory。
- source fetch 和 helper 输出同样只属于当前 conversation/context，不自动升级为 Memory。
- 如果用户要求“以后每天关注 Hugging Face”，这属于未来自动化/提醒或 Memory 授权问题，本阶段只记录边界，不实现后台任务。

Prompt Builder 需要让 news Skill 知道：

```text
你可以按需调用 read_skill_reference(ref_id) 获取声明过的领域资料。
你可以调用 fetch_news_source(source_id) 获取声明过的线上来源。
你可以调用当前 Skill 声明的只读 helper 解析和整理结果。
```

Capability Builder 需要按当前 `loaded_skills` 暴露：

- `read_skill_reference`
- `fetch_news_source`
- 当前 Skill 声明的 helper tools

未选中 `news` 时，不暴露 Hugging Face source/helper。

## 7. 阶段实施计划

### 阶段一：News Skill 骨架

目标：

- 新增 `app/skills/news/SKILL.md`。
- Router 能识别 Hugging Face、论文、blog、新闻简报、AI 简报等触发词。
- Capability 暂不增加真实网络工具。

验收：

- `tests/test_skill_loader.py` 识别 news Skill。
- `tests/test_skill_router.py` 能把 Hugging Face Papers / Blog 请求路由到 news。

学习重点：

- 新 domain 如何进入现有 Skill 元数据、路由和状态继承链路。

### 阶段二：Reference Manifest 与 Loader

目标：

- 设计并解析 news Skill references。
- 实现 `read_skill_reference(ref_id)`。
- 拒绝未声明 reference、路径穿越和非当前 Skill reference。

验收：

- 选中 news 后可读取声明过的 reference。
- 未选中 news 时不可读。
- `../PROJECT_CONTEXT.md` 之类路径被拒绝。
- reference 正文不进入 `Agent.messages`、Memory 或 Rolling Summary。

学习重点：

- 渐进式 context loading 和 Runtime 文件边界。

### 阶段三：Hugging Face Source Manifest

目标：

- 新增 `sources/huggingface_papers.yaml`。
- 新增 `sources/huggingface_blog.yaml`。
- 实现 manifest 解析和 source 白名单校验。

验收：

- `hf_daily_papers` 解析到 `https://huggingface.co/papers`。
- `hf_blog` 解析到 `https://huggingface.co/blog`。
- 任意 URL 输入被拒绝。
- 未声明 source_id 被拒绝。

学习重点：

- 线上读取能力为什么必须 source_id 化，而不是让模型传 URL。

### 阶段四：受控网络读取

目标：

- 实现 `fetch_news_source(source_id)`。
- 只允许读取声明过的 Hugging Face 页面。
- 设置超时、响应大小限制和结构化错误。

验收：

- 能读取 Hugging Face Papers。
- 能读取 Hugging Face Blog。
- 网络失败时返回可解释错误。
- 读取行为进入日志诊断。

学习重点：

- Tool 成功与模型口头声称成功的区别。
- 真实网络 I/O 如何进入 Runtime 可观察链路。

### 阶段五：只读 Helper

目标：

- 实现 `parse_hf_daily_papers`。
- 实现 `parse_hf_blog`。
- 实现简单 `rank_news_items` 与 `dedupe_news_items`。

验收：

- helper 输出结构化新闻条目。
- helper 不写文件、不联网、不读任意路径。
- 参数错误、解析失败、超时都有结构化错误。

学习重点：

- Skill 提供脚本工具时，脚本边界、参数 schema、输出 schema 和 Executor 二次校验如何配合。

### 阶段六：News Briefing 闭环

目标：

- 用户可以请求 Hugging Face Papers + Blog 简报。
- Agent 按需读取 reference。
- Agent 读取 Hugging Face source。
- Agent 调 helper 解析和排序。
- Agent 输出中文简报，包含标题、链接、来源、简短理由和主题归类。

验收：

- 不编造未读取的新闻。
- 不大段复制文章正文。
- 能区分 Papers 与 Blog。
- 用户要求 Agent / LLM / 多模态方向时，能按 topic reference 调整筛选和输出。

学习重点：

- 一个高级 Skill 如何把入口规则、reference、source 和 helper 串成完整领域能力。

### 阶段七：观测、测试与文档收口

目标：

- 增加聚焦回归测试。
- 更新 `PROJECT_CONTEXT.md` 记录稳定事实。
- 只有在用户确认阶段完成或里程碑变化后，再考虑更新 `CHANGELOG.md`。

建议测试：

```text
tests/test_skill_reference_loader.py
tests/test_news_source_manifest.py
tests/test_news_helpers.py
tests/test_agent_news_skill.py
```

测试覆盖：

- 未选中 Skill 不可读 reference。
- 未声明 reference 拒绝。
- 路径穿越拒绝。
- 未声明 source 拒绝。
- 任意 URL 拒绝。
- Hugging Face source manifest 可解析。
- helper 只读、结构化输出、错误结构化。
- reference/source/helper 不污染 Memory。
- Skill 正文和 reference 不追加进 `Agent.messages`。

## 8. 数据与版权边界

输出规则：

- 可以总结标题、链接、作者/组织、日期、热度、主题和简短价值判断。
- 不大段复制网页或文章正文。
- 明确标注来源为 Hugging Face。
- 对论文和博客保持“摘要/整理/观察”语气，不假装已经读完整论文或完整文章，除非后续实现了文章详情页读取。
- 如果只读取列表页，就只基于列表页可见信息做简报。

这条边界很重要：

```text
列表页读取 != 读完整论文
Blog 列表读取 != 读完整文章
```

如果后续要读取详情页，需要新增 source/detail manifest、版权策略和更严格的内容长度控制。

## 9. 与 Memory / Context 的关系

News Briefing 的结果默认属于当前对话和工具观察，不属于长期 Memory。

不能自动保存：

- 今日热门论文。
- 用户读过哪些新闻。
- 用户对某篇文章的兴趣。
- 用户长期关注方向。

只有当用户明确说：

```text
记住我以后重点关注 Agent 和 LLM 论文。
以后默认 Hugging Face 简报里优先看多模态。
```

才允许通过 Memory WRITE 工具保存偏好。保存成功必须以工具 action 为事实依据。

## 10. 未来扩展

本阶段完成后可以考虑：

- 增加 Hugging Face Models Trending。
- 增加 Hugging Face Datasets Trending。
- 增加 RSS 或公开 API source 类型。
- 增加用户手动订阅 source 列表。
- 增加每日自动简报，但这属于 Automation / Scheduler，不属于本阶段。
- 增加详情页读取，但需要额外版权和长度边界。
- 增加跨天趋势比较，但需要可写 business store 或用户明确授权的历史记录。

## 11. 推荐提交节奏

建议按小步提交：

1. `news` Skill 骨架和路由测试。
2. Skill Reference manifest / loader / 工具 / 测试。
3. Hugging Face Source manifest / 受控 fetch / 测试。
4. News helper manifest / helper executor / 测试。
5. Papers + Blog 简报闭环和文档更新。

每一步都应能单独解释：

```text
这一层属于 Skill / Tool / Capability / Context / Memory / Business Data / Logs 中的哪一类？
它读取了什么？
它能不能写？
它如何被授权？
它失败时 Runtime 如何知道？
它会不会污染长期状态？
```
