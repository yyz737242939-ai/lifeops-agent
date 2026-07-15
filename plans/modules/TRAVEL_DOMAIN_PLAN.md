# Travel Domain 最终设计说明

文档状态：阶段 5 实现完成后的稳定设计；真实 booking、HTTP/MCP provider 与上层 Executor/Planner 不属于本 Domain。

本计划遵守 `plans/DOMAIN_CONTRACT_STANDARD.md`。Travel planning/context/memory 的默认 scope ID 都是 Trip ID；具体 snapshot/candidate 类型由 Travel 拥有，但方法名和语义不另行定义。

## 当前实现状态

已完成第一个 Itinerary 纵向切片：

- typed external candidates、`ItineraryDraft`、`Itinerary`、`ItineraryItem` 与 `TravelDecision`；
- `travel_itineraries` migration、repository 和 request-local `TravelService`；
- Calendar / Weather / Transport / Lodging / Place 五个细分 EXTERNAL_READ Tools；原 `travel.search_options` 已从 Registry 删除；
- candidate 带 `observed_at`、`expires_at` 和 fixture provenance，并明确不代表 booking；
- WRITE 只接受当前 service 已生成的 draft ID 与显式 idempotency key，经过 Travel Skill candidate、Policy write effect、Gateway confirmation、transaction 和 `ExecutionEvidence`。

Travel Domain 阶段 5 完整初版已关闭：领域模型、schema v8、Trip / TravelConstraint repository/service/Tools、五个细分 external Port contracts、deterministic fixture adapters、EXTERNAL_READ Tools、request-local candidate compare / itinerary draft、draft-based Itinerary / ItineraryItem / TravelDecision WRITE、通用 KnowledgeReference、三个共享只读接口和小型历史 seed 均已完成。稳定化补充了保存前 expiry 复验、可注入 clock、跨 execution scope 隔离和过期后的幂等重试；当前测试数字以稳定化计划和推进日志为准。

## 1. 目标

本模块建立 planning-only 的旅行领域：收集约束、查询 fixture-backed 外部候选、比较方案、生成 itinerary draft，并在用户确认后保存 Trip / Itinerary 业务事实。Domain 只从业务角度组织 Travel models、service、repository、ports 和 tools，不拥有独立 Planner / Executor；它可以与 Research tools 出现在同一个通用 PlanRun 中。

### 1.1 目标业务能力

阶段 5 完整初版完成后，Travel 应能支持以下业务流程：

- 创建、查看、修改和归档 Trip；
- 保存目的地、日期、预算、同行人数、交通/住宿偏好、证件与其他旅行限制；
- 查询日历空闲时间、天气、交通、住宿和地点候选；
- 比较候选的价格、时间、有效期和约束匹配情况；
- 生成按天组织的 itinerary draft，并根据用户反馈重新比较或调整；
- 用户确认后保存 itinerary、itinerary items 和关键 TravelDecision；
- 搜索历史 Trip / Itinerary，并为相似旅行提供只读候选；
- 引用 Research 中已保存的目的地或会议资料，但不复制正文；
- 始终区分 external candidate、itinerary draft、已保存行程和真实 booking；
- 不执行订票、订房、付款、取消或消息发送。

## 2. 当前 V0 参考

V0 没有可直接迁移的完整 Travel Domain。只参考：

- source/helper 白名单和 ephemeral reference；
- Tool authorization、action evidence 和 failure observation；
- Task/Plan 的长期事实与临时执行策略区分。

Travel 模型、repository、service、ports 和 fixtures 在当前 runtime 中重新设计，不把 V0 todo/activity store 改名复用。

## 3. 当前范围

### 3.1 阶段 5 完整范围

- `Trip`、`TravelConstraint`、五类 typed external candidate、`TravelComparison`、`ItineraryDraft`、`Itinerary`、`ItineraryItem`、`TravelDecision`、`ExternalObservationRef`。
- 创建、查询、更新、归档 Trip，并保存日期、目的地、预算、同行人数、偏好和限制。
- fixture-backed Calendar、Weather、Transport、Lodging、Place external-read Ports；Domain service 只依赖 typed Port，不直接依赖 MCP/HTTP client。
- 每类外部查询返回 typed candidate / observation，统一携带 provider、observed/quoted time、expires_at、provenance 和 request-local ID。
- 候选查询、结构化比较、约束匹配和部分失败表达。
- itinerary draft 是 request-local 执行产物；用户确认后才保存 itinerary/version/decision。
- 历史 Trip 可归档和只读查询，为阶段 9 Context/Memory 测试提供材料。
- Travel 可用通用 `KnowledgeReference` 引用 Research Domain 保存的资料，只存 ID，不复制正文。
- 为阶段 6 Executor 提供 Tools；为阶段 7 Planner 实现共享 `DomainPlanningReadModel[TravelPlanningSnapshot]`；为阶段 9 Context / Memory 实现共享 candidate provider 接口。
- Tool contract 必须提供稳定、结构化、适合 ReAct 继续判断的 Observation，以及适合 Planner/DAG 判断依赖和部分失败的 typed output；Domain 不记录或解释模型 Thought。
- 正常、无结果、timeout、rate limit、过期价格、冲突和部分失败 fixtures。

### 3.2 阶段 5 不做

- 不真实订票、订房、付款、取消订单或发送消息。
- 不写 Calendar。
- 不承诺实时价格、库存或签证/安全结论。
- 不在阶段 5 接真实天气、交通、住宿 API。
- 不把旅行偏好自动写为 Memory。
- 不让 Travel service 直接依赖 MCP/HTTP client。
- 不实现阶段 6 ReAct loop、阶段 7 Planner、阶段 9 Context/Memory consumer 或阶段 10 Recovery；Domain 只提供稳定 Tool、read model 和 provider contract。

## 4. Runtime 与领域边界

```text
Travel Tool
    ↓ ToolGateway
TravelPlanningService
    ↓ external Port
Fixture Adapter（阶段 5）
    ↓
ExternalObservation（临时、带 fetched_at/expires_at/provenance）
    ↓
Candidate / ItineraryDraft（临时）
    ↓ 用户确认 + Policy allowed tool
Trip / Itinerary / Decision（业务事实）
```

### 4.1 外部 Port

保持小而有类型，不建立万能 provider：

```python
CalendarAvailabilityPort
WeatherInformationPort
TransportSearchPort
LodgingSearchPort
PlaceSearchPort
```

阶段 5 实现五个 fixture adapters；旧聚合 `TravelOptionPort` 已在 draft-based 保存完成后删除。Calendar fixture 保持当前 V1；未来若实现 `CalendarMcpAdapter` 或真实 HTTP adapter，它们只实现同一个 Calendar Port，不修改 Travel Domain。

MCP 只是 Port 的一种 adapter 实现，不是 Travel Domain 的依赖。Calendar MCP 已从当前 V1 施工阶段移除；未来地图、地点、天气、交通、住宿或 Calendar 如果存在合适 MCP server，也必须实现现有 typed Port，并把 MCP result 转换成 LifeOps-owned model 后再进入 Tool Gateway。不能把 MCP tool schema、server 名称或 provider SDK 类型泄漏到 Domain model/service。

### 4.2 未来适配接口

- Context 通过 `DomainContextProvider[TravelContextCandidate]` 获取当前 Trip、约束、选中候选和有限历史摘要。
- Memory 通过 `DomainMemoryCandidateProvider[TravelPreferenceCandidate]` 获取候选偏好；只有阶段 9 明确授权后才能成为 Memory。
- Planner 通过 `DomainPlanningReadModel[TravelPlanningSnapshot]` 获取规划所需事实，不读取 repository internals。
- Executor 通过 ToolGateway 调外部 READ 或 Domain WRITE tools。
- Travel 不定义 `TravelPlanRun` / `TravelExecutor`；通用 Planner 与 Tool 的匹配方式留到 Planner 模块施工时设计。
- ReAct Executor 可在同一个 run 中逐步调用约束读取、外部搜索、比较和 draft tools；每步只消费 typed ToolResult / Observation，不直接读取 service internals。
- Plan-and-Execute 可把跨 Domain 目标拆成 Research / Travel steps；`TravelPlanningSnapshot` 只提供 Trip 事实、缺失约束、候选覆盖、当前 draft/version 和未解决 decision，不生成 PlanStep。
- Recovery 使用 event/evidence 解释做到哪一步，不自动重放搜索或保存。
- 未来 Calendar MCP 只能替换 fixture adapter，不改变 service；当前 V1 不实施该 Adapter。
- DAG 可表达 calendar/weather/transport/lodging/place 独立读取，汇合后执行 compare → draft；每个节点必须有稳定 input/output、失败和 expiry 语义。阶段 5 不实现 scheduler，也不把 DAG node 写进 Domain。
- Eval 使用固定 fixtures，真实网络只允许可选 smoke test。

### 4.3 ReAct / Plan-and-Execute / DAG 接入条件

Travel 完整初版必须在不实现上层执行器的前提下满足：

- Tool 足够细粒度，使 ReAct 能根据一次 Observation 决定下一次 Action；
- request-local candidate / draft 使用稳定 ID，模型不能通过参数伪造 provider、价格、availability 或 provenance；
- ToolResult 明确 success、no results、expired、conflict、partial failure 和 retryable provider failure；
- READ Tool 无业务写入副作用；WRITE Tool 可重试时必须有幂等语义；
- Planner 只读快照能指出已知事实、缺失约束、可用候选和待决策项；
- 可并行 external reads 之间不共享可变状态，汇合后的 compare/draft 只消费显式输入 ID；
- 所有 WRITE 仍逐 action / step 经过 Policy、confirmation、Guardrail、transaction 和 evidence。

## 5. 数据模型 / 存储

阶段 5 目标 SQLite 表：

- `trips`
- `travel_constraints`
- `travel_itineraries`
- `travel_itinerary_items`
- `travel_decisions`
- `travel_knowledge_refs`

每张表仍必须在对应模型/service 实际施工时新增 migration 和 repository test，不能只因列在计划中就视为完成。

外部 observation 和未确认 candidate 默认不进入长期业务表。若为解释决策需要保存 snapshot，只保存紧凑 provider metadata、quoted_at、expires_at、source reference 和用户选中值，不保存全部原始响应。

`travel_knowledge_refs` 保存通用稳定引用，例如 `domain="research" + item_kind + item_id`。Travel 不直接 import 或查询 Research repository；引用存在性和只读摘要由未来通用 `KnowledgeReferenceResolver` contract 负责，解析失败不能阻止读取已经保存的 Trip 主体。

fixture：

```text
tests/fixtures/travel/
  calendar_available.json
  weather_tokyo_october.json
  transport_shanghai_tokyo.json
  lodging_tokyo.json
  places_tokyo.json
  provider_failures.json
```

## 6. 对外接口

Domain service：

```python
create_trip(...)
update_trip_constraints(...)
get_trip(...)
list_trips(...)
archive_trip(...)
search_transport(...)
search_lodging(...)
search_places(...)
check_calendar_availability(...)
get_weather(...)
compare_candidates(...)
build_itinerary_draft(...)
save_confirmed_itinerary(option_or_draft_id)
record_travel_decision(...)
get_planning_snapshot(trip_id)
query_context_candidates(query, budget_hint, scope_id=trip_id)
query_memory_candidates(query, limit, scope_id=trip_id)
```

Tools：

- `travel.create_trip`
- `travel.get_trip`
- `travel.list_trips`
- `travel.update_trip_constraints`
- `travel.check_calendar_availability`
- `travel.get_weather`
- `travel.search_transport`
- `travel.search_lodging`
- `travel.search_places`
- `travel.compare_options`
- `travel.build_itinerary_draft`
- `travel.save_itinerary`
- `travel.archive_trip`

所有 external lookup 是 EXTERNAL_READ；本地查询/比较/draft 是 READ 或 request-local 处理；创建、更新、保存、归档是 WRITE。所有 Tool 先由 Travel Skill candidate 与 Policy effect 求交，再经过 Guardrail 和 Gateway。

`travel.search_options`、对应 service 方法和旧聚合 `TravelOptionPort` 均已删除；ReAct 只看到五个细分 external-read Tools。`travel.save_itinerary` 只接受当前 request-local `draft_id` 与显式 `idempotency_key`。

## 7. 失败模式

- 日期、预算、人数或目的地不完整；
- Calendar 冲突；
- provider timeout/rate limit/no results/partial failure；
- schema 或单位不一致；
- 日期、时区、货币或人数口径不一致；
- 报价已过期；
- 外部内容 prompt injection；
- 把 lookup 误报为 booking；
- itinerary draft 未确认即保存；
- 多次保存产生重复 itinerary；
- ReAct retry 或 Planner resume 重复创建 Trip / Itinerary；
- 并行外部查询部分成功时丢失成功候选，或把 partial failure 误报为全量成功；
- KnowledgeReference 指向不存在/归档资料；
- 历史 Trip 被误当作当前偏好事实。

## 8. 测试和 Eval

- Trip/constraint/itinerary 状态、version 和 archive；
- 每个 Port 的 fixture contract test；
- 正常、无结果、timeout、rate-limit、过期和部分失败；
- READ/WRITE allowed effects、Skill candidates 和 confirmation；
- itinerary draft 与保存事实分离；
- Tool 参数不能伪造 provenance 或 booking 事实；
- 幂等保存和 transaction rollback；
- ReAct fake loop contract：search → observe → compare → draft，不提前实现 Executor；
- Plan-and-Execute fake consumer：读取 missing constraints / candidate coverage / pending decisions，不提前实现 Planner；
- DAG contract：五类 external reads 可独立执行，compare 只在显式依赖满足后消费结果；
- 历史 Trip/KnowledgeReference 查询；
- 大 fixture 下 Context candidate 数量和 budget hint；
- Executor / Planner / Context / Memory contract tests 使用 fake consumer，不提前实现消费者；
- Graph 到真实 handler 的端到端路径由阶段 5 共用 E2E 测试覆盖。

## 9. 文档更新

- 完成后更新 `docs/ARCHITECTURE.md`、`docs/PROGRESS_LOG.md`、`docs/RUNTIME_CONCEPTS.md`。
- 阶段 5 学习链接只覆盖 Port/adapter、Tool safety 和 fixture contract；当前 Stage 8 MCP 学习集中在 Research / Hugging Face，Travel 不新增 Calendar MCP 链接。
- planning-only 和外部数据边界维护在本模块计划与 `plans/RUNTIME_REFACTOR_PLAN.md`，不新增 decisions / ADR 文档。

## 10. 实施步骤

1. [已完成] 定义 Travel 模型、状态转换和业务不变量；已包含 `Trip`、`TravelConstraint`、`ExternalObservationRef`、typed candidates、`TravelComparison`、`ItineraryDraft`、`Itinerary`、`ItineraryItem` 和 `TravelDecision`，并通过独立类型与 provenance 引用明确 candidate → draft → saved itinerary 不能逆向冒充 booking。
2. [已完成] 增加 schema v6 migration、repository 和 service；建立 Travel 长期表基础形状，完成 Trip / TravelConstraint persistence、version conflict、archive 和 transaction rollback；Itinerary detail 后续由步骤 8 的 schema v7 扩展。
3. [已完成] 打通 Trip / TravelConstraint 的 create/get/list/update/archive service 与 READ/WRITE Tools；所有 Tool 绑定 Travel Skill，READ 无写入副作用，WRITE 经过 Policy effect、Gateway confirmation、transaction 和 `ExecutionEvidence`。
4. [已完成] 定义 Calendar、Weather、Transport、Lodging、Place 五个 typed Ports 与各自 typed query/candidate；统一 `ExternalObservationRef`、`ExternalLookupResult` 和 `ProviderFailure` contract，明确 success/no-results/partial-failure/failed、retryable、expiry 与 provenance；旧聚合 `TravelOptionPort` 已删除。
5. [已完成] 创建 Calendar、Weather、Transport、Lodging、Place 五类 schema-versioned fixtures 与 deterministic adapters；每个 adapter 只接受显式声明的 query，并统一覆盖 success/no-results/timeout/rate-limit/expired/partial-failure，候选稳定引用 fixture observation/provenance。
6. [已完成] 分别接入 `travel.check_calendar_availability`、`travel.get_weather`、`travel.search_transport`、`travel.search_lodging`、`travel.search_places` 五类 EXTERNAL_READ Tools；Tool 输出保留 typed status、observation、candidate 与 provider failure，结果保持 request-local 且不写 SQLite；聚合 `travel.search_options` 已从 Registry 删除，相关兼容代码随后在步骤 8 删除。
7. [已完成] 实现 request-local external result 汇合、destination/budget 约束匹配、结构化 `TravelComparison` / `CandidateAssessment` 和 `ItineraryDraft` version；接入 `travel.compare_options`、`travel.build_itinerary_draft` READ Tools，compare/draft 只接受当前 service 已缓存的 observation/candidate ID，并拒绝 provenance/价格防伪与 conflicting/expired candidate。
8. [已完成] `travel.save_itinerary` 已迁移为 draft-based WRITE：只接受当前 request-local `draft_id` 与显式 idempotency key，在一次 transaction 中保存 Itinerary、ItineraryItem 和 itinerary TravelDecision；相同 key + draft 返回同一结果，不同 draft 复用 key fail-closed，并保持逐 WRITE confirmation 与 `ExecutionEvidence`。旧 `CandidateOption` / `TravelOptionPort` / `search_options()` 兼容路径已删除。
9. [已完成] 增加通用 `KnowledgeReference` / `KnowledgeReferenceResolver` / structured resolution contract；schema v8 为 `travel_knowledge_refs` 增加稳定 reference ID，Travel 只保存 domain/item kind/item ID，不复制正文且不依赖 Research repository；resolver unavailable 不阻止读取 Trip 主体。
10. [已完成] 增加实现三个共享 Protocol 的 `TravelReadService`、`TravelPlanningSnapshot` / `TravelContextCandidate` / `TravelPreferenceCandidate` 与小型 schema-versioned 历史 seed；Planner/DAG 只读取长期事实覆盖与缺失约束，Context 按 Trip scope/budget 返回 provenance candidates，Memory 只返回显式保存的 transport/lodging/other constraints，不把历史 itinerary 自动推断为偏好。
11. [已完成] compiled Graph 已调用真实 `travel.search_places` handler 并返回 typed observation/candidate，external-read Policy 下 catalog 外 `travel.save_itinerary` 被 Guardrail 以 `tool_not_allowed` 拒绝且 SQLite 零写入。历史 `33/216` 仅是完成当时快照；稳定化后的统一结果见 `STAGE5_STABILIZATION_PLAN.md`。
