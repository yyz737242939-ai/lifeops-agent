# 迁移索引

本文档追踪 V0 文件和概念如何映射到当前 runtime。

## 规则

- 不要盲目复制 V0 模块。
- 只有当 V0 模块具有清晰的当前 runtime 职责时，才迁移。
- 如果迁移会保留旧耦合，就重写一个更小、更清晰的当前实现。
- 每一次重要的迁移、重写、归档或延后都记录在这里。

## 状态说明

- `migrate`：复用并适配。
- `rewrite`：实现更清晰的当前版本。
- `archive`：仅作为历史参考保留。
- `defer`：延后到后续版本。
- `drop`：有意从当前 runtime 中移除。

## 初始映射

| V0 区域 | 当前目标 | 状态 | 说明 |
|---|---|---|---|
| `legacy_v0/entrypoints/main_legacy.py` | `main.py` | archive/rewrite | 当前 runtime 会创建新的 CLI。 |
| `legacy_v0/app/agents/agent.py` | `app/runtime`, `app/orchestration`, `app/execution` | rewrite | 旧 Agent 聚合了太多 runtime 职责。 |
| `legacy_v0/app/tools/*` | `app/tools/*` | migrate/rewrite | 保留概念，拆分 definition、registry、capability、executor、result。 |
| `legacy_v0/app/context/*` | `app/context/*` | defer/rewrite | 初版保留简化 request context；完整 ref/index/compaction 延后。 |
| `legacy_v0/app/memory/*` | `app/memory/*` | rewrite | Semantic memory 迁移到 SQLite，profile 保持 markdown。 |
| `legacy_v0/app/tasks/*` | 无直接当前替代 | archive/defer | 不迁移通用 Task 业务 Domain。阶段 7 使用跨 Domain `PlanRun` / `PlanStep` 保存执行状态；长期业务事实由 Research / Travel 在授权 WRITE 成功后各自保存。 |
| `legacy_v0/app/runtime/recovery_*` | `app/recovery/*` | rewrite | 保留解释型 recovery，不做 replay。 |
| `legacy_v0/app/mcp/*` | `app/integrations/calendar_mcp/*` | rewrite | 当前 runtime 先使用 Calendar fixture read MCP。 |
| `legacy_v0/entrypoints/log_viewer_legacy.py`, `legacy_v0/app/log_viewer/*` | `app/inspector/*` | archive/defer | Inspector 读取 trace evidence，不复用旧 log viewer UI。 |
| `legacy_v0/entrypoints/product_ui_legacy.py`, `legacy_v0/app/product_ui/*` | 未来 product UI | archive/defer | UI 不属于初版runtime core。 |

## 模块计划

每个模块迁移都必须在实现前写入对应的 `plans/modules/*_PLAN.md`。
