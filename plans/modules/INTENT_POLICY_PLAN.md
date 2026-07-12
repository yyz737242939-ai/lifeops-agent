# Intent / Policy 模块计划

## 当前状态

阶段 3 Intent / Policy 初版已完成。

已完成：

- `app/intent/` 已包含 intent models、classifier 接口、规则 classifier、LLM classifier 空实现和 `IntentService`。
- Intent pipeline 已同时调用规则 classifier 和 LLM classifier 接口。
- LLM classifier 初版保持 `abstain` / `not_available`，不调用真实模型。
- `app/policy/` 已包含 `PolicyDecision`、`PolicyAction` 和 `PolicyService`。
- Policy 已覆盖 `allow`、`deny`、`requires_confirmation`。
- 不明确写入默认要求确认，非写入 intent 不产生 write authorization。
- LLM classifier result、metadata 和 planner/checkpoint 模拟字段不能绕过 Policy。
- Intent / Policy 已接入 Runtime Core trace 摘要。
- Intent、Policy 和 Runtime integration 聚焦测试已覆盖阶段 3 边界。
- `docs/PROGRESS_LOG.md`、`docs/ARCHITECTURE.md` 和 `docs/RUNTIME_CONCEPTS.md` 已同步当前边界。

仍保留到后续阶段：

- 真实 LLM structured output classifier。
- 多轮 pending confirmation / Interaction Safety State。
- Tool System `allowed_tools` 对齐。
- LangGraph interrupt / human-in-the-loop 映射。

阶段 3 收口验证：

- 已运行 `uv run python -m compileall app tests`。
- 按用户要求，本次不运行全量测试。

## 1. 目标

本模块对应 `plans/RUNTIME_REFACTOR_PLAN.md` 的“阶段 3：Runtime Core / Intent / Policy”中的 Intent Layer 和 Policy / Permission Layer。

目标是先解决两个 runtime 安全边界：

- Intent Layer 先判断用户大概想做什么，避免关键词误触发 planning 或 write。
- Policy / Permission Layer 成为写入授权事实源，阻止 Planner、LLM 文本、Recovery Context、LangGraph checkpoint 或 assistant final answer 绕过授权。

阶段 3 初版结束时，项目应具备：

- `app/intent/`：统一 classifier 接口、规则 classifier、LLM classifier 空实现和 intent service。
- `app/policy/`：policy decision 和 policy service。
- Intent pipeline 同时调用规则 classifier 和 LLM classifier 接口。
- LLM classifier 初版不调用真实模型，只返回 abstain / not_available，作为后续真实产品形态的扩展点。
- Policy 对不明确写入默认要求确认，不执行写入。

本模块不是完整自然语言理解系统，也不是完整权限平台。它先建立可解释、可测试、可扩展的 intent / permission 边界。

## 2. 当前 V0 参考

阶段 3 默认不读取 `legacy_v0/`。只有在后续施工时需要追溯旧 routing、旧 write safety、旧 confirmation 或旧 planner 误触发行为时，才按 `AGENTS.md` 的 Legacy 读取规则读取相关片段。

当前可依据的参考是：

- `docs/ARCHITECTURE.md`：业务写入必须来自用户当前输入中的明确授权。
- `docs/ARCHITECTURE.md`：Planner 输出、LangGraph checkpoint state、Recovery Context、conversation summary 和原始 LLM log 都不是事实来源。
- `docs/ARCHITECTURE.md`：runtime 使用 intent first，tool exposure 或 execution 之前先经过 policy。
- `plans/RUNTIME_REFACTOR_PLAN.md`：先判断 intent，再决定是否 planning，避免关键词误触发；Policy 是权限事实源。
- `plans/modules/STORAGE_SQLITE_PLAN.md`：observability 和 storage 只提供 evidence，不负责授权。

V0 的主要问题预计是：

- routing 容易受关键词触发影响，例如用户描述“计划”时被误认为请求 planner。
- write policy、interaction policy 和 tool execution 可能分散在多个模块。
- planner 或 assistant 文本容易被误当成已经授权的写入事实。

阶段 3 的升级方式是建立 IntentDecision 和 PolicyDecision，而不是一次性做复杂 NLU 或权限平台。

## 3. 当前范围

初版做：

- 创建 `app/intent/` 包。
- 定义 `IntentClassifier` 接口和 `IntentDecision` 模型。
- 实现 `RuleBasedIntentClassifier`，作为初版真实判断路径。
- 实现 `LlmIntentClassifier` 空实现，初版只返回 `abstain` / `not_available`。
- 实现 `IntentService`，统一调用规则 classifier 和 LLM classifier，并合成最终 decision。
- 创建 `app/policy/` 包。
- 定义 `PolicyDecision`、`PolicyAction` 等最小模型。
- 实现 `PolicyService`，根据 `RuntimeRequest` 和 `IntentDecision` 产出授权判断。
- 对不明确写入返回 `requires_confirmation`。
- 记录 Intent / Policy 的结构化 trace payload。

初版不做：

- 不调用真实 LLM。
- 不引入 embedding、向量检索、训练模型或外部分类服务。
- 不实现完整多轮 pending confirmation state。
- 不执行工具。
- 不写业务数据。
- 不新增业务 permission table。
- 不根据 Planner、LLM response 或 LangGraph checkpoint 授权写入。
- 不做组织级 RBAC、用户账户或 OAuth scope。

后续版本可做：

- 将 `LlmIntentClassifier` 接入真实 LLM structured output。
- 增加 classifier confidence arbitration、fallback 和 eval cases。
- 增加 multi-turn confirmation state。
- 只有真实需求出现时才增加风险分类，不预留 operation scope。
- 和 Tool System 的 `allowed_tools` 对齐。
- 和 LangGraph interrupts / human-in-the-loop 对齐，但不让它们成为授权事实源。

## 4. Runtime 边界

输入：

- `RuntimeRequest` 或等价 request context。
- 用户当前输入文本。
- 当前 request-local metadata。
- 可选的 domain hints 或 UI action source，初版可为空。

Intent 输出：

- `IntentDecision`。
- 结构化 reason。
- confidence 或确定性等级。
- classifier evidence 摘要。
- 是否需要 clarification。
- 是否存在 write candidate。

Policy 输出：

- `PolicyDecision`。
- `allowed` / `denied` / `requires_confirmation`。
- `allowed_tools` 初版可为空。
- reason。
- trace-safe payload。

依赖方向：

```text
runtime
-> intent / policy
-> common
```

允许：

- Runtime Core 调用 Intent 和 Policy。
- Intent service 聚合多个 classifier。
- Policy service 读取 IntentDecision 和当前用户输入。
- Runtime Core 把 IntentDecision / PolicyDecision 写入 trace。

禁止：

- Intent 依赖 Policy。
- Intent 或 Policy 直接写 SQLite。
- Intent 或 Policy 调用工具。
- Policy 调 Planner、Executor、Domain repository 或 LangGraph。
- Planner、Executor、LLM 文本、Recovery Context 或 checkpoint 反向授权写入。

关键边界：

- Intent 判断“用户可能想做什么”。
- Policy 判断“系统现在被允许做什么”。
- Executor 未来只能执行 Policy 允许的事。
- Trace 记录为什么这么判定，但 trace 本身不新增授权。
- LLM classifier 即使未来接入，也只能提供 intent signal，不能提供 write authorization。

## 5. 数据模型 / 存储

初版不新增 SQLite schema。

Intent 和 Policy 的完整中间状态保持 request-local。

可以写入 trace payload 的摘要：

- final intent type。
- classifier names。
- classifier status，例如 `matched`、`abstained`、`not_available`。
- confidence bucket。
- policy action。
- allowed tool 名称。
- requires confirmation reason。
- denied reason。

不能写入 trace payload 的内容：

- 大段完整用户隐私内容。
- 真实 LLM prompt / response 原文。
- token、OAuth secret 或外部凭证。
- 可被误读为授权事实的 planner 文本。

建议 request-local 模型：

```text
IntentDecision
- intent_type
- confidence
- needs_clarification
- write_candidate
- reason
- classifier_results

ClassifierResult
- classifier_name
- status
- intent_type
- confidence
- reason

PolicyDecision
- action
- allowed_tools
- requires_confirmation
- denied_reason
- reason
```

初版 intent 类型：

```text
chat
read
write_request
plan_request
clarification_needed
unsupported
```

初版 policy action：

```text
allow
deny
requires_confirmation
```

## 6. 对外接口

计划暴露的最小接口：

```text
app/intent/models.py
- IntentType
- IntentDecision
- ClassifierResult

app/intent/classifiers.py
- IntentClassifier
- RuleBasedIntentClassifier
- LlmIntentClassifier

app/intent/service.py
- IntentService
- IntentService.classify(request: RuntimeRequest) -> IntentDecision

app/policy/models.py
- PolicyAction
- PolicyDecision

app/policy/service.py
- PolicyService
- PolicyService.evaluate(request: RuntimeRequest, intent: IntentDecision) -> PolicyDecision
```

Rule-based classifier 原则：

- 禁止裸关键词触发。
- 使用动作、对象、语气和上下文组合判断。
- 对低置信度输入返回 `clarification_needed` 或低 confidence。
- 不授权写入。

LLM classifier 初版原则：

- 具有和未来真实 classifier 相同的接口。
- 默认返回 `abstain` / `not_available`。
- 不调用真实模型。
- 不写 LLM log，除非未来真的发起 LLM request；后续真实 LLM request / response 应写入 `llm.jsonl`。
- 在测试中可证明 pipeline 调用了它。

IntentService 合成原则：

- 先调用 `RuleBasedIntentClassifier`。
- 再调用 `LlmIntentClassifier`。
- 初版最终 decision 主要来自规则 classifier。
- 如果规则 classifier 低置信度且 LLM classifier abstain，则返回 `clarification_needed`。
- 所有 classifier result 都保留在 request-local decision 中，供 trace 摘要使用。

PolicyService 原则：

- 只基于当前用户输入和 IntentDecision 判断授权。
- Policy 只通过具体 `allowed_tools` 表达 Tool 授权；当前工具尚未接入时该列表为空。
- 疑似写入但不明确时返回 `requires_confirmation`。
- 未确认、拒绝或不明确请求不产生 allowed tools。
- 永远不从 LLM classifier、Planner、assistant 文本或 checkpoint 获得授权。

## 7. 失败模式

预期失败：

- 用户输入为空。
- 用户输入同时包含多个意图。
- 规则 classifier 返回低置信度。
- LLM classifier 不可用。
- LLM classifier 未来返回非法结构。
- IntentService 无法合成 decision。
- PolicyService 遇到未知 intent type。
- 疑似写入但缺少对象或动作。
- Policy 点名了未注册 Tool，或漏掉应授权的 Tool。

处理原则：

- 空输入返回 `clarification_needed` 或 `unsupported`，不授权写入。
- 多意图初版返回 `clarification_needed`，不自动拆任务。
- LLM classifier 不可用不影响规则 classifier 正常工作。
- LLM classifier 未来异常时应降级为 `abstain`，并记录 trace-safe error code。
- Policy 遇到未知 intent 默认 `deny` 或 `requires_confirmation`，不能默认 allow。
- 不明确写入默认 `requires_confirmation`，不执行写入。

建议 trace event：

- `intent.classification.started`
- `intent.classifier.completed`
- `intent.classifier.abstained`
- `intent.classification.completed`
- `intent.classification.failed`
- `policy.evaluation.started`
- `policy.evaluation.completed`
- `policy.confirmation.required`
- `policy.evaluation.denied`
- `policy.evaluation.failed`

## 8. 测试和 Eval

Intent 最小测试：

- “我计划明天跑步”不触发 `plan_request`，不产生 write candidate。
- “帮我规划明天的安排”返回 `plan_request`。
- “把明天跑步加入任务”返回 `write_request` 和 write candidate。
- “计划一下”返回 `clarification_needed`。
- 空输入返回 `clarification_needed` 或 `unsupported`。
- 裸关键词不能单独触发 planning 或 write。
- `IntentService` 会调用规则 classifier 和 LLM classifier。
- `LlmIntentClassifier` 初版返回 abstain，不调用真实模型。

Policy 最小测试：

- `chat` / `read` / `plan_request` 不产生 write authorization。
- 明确 `write_request` 可以通过 Policy，但当前工具尚未接入时 `allowed_tools` 为空。
- 疑似写入但对象不明确返回 `requires_confirmation`。
- 未知 intent 默认不 allow。
- LLM classifier 的结果不能直接授权写入。
- Planner / assistant / checkpoint 模拟字段不能绕过 Policy。

Runtime integration 测试：

- 一轮 run 同时产生 IntentDecision、PolicyDecision 和 trace events。
- policy `requires_confirmation` 时 RuntimeResult 不声称已写入。
- policy `allow` 时阶段 3 仍只返回授权 decision，不执行真实 tool。

暂不做 Eval：

- 阶段 3 只沉淀误触发样例，作为后续 Eval Harness case 的候选。
- 完整 eval runner 留到 `plans/modules/EVAL_HARNESS_PLAN.md`。

验证命令建议：

```powershell
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'; uv run python -m unittest discover -s tests -v
$env:UV_CACHE_DIR='D:\lifeops-agent\.tmp\uv-cache'; uv run python -m compileall app tests
```

## 9. 文档更新

阶段 3 Intent / Policy 完成后应更新：

- `docs/PROGRESS_LOG.md`：记录 `app/intent/`、`app/policy/` 已存在，LLM classifier 当前为空实现。
- `docs/ARCHITECTURE.md`：补充 Intent 和 Policy 的依赖方向、授权事实源和禁止反向授权。
- `docs/RUNTIME_CONCEPTS.md`：补充 Intent Layer、Policy / Permission Layer、Write Safety 的学习章节。
- `docs/AGENT_LEARNING_LINKS.md`：补充 structured output、guardrails 和 permission / safety 相关权威学习链接；不提前加入 Tool System、MCP 或 human-in-the-loop 链接。

通常不需要更新：

- `README.md`：除非阶段 3 入口已经成为正式 demo。
- `docs/RUNTIME_CONCEPTS.md`：沉淀阶段 3 已经学到的误触发防护和 write safety 解释。
- `CHANGELOG.md`：除非用户明确要求记录里程碑。

如实施时改变授权事实源，应更新 `docs/ARCHITECTURE.md`。

## 10. 实施步骤

建议小步施工顺序：

1. [x] 创建 `app/intent/` 和 `app/policy/` 空包。
2. [x] 定义 intent models：`IntentType`、`ClassifierResult`、`IntentDecision`。
3. [x] 定义 `IntentClassifier` 接口。
4. [x] 实现 `RuleBasedIntentClassifier`，覆盖最小误触发样例。
5. [x] 实现 `LlmIntentClassifier` 空实现，返回 abstain / not_available。
6. [x] 实现 `IntentService`，确保规则和 LLM classifier 都被调用。
7. [x] 定义 policy models：`PolicyAction`、`PolicyDecision`。
8. [x] 实现 `PolicyService`，覆盖 allow / deny / requires_confirmation。
9. [x] 将 IntentService 和 PolicyService 接入 Runtime Core。
10. [x] 添加 intent、policy 和 runtime integration 聚焦测试。
11. [x] 更新 `docs/PROGRESS_LOG.md`、`docs/ARCHITECTURE.md` 和 `docs/RUNTIME_CONCEPTS.md`。
12. [x] 运行最小相关测试和 compile 检查。

## Grill-me 检查清单

- 为什么不用真实 LLM 做 intent？
  - 因为阶段 3 的目标是先固定 runtime 边界和安全链路。真实 LLM 会引入不稳定性、成本、日志脱敏和测试复杂度。

- 为什么还要有 LLM classifier 接口？
  - 因为真实产品通常会保留规则、模型和 policy 的分层 pipeline。初版让 LLM classifier 作为空实现参与调用，可以提前验证接口形状，后续接真实模型时不推翻架构。

- 规则优先是不是字符串匹配？
  - 不是。规则 classifier 应看动作、对象、语气和组合模式，禁止看到单个关键词就触发 planning 或 write。

- Intent 和 Policy 最大区别是什么？
  - Intent 判断用户可能想做什么；Policy 判断系统被允许做什么。前者是语义判断，后者是授权事实源。

- 为什么 plan_request 不授权写入？
  - 规划只是生成执行策略或建议。只有用户当前输入中有明确写入授权，且 Policy 返回 allow，后续 executor 才能写入。

- requires_confirmation 初版为什么不做完整多轮？
  - 因为阶段 3 只建立授权模型和接口。多轮 pending confirmation 需要 Interaction / Safety State 配合，适合后续版本。

- LLM classifier 未来能不能授权？
  - 不能。即使未来 LLM classifier 接入真实模型，它也只能提供 intent signal。写入授权仍来自 Policy。
