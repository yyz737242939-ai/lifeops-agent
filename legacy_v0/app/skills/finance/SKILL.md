---
name: finance
description: Record expenses, summarize spending, set budgets, and check budget constraints. Use for concrete purchases, spending history, costs, or budget-aware decisions.
---

# Finance

Use finance tools for expenses, spending summaries, budgets, and money
constraints.

- Record a concrete purchase with `record_expense`.
- Use `summarize_spending` when totals are enough; avoid listing every expense.
- Check stored budgets before making budget-aware recommendations.
- Never invent exact totals, remaining budget, dates, or expense details.

## Context references

- Use the summary for totals, category totals, and recent high-level patterns.
- Call `read_context_ref` when the user requests individual transactions,
  exact dates, descriptions, ids, or a reconciliation of the original records.
