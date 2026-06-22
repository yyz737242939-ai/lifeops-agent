---
name: todo
description: Manage todos and build practical day plans. Use for adding, listing, updating, completing, deleting, prioritizing, scheduling, or planning from tasks.
---

# Todo

Use todo tools to capture and manage tasks.

- Use `medium` priority unless the user gives a clear priority signal.
- Use `YYYY-MM-DD` for due dates.
- Ask one short clarification only when a task cannot be captured safely.
- Use `update_todo` to change a title, due date, or priority.
- Use an empty `due_date` only when the user explicitly removes it.
- Call `plan_day` when the user asks for a plan based on saved todos.
- For cross-domain planning, combine the plan with the loaded wellbeing,
  finance, or activity skill instructions.

## Context references

- Use a todo summary for counts, priorities, overdue status, and top tasks.
- Call `read_context_ref` when the user needs exact task ids or records omitted
  from the summary, especially before updating, completing, or deleting one.
