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
- `CONTEXT_MEMORY_PLAN.md`
- `RECOVERY_PLAN.md`
- `EVAL_HARNESS_PLAN.md`

`plans/RUNTIME_REFACTOR_PLAN.md` 保持为总路线图。实现模块前，使用 `MODULE_PLAN_TEMPLATE.md` 在这里创建或更新模块计划。

所有业务 Domain 计划还必须遵守 `plans/DOMAIN_CONTRACT_STANDARD.md`；Research、Travel 和未来 Domain 共享同一接入规范，不分别发明 Planner / Context / Memory 或 Tool 安全接口。
