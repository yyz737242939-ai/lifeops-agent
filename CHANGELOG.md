# Changelog

本文件记录LifeOps Agent每个学习Milestone交付的主要能力。格式参考
[Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，但版本号表示项目学习阶段，
不等同于PyPI包的语义化版本。

## 当前功能总览

- 基于OpenAI Responses API兼容接口的多轮Function Calling Agent。
- Todo、日计划、Wellbeing、消费预算和活动推荐工具。
- 确定性Skill路由、多轮Skill状态、按需加载Skill正文。
- 动态Tool Schema、最小Capability和Runtime二次授权。
- 单次Chat RunState、结构化Action、预算、重试、超时、取消和停止原因。
- 工具错误归一化、写入幂等重放和确定性循环检测。
- Context Engine的滑动窗口、Rolling Summary、Context Index、Inspector、主动/被动/手动压缩触发和Context Eval回归。
- Memory v1：只读Profile、用户授权Semantic Memory、Memory工具、简单检索和本轮上下文注入。
- Tool Observation的inline、summary和Context Ref压缩。
- 当前输入写授权、批量删除确认和最终写入声明校验。
- Event、LLM I/O、Application三通道日志及本地Viewer。
- 131项自动化回归测试。

## [Milestone 1.2] - 2026-07-01

### Added

- 新增 `ContextEngine` 作为本轮 LLM input 编译入口，`Agent._request_llm()` 不再直接发送完整 `Agent.messages`，而是通过 `ContextEngine.assemble()` 生成工作上下文。
- 新增 Context Unit 化机制，将历史消息切分为 user、assistant、tool、protected system note 等单元，并保持 function call 与对应 tool observation 不被窗口切分。
- 新增滑动窗口组装策略：短对话保持 pass-through，长对话只发送 summary / protected units / retrieved units / recent units，避免无脑发送完整历史。
- 新增 Context Budget 配置，区分 `soft_limit_tokens` 与 `hard_limit_tokens`，当前使用字符数近似估算 token。
- 新增 deterministic Rolling Summary，用于压缩窗口外旧对话，记录用户目标、工具成功/失败、重要实体、受保护项和来源 unit ids。
- 新增主动压缩路径：回合结束后 `ContextEngine.after_turn()` 在完整历史超过 soft limit 时更新 deterministic summary，不调用 LLM。
- 新增被动预算保护路径：`ContextEngine.assemble()` 在 hard limit 压力下缩小 recent window，不生成新 summary，不调用 LLM。
- 新增手动压缩命令 `/compact`：该命令不进入 `Agent.messages`，会先更新 deterministic summary，再发起一次无工具 LLM 调用生成辅助性的 natural language summary。
- 新增 `ContextIndex`，对窗口外旧 Context Unit 提取确定性 metadata，并在精确后续请求中按 tool name、ref id、entity id、domain keyword 和 action status 召回相关旧 unit。
- 新增 `ContextInspector`，把 assembly report 整理为 overview、composition、decisions 和 diagnostics，用于日志观察和测试定位。
- 新增 Tool Observation 压缩策略：根据结果体积和列表数量选择 inline、summary、summary_reference 或 reference。
- 新增 `ContextRefStore`，为大体积或可恢复的 Tool Result 保存完整 payload，并支持通过 `read_context_ref` 按需恢复。
- 新增 Context Eval 自动化回归，覆盖压缩前后关键不变量，包括精确 Todo 后续操作、Expense 金额/日期恢复、失败 WRITE 摘要、protected 确认状态和 Ref 恢复。
- 新增 Memory v1：`data/memory/profile.md` 只读 Profile、`data/memory/semantic_memories.json` Semantic Memory Store，以及 `MemoryItem` 数据模型。
- 新增 Memory 工具：`save_memory`、`list_memories`、`delete_memory`。保存和删除 Memory 必须经过当前用户输入明确授权，查看 Memory 作为 READ 工具可用。
- 新增 Memory Retrieval：每轮 LLM 请求前，Runtime 按当前 `user_input` 从 active Semantic Memory 中用关键词、type 和 tag 做简单检索。
- 新增 Memory Context 注入：Profile 和相关 Semantic Memory 会作为本轮只读 system context 插入局部 LLM input。
- 新增 Memory 相关回归测试，覆盖 Profile 只读加载、Semantic Memory 保存/列出/软删除、授权边界、工具读写、删除后不注入，以及 Memory 不进入 `Agent.messages`。

### Changed

- Context 阶段从简单 Tool Result 压缩，升级为完整的 conversation working context 管理：完整历史仍保留在 `Agent.messages` / `ContextStore`，但每轮发送给模型的是经过预算控制、摘要、召回和窗口选择后的工作输入。
- 明确区分 Tool Observation 压缩与长期对话窗口管理：前者处理单次工具结果过大，后者处理跨轮历史持续增长。
- 明确 deterministic summary 是派生上下文，不是事实源；完整历史仍是事实源，工具成功/失败以 Runtime ActionRecord 和 Tool Observation 为准。
- 明确 natural language summary 只是 `/compact` 生成的辅助软上下文，不替代 deterministic summary 和完整历史。
- `ContextEngine` 继续只管理 conversation working context；Profile Memory 和 Semantic Memory 在 `ContextEngine.assemble()` 之后注入本轮局部 `input_messages`，不进入 Rolling Summary、ContextIndex 或 Tool Observation 压缩路径。
- Capability 默认不暴露 WRITE 工具；通用 WRITE 工具如 `save_memory`、`delete_memory` 也必须由当前输入授权后才会出现在本轮 Tool Schema 中。
- 写入安全边界扩展到 Memory：用户只是陈述偏好或事实不会自动保存，assistant 口头声称“记住了”不算，只有 `save_memory` 工具成功写入才是真正保存。
- `list_todos` 增加 `limit`、`status` 和 `sort` 参数，优先从工具源头减少 Observation 体积。
- 项目状态从“准备进入最小 Memory State 设计”更新为“Context + Memory v1 已完成第一轮闭环”。

### Fixed

- 修复长对话下完整历史持续塞入 LLM input 的问题，避免窗口无限增长。
- 修复 Function Call 与 Tool Observation 可能被窗口策略拆散的问题。
- 修复模型可能只凭 assistant 文本误判写入成功的问题：Rolling Summary 不把 assistant 口头成功声明当作真实成功。
- 修复窗口外精确事实完全丢失的问题：对 Todo id、Expense 金额/日期、Ref id 等高风险信息提供结构化摘要、索引召回或 Ref 恢复路径。
- 修复被动 hard limit 压力下可能仍超预算的问题：assemble 阶段会继续收缩 recent window。
- 修复删除后的 Memory 仍可能被使用的问题：Semantic Memory 采用 active/deleted 状态，默认查询和注入都排除 deleted items。

## [Milestone 1.1] - 2026-06-24

### Added

- 增加当前用户输入级别的写工具授权策略，未经明确授权不向模型暴露写能力。
- 增加批量删除确认保护，以及最终回答的写入成功声明校验。
- 日志Viewer支持发现和查看验收测试目录中的Session。
- Events页面增加单次Chat的LLM轮次、API请求数和工具执行尝试摘要。

### Changed

- RunState和ActionRecord字段明确区分单次Chat、LLM API请求和工具执行尝试的作用域。
- LLM Response日志改为诊断字段投影，删除重复的instructions、tools和空字段。
- 更新项目上下文和学习计划，下一阶段聚焦Context压缩与长期消息窗口。
- 清理第一阶段一次性UAT Runner、计划和运行产物，保留自动化回归测试。

### Fixed

- 修复建议类请求可能被模型误当成健康状态写入授权的问题。
- 防止模型在没有成功WRITE Action时声称数据已经保存或修改。
- 修复验收日志在Viewer中出现无效Session ID、无法选择的问题。

## [Milestone 1.0] - 2026-06-23

### Added

- 增加确定性Skill Router，以及Skill继承、切换、清理和Ref-only多轮状态。
- 增加按Skill动态构建Prompt、Tool Schema和授权集合的Capability机制。
- 增加单次请求RunState、ActionRecord、循环预算和结构化StopReason。
- 增加LLM/Tool显式重试、超时、协作式取消和部分成功结果保留。
- 增加工具副作用、幂等性、可重试性和超时元数据。
- 增加稳定调用签名、相同Observation和A-B-A-B循环检测。
- 增加Tool Result的领域摘要、Reference压缩及 `read_context_ref`。
- 增加Event、LLM I/O和Application三通道日志与本地Viewer。

### Changed

- 将Tool Registry、Executor、业务工具和公共JSON/时间工具拆分为清晰职责。
- Skill正文改为选中后按需加载，避免无关正文持续占用Context。
- SDK隐式重试改为Runtime显式管理和计数。

## [Milestone 0.1] - 2026-06-22

### Added

- 建立基础LLM聊天和Responses API调用链路。
- 实现Function Call执行循环，将Tool Observation返回模型继续推理。
- 建立Todo、Wellbeing、Finance和Activity Recommendation四个本地业务领域。
- 使用Pydantic和本地JSON文件保存Todo、日状态、消费及预算数据。
- 建立初版Skill路由、Context摘要和Agent运行日志。
