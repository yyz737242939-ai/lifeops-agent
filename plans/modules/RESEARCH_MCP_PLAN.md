# Stage 8 Research External Interfaces / Hugging Face MCP 模块计划

文档状态：已完成。步骤 1-14、offline/live 双层验证与文档 gate 均已关闭，Stage 8 结论为 `go`；Stage 9 Context / Memory gate 为 `go`，下一步先创建并确认其模块计划。

本计划是 `plans/modules/RESEARCH_KNOWLEDGE_DOMAIN_PLAN.md` 的 Stage 8 增量计划，遵守 `plans/DOMAIN_CONTRACT_STANDARD.md`。它不建立新的 Research Agent、Planner 或 Executor，也不改变通用 Plan-and-Execute / ReAct 控制骨架。

## 已冻结决策

- Stage 8 正式改为 Research External Interfaces / Hugging Face MCP；原 Context / Memory 后移到 Stage 9，Recovery / Feedback 后移到 Stage 10。
- Calendar MCP 从当前 V1 路线删除；Calendar fixture 业务能力继续保留，未来真实 Calendar MCP 只作为 Travel Port 的可选 Adapter。
- 论文主线是：创建 Topic → 通过 MCP 搜索 Hugging Face papers → 确认保存 Source → 确认关联 Topic。
- MCP 使用本地短生命周期 stdio Server；每次 `research.search_papers` 调用完成 initialize、`tools/list`、schema 校验、`tools/call` 和关闭，不维护后台常驻连接。
- MCP Server 使用官方 MCP Python SDK，外部论文读取使用官方 `huggingface_hub.HfApi`；公共读取显式使用 `token=False`，不要求 OpenAlex 或其他 API key。
- 不新增 `research_papers` 表，不升级 SQLite schema；论文继续映射为 request-local `ExternalObservation`，确认后复用 `ResearchSource` / `ResearchSourceSnapshot`。
- 模型可见 Research Tool 总数固定为 9；旧细粒度 briefing Tools 与新 Tools 在同一步原子替换，不长期并存。
- Planner / Executor 生产代码不修改；本阶段只通过既有 `ToolGateway`、`AllowedToolSet`、confirmation 和 evidence 接入。
- Stage 8 `go` 同时要求 deterministic/offline MCP E2E 和一次真实 Hugging Face MCP smoke。

## 1. 目标

本模块把已存在于 Research service / repository 的用户业务能力补齐为 Agent 可调用 Tool，并增加一个真实 MCP external-read 切片，使 Research 从“每日列表页简报”扩展到“按关键词搜索公开 AI 论文并保存到个人知识库”。

目标业务闭环：

```text
用户研究目标
-> research.create_topic（可选，WRITE confirmation）
-> research.search_papers（EXTERNAL_READ，经本地 stdio MCP）
-> request-local ExternalObservation
-> research.save_source（WRITE confirmation）
-> research.link_items（WRITE confirmation）
-> ResearchSource / Snapshot / Topic / KnowledgeLink
```

同时把当前模型需要连续调用的 briefing fetch → parse → rank → draft 四步收敛为一个 `research.build_brief` Tool；底层纯函数和 service 方法继续独立存在并单测。

本模块要证明：

- MCP 是外部 Port 的 Adapter channel，不是新的授权来源或执行循环；
- MCP Tool schema 和 provider SDK 类型不会泄漏到 Domain model、Planner 或 Executor；
- 外部搜索结果默认只属于当前 request，模型不能通过参数伪造论文 provenance；
- 只有确认后的 `save_source` / `link_items` 等 WRITE 才创建长期业务事实；
- 9 个 Tool 足以覆盖简报、论文搜索、Topic、知识搜索、保存、关联和 Revision，不引入万能聚合 Tool。

## 2. 当前 V0 参考

只读取以下 Legacy MCP 文件作为历史对照：

- `legacy_v0/app/mcp/client.py`
- `legacy_v0/app/mcp/types.py`
- `legacy_v0/app/mcp/errors.py`
- `legacy_v0/mcp_servers/mock_package_server.py`

可保留的经验：

- `McpServerConfig` 应明确 server ID、启动命令、工作目录和 timeout；
- stdio Server 的 stdout 必须只输出协议消息；普通日志只能写 stderr；
- MCP failure 应区分 server unavailable、timeout、protocol error 和 invalid response；
- `tools/list` 与 `tools/call` 的结果必须先规范化，不能直接作为 Domain 事实。

不继续使用的 V0 做法：

- 不手写或硬编码 JSON-RPC / MCP protocol version；
- 不用一次 `subprocess.run` 拼接多条请求模拟完整 session；
- 不把 stderr、异常文本或原始 provider payload直接返回给模型；
- 不把 MCP Tool 放进绕过当前 Registry / Gateway 的全局工具入口；
- 不迁移 package tracking 业务或旧 `COMMON_TOOL_NAMES` capability 设计。

当前 Research 实现是主要复用基础：

- `ExternalObservation`、`ResearchSource`、`ResearchSourceSnapshot`；
- request-local observation / document / item-set / draft 保存；
- `ResearchRepository` 的 URL、content hash、snapshot 和引用完整性约束；
- `ResearchService` 的 fetch / parse / rank / brief / save / Topic / Link / Revision 方法；
- 现有 Tool Gateway、Guardrails、`ConfirmedAction` 与 `ExecutionEvidence`；
- Hugging Face Papers / Blog manifest、HTML adapter 和 deterministic processing functions。

## 3. 当前范围

### 3.1 本阶段实现

- 增加官方 `mcp` Python SDK 与 `huggingface_hub` 依赖，并锁定实际验证版本。
- 增加最小通用 stdio MCP client boundary：配置、单次 session、discovery、call、规范化 result 和错误。
- 增加本地 Hugging Face Paper MCP Server，只暴露 MCP 级 `search_papers`。
- Server 使用 `HfApi(token=False).list_papers(query=..., limit=...)`；如列表结果缺少计划要求的安全字段，可在 Server 内部按 paper ID 调用 `paper_info(...)`，但不新增模型可见 Tool。
- 增加 Research-owned `PaperSearchPort` 和 `HuggingFaceMcpPaperSearchAdapter`。
- 把 MCP structured result 严格转换为现有 `ExternalObservation`，保存到当前 `ResearchService` request-local observation store。
- 增加 `research.search_papers`，并让现有 `research.save_source` 同时接受 Hugging Face briefing observation 与 paper observation ID。
- 增加 `research.create_topic`、`research.link_items`、`research.append_revision`。
- 扩展 `research.search_knowledge` 以支持 Topic listing / filtering，不单独增加 `research.list_topics`。
- 合并 briefing 模型 Tool 为 `research.build_brief`；底层 fetch / parse / dedupe / rank / draft 机制继续保留。
- 更新 Research Skill instructions、Tool contract freeze、聚焦测试、compiled E2E、真实 provider smoke 和当前文档。

### 3.2 本阶段不做

- 不修改 Planner、PlanningRouter、PlanController、ReactExecutor、Executor graph 或 outer graph 控制骨架。
- 不实现 Stage 9 Context / Memory consumer，不把 planning snapshot/context/memory candidate 暴露成 Tool。
- 不实现 Stage 10 Recovery / Feedback、自动 replay、后台重试或长连接恢复。
- 不实现远程 Streamable HTTP、SSE、OAuth、MCP authorization、Resources、Prompts、Sampling、Roots 或 server notifications。
- 不使用第三方远程 MCP Server，不部署网络服务，不维护常驻 MCP 进程或后台 event-loop thread。
- 不引入 OpenAlex、Semantic Scholar、Crossref 或第二个论文 provider。
- 不读取、下载、解析或保存论文全文/PDF；不做 embedding、RAG、引用网络或作者关系库。
- 不新增 Paper 表、Author 表、DOI 索引或 SQLite migration。
- 不自动保存搜索结果，不自动关联 Topic，不自动把 Source 升级为 Memory。
- 不在事件、LLM 日志或普通日志中写 MCP 原始 payload、全文、API token、异常正文或用户数据库内容。
- 不实现 Calendar MCP；Travel Calendar fixture 保持现状。

## 4. Runtime 边界

### 4.1 依赖方向

```text
ReactExecutor / PlanController（不修改）
-> ToolGateway（既有授权与安全边界）
-> research.search_papers handler
-> ResearchService
-> PaperSearchPort
-> HuggingFaceMcpPaperSearchAdapter
-> one-shot StdioMcpClient
-> local Hugging Face Paper MCP Server
-> huggingface_hub.HfApi
```

允许的实现位置：

```text
app/domains/research/ports.py
  PaperSearchPort

app/integrations/mcp/
  models.py
  errors.py
  client.py

app/integrations/research_mcp/
  adapter.py
  server.py
  provider.py
```

Domain service 只依赖 `PaperSearchPort`。`mcp.ClientSession`、`StdioServerParameters`、`PaperInfo`、MCP content block 和 provider exception 都不能进入 `app/domains/research/models.py` 或公共 Tool output。

### 4.2 同步 Tool 与异步 MCP 的桥接

当前 `ToolHandler = Callable[[ToolCall], ToolResult]` 且 `ToolGateway.execute(...)` 是同步接口。本阶段不改变该 contract。

`StdioMcpClient.call_tool_once(...)` 使用同步 façade 包装一个内部 async function：

1. 校验静态 `McpServerConfig`；
2. 使用官方 SDK 启动 stdio Server；
3. 建立 `ClientSession` 并 initialize；
4. 调用 `tools/list`；
5. 校验预期 `search_papers` 名称和 input schema；
6. 调用一次 `tools/call`；
7. 只接受满足约定的 `structuredContent`；
8. 关闭 session、stdio streams 和子进程；
9. 把结果或 typed failure 返回同步 handler。

当前同步 Gateway 路径可使用 `asyncio.run(...)`/SDK 推荐等价入口。若调用线程已经存在 active event loop，本阶段不启动后台线程兜底，而是 fail-closed 为稳定 bridge error；未来 runtime 异步化时再单独设计 async ToolHandler。

### 4.3 授权与事实边界

- `research.search_papers` 和 `research.build_brief` 是 `EXTERNAL_READ`；MCP discovery 不新增 Tool 权限。
- 模型只看到 LifeOps 冻结后的 9 个 Tool；不会看到 MCP Server 的动态 catalog。
- `tools/list` 只用于 runtime 校验已配置 Server 的实际能力，不能把新发现 Tool 动态加入 `AllowedToolSet`。
- paper result 先转换为 request-local `ExternalObservation`；未经 `research.save_source` 确认，不进入 SQLite。
- `research.save_source` 只接受当前 service 持有的 observation ID；不接受 title、authors、summary、URL、published time 或 provenance 作为可伪造参数。
- Topic、Source、Link、Revision 的 WRITE 继续要求 Policy write effect、精确 `ConfirmedAction`、transaction、成功 `ToolResult` 和 `ExecutionEvidence`。
- Planner output、MCP content、assistant 文本和 Hugging Face response 都不是授权来源。

## 5. 数据模型 / 存储

### 5.1 不新增持久化模型

Hugging Face paper 统一映射为现有模型：

```python
ExternalObservation(
    observation_id="research-observation-...",
    source_key="hf_paper",
    source_type="paper",
    title="...",
    url="https://huggingface.co/papers/<arxiv-id>",
    summary="bounded safe projection of authors + abstract/summary",
    published_at="...",
    content_hash="...",
    fetched_at="...",
    provenance="mcp:huggingface:<arxiv-id>",
)
```

确认保存后继续写：

```text
research_sources
research_source_snapshots
```

不新增 schema version。URL 继续承担 Source identity；normalized safe projection 的 hash 继续承担 snapshot content identity。作者和 arXiv ID 初版保留在 bounded summary、URL 与 provenance 中，不建立结构化关系表。

### 5.2 request-local 状态

- MCP raw result：只存在 Adapter call stack，验证和转换后释放。
- paper observations：保存在当前 `ResearchService` observation map，生命周期与一个 Tool execution scope 一致。
- brief documents / item sets / draft：继续使用当前 request-local stores。
- MCP session / subprocess：只存在于一次 `research.search_papers` handler 调用。
- 任何失败路径都不能写 `research_sources`、`research_source_snapshots`、`research_links` 或 `research_revisions`。

### 5.3 fixture

新增固定 Hugging Face paper fixture，至少包含：

- 正常多结果；
- 空结果；
- 缺失可选 published time；
- 重复 paper ID / URL；
- 超长 summary 截断；
- 非法 structured result；
- provider timeout / rate limit / unavailable；
- MCP Server unavailable / protocol error / schema mismatch / `isError=true`。

fixture 只能使用合成或固定公开样例，不包含真实用户查询、用户数据库内容或 secret。

## 6. 对外接口

### 6.1 Domain Port

```python
class PaperSearchPort(Protocol):
    def search_papers(
        self,
        query: str,
        limit: int,
    ) -> tuple[ExternalObservation, ...]: ...
```

约束：

- `query` trim 后非空并设长度上限；
- `limit` 为 `1..10`；
- 空 tuple 明确表示 no results；
- failure 使用 typed `ResearchPaperSearchError(code, retryable)`，不从异常文本推断；
- 返回值必须已经是 LifeOps-owned model，不含 SDK/MCP/provider 类型。

### 6.2 通用 MCP client contract

```python
McpServerConfig(
    server_id,
    command,
    args,
    cwd,
    timeout_seconds,
)

McpToolCallResult(
    server_id,
    tool_name,
    structured_content,
    is_error,
)

StdioMcpClient.call_tool_once(
    config,
    expected_tool,
    expected_input_schema,
    arguments,
) -> McpToolCallResult
```

`StdioMcpClient` 负责协议和 session，不知道 Research、Hugging Face、SQLite、Policy 或 Tool Gateway。`HuggingFaceMcpPaperSearchAdapter` 负责 MCP result → `ExternalObservation` 的业务转换。

### 6.3 MCP Server Tool

本地 Server 只暴露：

```text
search_papers(query: string, limit: integer 1..10)
```

Server structured result 固定包含一个 bounded `papers` 数组；每项只允许约定字段，例如 paper ID、title、authors、summary、published time 和 canonical Hugging Face paper URL。Server 不返回 raw `PaperInfo.__dict__`、response headers、token、exception 或完整 markdown/PDF。

### 6.4 模型可见 Research Tool surface

最终固定为 9 个：

| Tool | effect | 业务职责 |
|---|---|---|
| `research.build_brief` | `EXTERNAL_READ` | 聚合当前 HF source fetch → parse → rank → brief draft |
| `research.search_papers` | `EXTERNAL_READ` | 经 MCP 按关键词搜索 Hugging Face papers，产生 request-local observations |
| `research.search_knowledge` | `READ` | 搜索 Source/Note/Brief，或分页列出/筛选 Topic |
| `research.create_topic` | `WRITE` | 创建 Research Topic |
| `research.save_source` | `WRITE` | 按当前 observation ID 保存 briefing source 或 paper source |
| `research.save_brief` | `WRITE` | 按当前 draft ID 保存 Brief |
| `research.create_note` | `WRITE` | 创建 Note |
| `research.link_items` | `WRITE` | 在 Topic/Source/Note/Brief 之间创建 KnowledgeLink |
| `research.append_revision` | `WRITE` | 对已保存 item 追加不可覆盖的 Revision |

原子移除模型可见的：

- `research.fetch_source`
- `research.fetch_briefing_source`
- `research.parse_items`
- `research.rank_items`
- `research.build_brief_draft`

这些名字从 Registry、Research Skill workflow 和 frozen Tool surface 删除；对应 service 方法、pure processing functions 和聚焦单测保留。不得为了兼容把旧名和新名长期同时注册。

### 6.5 简化后的 Tool schema 规则

`research.build_brief`：

- 输入 `source_keys`、可选 `topic_filter`、bounded `limit`；
- 只允许 manifest 声明的 `hf_daily_papers` / `hf_blog`；
- 输出 draft ID、source observation IDs、item count 和 bounded draft projection；
- 不输出 raw HTML。

`research.search_papers`：

- 输入 `query` 与 bounded `limit`；
- 输出每篇 paper 的 observation ID、paper ID、title、bounded authors/summary、published time 和 canonical URL；
- 不接受任意 MCP server、tool name、endpoint 或 provider arguments。

`research.search_knowledge`：

- `query` 存在时搜索已保存知识；
- `query` 缺失时只允许 Topic listing/filtering；
- `item_kinds` 支持 `topic/source/note/brief`，继续使用稳定 `limit/offset`；
- 非法 mixed mode 明确失败，不静默改变查询语义。

三个新增业务 WRITE Tool 只把现有 service 方法安全暴露出来；每个都有独立 schema、confirmation 文案、结果和 evidence，不建立 `manage_research` 万能 Tool。

## 7. 失败模式

### 7.1 MCP / provider failure taxonomy

| error code | retryable | 含义 |
|---|---:|---|
| `mcp_server_unavailable` | true | Server 无法启动或意外退出 |
| `mcp_timeout` | true | initialize/list/call/close 超时 |
| `mcp_protocol_error` | false | MCP session 或协议响应失败 |
| `mcp_tool_schema_mismatch` | false | `tools/list` 与冻结 schema 不一致 |
| `mcp_tool_failed` | provider-dependent | `tools/call` 返回 `isError=true` |
| `mcp_result_invalid` | false | structured result 缺失、类型错误或越界 |
| `research_paper_no_results` | false | 合法查询无结果；Tool 可返回成功空结果或稳定 no-results 形状，不编造 |
| `research_paper_rate_limited` | true | Hugging Face 限流 |
| `research_paper_provider_unavailable` | true | Hugging Face timeout/5xx/网络不可用 |
| `research_paper_result_invalid` | false | provider 字段无法转换为安全 observation |

具体 provider exception、stderr、URL query string 和 response body 不进入 `ToolError.message`、event payload 或模型 observation。

### 7.2 业务失败

- paper observation 不属于当前 execution scope；
- observation 已过期或不存在；
- Source URL/content hash 重复；
- Topic 或 link target 不存在；
- self-link 或重复 link；
- Revision target 不存在；
- WRITE 没有匹配当前 action 的 confirmation；
- Brief source 尚未保存；
- `search_knowledge` mode/query/kinds/pagination 不一致。

全部 failure fail-closed；外部 READ 部分成功时只保留通过验证的 observations，并明确 partial/invalid count，不把缺失字段补写成事实。

### 7.3 进程与日志

- 正常或失败退出都必须关闭 session、streams 和子进程；Windows 测试要验证无遗留 Server process。
- Server stdout 保持协议纯净；普通日志只写 stderr，但 stderr 原文不透传给模型。
- 继续使用现有 `tool.call.requested/completed/failed` 和 Guardrail events；不为 MCP 修改 Executor event contract。
- 普通 application log 只记录 server ID、MCP tool name、阶段和安全 error code，不记录 query、arguments、papers 或异常正文。
- MCP/Provider failure 不改变主 Runtime 的授权事实，不写 SQLite，也不伪造 success evidence。

## 8. 测试和 Eval

### 8.1 单元测试

- `McpServerConfig`、normalized result 和 error invariant；
- official SDK one-shot stdio lifecycle；
- initialize → list → schema validation → call → close 顺序；
- timeout、Server exit、protocol error、schema mismatch、`isError`、invalid structured result；
- Hugging Face provider fixture normalization、去重、bounded authors/summary 和 canonical URL；
- `PaperSearchPort` contract 与 MCP result → `ExternalObservation` 转换；
- paper observation request-local 隔离；
- `build_brief` 聚合后继续保持现有 parse/dedupe/rank/draft 不变量；
- `search_knowledge` Topic mode 与 saved-item mode；
- create topic、link、revision 的 model/repository/service failure paths。

### 8.2 Tool / Gateway integration

- Registry 最终恰好注册 9 个 Research Tools；
- frozen Tool names/effects/risk/skill binding/schema hashes 更新；
- 旧 5 个 Tool 名明确不存在；
- `search_papers` / `build_brief` 经过 Research Skill candidate、Policy external-read effect 和 Gateway；
- 新增 WRITE Tool 每次都要求独立 `ConfirmedAction`，成功返回对应 `ExecutionEvidence`；
- 未确认、拒绝、stale confirmation、参数变化和错误 scope 均零写；
- `save_source` 可以保存当前 MCP paper observation，但不能从 arguments 伪造 paper metadata；
- catalog 外 MCP/Research Tool 调用继续被 `tool_not_allowed` 拒绝。

### 8.3 deterministic/offline compiled E2E

至少覆盖：

1. create topic → MCP fixture search → save source → link item；
2. search paper → 不确认 save → SQLite 零写；
3. MCP no results → 模型安全结束，不编造论文；
4. MCP timeout/unavailable → failed observation 回流，不写库；
5. MCP schema mismatch/invalid payload → fail-closed；
6. build brief 聚合 Tool → save sources → save brief；
7. search knowledge 列出 Topic 并搜索保存的 paper Source；
8. append revision 和重复/不存在 target；
9. Direct ReAct 与 confirmed PlanRun 都复用同一个现有 Executor/Gateway，不修改其实现。

offline E2E 必须启动真实本地 stdio fixture MCP Server，不能只 mock `PaperSearchPort`；Hugging Face provider 层使用固定 fixture，不访问网络。

### 8.4 真实 Hugging Face smoke

Stage 8 `go` 前必须至少运行一次：

```text
Runtime
-> existing Executor
-> ToolGateway
-> research.search_papers
-> one-shot stdio MCP Client
-> local MCP Server
-> public Hugging Face HfApi
-> bounded ToolObservation
```

smoke 使用 deterministic model client 强制选择已授权 Tool，避免把 LLM provider 可用性混入 MCP gate；不写真实用户数据库，可使用临时 SQLite。验证至少一个公开查询返回合法 paper observation，Server/session 正常关闭，日志中没有 payload/secret。

若 live provider 临时不可用，记录为 provider failure 并重试验证；在真实成功证据出现前，代码可以标记 implementation complete，但 Stage 8 不得宣布 `go`。

### 8.5 最终验证

- 先运行 MCP/Research 聚焦测试；
- 再运行 Tool/Gateway/Skill contract tests；
- 再运行 Executor/Planner compiled E2E，确认未修改控制骨架；
- 因 Tool surface 和 bootstrap 影响较广，最后运行统一离线 `unittest discover`、`compileall` 和 `git diff --check`；
- 真实 smoke 与离线 regression 分开记录，不能用网络成功代替 deterministic tests。

## 9. 文档更新

计划确认时同步：

- `README.md`：当前入口改为 Stage 8 Research MCP plan；
- `plans/RUNTIME_REFACTOR_PLAN.md`：正式重排 Stage 8-10，删除 Calendar MCP V1 阶段；
- `plans/modules/README.md`：登记本计划；
- `plans/modules/RESEARCH_KNOWLEDGE_DOMAIN_PLAN.md`：标记 Stage 8 增量计划已确认但尚未实现；
- `plans/modules/TRAVEL_DOMAIN_PLAN.md`：Calendar MCP 改为未来可选 Adapter；
- `docs/PROGRESS_LOG.md`：只记录计划确认、路线图调整和尚未实现事实；
- `docs/ARCHITECTURE.md`：把 Context / Memory 的未来接入编号改为 Stage 9，不提前把本计划写成已实现架构；
- `docs/MIGRATION_INDEX.md`：V0 MCP 对照目标改为通用 MCP client + Research MCP；
- `docs/AGENT_LEARNING_LINKS.md`：增加已确认的 MCP stdio、discovery/call、Adapter boundary 与 Hugging Face paper API 官方资料。

实现过程中/完成后同步：

- `docs/ARCHITECTURE.md`：补充实际 MCP client/server/adapter 依赖方向和 9 Tool current surface；
- `docs/RUNTIME_CONCEPTS.md`：补充 MCP 与 Domain Port、Tool Gateway、request-local observation、外部 provider failure 的本项目解释和面试讲法；
- `docs/PROGRESS_LOG.md`：逐步记录实际完成和验证事实；
- 本计划：逐项标记步骤状态和最终 gate；
- `README.md` / 总计划：只在全部关闭条件成立后把 Stage 8 标为完成，并把下一入口切到 Stage 9 Context / Memory。

本阶段学习范围只包括：

- stdio MCP client/server 生命周期；
- initialize、`tools/list`、schema validation、`tools/call` 和 structured result；
- MCP Adapter 到 LifeOps Domain model 的转换和安全边界；
- Hugging Face paper public read、no results、timeout、rate limit、invalid result 和 provenance。

不收录或实现远程 transport、OAuth、MCP authorization、Resources、Prompts、Sampling 或 Roots。

## 10. 实施步骤

1. **[已完成] 确认范围与冻结设计。** 已确认 Research 主线、Hugging Face provider、短生命周期 stdio MCP、零 schema migration、9 个 Tool、Stage 8-10 重排、双层 test gate 和学习范围；未修改生产代码。
2. **[已完成] 增加并锁定依赖与最小 MCP 公共类型。** 已加入官方 `mcp` / `huggingface_hub` 依赖；已定义 config、normalized result、typed errors 和依赖方向测试，未复制 SDK types 到 Domain。
3. **[已完成] 实现 one-shot stdio MCP client。** 已完成 initialize、`tools/list`、schema validation、`tools/call`、structured result、timeout 和可靠 close；使用官方 SDK，未复用 V0 手写协议。
4. **[已完成] 实现 Hugging Face Paper MCP Server。** 只暴露 MCP `search_papers`；已加入 provider façade、public `token=False` 读取、bounded normalization、fixture mode 和真实 stdio 协议纯净性验证。
5. **[已完成] 实现 Research PaperSearchPort / MCP Adapter。** 已把 validated MCP papers 转换为现有 `ExternalObservation`，并明确 no-results、去重、invalid result/failure、hash、URL 和 provenance；混合合法/非法 provider item 只保留合法 observations 并报告 `invalid_count`，全部非法 fail-closed；Domain 不依赖 SDK 类型。
6. **[已完成] 接入 `research.search_papers` 与现有保存链。** 已注册 EXTERNAL_READ Tool，`save_source` 只按当前 paper observation ID 保存；confirmation、evidence、scope 和读阶段零写测试通过。
7. **[已完成] 收敛 briefing Tool。** 已新增 `research.build_brief`，内部复用现有 fetch/parse/dedupe/rank/build；已原子移除旧五个模型可见 Tool，保留底层机制和单测。
8. **[已完成] 补齐 Topic / Link / Revision Tool。** 已注册 `create_topic`、`link_items`、`append_revision`，并扩展 `search_knowledge` Topic mode；全部经过既有 WRITE confirmation/evidence 或 READ boundary。
9. **[已完成] 冻结最终 9 Tool surface 与 Skill workflow。** 已更新 schema、description、effect/risk/skill binding、contract hashes 和 Research Skill instructions；依赖方向测试证明 Research/MCP 实现不导入 Planner/Executor。
10. **[已完成] 关闭 failure / process / observability 边界。** 已覆盖 provider/MCP/business failure taxonomy、Windows 正常/超时子进程关闭、stdout 协议纯净、日志最小化和真实 MCP provider failure 零写。
11. **[已完成] 运行聚焦单元与 integration tests。** 已依次验证 MCP、provider、Port/Adapter、Research service/repository、Tool/Gateway、confirmation/evidence 和 compatibility contracts；122 个测试通过。
12. **[已完成] 运行 deterministic/offline compiled E2E。** 已使用真实 stdio fixture MCP Server 跑完整 search/save/link/revision/topic read、brief、no-results、failure、zero-write、Direct/Plan 场景；27 个 E2E 测试通过。
13. **[已完成] 运行真实 Hugging Face smoke。** 已使用临时数据库和 deterministic model client 验证 Runtime → Executor → Gateway → one-shot stdio MCP → public Hugging Face paper search；live smoke 通过，并保留 provider failure / LifeOps contract failure 的显式分类。
14. **[已完成] 文档与 Stage gate 收口。** 已更新 Architecture、Progress、Concepts、README、总计划和本计划；最终统一离线 regression 执行 `414` 个测试，`412` 通过、`2` 个显式 live gate 跳过，`compileall` 与 `git diff --check` 通过。真实 LLM happy path 以一次 Tool 请求、零 Tool failure、一次成功、canonical paper links 和 SQLite 零写通过，因此 Stage 8 为 `go`。

## 完成标准

- 模型可见 Research Tool 恰好为冻结的 9 个，旧 5 个 Tool 名不再注册。
- `research.search_papers` 真实经过官方 MCP SDK、本地 stdio Server 和 Hugging Face public API。
- MCP result 只经 Adapter 转换为现有 `ExternalObservation`；Domain/Planner/Executor 不依赖 MCP/provider types。
- paper search 默认零写；确认后的 `save_source` / `link_items` 才形成业务事实和 evidence。
- 不新增 SQLite table/column/migration，不修改 Planner/Executor 生产代码。
- offline MCP fixture E2E、Research/Tool/Runtime affected suites 和统一离线 regression 全部通过。
- 真实 Hugging Face MCP smoke 有成功证据，且 session/进程正常关闭、日志无 payload/secret。
- 文档明确 Stage 8 已完成事实后，才将 Stage 9 Context / Memory gate 改为 `go`。

最终 gate：`go`。上述完成标准全部成立；Stage 9 Context / Memory 可以开始模块计划设计，但本阶段没有提前实现其生产能力。
