# LifeOps Domain Contract Standard

## 1. 目的

本标准约束 Research、Travel 和未来业务 Domain 的共同接入形状，使通用 ReAct Executor、Plan-and-Execute Planner、Context、Memory、Recovery、MCP adapters 和 DAG Scheduler 面向稳定 contract，而不为每个 Domain 建立专用执行循环。

本标准统一接口语义和命名，不统一业务字段，不要求万能 Domain 基类。

## 2. 统一分层

每个 Domain 默认使用：

```text
models.py       业务事实与 request-local typed models
ports.py        外部能力 Protocol
adapters        fixture / HTTP / MCP 等 Port 实现
repository.py   SQLite 业务事实读写
service.py      业务规则与 request-local workflow state
tools.py        ToolDefinition + handler
read_models.py  Planner / Context / Memory 只读实现
```

Domain 不依赖 LangGraph、Planner、Executor、DAG、具体 MCP server 或 provider SDK。

## 3. 统一状态边界

- 长期业务事实进入 Domain repository。
- external observation、candidate、draft 和 comparison 默认 request-local，使用稳定 ID。
- 模型只能提交 request-local ID，不能通过 Tool 参数伪造 provenance、价格、availability、content hash 或其他外部事实。
- Planner output、PlanStep、checkpoint、Context candidate 和 Memory candidate 都不是 Domain 事实。
- WRITE 必须来自 Policy 允许、当前确认、成功 ToolResult 和 ExecutionEvidence。

## 4. 统一外部 Port / Adapter 规范

- Protocol 命名 `<Capability>Port`。
- Adapter 命名 `<Provider><Capability>Adapter` 或 `Fixture<Capability>Adapter`。
- Domain service 只依赖 Port，不依赖 MCP/HTTP client。
- MCP 只是 adapter channel；MCP result 必须转换为 LifeOps-owned typed model。
- External observation/candidate 至少携带 request-local ID、provider/source reference、observed/quoted time、expires_at（适用时）和 provenance。
- provider failure 必须区分 no results、timeout、rate limit、expired、partial failure 和不可重试失败。

## 5. 统一 Tool 规范

- 名称使用 `<domain>.<verb>_<object>`。
- Tool 必须足够细粒度，避免聚合 Tool 与细分 Tool 长期重叠。
- EXTERNAL_READ 只访问外部系统；READ 只做本地读取或 request-local 处理；WRITE 创建或修改长期事实或外部副作用。
- Tool input/output 使用受支持的严格 JSON Schema，默认 `additionalProperties=false`。
- ToolResult 必须结构化表达 status、output 或 ToolError；WRITE success 必须携带 ExecutionEvidence。
- 所有 Tool 经过 selected Skill candidate、Policy effect、AllowedToolSet、pre/post Guardrails 和 ToolGateway。
- WRITE retry/resume 必须有幂等语义；confirmation 绑定 run、Tool call、Tool 名、canonical 参数摘要和有效期，交互层只能传递该结构化授权，不能用自由 metadata 代替。

## 6. 统一只读接口

所有 Domain 直接实现 `app/domains/contracts.py` 中的共享 Protocol：

```python
DomainPlanningReadModel.get_planning_snapshot(scope_id)

DomainContextProvider.query_context_candidates(
    query,
    budget_hint,
    scope_id=None,
)

DomainMemoryCandidateProvider.query_memory_candidates(
    query,
    limit,
    scope_id=None,
)
```

- `scope_id` 是 Domain 自己的稳定业务 scope，例如 Research Topic ID 或 Travel Trip ID。
- 不支持 scoped query 的 Domain 必须明确拒绝，不能静默忽略。
- Research 和 Travel 当前都支持 scoped query：Research 使用 Topic ID，Travel 使用 Trip ID；未知 scope 必须失败，不能退化为全局查询。
- Planning snapshot 只返回已知事实、覆盖情况、缺失信息和待决策项，不生成 PlanStep。
- Context candidate 必须携带 provenance 和 budget estimate，不组装最终 prompt。
- Memory candidate 只是候选，不自动写 Memory。

## 7. ReAct / Plan-and-Execute / DAG 接入标准

- ReAct：细粒度 Tool 输出足够支持 observe → next action，Domain 不保存 Thought。
- Plan-and-Execute：Planner 只消费 planning snapshot 和 Tool contract，不读取 repository internals。
- DAG：可并行 READ 不共享隐式可变状态；汇合节点只消费显式 result/candidate IDs；WRITE 保持独立确认节点。
- partial success 保留成功 Observation / evidence，不做跨 Domain 全局回滚。
- typed Port 的 `success`、`no_results`、`partial_failure`、`failed` 必须使用互斥结果形状；retryable 属于结构化 provider failure，不从异常文本推断。只有两个以上 Domain 出现相同候选/失败不变量时才提取共享 model，当前 Port model 继续由各 Domain 拥有。
- Recovery 不自动重放 external lookup 或 WRITE，只基于 stop reason、evidence 和事实状态提出恢复入口。

## 8. 统一测试关闭条件

每个完整 Domain 初版至少验证：

- model invariant 和状态转换；
- migration、repository、transaction、幂等和引用完整性；
- 每个 Port 的正常/失败 fixture contract；
- request-local observation/candidate/draft 不自动落库；
- Tool exposure、schema、Guardrail、confirmation 和 evidence；
- fake ReAct / Planner / Context / Memory / DAG consumer contracts；
- compiled Graph 真实 handler 成功路径和 catalog 外 Tool 拒绝路径；
- 长期 seed 下分页、预算和稳定排序；
- 文档与实际完成状态同步。

明确经用户排除的测试范围必须写入对应 Domain 计划，不能被误报为已覆盖。
