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

保留：结构化 schema、capability gating、action evidence、失败观察、source/helper 白名单。

重写：超大工具模块、业务逻辑与 runtime glue 混放、回调层层嵌套、模型文本声称成功、不同工具通道绕过统一安全边界。

## 3. 当前范围

### 3.1 初版做

- `ToolDefinition`：name、description、input/output schema、effect、risk、required scopes。
- `ToolRegistry`：注册、重复校验、按 name 查询、生成模型可见 catalog。
- `ToolCapabilitySet`：从 Skill hints、registry、Policy allowed tools 和 scopes 求交集。
- `ToolCall` / `ToolResult` / `ToolError` / `ExecutionEvidence`。
- `ToolExecutionContext`：run IDs、Policy、capabilities、TraceSink 和 request-local dependencies。
- 统一 `ToolGateway.execute(...)`。
- 执行前和执行后 `GuardrailDecision`。
- READ、WRITE、EXTERNAL_READ 三类 effect；阶段 5 不实现外部交易写入。
- Research / Travel tools 接入同一 gateway。
- 成功/失败 tool call 写入 `tool_calls` 摘要并追加语义 event。
- 可选 LangChain adapter，把 LifeOps definition 转成 LangChain tool；框架调用仍回到 `ToolGateway`。

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
  - capability
  - allowed_tools
  - WRITE scope
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

阶段 5 可由 orchestration 中最小 direct-execution node 调用 gateway；阶段 7 的通用 Executor 接入时替换调用方，不替换 gateway。ToolGateway 按 tool/capability 执行，不为每个 Domain 建独立 agent loop；同一 PlanRun 可以连续调用 Research 与 Travel handlers。

### 4.1 GuardrailDecision

至少包含：

- `action`: allow / deny / requires_confirmation；
- `stage`: pre_execution / post_execution；
- `reason_code` 与紧凑 reason；
- `tool_name`；
- `required_scopes` / `satisfied_scopes`；
- `sanitized_args_summary`；
- `evidence_requirements`。

Guardrail 是确定性安全边界。LangChain middleware 可作为额外 adapter/hook，但不得绕过或替代它。

### 4.2 未来适配接口

- Context 只通过 `ToolExecutionContext` 的窄引用提供已组装数据，不把完整 GraphState 注入工具。
- Memory tool 与业务 tool 使用同一 gateway，但 Memory WRITE 需要独立 scope。
- Planner 只看到 catalog，不调用 handler。
- Planner 的 step 绑定 objective / required capabilities / candidate tools，不绑定 Domain 子类。
- Executor 负责跨 Domain 调度、重试和反馈；gateway 负责单次调用安全与证据。
- Recovery 使用 tool evidence 解释停点，不自动 replay WRITE。
- LangGraph checkpoint 可保存 orchestration / PlanRun state 并支持恢复，但不能撤销已经提交的 Domain WRITE 或外部副作用。
- MCP / HTTP / shell 等通道未来都实现 handler adapter，并经过相同 gateway。
- DAG scheduler 调 Executor，不直接调用 registry handler。
- Inspector / Eval 读取 ToolResult、evidence 和 event，不执行工具。

## 5. 数据模型 / 存储

`ToolDefinition` 和 registry 是代码配置，不进入 SQLite。

`tool_calls` 保存一行一调用的关系摘要：run/tool/status/effect/timing/error/evidence reference；不保存大 raw payload、secret 或完整外部响应。

`events.jsonl` 保存 `tool.call.requested`、`tool.guardrail.decided`、`tool.call.completed` / `failed`。原始大响应写临时 reference，由后续 Context 计划定义生命周期。

## 6. 对外接口

```python
register_tool(definition, handler) -> None
resolve_capabilities(skill_hints, policy, registry) -> ToolCapabilitySet
execute_tool(call, context) -> ToolResult
to_langchain_tool(definition, gateway) -> BaseTool  # 可选 adapter
```

Domain handler 只调用 service；service 再调用 repository 或 external Port。

## 7. 失败模式

- 未注册、重复注册或 schema 不合法；
- Skill 暴露了未注册工具；
- Policy 未允许或 WRITE scope 不足；
- confirmation 缺失、过期或不绑定当前 action；
- 参数验证失败；
- handler timeout / provider failure；
- handler 声称成功但缺少 evidence；
- 外部输出含 prompt injection、敏感数据或过大 payload；
- transaction rollback 后错误标记成功；
- adapter 直接绕过 gateway。

## 8. 测试和 Eval

- registry、schema 和 capability intersection；
- READ / WRITE / EXTERNAL_READ guardrail matrix；
- allowed_tools 与 scope 分开验证；
- confirmation 绑定和拒绝路径；
- handler success/failure/timeout；
- post-execution evidence validation；
- tool_calls transaction 与 event 顺序；
- LangChain adapter 与原生调用返回等价 LifeOps result；
- Research source、Travel fixture 的正常、部分失败和恶意内容；
- 同一 PlanRun 中 Research 成功、Travel 失败时保留已提交事实，记录失败 step，并允许 bounded replan；
- stub_execute 仅在 Tool System 接入完成后移除。

## 9. 文档更新

- 完成后更新 `docs/ARCHITECTURE.md`、`docs/PROGRESS_LOG.md` 和 `docs/RUNTIME_CONCEPTS.md`。
- 权威 Tool / Guardrail / adapter 资料写入 `docs/AGENT_LEARNING_LINKS.md`。
- 关键取舍维护在本模块计划与 `plans/RUNTIME_REFACTOR_PLAN.md`，不新增 decisions / ADR 文档。

## 10. 实施步骤

1. [已完成] 定义 Tool、Capability、Result、Evidence、Guardrail 模型。
2. 实现 registry 和 schema validation。
3. 实现 capability intersection。
4. 实现 pre/post guardrail pipeline。
5. 实现原生 ToolGateway 和 tool_calls/event evidence。
6. 接入一个 Research READ tool 和一个受控 WRITE tool。
7. 接入 Travel fixture external READ 和 itinerary WRITE tool。
8. 实现并评估 LangChain adapter；仅在减少模型工具 schema glue 时保留。
9. 用真实 gateway 替换 stub execution 的最小路径。
10. 补测试并同步文档。
