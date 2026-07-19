# 模块计划

模块实施计划放在这里。

本目录用于存放聚焦的计划，例如：

- `STORAGE_SQLITE_PLAN.md`
- `RUNTIME_CORE_PLAN.md`
- `INTENT_POLICY_PLAN.md`
- `LANGGRAPH_ORCHESTRATION_PLAN.md`
- `SKILL_SYSTEM_PLAN.md`
- `TOOL_SYSTEM_PLAN.md`
- `RESEARCH_KNOWLEDGE_DOMAIN_PLAN.md`
- `RESEARCH_MCP_PLAN.md`
- `TRAVEL_DOMAIN_PLAN.md`
- `EXECUTOR_PLAN.md`
- `PLANNER_PLAN.md`
- `CONTEXT_MEMORY_PLAN.md`（Stage 9A/9B go；Stage 9 已关闭）
- `LIVE_USER_E2E_PLAN.md`（Stage 9 后整体验收；真实用户 confirmation 与 5 个 live LLM E2E）
- `TRACE_INSPECTION_EVAL_STANDARD_PLAN.md`（步骤 1-16 已完成；shared-standard gate 为 `go`）
- `RECOVERY_PLAN.md`（Stage 10步骤1-17已完成；最终gate为`go`）
- `INSPECTOR_PLAN.md`（Stage 11A步骤1-12、14-15已完成并关闭；正式DAG artifact归未来兼容性回归）
- `EVAL_HARNESS_PLAN.md`

`plans/RUNTIME_REFACTOR_PLAN.md` 保持为总路线图。实现模块前，使用 `MODULE_PLAN_TEMPLATE.md` 在这里创建或更新模块计划。

所有业务 Domain 计划还必须遵守 `plans/DOMAIN_CONTRACT_STANDARD.md`；Research、Travel 和未来 Domain 共享同一接入规范，不分别发明 Planner / Context / Memory 或 Tool 安全接口。
