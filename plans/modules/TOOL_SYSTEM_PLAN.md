# Tool System 模块计划

## 1. 目标

本模块建立统一、可审计、可扩展的工具执行边界，用真实 Tool Gateway 替换阶段 4 的 `stub_execute`。核心采用 LifeOps 原生模型和 Guardrails；LangChain 只作为可选 schema / invocation adapter，不成为授权源、事实源或唯一执行入口。

## 2. 当前 V0 参考

对照范围：

- `legacy_v0/app/tools/tool.py`
- `legacy_v0/app/tools/registry.py`
- `legacy_v0/app/tools/capability_builder.py`
- `legacy_v0/app/agents/action_recorder.py`
- `legacy_v0/app/runtime/run_state.py`
- `legacy_v0/tests/test_tool_authorization.py`
- `legacy_v0/tests/test_write_policy.py`

保留：结构化 schema、Policy 授权、action evidence、失败观察、source/helper 白名单。

重写：超大工具模块、业务逻辑与 runtime glue 混放、回调层层嵌套、模型文本声称成功、不同工具通道绕过统一安全边界。

## 3. 当前范围

### 3.1 初版做

- `ToolDefinition`：name、description、input/output schema、effect、risk、`skill_ids`；空 `skill_ids` 表示通用 Tool。
- `ToolRegistry`：注册、重复校验、按 name 查询、生成模型可见 catalog。
- `AllowedToolSet`：selected Skill 业务候选（加通用 Tool）与 Policy `allowed_effects` 求交后的本轮 Tool 白名单。
- `ToolCall` / `ToolResult` / `ToolError` / `ExecutionEvidence`。
- `ToolExecutionContext`：run IDs、Policy、AllowedToolSet、TraceSink 和 request-local dependencies。
- 统一 `ToolGateway.execute(...)`。
- 执行前和执行后 `GuardrailDecision`。
- READ、WRITE、EXTERNAL_READ 三类 effect；阶段 5 不实现外部交易写入。
- Research / Travel tools 接入同一 gateway。
- 成功/失败 tool call 写入 `tool_calls` 摘要并追加语义 event。
- 已评估但当前不保留 LangChain Tool adapter；LifeOps definition 已能直接生成模型 catalog，真实模型调用接入前增加 `StructuredTool` 只会复制 schema 和 invocation lifecycle。

### 3.2 初版不做

- 不使用 `create_agent` 替换当前 Runtime / LangGraph 主流程。
- 不让 LangChain `ToolRuntime.store` 保存 LifeOps 业务事实或 Memory。
- 不接 shell/code、hosted tools、真实 MCP 或付款/预订。
- 不实现自动 retry policy、并行 ToolNode 或跨 run confirmation resume；只保留接口。
- 不让 Domain tool 自己提交 transaction 或写 run record。

## 4. Runtime 边界

```text
Planner / Direct Executor（未来）
             ↓ ToolCall
        ToolGateway
             ↓
PreExecutionGuardrails
  - registered
  - membership in request-local AllowedToolSet
  - confirmation
  - args schema
             ↓
        tool handler
             ↓
PostExecutionGuardrails
  - result schema
  - sensitive output
  - success evidence
  - side-effect truth
             ↓
ToolResult + ExecutionEvidence + trace
```

阶段 5 可由 orchestration 中最小 direct-execution node 调用 gateway；阶段 6 的通用 ReAct Executor 接入时替换调用方，不替换 gateway。ToolGateway 按 Policy 授权后的具体 Tool 执行，不为每个 Domain 建独立 agent loop；同一 PlanRun 可以连续调用 Research 与 Travel handlers。

### 4.1 GuardrailDecision

至少包含：

- `action`: allow / deny / requires_confirmation；
- `stage`: pre_execution / post_execution；
- `reason_code` 与紧凑 reason；
- `tool_name`；
- `sanitized_args_summary`；
- `evidence_requirements`。

Guardrail 是确定性安全边界。LangChain middleware 可作为额外 adapter/hook，但不得绕过或替代它。

当前 V1 pre-Guardrail 接收 authorization 已生成的 `AllowedToolSet`，不再直接读取 `PolicyDecision`；WRITE 只在 `confirmed_tool_name` 与当前 `ToolCall.tool_name` 一致时继续，READ / EXTERNAL_READ 不要求确认。参数摘要绑定、过期时间和跨 run confirmation token 留到 Interaction Safety State 施工，不在本步提前实现。

### 4.2 未来适配接口

- Context 只通过 `ToolExecutionContext` 的窄引用提供已组装数据，不把完整 GraphState 注入工具。
- Memory tool 与业务 tool 使用同一 gateway；具体 WRITE Tool 必须被 Policy 点名授权。
- Planner 只看到 catalog，不调用 handler。
- Planner 的 step 与 Tool 如何匹配留到 Planner 模块施工时设计；当前 Tool System 不预留 capability 字段。
- Executor 负责跨 Domain 调度、重试和反馈；gateway 负责单次调用安全与证据。
- Recovery 使用 tool evidence 解释停点，不自动 replay WRITE。
- LangGraph checkpoint 可保存 orchestration / PlanRun state 并支持恢复，但不能撤销已经提交的 Domain WRITE 或外部副作用。
- MCP / HTTP / shell 等通道未来都实现 handler adapter，并经过相同 gateway。
- DAG scheduler 调 Executor，不直接调用 registry handler。
- Inspector / Eval 读取 ToolResult、evidence 和 event，不执行工具。

## 5. 数据模型 / 存储

`ToolDefinition` 和 registry 是代码配置，不进入 SQLite。

当前 Gateway 不写 `tool_calls`。现有表保留为阶段 2 migration 的历史兼容结构；只有 Inspector、Eval、Recovery 或产品历史查询出现明确的跨 Run 关系查询需求时，才重新设计摘要字段和写入边界。原始 arguments、output、secret 和完整外部响应不得进入该表。

`events.jsonl` 保存 `tool.call.requested`、`tool.guardrail.decided`、`tool.call.completed` / `failed`。原始大响应写临时 reference，由后续 Context 计划定义生命周期。

## 6. 对外接口

```python
register_tool(definition, handler) -> None
resolve_allowed_tools(selected_skill_ids, policy, registry) -> AllowedToolSet
execute_tool(call, context) -> ToolResult
```

Domain handler 只调用 service；service 再调用 repository 或 external Port。

## 7. 失败模式

- 未注册、重复注册或 schema 不合法；
- Tool 声明了错误 Skill ID，或 selected Skill 不匹配；
- Policy 未允许 Tool effect；
- WRITE confirmation 缺失或未绑定当前 Tool 名；参数摘要绑定和过期检查留到后续 Interaction Safety State；
- 参数验证失败；
- handler timeout / provider failure；
- handler 声称成功但缺少 evidence；
- 外部输出含 prompt injection、敏感数据或过大 payload；
- transaction rollback 后错误标记成功；
- adapter 直接绕过 gateway。

## 8. 测试和 Eval

- registry、schema、Skill candidate/common Tool 与 Policy effect intersection；
- READ / WRITE / EXTERNAL_READ guardrail matrix；
- READ / WRITE Tool 的 allowed effects、confirmation 和参数验证；
- confirmation 绑定和拒绝路径；
- handler success/failure/timeout；
- post-execution evidence validation；
- semantic event 顺序与 payload 脱敏；`tool_calls` 等真实查询消费者出现后再补 storage contract tests；
- 若未来真实 LangChain agent/ToolNode 成为调用方，再增加 adapter contract test，证明所有 invocation 仍回到 LifeOps Gateway；
- Research source、Travel fixture 的正常、部分失败和恶意内容；
- compiled Graph 从 START 到真实 Research handler 的 success path，以及恶意选择未授权 Tool 时的 Guardrail deny path；
- `stub_execute` 已由最小 `execute_tool` Direct Executor 路径替换；PlanRun / bounded replan 留到阶段 7。

## 9. 文档更新

- 完成后更新 `docs/ARCHITECTURE.md`、`docs/PROGRESS_LOG.md` 和 `docs/RUNTIME_CONCEPTS.md`。
- 权威 Tool / Guardrail / adapter 资料写入 `docs/AGENT_LEARNING_LINKS.md`。
- 关键取舍维护在本模块计划与 `plans/RUNTIME_REFACTOR_PLAN.md`，不新增 decisions / ADR 文档。

## 10. 实施步骤

1. [已完成] 定义 Tool、Result、Evidence、Guardrail 模型。
2. [已完成] 实现 registry 和 schema validation。
3. [已完成] 实现 Tool exposure intersection：selected Skill IDs 选出绑定的业务候选 Tool，空 `skill_ids` 的通用 Tool 始终作为候选，再与 Policy `allowed_effects` 和 registry contracts 求交；Skill 不授权，Policy 不枚举业务 Tool 名。
4. [已完成] 实现 pre/post guardrail pipeline：pre 消费 `AllowedToolSet` 并检查当前 Tool membership、注册状态、WRITE Tool 名确认和 input schema，不重复读取 Policy；post 检查 result identity、success、output schema 和 WRITE evidence。
5. [已完成] 实现原生 `ToolGateway` 和语义 events：按 `AllowedToolSet -> pre-Guardrail -> handler -> post-Guardrail` 执行，拒绝/确认不触达 handler，handler 异常与非法结果归一化为安全 `ToolResult`，event 不记录原始参数或输出。当前没有真实的跨 Run 查询消费者，因此 Gateway 不提前写 `tool_calls`。
6. [已完成] 接入最小真实 Research Domain 纵向切片：Research tools 绑定 `skill_ids=("research",)`；`research.fetch_source` 通过 fixture-backed `ResearchSourcePort` 产生 request-local `ExternalObservation`，`research.save_source` 只能按 observation ID 经 Policy WRITE effect、confirmation 和 Gateway 保存 `ResearchSource`，成功返回持久化 evidence；handler contract 接收完整 `ToolCall` 以绑定 call identity。
7. [已完成] 接入最小真实 Travel Domain 纵向切片并验证 Tool Runtime 不需要 Domain 特例；初始 `travel.search_options` / `CandidateOption` 兼容切片随后已由 Travel Domain 的五个 typed EXTERNAL_READ Tools、compare/draft 与 draft-based `travel.save_itinerary` 替代，WRITE 继续经过 Policy effect、confirmation、Gateway、transaction 和 evidence。
8. [已完成] 评估 LangChain adapter，当前不实现：本地 `langchain-core 1.4.9` 的 `StructuredTool` 接受 callable 与 Pydantic/JSON args schema，但 LifeOps 已有 JSON Schema catalog、ToolCall、Gateway 和 Result；当前没有 LangChain agent/ToolNode 调用方，adapter 会复制 schema/错误语义，并需要额外注入 request-local `AllowedToolSet`、confirmation 和 trace，不能减少现有 glue。未来只有真实调用方出现时再按窄 adapter 重新评估。
9. [已完成] 用真实 Gateway 替换 `stub_execute` 的最小 Direct Executor 路径：Skill 业务候选与 Policy effect 先形成 request-local `AllowedToolSet`，只有对应 filtered catalog 发送给 Responses function calling；V1 最多选择一个 `ToolCall`，随后仍由 pre/post Guardrail 和 Gateway 独立验证并执行。Registry、Gateway 与 Domain service 每次 invocation 重建，避免 observation/option 跨 run 泄漏；结构化 `ToolResult` 映射回 `RuntimeResult`。
10. [已完成] 补齐 compiled Graph -> Skill -> filtered catalog -> Gateway -> Domain handler 的阶段 5 E2E，以及未授权 Tool 的 Guardrail deny / no-write 断言；全量回归、compileall、冗余状态审计和当前文档同步均通过。
