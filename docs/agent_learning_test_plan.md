# Agent Learning Test Plan

This project is optimized for learning agent concepts through small, inspectable
code paths. The goal of these scenarios is to verify that tools behave as
expected and that context compaction is visible in logs.

## What Was Added

- Wellbeing domain: `record_daily_state`, `get_daily_state`, `list_daily_logs`
- Finance domain: `record_expense`, `list_expenses`, `summarize_spending`,
  `set_budget`, `check_budget`
- Activity recommendation: `recommend_activities`
- Prompt modules: core, todo, wellbeing, finance, activity, planning
- Context management:
  - summary compaction for medium-sized list results
  - reference compaction for large results
  - `read_context_ref` for progressive disclosure

## Manual CLI Scenarios

Run the app:

```powershell
uv run python main.py
```

### 1. Wellbeing Write

User:

```text
我昨晚睡了 5 小时，今天能量低，心情一般，记一下
```

Expected tool chain:

```text
record_daily_state
```

Expected outcome:

- `data/daily_logs.json` has today's log.
- The final answer confirms the recorded state.

### 2. Finance Write And Budget Check

User:

```text
我今天花了 88 买咖啡和午饭，算餐饮。顺便把本周餐饮预算设成 300，再检查一下还剩多少
```

Expected tool chain:

```text
record_expense -> set_budget -> check_budget
```

Expected outcome:

- `data/expenses.json` has one food expense.
- `data/budgets.json` has a weekly food budget.
- The answer reports remaining budget from tool output.

### 3. Activity Recommendation

User:

```text
我今天能量低，只有 30 分钟，不想花钱，在家，推荐一个恢复状态的活动
```

Expected tool chain:

```text
recommend_activities
```

Expected outcome:

- Recommendations should be free, home-compatible, low-energy, and under
  30 minutes.

### 4. Cross-Domain Planning

User:

```text
我昨晚只睡了 5 小时，今天能量低。这周餐饮预算紧，今天还有重要任务。帮我安排一个现实一点的今天计划，也加一个恢复活动。
```

Expected tool chain:

```text
record_daily_state -> check_budget or summarize_spending -> plan_day -> recommend_activities
```

Expected outcome:

- The plan mentions lower energy.
- Workload is reduced or ordered conservatively.
- At least one activity recommendation appears.
- The answer does not invent exact budget numbers unless a finance tool returned
  them.

### 5. Summary Compaction Observation

Create more than 8 todos, then ask:

```text
列出我的所有任务
```

Expected tool chain:

```text
list_todos
```

Expected context behavior:

- The Event `tool.completed` record contains the Action result and:
  - `context_compaction.strategy = "summary"`
  - `summary.open`
  - `summary.high_priority_open`
  - `summary.top_open_items`
- The next `llm.request.input` shows the compacted
  observation, not the full todo list.

### 6. Reference Compaction Observation

Create at least 30 expenses, then ask:

```text
列出我最近所有消费，先总结，如果需要明细再展开
```

Expected tool chain:

```text
list_expenses
```

Expected context behavior:

- The Event `tool.completed` record has:
  - `context_compaction.strategy = "reference"`
  - a non-empty `ref_id`
- `logs/context_refs/ctx_*.json` contains the complete expense result.
- The model sees a compacted observation with `ref_id`, summary, and the hint to
  use `read_context_ref` if exact records are needed.

Follow-up user:

```text
把刚才那批消费明细展开给我看
```

Expected tool chain:

```text
read_context_ref
```

Expected outcome:

- The full referenced records are available again.

## Code Reading Map

- Tool registry and metadata: `app/tools/registry.py`
- Tool authorization, timeout, and idempotency: `app/tools/executor.py`
- Business tool schemas and handlers: `app/tools/tool.py`
- Business memory stores:
  - `app/memory/todo_store.py`
  - `app/memory/daily_log_store.py`
  - `app/memory/expense_store.py`
  - `app/memory/activity_catalog.py`
- Prompt modularization: `app/prompts/system_prompt.py`
- Context compaction: `app/runtime/context_manager.py`
- Reference storage: `app/runtime/context_ref_store.py`
- Agent loop integration: `app/agents/agent.py`

## What To Inspect After Each Run

Look under:

```text
logs/conversations/
logs/context_refs/
```

For each session, compare:

- Context Ref files: complete results retained for later expansion
- `events.jsonl`: what was summarized and why
- `function_call_output` in later `llm.request` entries: what the model actually
  saw

That comparison is the main learning object for context management.
