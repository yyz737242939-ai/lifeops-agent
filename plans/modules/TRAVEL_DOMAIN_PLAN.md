# Travel Domain 模块计划

## 1. 目标

本模块建立 planning-only 的旅行领域：收集约束、查询 fixture-backed 外部候选、比较方案、生成 itinerary draft，并在用户确认后保存 Trip / Itinerary 业务事实。Domain 只从业务角度组织 Travel models、service、repository、ports 和 tools，不拥有独立 Planner / Executor；它可以与 Research tools 出现在同一个通用 PlanRun 中。

## 2. 当前 V0 参考

V0 没有可直接迁移的完整 Travel Domain。只参考：

- source/helper 白名单和 ephemeral reference；
- Tool authorization、action evidence 和 failure observation；
- Task/Plan 的长期事实与临时执行策略区分。

Travel 模型、repository、service、ports 和 fixtures 在当前 runtime 中重新设计，不把 V0 todo/activity store 改名复用。

## 3. 当前范围

### 3.1 初版做

- `Trip`、`TravelConstraint`、`CandidateOption`、`Itinerary`、`ItineraryItem`、`TravelDecision`、`ExternalObservationRef`。
- 创建、查询、更新、归档 Trip。
- 保存日期、目的地、预算、同行人数、偏好和限制。
- fixture-backed Calendar、Weather、Transport、Lodging、Place external-read ports。
- 候选查询和结构化比较。
- itinerary draft 是临时执行产物；用户确认后才保存 itinerary/version/decision。
- 历史 Trip 可归档和只读查询，为长期 Context/Memory 测试提供材料。
- Travel 可用通用 `KnowledgeReference` 引用 Research Domain 保存的攻略/资料，只存 ID，不复制正文。
- 正常、无结果、timeout、rate limit、过期价格、冲突和部分失败 fixtures。

### 3.2 初版不做

- 不真实订票、订房、付款、取消订单或发送消息。
- 不写 Calendar。
- 不承诺实时价格、库存或签证/安全结论。
- 不在阶段 5 接真实天气、交通、住宿 API。
- 不把旅行偏好自动写为 Memory。
- 不让 Travel service 直接依赖 MCP/HTTP client。

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

阶段 5 只实现 fixture adapters。阶段 8 `CalendarMcpAdapter` 实现同一个 Calendar Port；以后真实 HTTP adapters 独立新增，不修改 Travel Domain。

### 4.2 未来适配接口

- Context 通过 `TravelContextProvider` 获取当前 Trip、约束、选中候选和有限历史摘要。
- Memory 通过 `TravelPreferenceCandidateProvider` 获取候选偏好；只有阶段 6 明确授权后才能成为 Memory。
- Planner 通过 `TravelPlanningReadModel` 获取规划所需事实，不读取 repository internals。
- Executor 通过 ToolGateway 调外部 READ 或 Domain WRITE tools。
- Travel 不定义 `TravelPlanRun` / `TravelExecutor`；通用 Planner 与 Tool 的匹配方式留到 Planner 模块施工时设计。
- Recovery 使用 event/evidence 解释做到哪一步，不自动重放搜索或保存。
- Calendar MCP 只替换 fixture adapter，不改变 service。
- DAG 可表达 calendar/weather/transport/lodging 并行读取与后续比较；阶段 5 不实现 scheduler。
- Eval 使用固定 fixtures，真实网络只允许可选 smoke test。

## 5. 数据模型 / 存储

候选 SQLite 表：

- `trips`
- `travel_constraints`
- `travel_itineraries`
- `travel_itinerary_items`
- `travel_decisions`
- `travel_knowledge_refs`

外部 observation 和未确认 candidate 默认不进入长期业务表。若为解释决策需要保存 snapshot，只保存紧凑 provider metadata、quoted_at、expires_at、source reference 和用户选中值，不保存全部原始响应。

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
compare_candidates(...)
build_itinerary_draft(...)
save_confirmed_itinerary(...)
record_travel_decision(...)
get_planning_read_model(trip_id)
query_context_candidates(trip_id, budget_hint)
```

Tools：

- `create_trip`
- `get_trip`
- `search_travel_options`
- `check_calendar_availability`
- `get_travel_weather`
- `compare_travel_options`
- `build_itinerary_draft`
- `save_itinerary`
- `archive_trip`

所有 external lookup 是 EXTERNAL_READ；创建/更新/保存/归档是 WRITE。

## 7. 失败模式

- 日期、预算、人数或目的地不完整；
- Calendar 冲突；
- provider timeout/rate limit/no results/partial failure；
- schema 或单位不一致；
- 报价已过期；
- 外部内容 prompt injection；
- 把 lookup 误报为 booking；
- itinerary draft 未确认即保存；
- 多次保存产生重复 itinerary；
- KnowledgeReference 指向不存在/归档资料；
- 历史 Trip 被误当作当前偏好事实。

## 8. 测试和 Eval

- Trip/constraint/itinerary 状态与 version；
- 每个 Port 的 fixture contract test；
- 正常、无结果、timeout、rate-limit、过期和部分失败；
- READ/WRITE allowed tools 和 confirmation；
- itinerary draft 与保存事实分离；
- 幂等保存和 transaction rollback；
- 历史 Trip/KnowledgeReference 查询；
- 大 fixture 下 Context candidate 数量和 budget hint；
- Plan-and-Execute contract：collect constraints → external reads → compare → draft → confirm → save；
- Recovery/DAG/Eval 使用 fake consumer 验证接口，不提前实现后续模块。

## 9. 文档更新

- 完成后更新 `docs/ARCHITECTURE.md`、`docs/PROGRESS_LOG.md`、`docs/RUNTIME_CONCEPTS.md`。
- 阶段 5 学习链接只覆盖 Port/adapter、Tool safety 和 fixture contract；Calendar MCP 链接等阶段 8 再补。
- planning-only 和外部数据边界维护在本模块计划与 `plans/RUNTIME_REFACTOR_PLAN.md`，不新增 decisions / ADR 文档。

## 10. 实施步骤

1. 定义 Travel 模型、状态转换和不变量。
2. 增加 migration、repository 和 service。
3. 定义五个 external Ports 和统一 provenance 字段。
4. 创建正常/失败 fixtures 与 adapters。
5. 打通 Trip/constraint READ/WRITE tools。
6. 打通 external READ、candidate compare 和 itinerary draft。
7. 接入确认后的 itinerary 保存和 evidence。
8. 增加 Research KnowledgeReference。
9. 增加 future consumer contract tests 和长期 seed。
10. 同步文档并验证完整场景。
