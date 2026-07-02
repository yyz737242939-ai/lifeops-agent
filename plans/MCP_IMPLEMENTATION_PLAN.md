# MCP v1 实现计划

本文档用于下一阶段继续施工。目标是用一个小而完整、且与现有业务 domain 不重叠的例子学习 MCP 在 Agent Runtime 中的角色：

```text
LifeOps Agent
-> Tool / Capability / Executor
-> MCP Client / Adapter
-> MCP Protocol
-> Mock Package Tracking MCP Server
-> local JSON data
```

第一版不把包裹物流做成新的 domain，也不通过 Skill 控制。Package Tracking MCP 工具作为全局只读工具暴露，用来集中学习 MCP 的协议边界、工具发现、调用流程、错误处理、权限效果和可观测性。

选择 Package Tracking 的原因：

- 它和 Todo、Finance、Daily Log、Activity 等现有 domain 没有语义重叠。
- 它天然像一个外部系统查询，而不是 LifeOps 内部业务状态。
- 第一版只读即可，不涉及写入授权。
- 后续可替换成真实物流 API，而 Agent 侧仍只认识 MCP 暴露的工具。

## 0. 当前事实与施工边界

当前仓库已有：

- `app/tools/registry.py` 和 `app/tools/tool.py`：全局 Tool 注册与 ToolDefinition。
- `app/tools/capability_builder.py`：决定本轮模型可见工具。
- `app/tools/executor.py`：统一执行工具、处理超时、重试、幂等和错误结构。
- `app/agents/agent.py`：Agent Loop、工具调用、Tool Observation 和 Runtime 状态记录。
- `app/observability/*`：事件日志、LLM I/O 日志和应用日志。
- `app/context/*`：Conversation Working Context、Ref、Summary 和压缩边界。
- `app/memory/*`：Profile Memory 与用户授权 Semantic Memory。

本阶段新增：

```text
app/mcp/
  client.py
  types.py
  errors.py

mcp_servers/
  mock_package_server.py

data/mock_packages/
  shipments.json
```

目录名可在实现时按现有代码风格微调，但职责边界保持不变。

本阶段明确不做：

- 不接真实物流平台、购物平台或账号系统。
- 不做 OAuth、登录态、真实网络 API 或后台同步。
- 不做 MCP WRITE 工具。
- 不新增 Package / Shipping domain。
- 不新增 Package Skill。
- 不做通用多 server 管理平台。
- 不实现 MCP resource / prompt 的完整能力。
- 不把包裹查询结果写入 Memory、业务数据或长期历史。

## 1. 核心目标

完成后，用户可以问：

```text
查一下 PKG-001 到哪了。
我的包裹预计什么时候送到？
这个快递最近一次物流更新是什么？
```

Agent 的理想工作流：

```text
用户请求
-> Capability Builder 默认暴露全局 Package MCP READ tools
-> 模型调用 track_package_via_mcp 或 list_package_updates_via_mcp
-> Tool 函数调用 MCP Adapter
-> MCP Adapter 连接 Mock Package Tracking MCP Server
-> MCP Server 从 data/mock_packages/shipments.json 读取数据
-> MCP Server 返回结构化结果
-> Executor 返回 Tool Observation
-> Agent 基于真实 Observation 回复用户
```

核心学习点：

- MCP Server 是外部能力提供者，不属于 Agent 内部 domain。
- MCP Client / Adapter 是 Runtime 接入层，不直接表达业务策略。
- Tool Bridge 把 MCP tool 转成 Agent 当前能理解的 ToolDefinition。
- Capability / Executor 仍然是 Agent 侧安全与可观察边界。
- MCP 返回内容默认属于本轮工具观察，不是 Memory，也不是业务数据写入。
- 外部查询结果和内部业务状态必须保持分离。

## 2. Mock Package Tracking MCP Server

### 目标

实现一个真实 MCP Server 进程，但它背后的外部系统先用本地 JSON mock。

第一版工具：

```text
track_package(tracking_number: str)
list_package_updates(tracking_number: str)
estimate_delivery_window(tracking_number: str)
```

建议 mock 数据：

```text
data/mock_packages/shipments.json
```

示例字段：

```text
tracking_number
carrier
status
current_location
estimated_delivery_date
estimated_delivery_window
updates
```

`updates` 可包含：

```text
timestamp
location
status
detail
```

规则：

- Server 只读 `data/mock_packages/shipments.json`。
- Server 不写文件。
- Server 不访问网络。
- 参数错误返回结构化 MCP 错误。
- 不存在的 tracking number 返回明确的 not found 错误。
- 时间字段先使用简单 ISO 字符串，不引入复杂时区系统。

### 验收

- MCP Server 能列出 `track_package`、`list_package_updates` 和 `estimate_delivery_window`。
- 调用 `track_package` 能返回指定包裹的当前状态。
- 调用 `list_package_updates` 能返回物流更新列表。
- 调用 `estimate_delivery_window` 能返回预计送达时间。
- 未知工具、缺少参数和不存在的 tracking number 有明确错误。

## 3. MCP Adapter

### 目标

新增 Agent 侧 MCP Adapter，负责连接 server、发现工具、调用工具和规范化错误。

建议职责：

```text
start/connect MCP server
list tools
call tool
normalize MCP errors
enforce timeout
return JSON-safe result
```

Adapter 不应该知道 Package Tracking 是 LifeOps 的业务模型，也不应该直接修改 Agent.messages、Memory 或业务 store。

### 验收

- Adapter 能连接 Mock Package Tracking MCP Server。
- Adapter 能读取 server 暴露的工具 schema。
- Adapter 能调用工具并返回 JSON-safe dict。
- Server 不可用、超时、未知工具和参数错误会被转成 Runtime 可理解的错误结构。

## 4. Tool Bridge

### 目标

把 MCP Package Tracking 能力接入当前 Tool Registry。

第一版建议使用三个明确工具，而不是过早做通用 `call_mcp_tool`：

```text
track_package_via_mcp(tracking_number)
list_package_updates_via_mcp(tracking_number)
estimate_delivery_window_via_mcp(tracking_number)
```

原因：

- 更容易观察 Tool Schema 如何被模型使用。
- 更容易确认 READ / WRITE 边界。
- 更容易写聚焦测试。
- 后续再抽象通用 MCP Tool Bridge 时，有真实经验作为依据。

规则：

- 三个工具都是 `ToolEffect.READ`。
- 工具描述明确数据来自 Mock Package Tracking MCP Server。
- 工具函数只通过 MCP Adapter 获取结果，不直接读 `shipments.json`。
- MCP 调用失败时返回结构化错误，不让模型假装已经读取成功。

### 验收

- 三个 MCP Package tools 出现在全局工具集合中。
- 三个工具 effect 均为 READ。
- 直接调用工具会走 MCP Adapter。
- 工具 observation 中能看出来源是 MCP package tracking server。

## 5. Capability / Executor / Observability 接入

### 目标

MCP 工具虽然全局暴露，但仍必须经过现有 Runtime 边界。

接入原则：

- 全局可见不等于绕过 Capability Builder。
- READ 不需要用户写入授权。
- Executor 仍负责调用、超时和错误归一化。
- Observability 需要记录本轮调用了哪个 MCP server、哪个 tool、参数和结果状态。

建议日志字段：

```text
server_id
mcp_tool_name
agent_tool_name
effect
duration_ms
status
error_code
```

### 验收

- MCP Package READ tools 默认可见。
- 工具调用进入现有事件日志链路。
- 错误不会破坏 Agent Loop。
- 包裹查询结果不写入 Memory。
- 包裹查询结果不自动写入业务数据。

## 6. 测试计划

建议新增或更新测试：

```text
tests/test_mcp_adapter.py
tests/test_mcp_package_tools.py
tests/test_capability_builder.py
tests/test_agent_mcp_package.py
```

测试覆盖：

- MCP Adapter 能列出 mock package tools。
- MCP Adapter 能调用 `track_package`。
- MCP Adapter 能调用 `list_package_updates`。
- MCP Adapter 能调用 `estimate_delivery_window`。
- 未知 MCP tool 被拒绝。
- 不存在的 tracking number 返回结构化 not found。
- MCP server 错误会被规范化。
- Package MCP tools 默认进入全局 READ tool 集合。
- Package MCP tools 不需要 WRITE 授权。
- Tool 函数通过 MCP Adapter，而不是直接读 mock JSON。
- MCP 返回内容不会写入 Memory。
- MCP 失败时 Agent 能如实说明不可用或读取失败。

第一版不默认运行全量测试。优先运行新增测试和被影响的 Capability / Tool / Agent Loop 聚焦测试。

## 7. 阶段实施顺序

### 阶段一：计划与最小数据（已完成）

目标：

- 新增本计划。
- 新增 `data/mock_packages/shipments.json` 样例数据。

验收：

- 计划明确 MCP 不等于 domain。
- Package Tracking 第一版是全局 READ MCP 工具，不走 Skill。
- Package Tracking 和现有 domain 没有语义重叠。

### 阶段二：Mock Package Tracking MCP Server（已完成）

目标：

- 实现本地 MCP Server。
- 提供 `track_package`、`list_package_updates` 和 `estimate_delivery_window`。

验收：

- Server 可被独立测试。
- mock 数据读取和参数错误处理稳定。

### 阶段三：MCP Adapter（已完成）

目标：

- 新增 `app/mcp/*`。
- Agent 侧能连接、发现和调用 MCP tools。

验收：

- Adapter 测试覆盖成功路径、未知工具、参数错误、not found 和 server 不可用。

### 阶段四：全局 Tool Bridge（已完成）

目标：

- 注册 `track_package_via_mcp`。
- 注册 `list_package_updates_via_mcp`。
- 注册 `estimate_delivery_window_via_mcp`。
- 三者都是 READ tools。

验收：

- Capability Builder 默认暴露它们。
- Executor 能执行它们。

### 阶段五：Agent 闭环（已完成）

目标：

- 用户用自然语言询问包裹状态。
- Agent 调用 MCP Package tools。
- Agent 基于 Tool Observation 回复。

验收：

- 不编造未读取的物流状态。
- MCP 调用失败时如实说明失败。
- 查询结果不进入 Memory。

### 阶段六：文档收口（已完成）

目标：

- 更新 `PROJECT_CONTEXT.md` 记录 MCP v1 稳定事实、边界和验证结果。
- 更新 `LEARNING_PROGRESS.md` 记录 MCP 学习结论和下一阶段。
- `CHANGELOG.md` 只在用户明确要求阶段性记录时更新。

## 8. 后续扩展

本阶段完成后可以考虑：

- 把三个显式 tools 抽象成通用 MCP Tool Bridge。
- 支持多个 MCP server 的配置。
- 支持 MCP resource，并学习 resource 和 tool 的区别。
- 引入真实物流 API，但仍藏在 MCP Server 背后。
- 为真实外部账号数据增加 Permission / Safety State。
- 为 MCP WRITE tools 增加明确授权、确认和幂等保护。
- 如果未来出现包裹管理、购物记录或售后流程等长期业务模型，再考虑新增独立 domain。

## 9. 学习检查问题

每一步完成后，都要能回答：

```text
这一层属于 Tool、Capability、Executor、Runtime State、Context、Memory、Domain 还是 Logs？
MCP Server 和 Agent 内部 Tool 的边界在哪里？
MCP tool 返回的内容会进入哪些上下文？不会进入哪里？
全局 READ tool 为什么仍然需要 Capability / Executor？
为什么 Package Tracking 第一版不应该进入现有 domain？
如果未来变成 WRITE tool，需要新增哪些授权和安全状态？
如果换成真实物流 API，Agent 侧哪些代码应该不变？
```
